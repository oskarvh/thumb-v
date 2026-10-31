"""Program-level lockstep: the model against an ARMv6-M reference, one instruction at a time.

The reference is a hybrid: Unicorn executes Thumb code as a Cortex-M0, and a
second copy of the native RV32 executor runs RISC-V code, reading and writing
Unicorn's memory. ARM registers are handed between the two through the D2
register mapping whenever execution crosses between instruction sets. For a
Thumb-only program the reference is plain Unicorn.

After every step (one Thumb instruction or one RV32 op) the lockstep compares
the PC, r0-r14, NZCV (after Thumb instructions), the memory writes the step
made, and the RISC-V registers Thumb code must preserve. Memory is compared in
full at the end.

Where Thumb-V deliberately differs from a real Cortex-M, the reference is
adjusted:
- Q1: a BX, BLX or POP {pc} to an even address outside the Thumb regions
  returns to RISC-V. A Cortex-M would fault, so the reference sets bit 0 of
  the target for that instruction only.
- Flags are UNKNOWN after a call (AAPCS), and RISC-V code may clobber the
  model's flag registers. On each RISC-V -> Thumb transition the reference
  adopts the model's flags.
"""

import argparse
import sys
from collections import deque
from dataclasses import dataclass, field

import capstone
import unicorn
from unicorn import arm_const as A

from . import elf, isa, regmap
from .expander import Options, expand
from .machine import PAGE, Machine, Trap

UC_REGS = [getattr(A, f"UC_ARM_REG_R{i}") for i in range(13)] + [A.UC_ARM_REG_SP, A.UC_ARM_REG_LR]

# RISC-V registers that are neither ARM state nor expander temporaries or
# flags: Thumb code must leave them untouched.
PRESERVED = sorted(set(range(1, 32)) - {r for r in regmap.ARM_TO_RV if r is not None}
                   - {regmap.T1, regmap.T2, regmap.T3, regmap.T4, regmap.T5, regmap.T6}
                   - {regmap.FN, regmap.FZ, regmap.FC, regmap.FV})

RAM_BASE, RAM_SIZE = 0x2000_0000, 0x1_0000


@dataclass
class Layout:
    regions: list[tuple[int, int]]        # mapped memory, (base, size), page-aligned
    thumb_regions: list[tuple[int, int]]  # [base, limit) decoded as Thumb

    @classmethod
    def for_images(cls, images, ram=(RAM_BASE, RAM_SIZE)):
        spans = [(s.addr, s.addr + len(s.data)) for img in images for s in img.segments]
        spans.append((ram[0], ram[0] + ram[1]))
        pages = sorted({p for lo, hi in spans for p in range(lo // PAGE, (hi + PAGE - 1) // PAGE)})
        regions = []
        for p in pages:
            if regions and regions[-1][0] + regions[-1][1] == p * PAGE:
                regions[-1] = (regions[-1][0], regions[-1][1] + PAGE)
            else:
                regions.append((p * PAGE, PAGE))
        thumb = [rng for img in images if img.is_thumb for rng in img.code_ranges()]
        return cls(regions, thumb)

    def in_thumb(self, addr):
        return any(lo <= addr < hi for lo, hi in self.thumb_regions)


class ReferenceFault(Exception):
    pass


class _UnicornMemory:
    """Memory interface for the reference RV32 executor, backed by Unicorn."""

    def __init__(self, uc, log):
        self.uc, self.log = uc, log

    def read_bytes(self, addr, n):
        try:
            return bytes(self.uc.mem_read(addr, n))
        except unicorn.UcError:
            raise Trap("load_access_fault", 0, addr) from None

    def read(self, addr, n):
        return int.from_bytes(self.read_bytes(addr, n), "little")

    def write_bytes(self, addr, data):
        try:
            self.uc.mem_write(addr, bytes(data))
        except unicorn.UcError:
            raise Trap("store_access_fault", 0, addr) from None

    def write(self, addr, n, value):
        value &= (1 << (8 * n)) - 1
        self.write_bytes(addr, value.to_bytes(n, "little"))
        self.log.append((addr, n, value))


class Reference:
    """Unicorn (Cortex-M0) for Thumb code, the native RV32 executor for RISC-V code."""

    def __init__(self, layout: Layout, images):
        self.layout = layout
        self.uc = uc = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_THUMB | unicorn.UC_MODE_MCLASS)
        uc.ctl_set_cpu_model(A.UC_CPU_ARM_CORTEX_M0)
        for base, size in layout.regions:
            uc.mem_map(base, size)
        for img in images:
            for seg in img.segments:
                uc.mem_write(seg.addr, seg.data)
        self.writes: list[tuple[int, int, int]] = []
        uc.hook_add(unicorn.UC_HOOK_MEM_WRITE, self._on_write)
        self.rv = Machine(thumb_regions=layout.thumb_regions)
        self.rv.mem = _UnicornMemory(uc, self.writes)
        self.mode = "rv"   # which side holds the ARM registers
        self.pc = 0

    def _on_write(self, uc, access, address, size, value, user):
        self.writes.append((address, size, value & ((1 << (8 * size)) - 1)))

    # ARM register access, from whichever side currently holds them.
    def reg(self, i):
        return self.uc.reg_read(UC_REGS[i]) if self.mode == "thumb" else self.rv.x[regmap.rv(i)]

    def set_reg(self, i, value):
        if self.mode == "thumb":
            self.uc.reg_write(UC_REGS[i], value)
        else:
            self.rv.x[regmap.rv(i)] = value

    @property
    def flags(self):
        return self.uc.reg_read(A.UC_ARM_REG_XPSR) >> 28

    def set_flags(self, nzcv):
        self.uc.reg_write(A.UC_ARM_REG_XPSR, nzcv << 28 | 1 << 24)

    def _switch(self, mode):
        if mode == self.mode:
            return
        values = [self.reg(i) for i in range(15)]
        self.mode = mode
        for i, v in enumerate(values):
            self.set_reg(i, v)

    def step(self, model_flags):
        """Execute one instruction. `model_flags` is adopted on entry to Thumb code."""
        pc = self.pc
        if not self.layout.in_thumb(pc):
            self._switch("rv")
            self.rv.pc = pc
            self.rv.step()
            self.pc = self.rv.pc
            return
        if self.mode == "rv":
            self._switch("thumb")
            self.set_flags(model_flags)
        restore = self._interworking_target(pc)
        try:
            self.uc.emu_start(pc | 1, 0, count=1)
            error = None
        except unicorn.UcError as e:
            error = e
        new_pc = self.uc.reg_read(A.UC_ARM_REG_PC) & ~1
        if restore:
            restore()
        # Unicorn decodes the next instruction before stopping. After a branch
        # to RISC-V code that can fail harmlessly; any other error is a fault.
        if error and (new_pc == pc or self.layout.in_thumb(new_pc)):
            raise ReferenceFault(f"Unicorn: {error} at {pc:#010x}")
        self.pc = new_pc

    def _interworking_target(self, pc):
        """Set bit 0 of an even branch target outside the Thumb regions (Q1).

        Returns a function that undoes the change, or None.
        """
        hw1 = int.from_bytes(self.uc.mem_read(pc, 2), "little")
        decoded = isa.decode(hw1)
        if decoded is None:
            return None
        enc, f = decoded
        if enc.name in ("BX", "BLX") and f["m"] < 15:
            value = self.reg(f["m"])
            if not value & 1 and not self.layout.in_thumb(value):
                self.set_reg(f["m"], value | 1)
                if enc.name == "BLX" and f["m"] == 14:
                    return None  # BLX LR overwrites LR anyway
                return lambda: self.set_reg(f["m"], value)
        if enc.name == "POP" and f["P"]:
            slot = self.reg(13) + 4 * bin(f["r"]).count("1")
            value = int.from_bytes(self.uc.mem_read(slot, 4), "little")
            if not value & 1 and not self.layout.in_thumb(value):
                self.uc.mem_write(slot, (value | 1).to_bytes(4, "little"))
                return lambda: self.uc.mem_write(slot, value.to_bytes(4, "little"))
        return None


@dataclass
class Divergence:
    step: int
    pc: int
    instruction: str
    problems: list[str]
    history: list[str] = field(default_factory=list)

    def __str__(self):
        lines = [f"divergence at step {self.step}, pc {self.pc:#010x}: {self.instruction}"]
        lines += [f"  {p}" for p in self.problems]
        if self.history:
            lines.append("  preceding instructions:")
            lines += [f"    {h}" for h in self.history]
        return "\n".join(lines)


@dataclass
class Result:
    steps: int = 0
    thumb_steps: int = 0
    rv_ops: int = 0                # RV32 ops the model executed, native and expanded
    divergence: Divergence | None = None
    stopped: str = ""              # "stop address", "max steps", or a fault description
    final_regs: list[int] = field(default_factory=list)
    model: Machine | None = None   # the model's final state

    @property
    def ok(self):
        return self.divergence is None and self.stopped == "stop address"

    def read_symbol(self, image, name, size):
        """Bytes of a symbol in the model's final memory."""
        return self.model.mem.read_bytes(image.symbols[name], size)


_THUMB_DIS = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB | capstone.CS_MODE_MCLASS)
_RV_DIS = capstone.Cs(capstone.CS_ARCH_RISCV, capstone.CS_MODE_RISCV32)


def _disassemble(dis, code, addr):
    insn = next(dis.disasm(code, addr), None)
    return f"{insn.mnemonic} {insn.op_str}".strip() if insn else code.hex()


def describe(machine: Machine, layout: Layout, pc: int) -> str:
    """Disassembly of the instruction at pc, with its expansion for Thumb code."""
    try:
        if layout.in_thumb(pc):
            hw1 = machine.mem.read(pc, 2)
            hw2 = machine.mem.read(pc + 2, 2) if isa.is_32bit(hw1) else 0
            code = machine.mem.read_bytes(pc, 4 if isa.is_32bit(hw1) else 2)
            exp = expand(hw1, hw2, pc, machine.options)
            ops = "; ".join(_disassemble(_RV_DIS, op.to_bytes(4, "little"), pc) for op in exp.ops)
            return f"{pc:#010x}  {_disassemble(_THUMB_DIS, code, pc):28} -> {ops}"
        code = machine.mem.read_bytes(pc, 4)
        return f"{pc:#010x}  {_disassemble(_RV_DIS, code, pc)}  (RV32)"
    except Trap:
        return f"{pc:#010x}  <unmapped>"


def _model_flags(m):
    return m.x[regmap.FN] << 3 | m.x[regmap.FZ] << 2 | m.x[regmap.FC] << 1 | m.x[regmap.FV]


def _compare(m, ref, thumb_step):
    problems = []
    if m.pc & ~1 != ref.pc & ~1:
        problems.append(f"next PC: reference {ref.pc:#010x}, model {m.pc:#010x}")
    for i in range(15):
        want, got = ref.reg(i), m.x[regmap.rv(i)]
        if want != got:
            problems.append(f"r{i}: reference {want:#010x}, model {got:#010x}")
    for x in PRESERVED:
        if ref.rv.x[x] != m.x[x]:
            problems.append(f"x{x}: reference {ref.rv.x[x]:#010x}, model {m.x[x]:#010x}")
    if thumb_step and ref.flags != _model_flags(m):
        problems.append(f"NZCV: reference {ref.flags:04b}, model {_model_flags(m):04b}")
    if sorted(ref.writes) != sorted(m.mem.log):
        fmt = lambda ws: ", ".join(f"[{a:#x}]{s}={v:#x}" for a, s, v in sorted(ws)) or "none"
        problems.append(f"writes: reference {fmt(ref.writes)}; model {fmt(m.mem.log)}")
    return problems


def _load_model(images, layout, options):
    m = Machine(thumb_regions=layout.thumb_regions, options=options)
    for base, size in layout.regions:
        m.mem.map(base, size)
    for img in images:
        for seg in img.segments:
            m.mem.write_bytes(seg.addr, seg.data)
    return m


def simulate(images, stop: int, entry: int | None = None, max_steps: int = 50_000_000,
             options: Options = Options()) -> Result:
    """Run the model alone (no reference) from `entry` until pc == `stop`."""
    layout = Layout.for_images(images)
    m = _load_model(images, layout, options)
    m.pc = (images[0].entry if entry is None else entry) & ~1
    stop &= ~1
    result = Result(model=m)
    try:
        while result.steps < max_steps and m.pc != stop:
            m.step()
            result.steps += 1
        result.stopped = "stop address" if m.pc == stop else "max steps"
    except Trap as trap:
        result.stopped = f"model trap: {trap}"
        result.divergence = Divergence(result.steps, m.pc, describe(m, layout, m.pc), [result.stopped])
    result.thumb_steps, result.rv_ops = m.retired_thumb, m.retired_ops
    result.final_regs = [m.x[regmap.rv(i)] for i in range(15)]
    return result


def run(images, stop: int, entry: int | None = None, max_steps: int = 2_000_000,
        history: int = 8) -> Result:
    """Run the model and the reference in lockstep from `entry` until pc == `stop`.

    `entry` defaults to the entry point of the first image.
    """
    layout = Layout.for_images(images)
    m = _load_model(images, layout, Options(exact_lr=True))
    ref = Reference(layout, images)
    m.pc = ref.pc = (images[0].entry if entry is None else entry) & ~1
    stop &= ~1

    result = Result()
    recent = deque(maxlen=history)
    while result.steps < max_steps:
        if m.pc == stop:
            result.stopped = "stop address"
            break
        pc, thumb_step = m.pc, layout.in_thumb(m.pc)
        text = describe(m, layout, pc)
        m.mem.log = []
        ref.writes.clear()
        ops_before = m.retired_ops
        try:
            m.step()
        except Trap as trap:
            result.stopped = f"model trap: {trap}"
            result.divergence = Divergence(result.steps, pc, text, [result.stopped], list(recent))
            break
        try:
            ref.step(_model_flags(m))
        except (ReferenceFault, Trap) as fault:
            result.stopped = f"reference fault: {fault}"
            result.divergence = Divergence(result.steps, pc, text, [result.stopped], list(recent))
            break
        result.steps += 1
        result.thumb_steps += thumb_step
        result.rv_ops += m.retired_ops - ops_before
        problems = _compare(m, ref, thumb_step)
        if problems:
            result.divergence = Divergence(result.steps, pc, text, problems, list(recent))
            result.stopped = "divergence"
            break
        recent.append(text)
    else:
        result.stopped = "max steps"

    if result.ok:
        for base, size in layout.regions:
            if bytes(ref.uc.mem_read(base, size)) != m.mem.read_bytes(base, size):
                result.divergence = Divergence(result.steps, m.pc, "end of run",
                                               [f"memory differs in {base:#x}+{size:#x}"])
                result.stopped = "divergence"
                break
    result.final_regs = [m.x[regmap.rv(i)] for i in range(15)]
    result.model = m
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run ELF images in the model and the reference in lockstep.")
    parser.add_argument("elf", nargs="+", help="ELF images; the first one's entry point is used")
    parser.add_argument("--stop", default="done", help="symbol (or address) to stop at")
    parser.add_argument("--max-steps", type=int, default=2_000_000)
    args = parser.parse_args(argv)

    images = [elf.load(p) for p in args.elf]
    symbols = {k: v for img in images for k, v in img.symbols.items()}
    stop = symbols[args.stop] if args.stop in symbols else int(args.stop, 0)
    result = run(images, stop, max_steps=args.max_steps)
    print(f"{result.steps} steps ({result.thumb_steps} Thumb instructions, "
          f"{result.rv_ops} RV32 ops in the model), stopped: {result.stopped}")
    if result.divergence:
        print(result.divergence)
        return 1
    print(f"r0 = {result.final_regs[0]:#010x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
