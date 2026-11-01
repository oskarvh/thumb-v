"""Phase 2.3: the RTL expander against the model, for every 16-bit instruction
and a large sweep of the 32-bit ones.

The rule (rtl/core/src/main/scala/thumbv/Thumb.scala): wherever the model
(Options(flags="none"), the hardware's mode until its flags unit) expands an
instruction to a single op, the RTL produces that op, bit for bit; everywhere
else it produces the illegal instruction, until the sequencer (Phase 3).
Single-op expansions don't depend on the PC's alignment; the model is checked
at both.
"""

import random

import pytest

from thumbv import expander, isa, rtlsim
from thumbv import rv32 as r
from thumbv.build import ToolMissing

from conftest import REQUIRE_RTL

NONE = expander.Options(flags="none")
PCS = (0x1_0000, 0x1_0002)     # both halfword alignments


def expected(hw1, hw2):
    """The op the RTL must produce, the same at both PC alignments."""
    ops = {expander.expand(hw1, hw2, pc, NONE).ops for pc in PCS}
    assert len(ops) == 1 or all(len(o) > 1 for o in ops), f"{hw1:04x} {hw2:04x} depends on the PC"
    ops = ops.pop()
    return ops[0] if len(ops) == 1 else r.ILLEGAL


def instructions_16():
    rng = random.Random(16)
    return [(hw, rng.getrandbits(16)) for hw in range(0x10000) if not isa.is_32bit(hw)]


def instructions_32():
    """Every 32-bit first halfword with random second halfwords, every second
    halfword for the encodings' first halfwords, and BL's range boundary."""
    rng = random.Random(32)
    firsts = [hw for hw in range(0x10000) if isa.is_32bit(hw)]
    out = [(hw1, rng.getrandbits(16)) for hw1 in firsts for _ in range(16)]
    for hw1 in (0xF000, 0xF400, 0xF7FF, 0xF3BF, 0xF380, 0xF3EF, 0xE800):
        out += [(hw1, hw2) for hw2 in range(0x10000)]
    # BL: every first halfword, every J1/J2 combination, offsets at both ends.
    for hw1 in range(0xF000, 0xF800):
        for jk in (0b00, 0b01, 0b10, 0b11):
            for low in (0x000, 0x7FF, rng.getrandbits(11)):
                out.append((hw1, 0xD000 | (jk >> 1) << 13 | (jk & 1) << 11 | low))
    return out


@pytest.fixture(scope="module")
def expander_sim():
    try:
        return rtlsim.expander_simulator()
    except ToolMissing as missing:
        if REQUIRE_RTL:
            pytest.fail(f"{missing} not found")
        pytest.skip(f"{missing} not found")


def check(instructions, tmp_path):
    rtl = rtlsim.expand_rtl(instructions, tmp_path)
    assert len(rtl) == len(instructions)
    wrong = [(hw1, hw2, got, expected(hw1, hw2)) for (hw1, hw2), got in zip(instructions, rtl)
             if got != expected(hw1, hw2)]
    report = "\n".join(f"{hw1:04x} {hw2:04x} {expander.expand(hw1, hw2, PCS[0], NONE).name:10} "
                       f"RTL {got:08x}, model {want:08x}" for hw1, hw2, got, want in wrong[:20])
    assert not wrong, f"{len(wrong)} of {len(instructions)} differ:\n{report}"
    return rtl


def test_every_16bit_instruction(expander_sim, tmp_path):
    rtl = check(instructions_16(), tmp_path)
    # The 2.2 subset: about 39,000 of the 63,488 16-bit halfwords are single ops.
    assert sum(op != r.ILLEGAL for op in rtl) > 38_000


def test_32bit_instructions(expander_sim, tmp_path):
    check(instructions_32(), tmp_path)
