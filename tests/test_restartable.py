"""Every expansion can be restarted from its first op (Phase 3).

A fault part-way through a Thumb instruction (a load or store that faults)
traps with mepc at the instruction's address, and the handler returns there:
the whole instruction runs again from op 0. That is only correct if the ops
before the faulting one haven't overwritten any of the instruction's inputs,
the registers it reads before writing them. So: no op before a load or store
may write an input register. (ARMv6-M restarts LDM/STM the same way.)
"""

import pytest

from thumbv import expander, isa

_LOAD, _STORE, _OP_IMM, _OP, _LUI, _AUIPC = 0x03, 0x23, 0x13, 0x33, 0x37, 0x17
_BRANCH, _JALR, _JAL, _SYSTEM = 0x63, 0x67, 0x6F, 0x73


def reads_writes(op):
    """(registers read, register written or None) of an RV32 op."""
    opcode, rd, f3 = op & 0x7F, op >> 7 & 31, op >> 12 & 7
    rs1, rs2 = op >> 15 & 31, op >> 20 & 31
    reads = {
        _OP: {rs1, rs2}, _STORE: {rs1, rs2}, _BRANCH: {rs1, rs2},
        _OP_IMM: {rs1}, _LOAD: {rs1}, _JALR: {rs1},
        _SYSTEM: {rs1} if f3 in (1, 2, 3) else set(),
    }.get(opcode, set())
    writes = rd if opcode in (_OP, _OP_IMM, _LOAD, _LUI, _AUIPC, _JAL, _JALR, _SYSTEM) else None
    return reads - {0}, writes or None


def violation(ops):
    """The first problem with restarting `ops`, or None."""
    inputs, written = set(), set()
    for op in ops:
        reads, writes = reads_writes(op)
        inputs |= reads - written
        if writes is not None:
            written.add(writes)
    clobbered = set()
    for i, op in enumerate(ops):
        if op & 0x7F in (_LOAD, _STORE) and clobbered & inputs:
            return f"op {i} can fault after inputs {sorted(clobbered & inputs)} were overwritten"
        _, writes = reads_writes(op)
        if writes is not None:
            clobbered.add(writes)
    return None


@pytest.mark.parametrize("flags", ["none", "A"])
def test_every_16bit_expansion_restarts(flags):
    options = expander.Options(flags=flags)
    bad = []
    for hw in range(0x10000):
        if isa.is_32bit(hw):
            continue
        e = expander.expand(hw, 0, 0x1_4000, options)
        problem = violation(e.ops)
        if problem:
            bad.append(f"{hw:04x} {e.name}: {problem}")
    assert not bad, "\n".join(bad[:20])


def test_the_check_catches_a_bad_order():
    # LDM r0!, {r1, r2} with write-back first: a fault on the second load
    # would restart with r0 already moved.
    from thumbv import rv32 as r
    bad = [r.addi(10, 10, 8), r.lw(11, 10, -8), r.lw(12, 10, -4)]
    assert violation(bad)
    good = [r.lw(11, 10, 0), r.lw(12, 10, 4), r.addi(10, 10, 8)]
    assert violation(good) is None
