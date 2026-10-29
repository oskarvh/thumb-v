"""Single-instruction lockstep: every encoding, random operands, model vs Unicorn.

For each case: random registers, flags, PRIMASK, code and RAM contents, and a
random instance of the encoding at a random PC. Unicorn executes it as a
Cortex-M0; the model executes its RV32 expansion. Registers, flags, next PC,
RAM and PRIMASK must match exactly. The model runs with exact_lr so LR matches.

Cases avoid UNPREDICTABLE encodings and, for register branches, targets with
bit 0 clear: a real Cortex-M faults on those, while Thumb-V ignores bit 0 (Q1).
"""

import random
from dataclasses import dataclass, field

import pytest
import unicorn
from unicorn import arm_const as A

from thumbv import isa, regmap
from thumbv.expander import Options
from thumbv.machine import Machine, Trap

CODE_BASE, CODE_SIZE = 0x1000, 0x2000
RAM_BASE, RAM_SIZE = 0x2000_0000, 0x1000
RAM_END = RAM_BASE + RAM_SIZE
CASES = 300
PARK = b"\xfe\xe7"  # `b .`, placed where Unicorn will fetch next

UC_REGS = [getattr(A, f"UC_ARM_REG_R{i}") for i in range(13)] + [A.UC_ARM_REG_SP, A.UC_ARM_REG_LR]

# Not run here: traps and sleeps are tested separately below.
NOT_LOCKSTEPPED = {"UDF", "SVC", "BKPT", "WFI", "WFE", "YIELD"}

EDGES = [0, 1, 2, 31, 32, 33, 0x7FFFFFFF, 0x80000000, 0x80000001, 0xFFFFFFFF, 0xFFFFFFFE]


@dataclass
class Case:
    name: str
    hw1: int
    hw2: int
    length: int
    regs: list[int]                # r0-r14
    flags: int                     # NZCV
    primask: int
    pc: int
    ram_words: dict[int, int] = field(default_factory=dict)  # forced RAM contents

    def describe(self):
        insn = f"{self.hw1:04x}" + (f" {self.hw2:04x}" if self.length == 4 else "")
        state = ", ".join(f"r{i}={v:#x}" for i, v in enumerate(self.regs))
        return (f"{self.name} [{insn}] at {self.pc:#x}, NZCV={self.flags:04b}, "
                f"PRIMASK={self.primask}, {state}")


def rand_value(rng):
    kind = rng.random()
    if kind < 0.25:
        return rng.choice(EDGES)
    if kind < 0.45:
        return rng.randrange(65)
    if kind < 0.55:  # interesting low byte (shift amounts) under random high bits
        return (rng.getrandbits(32) & ~0xFF) | rng.choice([*range(41), *range(220, 256)])
    return rng.getrandbits(32)


def rand_instance(rng, enc):
    """Random field values for `enc`: (hw1, hw2, fields)."""
    while True:
        word = enc.value | (rng.getrandbits(32) & ~enc.mask & ((1 << (8 * enc.length)) - 1))
        hw1, hw2 = (word >> 16, word & 0xFFFF) if enc.length == 4 else (word, 0)
        decoded = isa.decode(hw1, hw2)
        if decoded and decoded[0] is enc:  # e.g. LSLS #0 decodes as MOVS_reg instead
            return hw1, hw2, decoded[1]


def branch_target(rng):
    """A Thumb address (bit 0 set) in executable memory: the ARMv6-M default
    map makes 0x4000_0000-0x5FFF_FFFF and 0xA000_0000 upwards execute-never."""
    return rng.getrandbits(30) | 1


def ram_addr(rng, size, room=0):
    """A random `size`-aligned RAM address with `room` bytes of space after it."""
    return RAM_BASE + rng.randrange(0, RAM_SIZE - room - size + 1, size)


def make_case(rng, name):
    """One random case for encoding `name`, or None to retry."""
    enc = isa.BY_NAME[name]
    hw1, hw2, f = rand_instance(rng, enc)
    case_pc = CODE_BASE + 2 * rng.randrange(0x1000 // 2)
    regs = [rand_value(rng) for _ in range(13)]
    regs.append(ram_addr(rng, 4))  # SP: word-aligned, in RAM
    regs.append(rand_value(rng))   # LR
    ram_words = {}

    if name.endswith("_imm") and name[:3] in ("STR", "LDR"):
        size = 4 if name[3] == "_" else (1 if name[3] == "B" else 2)
        regs[f["n"]] = (ram_addr(rng, size) - f["i"] * size) & 0xFFFFFFFF
    elif name.endswith("_reg") and name[:3] in ("STR", "LDR"):
        if f["n"] == f["m"]:
            return None
        size = {"": 4, "H": 2, "B": 1, "SB": 1, "SH": 2}[name[3:-4]]
        regs[f["m"]] = (ram_addr(rng, size) - regs[f["n"]]) & 0xFFFFFFFF
    elif name in ("STR_sp", "LDR_sp"):
        regs[13] = ram_addr(rng, 4, room=f["i"] * 4)
    elif name in ("PUSH", "POP", "STM", "LDM"):
        n = bin(f["r"]).count("1") + f.get("M", 0) + f.get("P", 0)
        if n == 0:
            return None
        if name == "STM" and f["r"] >> f["n"] & 1 and f["r"] & ((1 << f["n"]) - 1):
            return None  # base in the list but not lowest: UNKNOWN value stored
        if name == "PUSH":  # stores go below SP
            regs[13] = ram_addr(rng, 4, room=4 * n) + 4 * n
        elif name == "POP":
            regs[13] = ram_addr(rng, 4, room=4 * n)
            if f["P"]:
                ram_words[regs[13] + 4 * (n - 1)] = branch_target(rng)
        else:
            regs[f["n"]] = ram_addr(rng, 4, room=4 * n)
    elif name in ("ADD_hi", "MOV_hi"):
        rd, m = f["D"] << 3 | f["d"], f["m"]
        if rd == 15 and m == 15:
            return None
        if rd == 13:  # SP must stay word-aligned (bits 1:0 are RAZ/WI)
            if m == 15:
                return None
            if m != 13:
                regs[m] &= ~3
        if rd == 15:
            if m == 13:
                return None
            target = branch_target(rng)
            regs[m] = (target - (case_pc + 4)) & 0xFFFFFFFF if name == "ADD_hi" else target
    elif name == "CMP_hi":
        n = f["N"] << 3 | f["n"]
        if (n < 8 and f["m"] < 8) or 15 in (n, f["m"]):
            return None
    elif name in ("BX", "BLX"):
        if f["m"] in (13, 15):  # BX SP: SP is word-aligned, so bit 0 is clear
            return None
        regs[f["m"]] = branch_target(rng)
    elif name == "BL":
        s, i1, i2 = f["s"], 1 - (f["j"] ^ f["s"]), 1 - (f["k"] ^ f["s"])
        imm = s << 24 | i1 << 23 | i2 << 22 | f["i"] << 1
        if case_pc + 4 + imm - (s << 25) < 0:
            return None  # wraps to 0xFFxxxxxx: execute-never
    elif name in ("MSR", "MRS"):
        if f["n" if name == "MSR" else "d"] in (13, 15):
            return None
        hw2 = hw2 & ~0xFF | rng.choice([0, 16])  # APSR or PRIMASK (Q7)
    elif name in ("DSB", "DMB", "ISB"):
        hw2 |= 0xF  # option SY; other options are reserved

    return Case(name, hw1, hw2, enc.length, regs, flags=rng.getrandbits(4),
                primask=rng.getrandbits(1), pc=case_pc,
                ram_words=ram_words)


def run_model(case, code, ram):
    m = Machine(thumb_regions=[(CODE_BASE, CODE_BASE + CODE_SIZE)], options=Options(exact_lr=True))
    m.mem.map(CODE_BASE, CODE_SIZE)
    m.mem.map(RAM_BASE, RAM_SIZE)
    m.mem.write_bytes(CODE_BASE, bytes(code))
    m.mem.write_bytes(RAM_BASE, bytes(ram))
    for i, value in enumerate(case.regs):
        m.x[regmap.rv(i)] = value
    f = case.flags
    m.x[regmap.FN], m.x[regmap.FZ], m.x[regmap.FC], m.x[regmap.FV] = f >> 3, f >> 2 & 1, f >> 1 & 1, f & 1
    m.mstatus = 0 if case.primask else 8
    m.pc = case.pc
    m.step()
    return m


class Unicorn:
    """Unicorn as a Cortex-M0, mapping pages on demand for out-of-range fetches."""

    def __init__(self):
        self.uc = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_THUMB | unicorn.UC_MODE_MCLASS)
        self.uc.ctl_set_cpu_model(A.UC_CPU_ARM_CORTEX_M0)
        self.uc.mem_map(CODE_BASE, CODE_SIZE)
        self.uc.mem_map(RAM_BASE, RAM_SIZE)
        self.extra_pages = []
        self.uc.hook_add(unicorn.UC_HOOK_MEM_FETCH_UNMAPPED, self._map_on_fetch)

    def _map_on_fetch(self, uc, access, address, size, value, user):
        base = address & ~0xFFF
        uc.mem_map(base, 0x1000)
        uc.mem_write(address & ~1, PARK)
        self.extra_pages.append(base)
        return True

    def run(self, case, code, ram):
        uc = self.uc
        uc.mem_write(CODE_BASE, bytes(code))
        uc.ctl_remove_cache(CODE_BASE, CODE_BASE + CODE_SIZE)  # drop stale translated code
        uc.mem_write(RAM_BASE, bytes(ram))
        for reg, value in zip(UC_REGS, case.regs):
            uc.reg_write(reg, value)
        uc.reg_write(A.UC_ARM_REG_XPSR, case.flags << 28 | 1 << 24)
        uc.reg_write(A.UC_ARM_REG_PRIMASK, case.primask)
        try:
            uc.emu_start(case.pc | 1, RAM_END, count=1)
            error = None
        except unicorn.UcError as e:
            error = str(e)
        for base in self.extra_pages:
            uc.mem_unmap(base, 0x1000)
        self.extra_pages.clear()
        return error


@pytest.fixture(scope="module")
def uc():
    return Unicorn()


def park_at(code, ram, addr, case):
    """Put `b .` at addr (where Unicorn fetches next), unless it overlaps the instruction."""
    if case.pc <= addr < case.pc + case.length or case.pc <= addr + 1 < case.pc + case.length:
        return
    addr &= ~1
    if CODE_BASE <= addr < CODE_BASE + CODE_SIZE - 1:
        code[addr - CODE_BASE:addr - CODE_BASE + 2] = PARK
    elif RAM_BASE <= addr < RAM_END - 1:
        ram[addr - RAM_BASE:addr - RAM_BASE + 2] = PARK


def run_case(uc, rng, case):
    code = bytearray(rng.randbytes(CODE_SIZE))
    ram = bytearray(rng.randbytes(RAM_SIZE))
    for addr, word in case.ram_words.items():
        ram[addr - RAM_BASE:addr - RAM_BASE + 4] = word.to_bytes(4, "little")
    insn = case.hw1.to_bytes(2, "little") + (case.hw2.to_bytes(2, "little") if case.length == 4 else b"")
    code[case.pc - CODE_BASE:case.pc - CODE_BASE + case.length] = insn

    try:
        # Unicorn decodes the instruction it stops at, so make that a valid one.
        park_at(code, ram, run_model(case, code, ram).pc, case)
        m = run_model(case, code, ram)
    except Trap as trap:
        return [f"model trap: {trap}"]
    error = uc.run(case, code, ram)
    u = uc.uc

    problems = [f"unicorn error: {error}"] if error else []
    for i, reg in enumerate(UC_REGS):
        want, got = u.reg_read(reg), m.x[regmap.rv(i)]
        if want != got:
            problems.append(f"r{i}: unicorn {want:#010x}, model {got:#010x}")
    want_flags = u.reg_read(A.UC_ARM_REG_XPSR) >> 28
    got_flags = m.x[regmap.FN] << 3 | m.x[regmap.FZ] << 2 | m.x[regmap.FC] << 1 | m.x[regmap.FV]
    if want_flags != got_flags:
        problems.append(f"NZCV: unicorn {want_flags:04b}, model {got_flags:04b}")
    want_pc, got_pc = u.reg_read(A.UC_ARM_REG_PC) & ~1, m.pc & ~1
    if want_pc != got_pc:
        problems.append(f"next PC: unicorn {want_pc:#010x}, model {got_pc:#010x}")
    if u.mem_read(RAM_BASE, RAM_SIZE) != m.mem.read_bytes(RAM_BASE, RAM_SIZE):
        problems.append("RAM differs")
    want_pm, got_pm = u.reg_read(A.UC_ARM_REG_PRIMASK) & 1, int(not m.mstatus & 8)
    if want_pm != got_pm:
        problems.append(f"PRIMASK: unicorn {want_pm}, model {got_pm}")
    return problems


@pytest.mark.parametrize("name", [e.name for e in isa.ENCODINGS if e.name not in NOT_LOCKSTEPPED])
def test_lockstep(uc, name):
    rng = random.Random(f"lockstep-{name}")
    done = 0
    while done < CASES:
        case = make_case(rng, name)
        if case is None:
            continue
        problems = run_case(uc, rng, case)
        if problems:
            pytest.fail(case.describe() + ":\n  " + "\n  ".join(problems))
        done += 1


@pytest.mark.parametrize("hw, cause", [
    (0xDE2A, "illegal_instruction"),   # udf #42
    (0xDF2A, "ecall"),                 # svc #42
    (0xBE2A, "breakpoint"),            # bkpt #42
    (0xB100, "illegal_instruction"),   # cbz: ARMv7-M only, undefined here
])
def test_traps(hw, cause):
    m = Machine(thumb_regions=[(CODE_BASE, CODE_BASE + CODE_SIZE)])
    m.mem.map(CODE_BASE, CODE_SIZE)
    m.mem.write(CODE_BASE, 2, hw)
    m.pc = CODE_BASE
    with pytest.raises(Trap) as trap:
        m.step()
    assert trap.value.cause == cause and trap.value.pc == CODE_BASE


@pytest.mark.parametrize("hw", [0xBF10, 0xBF20, 0xBF30])  # yield, wfe, wfi
def test_sleep_hints_fall_through(hw):
    m = Machine(thumb_regions=[(CODE_BASE, CODE_BASE + CODE_SIZE)])
    m.mem.map(CODE_BASE, CODE_SIZE)
    m.mem.write(CODE_BASE, 2, hw)
    m.pc = CODE_BASE
    m.step()
    assert m.pc == CODE_BASE + 2
