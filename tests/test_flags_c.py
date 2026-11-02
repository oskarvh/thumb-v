"""The expander's strategy C: the hardware flags unit (Options(flags="C"), Phase 4).

Every 16-bit instruction whose expansion differs from strategy A must leave
the same ARM registers, PC and NZCV as strategy A, from random registers and
flags. Plus the side-band rules the hardware relies on.
"""

import random

import pytest

from thumbv import expander, isa, regmap
from thumbv import rv32 as r
from thumbv.machine import Machine
from thumbv.regmap import ARM_TO_RV

A, C = expander.Options(), expander.Options(flags="C")
CODE = 0x1_0000
FLAG_REGS = ((regmap.FN, 8), (regmap.FZ, 4), (regmap.FC, 2), (regmap.FV, 1))
NOT_RUN = {"UNDEFINED", "UDF", "SVC", "BKPT"}     # traps, the same in both
MAX_OPS = 16                                      # the sequencer's 4-bit step


def run_one(hw1, hw2, regs, flags, options):
    m = Machine(thumb_regions=[(CODE, CODE + 0x1000)], options=options)
    m.mem.map(CODE, 0x1000)
    m.mem.write_bytes(CODE, hw1.to_bytes(2, "little") + hw2.to_bytes(2, "little"))
    m.pc = CODE
    for arm, value in enumerate(regs):
        m.x[ARM_TO_RV[arm]] = value
    if options.flags == "C":
        m.nzcv = flags
    else:
        for reg, bit in FLAG_REGS:
            m.x[reg] = int(bool(flags & bit))
    m.step()
    out = m.nzcv if options.flags == "C" else sum(bit for reg, bit in FLAG_REGS if m.x[reg])
    return [m.x[ARM_TO_RV[arm]] for arm in range(15)], m.pc, out


def random_regs(rng):
    values = [rng.choice([0, 1, 31, 32, 33, 255, 256, 0x7FFF_FFFF, 0x8000_0000, 0xFFFF_FFFF,
                          rng.getrandbits(8), rng.getrandbits(32)]) for _ in range(15)]
    values[13] = 0x2000_0000            # SP: unused here, but keep it plausible
    return values


def test_c_matches_strategy_a():
    rng = random.Random(1)
    checked = 0
    for hw in range(0x10000):
        if isa.is_32bit(hw):
            continue
        a = expander.expand(hw, 0, CODE, A)
        if a.name in NOT_RUN or a.ops == expander.expand(hw, 0, CODE, C).ops:
            continue
        for _ in range(4):
            regs, flags = random_regs(rng), rng.getrandbits(4)
            assert run_one(hw, 0, regs, flags, C) == run_one(hw, 0, regs, flags, A), \
                f"{hw:#06x} {a.name} regs {[hex(v) for v in regs]} flags {flags:04b}"
            checked += 1
    assert checked > 80_000         # about 21,000 halfwords: data processing and B<cond>


@pytest.mark.parametrize("hw1, hw2", [
    (0xF380, 0x8800),               # MSR APSR, r0
    (0xF3EF, 0x8000),               # MRS r0, APSR
    (0xF3EF, 0x8700),               # MRS r7, APSR
])
def test_c_apsr_access_matches_strategy_a(hw1, hw2):
    rng = random.Random(hw1 ^ hw2)
    for _ in range(64):
        regs, flags = random_regs(rng), rng.getrandbits(4)
        assert run_one(hw1, hw2, regs, flags, C) == run_one(hw1, hw2, regs, flags, A)


def test_c_side_band_rules():
    """What the hardware relies on: expansions fit the sequencer, only the
    last op may be a conditional branch, and RISC-V words stay 32 bits."""
    longest = 0
    for hw in range(0x10000):
        if isa.is_32bit(hw):
            continue
        ops = expander.expand(hw, 0, CODE, C).ops
        longest = max(longest, len(ops))
        for i, op in enumerate(ops):
            assert op >> (r.SIDEBAND + 8) == 0
            if r.kind(op) == r.BRANCH:
                assert i == len(ops) - 1 and r.word(op) & 0x01FFF07F == 0x63
    assert longest <= MAX_OPS
