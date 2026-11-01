"""The RTL expander against the model (Phases 2.3, 3.1): every 16-bit
instruction at both PC alignments and a large sweep of the 32-bit ones, op by
op through each expansion.

The rule (rtl/core/src/main/scala/thumbv/Thumb.scala): for every instruction
the RTL implements so far, op k of the RTL's expansion is op k of the model's
(Options(flags="none"), the hardware's mode until its flags unit), bit for
bit, and `last` marks the model's last op. Every other instruction is the
illegal instruction, as a single op. Neither op 0 nor the expansion's length
may depend on the PC's alignment, because the fetcher expands op 0 and
decides whether it's the last before the alignment is known.
"""

import random

import pytest

from thumbv import expander, isa, rtlsim
from thumbv import rv32 as r
from thumbv.build import ToolMissing

from conftest import REQUIRE_RTL

NONE = expander.Options(flags="none")
BASE = 0x1_4000

# Multi-op instructions the RTL implements, by step of the plan.
MULTI_OP = {
    # 3.1: two- to five-op sequences.
    "LDR_lit", "ADR", "BICS", "SXTH", "SXTB", "UXTH", "BL",
    "STR_reg", "STRH_reg", "STRB_reg", "LDRSB_reg", "LDR_reg", "LDRH_reg", "LDRB_reg", "LDRSH_reg",
    "ADD_hi", "MOV_hi", "BX", "BLX",
    # 3.2: register lists.
    "PUSH", "POP", "LDM", "STM",
}


def expected(hw1, hw2, pc1):
    """The RTL's expansion: [(op, last), ...]."""
    e = expander.expand(hw1, hw2, BASE + 2 * pc1, NONE)
    if len(e.ops) > 1 and e.name not in MULTI_OP:
        return [(r.ILLEGAL, True)]
    return [(op, k == len(e.ops) - 1) for k, op in enumerate(e.ops)]


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


def check(instructions, alignments, tmp_path):
    """Compare every op of every instruction; returns the RTL's expansions."""
    queries, wanted = [], []
    for hw1, hw2 in instructions:
        for pc1 in alignments:
            want = expected(hw1, hw2, pc1)
            other = expected(hw1, hw2, 1 - pc1)
            assert want[0] == other[0], f"{hw1:04x}: op 0 depends on the PC"
            assert len(want) == len(other), f"{hw1:04x}: the length depends on the PC"
            for step, item in enumerate(want):
                queries.append((hw1, hw2, pc1, step))
                wanted.append(item)
    got = rtlsim.expand_rtl(queries, tmp_path)
    assert len(got) == len(queries)
    wrong = [(q, g, w) for q, g, w in zip(queries, got, wanted) if g != w]
    report = "\n".join(
        f"{hw1:04x} {hw2:04x} pc1={pc1} step={step} "
        f"{expander.expand(hw1, hw2, BASE + 2 * pc1, NONE).name:10} "
        f"RTL {g[0]:08x}{' last' if g[1] else ''}, model {w[0]:08x}{' last' if w[1] else ''}"
        for (hw1, hw2, pc1, step), g, w in wrong[:20])
    assert not wrong, f"{len(wrong)} of {len(queries)} ops differ:\n{report}"
    return got


def test_every_16bit_instruction(expander_sim, tmp_path):
    got = check(instructions_16(), (0, 1), tmp_path)
    assert sum(op != r.ILLEGAL for op, _ in got) > 80_000


def test_32bit_instructions(expander_sim, tmp_path):
    check(instructions_32(), (0,), tmp_path)
