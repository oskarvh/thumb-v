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
from . import rv32
from .build import REPO, ToolMissing
from .expander import Options
from .lockstep import Divergence, Layout, _load_model, describe
from .machine import PAGE, Trap
from .rv32 import MSTATUS_MIE

CORE = REPO / "build" / "rtl" / "VexRiscv.v"
SIM_DIR = REPO / "build" / "sim"
SOURCES = [CORE, *sorted((REPO / "rtl" / "soc").glob("*.v")), REPO / "sim" / "tb.sv"]

# The SoC's memory map, see rtl/soc/thumbv_soc.v: (base, size in bytes).
CODE_REGION = (0x0000_0000, 0x4_0000)
DATA_REGION = (0x2000_0000, 0x1_0000)
IO_BASE, IO_SIZE = 0x1000_0000, 16
# Devices, whose loads the model takes from the RTL's trace: the I/O
# registers, the interrupt controller's CLAIM/COMPLETE and the System
# Control Space (base, size in bytes).
DEVICES = [(IO_BASE, IO_SIZE), (0x1000_1000, 8), (0xE000_E000, 0x1000)]


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


EXPANDER = REPO / "build" / "rtl" / "ThumbExpander.v"
EXPANDER_SOURCES = [EXPANDER, REPO / "sim" / "expander_tb.sv"]


def expander_simulator() -> Path:
    """The testbench for the expander alone (sim/expander_tb.sv), built if out of date."""
    if shutil.which("verilator") is None:
        raise ToolMissing("verilator")
    if not EXPANDER.exists():
        if shutil.which("sbt") is None:
            raise ToolMissing("sbt")
        subprocess.run(["make", "-C", str(REPO), "core"], check=True, capture_output=True)
    build_dir = SIM_DIR / "expander"
    binary = build_dir / "obj_dir" / "expander_tb"
    if not binary.exists() or binary.stat().st_mtime < max(s.stat().st_mtime for s in EXPANDER_SOURCES):
        build_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["verilator", "--binary", "--timing", "-j", "0", "--top-module", "expander_tb",
                        "-o", "expander_tb", *map(str, EXPANDER_SOURCES)],
                       cwd=build_dir, check=True, capture_output=True)
    return binary


def expand_rtl(queries, out_dir: Path) -> list[tuple[int, bool]]:
    """The RTL expander's (op, last) for each (hw1, hw2, pc1, step); op has the
    flags side-band in bits 39:32, as the model's ops."""
    sim = expander_simulator()
    inputs, outputs = out_dir / "expander_in.txt", out_dir / "expander_out.txt"
    inputs.write_text("".join(f"{hw1:04x} {hw2:04x} {pc1:x} {step:x}\n" for hw1, hw2, pc1, step in queries))
    subprocess.run([str(sim), f"+in={inputs}", f"+out={outputs}"], check=True, capture_output=True)
    words = outputs.read_text().split()
    return [(int(op, 16), last == "1") for op, last in zip(words[::2], words[1::2])]


NVIC_SOURCES = [REPO / "rtl" / "soc" / "thumbv_nvic.v", REPO / "sim" / "nvic_tb.sv"]


def nvic_simulator() -> Path:
    """The testbench for the interrupt controller alone (sim/nvic_tb.sv), built if out of date."""
    if shutil.which("verilator") is None:
        raise ToolMissing("verilator")
    build_dir = SIM_DIR / "nvic"
    binary = build_dir / "obj_dir" / "nvic_tb"
    if not binary.exists() or binary.stat().st_mtime < max(s.stat().st_mtime for s in NVIC_SOURCES):
        build_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["verilator", "--binary", "--timing", "-j", "0", "--top-module", "nvic_tb",
                        "-o", "nvic_tb", *map(str, NVIC_SOURCES)],
                       cwd=build_dir, check=True, capture_output=True)
    return binary


def run_nvic(cycles, out_dir: Path) -> list[tuple[int, bool]]:
    """The controller's (read data, irq) after each cycle of `cycles`:
    [(op, addr, data, lines)], op 0 none, 1 read, 2 write."""
    sim = nvic_simulator()
    inputs, outputs = out_dir / "nvic_in.txt", out_dir / "nvic_out.txt"
    inputs.write_text("".join(f"{op:x} {a:x} {d:x} {l:x}\n" for op, a, d, l in cycles))
    subprocess.run([str(sim), f"+in={inputs}", f"+out={outputs}"], check=True, capture_output=True)
    words = outputs.read_text().split()
    return [(int(v, 16), irq == "1") for v, irq in zip(words[::2], words[1::2])]


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
    nzcv: int        # the flags unit's NZCV after the op

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
        wave: Path | None = None, memories: Memories = SIM, irq: int | None = None) -> Result:
    """Run a program on the SoC in Verilator; `wave` names an FST waveform file to write.

    `irq`, a seed, makes the testbench raise the timer interrupt again and
    again (sim/tb.sv); the program acknowledges each with a store to 0x1000_000C.
    """
    sim = simulator(memories)
    code, data = memory_images(images, out_dir, memories)
    trace_path = out_dir / "trace.txt"
    args = [str(sim), f"+code={code}", f"+data={data}", f"+cycles={max_cycles}"]
    if trace:
        args.append(f"+trace={trace_path}")
    if wave:
        args.append(f"+wave={wave}")
    if irq:
        args.append(f"+irq={irq}")
    out = subprocess.run(args, check=True, capture_output=True, text=True).stdout
    lines = [l for l in out.splitlines(keepends=True) if not l.startswith("- ")]  # Verilator's $finish note
    status, a0, cycles, instructions = lines[-1].split()
    uart = "".join(lines[:-1])[:-1]   # the testbench starts its last line with a newline
    retired = [Retired.parse(l) for l in trace_path.read_text().splitlines()] if trace else []
    return Result(status, int(a0, 16), int(cycles), int(instructions), uart, retired)


# The hardware's expander mode: strategy C, the flags unit (Phase 4).
HARDWARE = Options(flags="C")


RESET_VECTOR = 0x0002_0000


def thumb_boot(thumb: elf.Image) -> elf.Image:
    """A RISC-V boot stub for a Thumb-only program (tests/link/thumb.ld) on the
    SoC, which resets into RISC-V at RESET_VECTOR: mark the program's code as
    Thumb region 0, then jump to its entry point. Put it first in the image
    list, so the model starts there too."""
    base = min(lo for lo, hi in thumb.code_ranges())
    limit = max(hi for lo, hi in thumb.code_ranges())
    limit = (limit + 3) & ~3
    if limit > RESET_VECTOR:
        raise ValueError(f"Thumb code up to {limit:#x} overlaps the boot stub at {RESET_VECTOR:#x}")
    t0 = 5

    def li(value):
        hi, lo = rv32.split_offset(value)
        return [rv32.lui(t0, hi & 0xFFFFF), rv32.addi(t0, t0, lo)]

    ops = [*li(base), rv32.csrrw(0, rv32.THUMB_REGION0, t0),
           *li(limit), rv32.csrrw(0, rv32.THUMB_REGION0 + 1, t0),
           rv32.fence_i(),
           *li(thumb.entry & ~1), rv32.jalr(0, t0, 0)]
    code = b"".join(op.to_bytes(4, "little") for op in ops)
    return elf.Image("EM_RISCV", RESET_VECTOR, [elf.Segment(RESET_VECTOR, code, True)], {}, {})


# The interrupt the core takes: the machine external interrupt, which the
# interrupt controller drives (rtl/soc/thumbv_nvic.v, Phase 5.2).
EXTERNAL_INTERRUPT = 11


def lockstep(images, result: Result, options: Options = HARDWARE,
             interrupt: int = EXTERNAL_INTERRUPT) -> Divergence | None:
    """Replay the RTL's retire trace against the model; the first difference, if any."""
    return replay(images, result, options, interrupt)[0]


def replay(images, result: Result, options: Options = HARDWARE, interrupt: int = EXTERNAL_INTERRUPT):
    """lockstep(), and the model it ran: (divergence or None, Machine). Without
    a divergence, the model's state is the RTL's, memory included, so a test
    can read a program's results from it.

    The RTL retires each op of a Thumb instruction as its own record, all with
    the instruction's address (PC-hold), so the model runs Thumb code one op
    at a time too: op k of its expansion against record k.

    Traps (Phase 5.1): a trapping op doesn't retire, so the trace goes on at
    the trap vector instead. There, the model runs its op on a snapshot: if
    the op traps, it was that synchronous trap; if not, the model rolls back
    and takes `interrupt`, which must be at an instruction boundary (op 0)
    with interrupts enabled. FormalPlugin doesn't flag interrupts itself.
    """
    layout = Layout.for_images(images)
    m = _load_model(images, layout, options)
    for base, size in DEVICES:
        m.mem.map(base & ~(PAGE - 1), PAGE)
    m.pc = images[0].entry & ~1
    trace, i = result.trace, 0
    while i < len(trace):
        pc = m.pc
        if m.in_thumb(pc):
            hw1 = m.mem.read(pc, 2)
            hw2 = m.mem.read(pc + 2, 2) if expander.isa.is_32bit(hw1) else 0
            e = expander.expand(hw1, hw2, pc, options)
            ops, length = e.ops, e.length
            # The RVFI word holds the instruction as fetched: for a 16-bit
            # Thumb instruction, only its low half is the instruction.
            n = length
        else:
            ops, length, n = [m.mem.read(pc, 4)], 4, 4
        insn = m.mem.read(pc, n)
        target, trapped = None, False
        for k, op in enumerate(ops):
            if i == len(trace):
                return None, m                    # the run ended part-way through
            r = trace[i]
            if r.pc != pc and r.pc == m.trap_vector:
                problem = _enter_trap(m, op, k, pc, length, interrupt)
                if problem:
                    return (Divergence(i, r.pc, describe(m, layout, pc), [problem]), m)
                trapped = True
                break
            problems = []
            if r.pc != pc:
                problems.append(f"pc: model {pc:#010x}, RTL {r.pc:#010x}")
            elif insn != r.insn & ((1 << 8 * n) - 1):
                problems.append(f"instruction: model {insn:#0{2 + 2 * n}x}, RTL {r.insn:#010x}")
            if problems:
                return (Divergence(i, r.pc, describe(m, layout, r.pc), problems), m)
            if r.rmask and any(base <= r.mem_addr < base + size for base, size in DEVICES):
                m.mem.write(r.mem_addr, 4, r.rdata)   # what the device returned
            before = list(m.x)
            m.mem.log = []
            try:
                target = m.execute(op, pc, link=pc + length)
            except Trap as trap:
                return (Divergence(i, r.pc, describe(m, layout, r.pc), [f"model trap: {trap}"]), m)
            changed = {j for j in range(32) if m.x[j] != before[j]}
            if r.rd and m.x[r.rd] != r.rd_wdata:
                problems.append(f"x{r.rd}: model {m.x[r.rd]:#010x}, RTL {r.rd_wdata:#010x}")
            if changed - {r.rd}:
                problems.append(f"model also wrote {sorted(changed - {r.rd})}")
            if options.flags == "C" and m.nzcv != r.nzcv:
                problems.append(f"NZCV: model {m.nzcv:04b}, RTL {r.nzcv:04b}")
            model_stores = {a + j: (v >> 8 * j) & 0xFF for a, k, v in m.mem.log for j in range(k)}
            rtl_stores = {r.mem_addr + j: (r.wdata >> 8 * j) & 0xFF for j in range(4) if r.wmask >> j & 1}
            if model_stores != rtl_stores:
                problems.append(f"stores: model {_bytes(model_stores)}, RTL {_bytes(rtl_stores)}")
            if problems:
                return (Divergence(i, r.pc, describe(m, layout, r.pc), problems), m)
            i += 1
        if not trapped:
            m.pc = target if target is not None else (pc + length) & 0xFFFF_FFFF
    return None, m


def _enter_trap(m, op, k, pc, length, interrupt) -> str | None:
    """The RTL went to the trap vector instead of retiring op k of the
    instruction at pc: take the same trap in the model. A problem, or None."""
    state = m.snapshot()
    try:
        m.execute(op, pc, link=pc + length)
    except Trap as trap:
        m.restore(state)
        m.take_trap(trap)
        return None
    m.restore(state)
    if k:
        return f"RTL trapped at op {k}, which doesn't trap in the model (interrupts only between instructions)"
    if not m.mstatus & MSTATUS_MIE:
        return "RTL took an interrupt with mstatus.MIE clear"
    m.interrupt(interrupt)
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
