"""RTL simulation: the SoC in Verilator, checked against the model one instruction at a time.

The testbench (sim/tb.sv) loads a program into the SoC's RAMs, runs until the
core retires `j .` (the startup code's `done` loop), prints what the UART
sent, and logs every retired instruction from the core's RVFI port. `lockstep`
replays that trace against the model: the same PC and instruction, the same
register write, the same bytes stored.

Loads from I/O registers (the UART status) are inputs from the outside world:
the model reads whatever the RTL read.

    python -m thumbv.rtlsim program.elf [--wave out.fst]
"""

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import elf, expander
from .build import REPO, ToolMissing
from .expander import Options
from .lockstep import Divergence, Layout, _load_model, describe
from .machine import PAGE, Trap

CORE = REPO / "build" / "rtl" / "VexRiscv.v"
SIM_DIR = REPO / "build" / "sim"
SOURCES = [CORE, *sorted((REPO / "rtl" / "soc").glob("*.v")), REPO / "sim" / "tb.sv"]

# The SoC's memory map, see rtl/soc/thumbv_soc.v: (base, size in bytes).
CODE_REGION = (0x0000_0000, 0x4_0000)
DATA_REGION = (0x2000_0000, 0x1_0000)
IO_BASE, IO_SIZE = 0x1000_0000, 16


@dataclass(frozen=True)
class Memories:
    """RAM sizes in words. A RAM smaller than its region repeats through it."""
    name: str
    code_words: int
    data_words: int


SIM = Memories("sim", 65536, 16384)     # the RAMs fill their regions
BOARD = Memories("board", 8192, 4096)   # the CYC1000: 32 KiB code, 16 KiB data

EXIT, TIMEOUT = "EXIT", "TIMEOUT"


def simulator(memories: Memories = SIM) -> Path:
    """The Verilator testbench binary, built (and the core generated) if out of date."""
    if shutil.which("verilator") is None:
        raise ToolMissing("verilator")
    if not CORE.exists():
        if shutil.which("sbt") is None:
            raise ToolMissing("sbt")
        subprocess.run(["make", "-C", str(REPO), "core"], check=True, capture_output=True)
    build_dir = SIM_DIR / memories.name
    binary = build_dir / "obj_dir" / "tb"
    if not binary.exists() or binary.stat().st_mtime < max(s.stat().st_mtime for s in SOURCES):
        build_dir.mkdir(parents=True, exist_ok=True)
        # Tracing is compiled in (about 8% slower even when not dumping) so that
        # +wave works without a second build.
        subprocess.run(["verilator", "--binary", "--timing", "--trace-fst", "-j", "0", "--top-module", "tb",
                        f"-GCODE_WORDS={memories.code_words}", f"-GDATA_WORDS={memories.data_words}",
                        "-o", "tb", *map(str, SOURCES)], cwd=build_dir, check=True, capture_output=True)
    return binary


def memory_images(images, out_dir: Path, memories: Memories = SIM, suffix: str = ".hex") -> tuple[Path, Path]:
    """$readmemh files for the code and data RAMs.

    With RAMs smaller than their regions, addresses wrap around the RAM; two
    bytes of the program landing on the same RAM byte is an error. Files are
    only rewritten when their contents change, so their timestamps can drive
    rebuilds. (Quartus reads any .hex file as Intel HEX: the board uses .mem.)
    """
    regions = {"code": (*CODE_REGION, memories.code_words), "data": (*DATA_REGION, memories.data_words)}
    words = {name: {} for name in regions}
    owner = {}
    for img in images:
        for seg in img.segments:
            for name, (base, size, ram_words) in regions.items():
                if base <= seg.addr and seg.addr + len(seg.data) <= base + size:
                    break
            else:
                raise ValueError(f"segment at {seg.addr:#x} is outside the SoC's memory regions")
            for i, byte in enumerate(seg.data):
                offset = (seg.addr - base + i) % (4 * ram_words)
                addr = seg.addr + i
                if owner.setdefault((name, offset), addr) != addr:
                    raise ValueError(f"{addr:#x} and {owner[name, offset]:#x} share a byte of the "
                                     f"{memories.name} {name} RAM")
                word, lane = divmod(offset, 4)
                words[name][word] = words[name].get(word, 0) | byte << 8 * lane
    paths = []
    for name, contents in words.items():
        path = out_dir / f"{name}{suffix}"
        text = "".join(f"@{w:x} {v:08x}\n" for w, v in sorted(contents.items()))
        if not path.exists() or path.read_text() != text:
            path.write_text(text)
        paths.append(path)
    return paths[0], paths[1]


@dataclass
class Retired:
    """One instruction retired by the core, from the RVFI port."""
    pc: int
    insn: int
    rd: int          # 0 if no register was written
    rd_wdata: int
    mem_addr: int    # word-aligned
    rmask: int
    wmask: int
    rdata: int
    wdata: int
    trap: int

    @classmethod
    def parse(cls, line: str):
        return cls(*(int(f, 16) for f in line.split()))


@dataclass
class Result:
    status: str                  # EXIT or TIMEOUT
    a0: int                      # main's return value
    cycles: int
    instructions: int
    uart: str
    trace: list[Retired] = field(default_factory=list)


def run(images, out_dir: Path, max_cycles: int = 10_000_000, trace: bool = True,
        wave: Path | None = None, memories: Memories = SIM) -> Result:
    """Run a program on the SoC in Verilator; `wave` names an FST waveform file to write."""
    sim = simulator(memories)
    code, data = memory_images(images, out_dir, memories)
    trace_path = out_dir / "trace.txt"
    args = [str(sim), f"+code={code}", f"+data={data}", f"+cycles={max_cycles}"]
    if trace:
        args.append(f"+trace={trace_path}")
    if wave:
        args.append(f"+wave={wave}")
    out = subprocess.run(args, check=True, capture_output=True, text=True).stdout
    lines = [l for l in out.splitlines(keepends=True) if not l.startswith("- ")]  # Verilator's $finish note
    status, a0, cycles, instructions = lines[-1].split()
    uart = "".join(lines[:-1])[:-1]   # the testbench starts its last line with a newline
    retired = [Retired.parse(l) for l in trace_path.read_text().splitlines()] if trace else []
    return Result(status, int(a0, 16), int(cycles), int(instructions), uart, retired)


def lockstep(images, result: Result) -> Divergence | None:
    """Replay the RTL's retire trace against the model; the first difference, if any."""
    layout = Layout.for_images(images)
    m = _load_model(images, layout, Options())
    m.mem.map(IO_BASE, PAGE)
    m.pc = images[0].entry & ~1
    for step, r in enumerate(result.trace):
        problems = []
        if m.pc != r.pc:
            problems.append(f"pc: model {m.pc:#010x}, RTL {r.pc:#010x}")
        else:
            # The RVFI word holds the instruction as fetched: for a 16-bit
            # Thumb instruction, only its low half is the instruction.
            n = 4
            if m.in_thumb(m.pc) and not expander.isa.is_32bit(m.mem.read(m.pc, 2)):
                n = 2
            insn = m.mem.read(m.pc, n)
            if insn != r.insn & ((1 << 8 * n) - 1):
                problems.append(f"instruction: model {insn:#0{2 + 2 * n}x}, RTL {r.insn:#010x}")
        if problems:
            return Divergence(step, r.pc, describe(m, layout, r.pc), problems)
        if r.rmask and IO_BASE <= r.mem_addr < IO_BASE + IO_SIZE:
            m.mem.write(r.mem_addr, 4, r.rdata)   # what the device returned
        before = list(m.x)
        m.mem.log = []
        try:
            m.step()
        except Trap as trap:
            return Divergence(step, r.pc, describe(m, layout, r.pc), [f"model trap: {trap}"])
        changed = {i for i in range(32) if m.x[i] != before[i]}
        if r.rd and m.x[r.rd] != r.rd_wdata:
            problems.append(f"x{r.rd}: model {m.x[r.rd]:#010x}, RTL {r.rd_wdata:#010x}")
        if changed - {r.rd}:
            problems.append(f"model also wrote {sorted(changed - {r.rd})}")
        model_stores = {a + i: (v >> 8 * i) & 0xFF for a, n, v in m.mem.log for i in range(n)}
        rtl_stores = {r.mem_addr + i: (r.wdata >> 8 * i) & 0xFF for i in range(4) if r.wmask >> i & 1}
        if model_stores != rtl_stores:
            problems.append(f"stores: model {_bytes(model_stores)}, RTL {_bytes(rtl_stores)}")
        if problems:
            return Divergence(step, r.pc, describe(m, layout, r.pc), problems)
    return None


def _bytes(stores):
    return "{" + ", ".join(f"{a:#x}: {v:#04x}" for a, v in sorted(stores.items())) + "}"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run an RV32 program on the SoC in Verilator, "
                                                 "in lockstep with the model.")
    parser.add_argument("elf", nargs="+", type=Path)
    parser.add_argument("--cycles", type=int, default=10_000_000)
    parser.add_argument("--out", type=Path, default=SIM_DIR / "run", help="where to put hex files and trace")
    parser.add_argument("--wave", type=Path, help="write an FST waveform of every signal to this file")
    parser.add_argument("--board", action="store_true", help="simulate the board's smaller RAMs")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    images = [elf.load(p) for p in args.elf]
    result = run(images, args.out, args.cycles, wave=args.wave, memories=BOARD if args.board else SIM)
    sys.stdout.write(result.uart if result.uart.endswith("\n") or not result.uart else result.uart + "\n")
    print(f"{result.status}: a0 = {result.a0:#x}, {result.instructions} instructions "
          f"in {result.cycles} cycles (CPI {result.cycles / max(1, result.instructions):.2f})")
    divergence = lockstep(images, result)
    print(divergence if divergence else f"lockstep: {len(result.trace)} instructions match the model")
    if args.wave:
        print(f"waveform: {args.wave}")
    return 0 if result.status == EXIT and divergence is None else 1


if __name__ == "__main__":
    sys.exit(main())
