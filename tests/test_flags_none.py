"""The expander's result-only flags mode (Options(flags="none"), Phase 2).

Every 16-bit instruction whose expansion differs from strategy A must leave
the same ARM registers as strategy A (flags and expander temporaries aside),
or be illegal if it reads the flags.
"""

import random

import pytest

from thumbv import expander, isa
from thumbv import rv32 as r
from thumbv.machine import Machine
from thumbv.regmap import ARM_TO_RV

A, NONE = expander.Options(), expander.Options(flags="none")
CODE = 0x1_0000
READS_FLAGS = {"ADCS", "SBCS", "B_cond"}


def differing_halfwords():
    """16-bit halfwords whose expansion differs between the two modes."""
    out = []
    for hw in range(0x10000):
        if isa.is_32bit(hw):
            continue
        if expander.expand(hw, 0, CODE, A).ops != expander.expand(hw, 0, CODE, NONE).ops:
            out.append(hw)
    return out


def run_one(hw, regs, options):
    m = Machine(thumb_regions=[(CODE, CODE + 0x1000)], options=options)
    m.mem.map(CODE, 0x1000)
    m.mem.write_bytes(CODE, hw.to_bytes(2, "little"))
    m.pc = CODE
    for arm, value in enumerate(regs):
        m.x[ARM_TO_RV[arm]] = value
    m.step()
    return [m.x[ARM_TO_RV[arm]] for arm in range(15)], m.pc


def test_none_matches_strategy_a():
    rng = random.Random(1)
    halfwords = differing_halfwords()
    assert len(halfwords) > 10_000          # the data-processing space
    for hw in halfwords:
        name = expander.expand(hw, 0, CODE, A).name
        if name in READS_FLAGS:
            assert expander.expand(hw, 0, CODE, NONE).ops == (r.ILLEGAL,), name
            continue
        # Shift amounts: small, 0, 32 and large values all matter.
        values = [rng.choice([0, 1, 31, 32, 33, 255, 256, rng.getrandbits(8), rng.getrandbits(32)])
                  for _ in range(15)]
        values[13] = 0x2000_0000            # SP: unused here, but keep it plausible
        assert run_one(hw, values, NONE) == run_one(hw, values, A), f"{hw:#06x} {name}"


@pytest.mark.parametrize("hw1, hw2, name", [
    (0xF3EF, 0x8000, "MRS"),                # MRS r0, APSR
    (0xF380, 0x8800, "MSR"),                # MSR APSR, r0
])
def test_none_apsr_access_is_illegal(hw1, hw2, name):
    e = expander.expand(hw1, hw2, CODE, NONE)
    assert e.name == name and e.ops == (r.ILLEGAL,)
