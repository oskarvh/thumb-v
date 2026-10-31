"""RTL simulation: the SoC in Verilator, checked against the model one instruction at a time.

The testbench (sim/tb.sv) loads a program into the SoC's RAMs, runs until the
core retires `j .` (the startup code's `done` loop), prints what the UART
sent, and logs every retired instruction from the core's RVFI port. `lockstep`
replays that trace against the model: the same PC and instruction, the same
register write, the same bytes stored.

Loads from I/O registers (the UART status) are inputs from the outside world:
the model reads whatever the RTL read.

    python -m thumbv.rtlsim program.elf [--trace out.txt]
"""

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import elf
from .build import REPO, ToolMissing
from .expander import Options
from .lockstep import Divergence, Layout, _load_model, describe
from .machine import PAGE, Trap

CORE = REPO / "build" / "rtl" / "VexRiscv.v"
SIM_DIR = REPO / "build" / "sim"
SIMULATOR = SIM_DIR / "obj_dir" / "tb"
SOURCES = [CORE, *sorted((REPO / "rtl" / "soc").glob("*.v")), REPO / "sim" / "tb.sv"]

# The SoC's memory map, see rtl/soc/thumbv_soc.v.
CODE_BASE, CODE_WORDS = 0x0000_0000, 65536
DATA_BASE, DATA_WORDS = 0x2000_0000, 16384
IO_BASE, IO_SIZE = 0x1000_0000, 16

EXIT, TIMEOUT = "EXIT", "TIMEOUT"


def simulator() -> Path:
    """The Verilator testbench binary, built (and the core generated) if out of date."""
    if shutil.which("verilator") is None:
        raise ToolMissing("verilator")
    if not CORE.exists():
        if shutil.which("sbt") is None:
            raise ToolMissing("sbt")
        subprocess.run(["make", "-C", str(REPO), "core"], check=True, capture_output=True)
    if not SIMULATOR.exists() or SIMULATOR.stat().st_mtime < max(s.stat().st_mtime for s in SOURCES):
        SIM_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(["verilator", "--binary", "--timing", "-j", "0", "--top-module", "tb",
                        "-o", "tb", *map(str, SOURCES)], cwd=SIM_DIR, check=True, capture_output=True)
    return SIMULATOR


def memory_images(images, out_dir: Path) -> tuple[Path, Path]:
    """$readmemh files for the code and data RAMs."""
    regions = {"code": (CODE_BASE, CODE_WORDS, {}), "data": (DATA_BASE, DATA_WORDS, {})}
    for img in images:
        for seg in img.segments:
            for name, (base, words, out) in regions.items():
                if base <= seg.addr and seg.addr + len(seg.data) <= base + 4 * words:
                    break
            else:
                raise ValueError(f"segment at {seg.addr:#x} is outside the SoC's RAMs")
            for i, byte in enumerate(seg.data):
                word, lane = divmod(seg.addr - base + i, 4)
                out[word] = out.get(word, 0) | byte << 8 * lane
    paths = []
    for name, (_, _, words) in regions.items():
        path = out_dir / f"{name}.hex"
        path.write_text("".join(f"@{w:x} {v:08x}\n" for w, v in sorted(words.items())))
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


def run(images, out_dir: Path, max_cycles: int = 10_000_000, trace: bool = True) -> Result:
    """Run a program on the SoC in Verilator."""
    sim = simulator()
    code, data = memory_images(images, out_dir)
    trace_path = out_dir / "trace.txt"
    args = [str(sim), f"+code={code}", f"+data={data}", f"+cycles={max_cycles}"]
    if trace:
        args.append(f"+trace={trace_path}")
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
            insn = m.mem.read(m.pc, 4)
            if insn != r.insn:
                problems.append(f"instruction: model {insn:#010x}, RTL {r.insn:#010x}")
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
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    images = [elf.load(p) for p in args.elf]
    result = run(images, args.out, args.cycles)
    sys.stdout.write(result.uart)
    print(f"\n{result.status}: a0 = {result.a0:#x}, {result.instructions} instructions "
          f"in {result.cycles} cycles (CPI {result.cycles / max(1, result.instructions):.2f})")
    divergence = lockstep(images, result)
    print(divergence if divergence else f"lockstep: {len(result.trace)} instructions match the model")
    return 0 if result.status == EXIT and divergence is None else 1


if __name__ == "__main__":
    sys.exit(main())
