"""Phase 0.7 measurements: the cost breakdown, flag liveness and the strategy costs."""

import pytest

from thumbv import build, elf, isa, measure
from thumbv.measure import C, N, V, Z


def test_breakdown_matches_expander():
    """For every 16-bit encoding, result + flag ops + move add up to the expansion."""
    for hw in range(0x10000):
        if not isa.is_32bit(hw):
            measure.analyse(0x1000, hw, 0)   # asserts the breakdown


PROGRAM = """
    .syntax unified
    .thumb
    .section .text.start, "ax"
    .global _start
    .thumb_func
_start:
    movs r0, #1        @ N, Z dead: the cmp overwrites them
    cmp r0, #1         @ Z read by the beq right after it (fused); N, C, V dead
    beq 1f
    nop
1:  adds r1, r0, r0    @ all dead: the lsls overwrites N, Z, C, the adcs V
    lsls r2, r1, #1    @ N read by the bmi right after it, C by the adcs
    bmi 2f
2:  adcs r3, r3, r3    @ reads C; its own flags are all dead
    movs r4, #0
    lsls r4, r4, r0    @ register shift by 1: writes N, Z, C
    movs r5, #0
    lsls r5, r5, r5    @ register shift by 0: writes N, Z; C passes through
    .global done
done:
    b done
"""


@pytest.fixture
def program(build_thumb_asm):
    image = elf.load(build_thumb_asm("measure", PROGRAM))
    return image, measure.trace([image], stop=image.symbols["done"])


def live_by_name(t):
    out = {}
    for (pc, live, fused, branch), n in t.writes.items():
        out.setdefault(t.statics[pc].name, []).append((live, fused, branch is not None))
    return out


def test_liveness(program):
    _, t = program
    w = live_by_name(t)
    assert w["CMP_imm"] == [(0, Z, True)]
    assert w["ADDS_reg"] == [(0, 0, False)]
    assert w["LSLS_imm"] == [(C, N, True)]
    assert w["ADCS"] == [(0, 0, False)]
    assert w["MOVS_imm"] == [(0, 0, False)] * 3
    assert w["LSLS_reg"] == [(0, 0, False)] * 2
    assert t.cross_call_reads == 0


def test_costs_are_consistent(program):
    _, t = program
    c = measure.costs(t)
    assert c["A"] == t.rv_ops                       # all-Thumb program: every op is accounted
    assert c["peek unsafe"] == 0
    assert c["A oracle"] <= c["A peek-4"] <= c["A peek-2"] <= c["A peek-1"] <= c["A"]
    assert c["A fused"] <= c["A oracle"]
    assert c["C shift"] <= c["C fused imm"] <= c["C fused"] <= c["C"] < c["A"]


def test_peek_stops_at_branches():
    code = {}
    for pc, hw in [(0x100, 0x2001),   # movs r0, #1
                   (0x102, 0xD000),   # beq: reads Z, and the target is unknown
                   (0x104, 0x2002)]:  # movs r0, #2
        code[pc] = measure.analyse(pc, hw, 0)
    assert measure.peek_dead(code, code[0x100], 4) == 0
    code[0x102] = measure.analyse(0x102, 0x2003, 0)   # movs r0, #3 instead: kills N and Z
    assert measure.peek_dead(code, code[0x100], 1) == N | Z


def test_peek_kills_at_calls_and_returns():
    code = {0x100: measure.analyse(0x100, 0x1840, 0),   # adds r0, r0, r1
            0x102: measure.analyse(0x102, 0x4770, 0)}   # bx lr
    assert measure.peek_dead(code, code[0x100], 1) == N | Z | C | V


def test_origins(tmp_path):
    try:
        path = build.float_kernels(tmp_path)
    except build.ToolMissing as missing:
        pytest.skip(f"{missing} not found")
    image = elf.load(path)
    t = measure.trace([image], stop=image.symbols["done"])
    origins = measure.shift_origins(t, path)["by origin"]
    assert origins["soft-float"] > origins.get("program", 0)
