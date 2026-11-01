"""Thumb to RV32 expander: the golden model of the hardware expander.

`expand()` turns one Thumb instruction into a sequence of RV32 instruction
words, following docs/isa-coverage.md. Rules every sequence obeys:

- Every op executes with pc = the Thumb instruction's address (PC-hold), so
  `auipc` yields that address. ARM's "PC reads as PC+4" is added explicitly.
- A link value (`jal`/`jalr` rd) is the Thumb address plus the Thumb
  instruction's length (Q2). LR bit 0 is left clear unless
  `Options.exact_lr` is set (Q1).
- Only the last op may transfer control. A sequence can't branch within
  itself, because its ops share one PC; flag logic is therefore branch-free.
- ARM-visible state may be written in any order: interrupts are only taken
  between Thumb instructions (D3).

Flags follow strategy A: N, Z, C and V each held as 0 or 1 in their own
register (regmap.FN/FZ/FC/FV). `Options.flags = "none"` is the hardware's
interim mode until its flags unit (Phase 4): flag-setting instructions
compute only their result, compares do nothing, and instructions that read
the flags (ADCS, SBCS, B<cond>, MRS/MSR of the APSR) are illegal, so code
that depends on flags traps instead of going wrong.
"""

from dataclasses import dataclass

from . import isa
from . import rv32 as r
from .regmap import FC, FN, FV, FZ, LR, PC, SP, T1, T2, T3, T4, T5, T6, rv


@dataclass(frozen=True)
class Options:
    exact_lr: bool = False  # set bit 0 of LR on BL/BLX, as a real Cortex-M does
    flags: str = "A"        # "A": strategy A; "none": results only (see above)

    def __post_init__(self):
        if self.flags not in ("A", "none"):
            raise ValueError(f"unknown flags mode {self.flags!r}")


@dataclass(frozen=True)
class Expansion:
    name: str               # encoding name from isa.py, or "UNDEFINED"
    ops: tuple[int, ...]    # RV32 instruction words
    length: int             # Thumb instruction length: the PC advance after the last op


def expand(hw1: int, hw2: int = 0, pc: int = 0, options: Options = Options()) -> Expansion:
    decoded = isa.decode(hw1, hw2)
    if decoded is None:
        return Expansion("UNDEFINED", (r.ILLEGAL,), 4 if isa.is_32bit(hw1) else 2)
    enc, f = decoded
    # Handlers shared by several encodings tell them apart by name.
    ops = _HANDLERS[enc.name]({**f, "_name": enc.name}, pc, options)
    return Expansion(enc.name, tuple(ops), enc.length)


_HANDLERS = {}


def _handles(*names):
    def register(fn):
        for name in names:
            _HANDLERS[name] = fn
        return fn
    return register


def _sext(value, bits):
    sign = 1 << (bits - 1)
    return (value & (sign - 1)) - (value & sign)


def _read(arm_reg, scratch):
    """Ops and register to read ARM register `arm_reg`; the PC reads as PC+4."""
    if arm_reg == PC:
        return [r.auipc(scratch, 0), r.addi(scratch, scratch, 4)], scratch
    return [], rv(arm_reg)


def _pc_relative(pc, imm):
    """Offset from the Thumb address to Align(PC+4, 4) + imm."""
    return ((pc + 4) & ~3) - pc + imm


# --- Flags (strategy A) -------------------------------------------------------

def _nz(res):
    return [r.srli(FN, res, 31), r.sltiu(FZ, res, 1)]


def _add_cv(a, b, res, imm=None):
    """C and V for res = a + b, or a + imm (0 <= imm < 2048)."""
    return [
        r.sltu(FC, res, a),
        r.xor(T5, res, a),
        r.xori(T6, res, imm) if imm is not None else r.xor(T6, res, b),
        r.and_(T5, T5, T6),
        r.srli(FV, T5, 31),
    ]


def _sub_cv(a, b, res, imm=None):
    """C and V for res = a - b, or a - imm (0 <= imm < 2048). ARM's C is NOT borrow."""
    return [
        r.sltiu(FC, a, imm) if imm is not None else r.sltu(FC, a, b),
        r.xori(FC, FC, 1),
        r.xori(T5, a, imm) if imm is not None else r.xor(T5, a, b),
        r.xor(T6, a, res),
        r.and_(T5, T5, T6),
        r.srli(FV, T5, 31),
    ]


def _with_flags(o, rd, sources, compute, cv):
    """Compute into rd (or T1 if rd is also a source), set NZCV, then move to rd.

    `rd` is None for compare instructions, whose result only feeds the flags.
    Without flags, just the result; a compare does nothing.
    """
    if o.flags == "none":
        return compute(rd) if rd is not None else [r.nop()]
    dst = rd if rd is not None and rd not in sources else T1
    ops = compute(dst) + _nz(dst) + cv(dst)
    if rd is not None and dst != rd:
        ops.append(r.mv(rd, dst))
    return ops


def _adc(rd, a, b):
    """rd = a + b + C with NZCV. Also used for SBCS as a + NOT(b) + C."""
    return [
        r.add(T1, a, b),
        r.sltu(T2, T1, a),        # carry out of a + b
        r.add(T3, T1, FC),        # result
        r.sltu(T1, T3, T1),       # carry out of + C
        r.or_(FC, T2, T1),
        r.xor(T5, T3, a),
        r.xor(T6, T3, b),
        r.and_(T5, T5, T6),
        r.srli(FV, T5, 31),
        *_nz(T3),
        r.mv(rd, T3),
    ]


def _result(o, result, flag_ops):
    """`result` alone without flags, else `result` and the flag ops.

    Each is a list; `flag_ops` is a function of nothing, so it isn't built
    when unused. The order (flag ops around the result) is the caller's.
    """
    return result if o.flags == "none" else flag_ops()


def _reads_flags(o):
    """Without flags, instructions that read them are illegal."""
    return o.flags == "none"


def _keep_c_if_zero_amount(new_c, amount):
    """FC = new_c, unless the shift amount is 0, which leaves C unchanged."""
    return [
        r.sltiu(T3, amount, 1),
        r.and_(T5, FC, T3),
        r.xori(T3, T3, 1),
        r.and_(new_c, new_c, T3),
        r.or_(FC, new_c, T5),
    ]


# --- Shift (immediate), add, subtract, move, compare -----------------------------

@_handles("LSLS_imm")
def _lsls_imm(f, pc, o):
    rd, rm, k = rv(f["d"]), rv(f["m"]), f["i"]  # k != 0: k == 0 decodes as MOVS_reg
    return _result(o, [r.slli(rd, rm, k)],
                   lambda: [r.srli(FC, rm, 32 - k), r.andi(FC, FC, 1), r.slli(rd, rm, k), *_nz(rd)])


@_handles("MOVS_reg")
def _movs_reg(f, pc, o):
    rd, rm = rv(f["d"]), rv(f["m"])
    return _result(o, [r.mv(rd, rm)], lambda: [r.mv(rd, rm), *_nz(rd)])


@_handles("LSRS_imm", "ASRS_imm")
def _shift_right_imm(f, pc, o):
    rd, rm = rv(f["d"]), rv(f["m"])
    k = f["i"] or 32  # imm5 = 0 encodes a shift by 32
    if f["_name"] == "LSRS_imm":
        result = r.addi(rd, 0, 0) if k == 32 else r.srli(rd, rm, k)
    else:
        result = r.srai(rd, rm, min(k, 31))
    return _result(o, [result], lambda: [r.srli(FC, rm, k - 1), r.andi(FC, FC, 1), result, *_nz(rd)])


@_handles("ADDS_reg")
def _adds_reg(f, pc, o):
    rd, rn, rm = rv(f["d"]), rv(f["n"]), rv(f["m"])
    return _with_flags(o, rd, (rn, rm), lambda d: [r.add(d, rn, rm)],
                       lambda d: _add_cv(rn, rm, d))


@_handles("SUBS_reg")
def _subs_reg(f, pc, o):
    rd, rn, rm = rv(f["d"]), rv(f["n"]), rv(f["m"])
    return _with_flags(o, rd, (rn, rm), lambda d: [r.sub(d, rn, rm)],
                       lambda d: _sub_cv(rn, rm, d))


@_handles("ADDS_imm3", "ADDS_imm8")
def _adds_imm(f, pc, o):
    rd = rv(f["d"])
    rn = rv(f["n"]) if "n" in f else rd
    imm = f["i"]
    return _with_flags(o, rd, (rn,), lambda d: [r.addi(d, rn, imm)],
                       lambda d: _add_cv(rn, None, d, imm=imm))


@_handles("SUBS_imm3", "SUBS_imm8")
def _subs_imm(f, pc, o):
    rd = rv(f["d"])
    rn = rv(f["n"]) if "n" in f else rd
    imm = f["i"]
    return _with_flags(o, rd, (rn,), lambda d: [r.addi(d, rn, -imm)],
                       lambda d: _sub_cv(rn, None, d, imm=imm))


@_handles("MOVS_imm")
def _movs_imm(f, pc, o):
    rd = rv(f["d"])
    return _result(o, [r.addi(rd, 0, f["i"])], lambda: [r.addi(rd, 0, f["i"]), *_nz(rd)])


@_handles("CMP_imm")
def _cmp_imm(f, pc, o):
    rn, imm = rv(f["n"]), f["i"]
    return _with_flags(o, None, (), lambda d: [r.addi(d, rn, -imm)],
                       lambda d: _sub_cv(rn, None, d, imm=imm))


# --- Data processing (register) -------------------------------------------------

_LOGICAL = {"ANDS": r.and_, "EORS": r.xor, "ORRS": r.or_}


@_handles(*_LOGICAL)
def _logical(f, pc, o):
    rdn, rm = rv(f["d"]), rv(f["m"])
    op = _LOGICAL[f["_name"]](rdn, rdn, rm)
    return _result(o, [op], lambda: [op, *_nz(rdn)])


@_handles("BICS")
def _bics(f, pc, o):
    rdn, rm = rv(f["d"]), rv(f["m"])
    ops = [r.xori(T1, rm, -1), r.and_(rdn, rdn, T1)]
    return _result(o, ops, lambda: [*ops, *_nz(rdn)])


@_handles("MVNS")
def _mvns(f, pc, o):
    rd, rm = rv(f["d"]), rv(f["m"])
    return _result(o, [r.xori(rd, rm, -1)], lambda: [r.xori(rd, rm, -1), *_nz(rd)])


@_handles("MULS")
def _muls(f, pc, o):
    rdm, rn = rv(f["d"]), rv(f["n"])
    return _result(o, [r.mul(rdm, rn, rdm)], lambda: [r.mul(rdm, rn, rdm), *_nz(rdm)])


@_handles("TST")
def _tst(f, pc, o):
    rn, rm = rv(f["n"]), rv(f["m"])
    return _result(o, [r.nop()], lambda: [r.and_(T1, rn, rm), *_nz(T1)])


@_handles("RSBS")
def _rsbs(f, pc, o):
    rd, rn = rv(f["d"]), rv(f["n"])
    return _with_flags(o, rd, (rn,), lambda d: [r.sub(d, 0, rn)],
                       lambda d: _sub_cv(0, rn, d))


@_handles("CMP_reg")
def _cmp_reg(f, pc, o):
    rn, rm = rv(f["n"]), rv(f["m"])
    return _with_flags(o, None, (), lambda d: [r.sub(d, rn, rm)],
                       lambda d: _sub_cv(rn, rm, d))


@_handles("CMN")
def _cmn(f, pc, o):
    rn, rm = rv(f["n"]), rv(f["m"])
    return _with_flags(o, None, (), lambda d: [r.add(d, rn, rm)],
                       lambda d: _add_cv(rn, rm, d))


@_handles("ADCS")
def _adcs(f, pc, o):
    rdn, rm = rv(f["d"]), rv(f["m"])
    if _reads_flags(o):
        return [r.ILLEGAL]
    return _adc(rdn, rdn, rm)


@_handles("SBCS")
def _sbcs(f, pc, o):
    rdn, rm = rv(f["d"]), rv(f["m"])
    if _reads_flags(o):
        return [r.ILLEGAL]
    return [r.xori(T4, rm, -1), *_adc(rdn, rdn, T4)]


@_handles("LSLS_reg")
def _lsls_reg(f, pc, o):
    rdn, rm = rv(f["d"]), rv(f["m"])
    if o.flags == "none":   # zero for amounts of 32 and more
        return [r.andi(T1, rm, 255), r.sll(T4, rdn, T1), r.sltiu(T3, T1, 32), r.sub(T3, 0, T3),
                r.and_(rdn, T4, T3)]
    return [
        r.andi(T1, rm, 255),           # ARM's amount: rm[7:0]
        # C candidate: bit (32 - amount) for amounts 1-32, 0 above 32.
        r.sub(T2, 0, T1),
        r.srl(T2, rdn, T2),
        r.andi(T2, T2, 1),
        r.sltiu(T3, T1, 33),
        r.and_(T2, T2, T3),
        # Result: zero for amounts of 32 and more.
        r.sll(T4, rdn, T1),
        r.sltiu(T3, T1, 32),
        r.sub(T3, 0, T3),
        r.and_(T4, T4, T3),
        *_keep_c_if_zero_amount(T2, T1),
        r.mv(rdn, T4),
        *_nz(rdn),
    ]


@_handles("LSRS_reg")
def _lsrs_reg(f, pc, o):
    rdn, rm = rv(f["d"]), rv(f["m"])
    if o.flags == "none":
        return [r.andi(T1, rm, 255), r.srl(T4, rdn, T1), r.sltiu(T3, T1, 32), r.sub(T3, 0, T3),
                r.and_(rdn, T4, T3)]
    return [
        r.andi(T1, rm, 255),
        # C candidate: bit (amount - 1) for amounts 1-32, 0 above 32.
        r.addi(T2, T1, -1),
        r.srl(T2, rdn, T2),
        r.andi(T2, T2, 1),
        r.sltiu(T3, T1, 33),
        r.and_(T2, T2, T3),
        r.srl(T4, rdn, T1),
        r.sltiu(T3, T1, 32),
        r.sub(T3, 0, T3),
        r.and_(T4, T4, T3),
        *_keep_c_if_zero_amount(T2, T1),
        r.mv(rdn, T4),
        *_nz(rdn),
    ]


@_handles("ASRS_reg")
def _asrs_reg(f, pc, o):
    rdn, rm = rv(f["d"]), rv(f["m"])
    if o.flags == "none":   # amounts of 32 and more behave as 31
        return [r.andi(T1, rm, 255), r.sltiu(T3, T1, 32), r.addi(T3, T3, -1), r.or_(T3, T1, T3),
                r.sra(rdn, rdn, T3)]
    return [
        r.andi(T1, rm, 255),
        # C candidate: bit min(amount - 1, 31). Saturate: OR with -1 if >= 32.
        r.addi(T2, T1, -1),
        r.sltiu(T3, T2, 32),
        r.addi(T3, T3, -1),
        r.or_(T2, T2, T3),
        r.srl(T2, rdn, T2),
        r.andi(T2, T2, 1),
        # Result: amounts of 32 and more behave as 31 (sign fill).
        r.sltiu(T3, T1, 32),
        r.addi(T3, T3, -1),
        r.or_(T3, T1, T3),
        r.sra(T4, rdn, T3),
        *_keep_c_if_zero_amount(T2, T1),
        r.mv(rdn, T4),
        *_nz(rdn),
    ]


@_handles("RORS")
def _rors(f, pc, o):
    rdn, rm = rv(f["d"]), rv(f["m"])
    if o.flags == "none":
        return [r.andi(T3, rm, 31), r.srl(T4, rdn, T3), r.sub(T3, 0, T3), r.sll(T3, rdn, T3),
                r.or_(rdn, T4, T3)]
    return [
        r.andi(T1, rm, 255),
        r.andi(T3, T1, 31),
        r.srl(T4, rdn, T3),
        r.sub(T3, 0, T3),
        r.sll(T3, rdn, T3),
        r.or_(T4, T4, T3),
        r.srli(T2, T4, 31),            # C candidate: result bit 31
        *_keep_c_if_zero_amount(T2, T1),
        r.mv(rdn, T4),
        *_nz(rdn),
    ]


# --- Special data processing and branch exchange ----------------------------------

@_handles("ADD_hi")
def _add_hi(f, pc, o):
    rdn, m = f["D"] << 3 | f["d"], f["m"]
    if rdn == PC:
        read, rm = _read(m, T2)
        return [*read, r.auipc(T1, 0), r.add(T1, T1, rm), r.jalr(0, T1, 4)]
    read, rm = _read(m, T1)
    return [*read, r.add(rv(rdn), rv(rdn), rm)]


@_handles("CMP_hi")
def _cmp_hi(f, pc, o):
    read_n, rn = _read(f["N"] << 3 | f["n"], T2)
    read_m, rm = _read(f["m"], T3)
    if o.flags == "none":
        return [r.nop()]
    return read_n + read_m + _with_flags(o, None, (), lambda d: [r.sub(d, rn, rm)],
                                         lambda d: _sub_cv(rn, rm, d))


@_handles("MOV_hi")
def _mov_hi(f, pc, o):
    rd, m = f["D"] << 3 | f["d"], f["m"]
    if rd == PC:
        read, rm = _read(m, T1)
        return [*read, r.jalr(0, rm, 0)]
    if m == PC:
        return [r.auipc(rv(rd), 0), r.addi(rv(rd), rv(rd), 4)]
    return [r.mv(rv(rd), rv(m))]


@_handles("BX")
def _bx(f, pc, o):
    read, rm = _read(f["m"], T1)
    return [*read, r.jalr(0, rm, 0)]


@_handles("BLX")
def _blx(f, pc, o):
    read, rm = _read(f["m"], T1)
    if o.exact_lr:
        return [*read, r.mv(T1, rm), r.auipc(LR, 0), r.addi(LR, LR, 3), r.jalr(0, T1, 0)]
    return [*read, r.jalr(LR, rm, 0)]


# --- Loads and stores -------------------------------------------------------------

@_handles("LDR_lit")
def _ldr_lit(f, pc, o):
    return [r.auipc(T1, 0), r.lw(rv(f["t"]), T1, _pc_relative(pc, f["i"] * 4))]


_REG_OFFSET = {
    "STR_reg": r.sw, "STRH_reg": r.sh, "STRB_reg": r.sb, "LDRSB_reg": r.lb,
    "LDR_reg": r.lw, "LDRH_reg": r.lhu, "LDRB_reg": r.lbu, "LDRSH_reg": r.lh,
}


@_handles(*_REG_OFFSET)
def _reg_offset(f, pc, o):
    return [r.add(T1, rv(f["n"]), rv(f["m"])), _REG_OFFSET[f["_name"]](rv(f["t"]), T1, 0)]


_IMM_OFFSET = {  # op, immediate scale
    "STR_imm": (r.sw, 4), "LDR_imm": (r.lw, 4), "STRB_imm": (r.sb, 1),
    "LDRB_imm": (r.lbu, 1), "STRH_imm": (r.sh, 2), "LDRH_imm": (r.lhu, 2),
}


@_handles(*_IMM_OFFSET)
def _imm_offset(f, pc, o):
    op, scale = _IMM_OFFSET[f["_name"]]
    return [op(rv(f["t"]), rv(f["n"]), f["i"] * scale)]


@_handles("STR_sp")
def _str_sp(f, pc, o):
    return [r.sw(rv(f["t"]), SP, f["i"] * 4)]


@_handles("LDR_sp")
def _ldr_sp(f, pc, o):
    return [r.lw(rv(f["t"]), SP, f["i"] * 4)]


# --- Address generation and stack adjustment ---------------------------------------

@_handles("ADR")
def _adr(f, pc, o):
    rd = rv(f["d"])
    return [r.auipc(rd, 0), r.addi(rd, rd, _pc_relative(pc, f["i"] * 4))]


@_handles("ADD_rd_sp")
def _add_rd_sp(f, pc, o):
    return [r.addi(rv(f["d"]), SP, f["i"] * 4)]


@_handles("ADD_sp")
def _add_sp(f, pc, o):
    return [r.addi(SP, SP, f["i"] * 4)]


@_handles("SUB_sp")
def _sub_sp(f, pc, o):
    return [r.addi(SP, SP, -f["i"] * 4)]


# --- Miscellaneous ----------------------------------------------------------------

@_handles("SXTH")
def _sxth(f, pc, o):
    rd, rm = rv(f["d"]), rv(f["m"])
    return [r.slli(rd, rm, 16), r.srai(rd, rd, 16)]


@_handles("SXTB")
def _sxtb(f, pc, o):
    rd, rm = rv(f["d"]), rv(f["m"])
    return [r.slli(rd, rm, 24), r.srai(rd, rd, 24)]


@_handles("UXTH")
def _uxth(f, pc, o):
    rd, rm = rv(f["d"]), rv(f["m"])
    return [r.slli(rd, rm, 16), r.srli(rd, rd, 16)]


@_handles("UXTB")
def _uxtb(f, pc, o):
    return [r.andi(rv(f["d"]), rv(f["m"]), 255)]


def _reg_list(bits):
    return [k for k in range(8) if bits >> k & 1]


@_handles("PUSH")
def _push(f, pc, o):
    regs = _reg_list(f["r"]) + ([14] if f["M"] else [])
    n = len(regs)
    if n == 0:  # UNPREDICTABLE
        return [r.nop()]
    stores = [r.sw(rv(reg), SP, 4 * (i - n)) for i, reg in enumerate(regs)]
    return [*stores, r.addi(SP, SP, -4 * n)]


@_handles("POP")
def _pop(f, pc, o):
    regs = _reg_list(f["r"])
    n = len(regs) + f["P"]
    if n == 0:  # UNPREDICTABLE
        return [r.nop()]
    loads = [r.lw(rv(reg), SP, 4 * i) for i, reg in enumerate(regs)]
    if f["P"]:
        return [*loads, r.lw(T1, SP, 4 * (n - 1)), r.addi(SP, SP, 4 * n), r.jalr(0, T1, 0)]
    return [*loads, r.addi(SP, SP, 4 * n)]


@_handles("CPSID")
def _cpsid(f, pc, o):
    return [r.csrrci(0, r.MSTATUS, r.MSTATUS_MIE)]


@_handles("CPSIE")
def _cpsie(f, pc, o):
    return [r.csrrsi(0, r.MSTATUS, r.MSTATUS_MIE)]


@_handles("REV")
def _rev(f, pc, o):
    rd, rm = rv(f["d"]), rv(f["m"])
    return [
        r.srli(T1, rm, 24),
        r.slli(T2, rm, 24),
        r.or_(T1, T1, T2),
        r.lui(T3, 0x10),
        r.addi(T3, T3, -256),          # 0x0000FF00
        r.srli(T2, rm, 8),
        r.and_(T2, T2, T3),
        r.or_(T1, T1, T2),
        r.and_(T2, rm, T3),
        r.slli(T2, T2, 8),
        r.or_(rd, T1, T2),
    ]


@_handles("REV16")
def _rev16(f, pc, o):
    rd, rm = rv(f["d"]), rv(f["m"])
    return [
        r.lui(T3, 0xFF0),
        r.addi(T3, T3, 0xFF),          # 0x00FF00FF
        r.srli(T1, rm, 8),
        r.and_(T1, T1, T3),
        r.and_(T2, rm, T3),
        r.slli(T2, T2, 8),
        r.or_(rd, T1, T2),
    ]


@_handles("REVSH")
def _revsh(f, pc, o):
    rd, rm = rv(f["d"]), rv(f["m"])
    return [
        r.slli(T1, rm, 24),
        r.srai(T1, T1, 16),            # low byte -> bits 15:8, sign-extended
        r.srli(T2, rm, 8),
        r.andi(T2, T2, 255),
        r.or_(rd, T1, T2),
    ]


@_handles("BKPT")
def _bkpt(f, pc, o):
    return [r.ebreak()]


@_handles("NOP", "YIELD", "SEV", "WFE")  # WFE as a nop: Q5
def _hint_nop(f, pc, o):
    return [r.nop()]


@_handles("WFI")
def _wfi(f, pc, o):
    return [r.wfi()]


# --- Load and store multiple ---------------------------------------------------------

@_handles("STM")
def _stm(f, pc, o):
    rn, regs = rv(f["n"]), _reg_list(f["r"])
    if not regs:  # UNPREDICTABLE
        return [r.nop()]
    return [*(r.sw(rv(reg), rn, 4 * i) for i, reg in enumerate(regs)),
            r.addi(rn, rn, 4 * len(regs))]


@_handles("LDM")
def _ldm(f, pc, o):
    n, regs = f["n"], _reg_list(f["r"])
    if not regs:  # UNPREDICTABLE
        return [r.nop()]
    rn = rv(n)
    # Addresses ascend with register number; the base register is loaded last.
    order = [reg for reg in regs if reg != n] + [reg for reg in regs if reg == n]
    ops = [r.lw(rv(reg), rn, 4 * regs.index(reg)) for reg in order]
    if n not in regs:
        ops.append(r.addi(rn, rn, 4 * len(regs)))
    return ops


# --- Branches and exception generation -------------------------------------------------

def _cond_branch(cond, off):
    return {
        0x0: [r.bne(FZ, 0, off)],                  # EQ: Z
        0x1: [r.beq(FZ, 0, off)],                  # NE: !Z
        0x2: [r.bne(FC, 0, off)],                  # CS: C
        0x3: [r.beq(FC, 0, off)],                  # CC: !C
        0x4: [r.bne(FN, 0, off)],                  # MI: N
        0x5: [r.beq(FN, 0, off)],                  # PL: !N
        0x6: [r.bne(FV, 0, off)],                  # VS: V
        0x7: [r.beq(FV, 0, off)],                  # VC: !V
        0x8: [r.bltu(FZ, FC, off)],                # HI: C && !Z
        0x9: [r.bgeu(FZ, FC, off)],                # LS: !C || Z
        0xA: [r.beq(FN, FV, off)],                 # GE: N == V
        0xB: [r.bne(FN, FV, off)],                 # LT: N != V
        0xC: [r.xor(T1, FN, FV), r.or_(T1, T1, FZ), r.beq(T1, 0, off)],  # GT
        0xD: [r.xor(T1, FN, FV), r.or_(T1, T1, FZ), r.bne(T1, 0, off)],  # LE
    }[cond]


@_handles("B_cond")
def _b_cond(f, pc, o):
    if _reads_flags(o):
        return [r.ILLEGAL]
    return _cond_branch(f["c"], _sext(f["i"], 8) * 2 + 4)


@_handles("UDF")
def _udf(f, pc, o):
    return [r.ILLEGAL]


@_handles("SVC")
def _svc(f, pc, o):
    return [r.ecall()]


@_handles("B")
def _b(f, pc, o):
    return [r.jal(0, _sext(f["i"], 11) * 2 + 4)]


# --- 32-bit instructions -------------------------------------------------------------

@_handles("BL")
def _bl(f, pc, o):
    s = f["s"]
    i1, i2 = 1 - (f["j"] ^ s), 1 - (f["k"] ^ s)
    imm = _sext(s << 24 | i1 << 23 | i2 << 22 | f["i"] << 1, 25)
    off = imm + 4
    link = [r.auipc(LR, 0), r.addi(LR, LR, 5)] if o.exact_lr else []
    rd = 0 if o.exact_lr else LR
    if -(1 << 20) <= off < (1 << 20):
        return [*link, r.jal(rd, off)]
    hi, lo = r.split_offset(off)
    return [r.auipc(T1, hi), *link, r.jalr(rd, T1, lo)]


_APSR, _PRIMASK = 0, 16  # SYSm values handled inline (Q7); others trap


@_handles("MSR")
def _msr(f, pc, o):
    n, sysm = f["n"], f["s"]
    if n in (13, PC):  # UNPREDICTABLE
        return [r.ILLEGAL]
    rn = rv(n)
    if sysm == _APSR:
        if _reads_flags(o):     # writes them, but without a flags unit there's nowhere to put them
            return [r.ILLEGAL]
        return [
            r.srli(FN, rn, 31),
            r.srli(FZ, rn, 30), r.andi(FZ, FZ, 1),
            r.srli(FC, rn, 29), r.andi(FC, FC, 1),
            r.srli(FV, rn, 28), r.andi(FV, FV, 1),
        ]
    if sysm == _PRIMASK:  # PRIMASK = 1 masks interrupts: MIE = NOT rn[0]
        return [
            r.andi(T1, rn, 1),
            r.xori(T1, T1, 1),
            r.slli(T1, T1, 3),
            r.csrrci(0, r.MSTATUS, r.MSTATUS_MIE),
            r.csrrs(0, r.MSTATUS, T1),
        ]
    return [r.ILLEGAL]


@_handles("MRS")
def _mrs(f, pc, o):
    d, sysm = f["d"], f["s"]
    if d in (13, PC):  # UNPREDICTABLE
        return [r.ILLEGAL]
    rd = rv(d)
    if sysm == _APSR:
        if _reads_flags(o):
            return [r.ILLEGAL]
        return [
            r.slli(T1, FN, 31),
            r.slli(T2, FZ, 30), r.or_(T1, T1, T2),
            r.slli(T2, FC, 29), r.or_(T1, T1, T2),
            r.slli(T2, FV, 28), r.or_(rd, T1, T2),
        ]
    if sysm == _PRIMASK:
        return [r.csrrs(T1, r.MSTATUS, 0), r.srli(T1, T1, 3), r.andi(T1, T1, 1),
                r.xori(rd, T1, 1)]
    return [r.ILLEGAL]


@_handles("DSB", "DMB")
def _barrier(f, pc, o):
    return [r.fence()]


@_handles("ISB")
def _isb(f, pc, o):
    return [r.fence_i()]


assert set(_HANDLERS) == set(isa.BY_NAME), "every encoding needs exactly one expansion"
