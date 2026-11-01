"""RV32IM instruction encoders, plus the few system instructions the expander emits.

Each function returns one 32-bit instruction word. Register arguments are
RISC-V register numbers (0-31); immediates are checked against their ranges.
"""

ILLEGAL = 0x00000000  # defined by the RISC-V spec as an illegal instruction

MSTATUS = 0x300
# Thumb region CSRs (custom machine read/write): base0, limit0, base1, limit1.
# Region i is [base_i, limit_i), word-aligned; the low two bits read as zero.
THUMB_REGION0 = 0x7C0
THUMB_REGIONS = 2
MSTATUS_MIE = 1 << 3
MSTATUS_MPP = 3 << 11   # machine mode, the only one: hard-wired, as on VexRiscv

_LOAD, _STORE, _BRANCH, _JALR, _JAL = 0x03, 0x23, 0x63, 0x67, 0x6F
_OP_IMM, _OP, _LUI, _AUIPC = 0x13, 0x33, 0x37, 0x17
_MISC_MEM, _SYSTEM = 0x0F, 0x73


def _check_reg(*regs):
    for r in regs:
        if not 0 <= r < 32:
            raise ValueError(f"bad register x{r}")


def _check_signed(value, bits, what):
    if not -(1 << (bits - 1)) <= value < (1 << (bits - 1)):
        raise ValueError(f"{what} {value} out of range for {bits} bits")


def _r(funct7, rs2, rs1, funct3, rd, opcode):
    _check_reg(rd, rs1, rs2)
    return funct7 << 25 | rs2 << 20 | rs1 << 15 | funct3 << 12 | rd << 7 | opcode


def _i(imm, rs1, funct3, rd, opcode):
    _check_reg(rd, rs1)
    _check_signed(imm, 12, "immediate")
    return (imm & 0xFFF) << 20 | rs1 << 15 | funct3 << 12 | rd << 7 | opcode


def _s(imm, rs2, rs1, funct3):
    _check_reg(rs1, rs2)
    _check_signed(imm, 12, "offset")
    imm &= 0xFFF
    return (imm >> 5) << 25 | rs2 << 20 | rs1 << 15 | funct3 << 12 | (imm & 0x1F) << 7 | _STORE


def _b(off, rs2, rs1, funct3):
    _check_reg(rs1, rs2)
    _check_signed(off, 13, "branch offset")
    if off & 1:
        raise ValueError("branch offset must be even")
    off &= 0x1FFF
    return ((off >> 12) << 31 | ((off >> 5) & 0x3F) << 25 | rs2 << 20 | rs1 << 15
            | funct3 << 12 | ((off >> 1) & 0xF) << 8 | ((off >> 11) & 1) << 7 | _BRANCH)


def _u(imm20, rd, opcode):
    _check_reg(rd)
    if not -(1 << 19) <= imm20 < (1 << 20):
        raise ValueError(f"upper immediate {imm20} out of range")
    return (imm20 & 0xFFFFF) << 12 | rd << 7 | opcode


def lui(rd, imm20):
    return _u(imm20, rd, _LUI)


def auipc(rd, imm20):
    return _u(imm20, rd, _AUIPC)


def jal(rd, off):
    _check_reg(rd)
    _check_signed(off, 21, "jump offset")
    if off & 1:
        raise ValueError("jump offset must be even")
    off &= 0x1FFFFF
    return ((off >> 20) << 31 | ((off >> 1) & 0x3FF) << 21 | ((off >> 11) & 1) << 20
            | ((off >> 12) & 0xFF) << 12 | rd << 7 | _JAL)


def jalr(rd, rs1, off=0):
    return _i(off, rs1, 0, rd, _JALR)


def beq(rs1, rs2, off):
    return _b(off, rs2, rs1, 0)


def bne(rs1, rs2, off):
    return _b(off, rs2, rs1, 1)


def blt(rs1, rs2, off):
    return _b(off, rs2, rs1, 4)


def bge(rs1, rs2, off):
    return _b(off, rs2, rs1, 5)


def bltu(rs1, rs2, off):
    return _b(off, rs2, rs1, 6)


def bgeu(rs1, rs2, off):
    return _b(off, rs2, rs1, 7)


def lb(rd, rs1, off):
    return _i(off, rs1, 0, rd, _LOAD)


def lh(rd, rs1, off):
    return _i(off, rs1, 1, rd, _LOAD)


def lw(rd, rs1, off):
    return _i(off, rs1, 2, rd, _LOAD)


def lbu(rd, rs1, off):
    return _i(off, rs1, 4, rd, _LOAD)


def lhu(rd, rs1, off):
    return _i(off, rs1, 5, rd, _LOAD)


def sb(rs2, rs1, off):
    return _s(off, rs2, rs1, 0)


def sh(rs2, rs1, off):
    return _s(off, rs2, rs1, 1)


def sw(rs2, rs1, off):
    return _s(off, rs2, rs1, 2)


def addi(rd, rs1, imm):
    return _i(imm, rs1, 0, rd, _OP_IMM)


def slti(rd, rs1, imm):
    return _i(imm, rs1, 2, rd, _OP_IMM)


def sltiu(rd, rs1, imm):
    return _i(imm, rs1, 3, rd, _OP_IMM)


def xori(rd, rs1, imm):
    return _i(imm, rs1, 4, rd, _OP_IMM)


def ori(rd, rs1, imm):
    return _i(imm, rs1, 6, rd, _OP_IMM)


def andi(rd, rs1, imm):
    return _i(imm, rs1, 7, rd, _OP_IMM)


def _shift_imm(funct7, shamt, rs1, funct3, rd):
    if not 0 <= shamt < 32:
        raise ValueError(f"shift amount {shamt} out of range")
    return _r(funct7, shamt, rs1, funct3, rd, _OP_IMM)


def slli(rd, rs1, shamt):
    return _shift_imm(0x00, shamt, rs1, 1, rd)


def srli(rd, rs1, shamt):
    return _shift_imm(0x00, shamt, rs1, 5, rd)


def srai(rd, rs1, shamt):
    return _shift_imm(0x20, shamt, rs1, 5, rd)


def add(rd, rs1, rs2):
    return _r(0x00, rs2, rs1, 0, rd, _OP)


def sub(rd, rs1, rs2):
    return _r(0x20, rs2, rs1, 0, rd, _OP)


def sll(rd, rs1, rs2):
    return _r(0x00, rs2, rs1, 1, rd, _OP)


def slt(rd, rs1, rs2):
    return _r(0x00, rs2, rs1, 2, rd, _OP)


def sltu(rd, rs1, rs2):
    return _r(0x00, rs2, rs1, 3, rd, _OP)


def xor(rd, rs1, rs2):
    return _r(0x00, rs2, rs1, 4, rd, _OP)


def srl(rd, rs1, rs2):
    return _r(0x00, rs2, rs1, 5, rd, _OP)


def sra(rd, rs1, rs2):
    return _r(0x20, rs2, rs1, 5, rd, _OP)


def or_(rd, rs1, rs2):
    return _r(0x00, rs2, rs1, 6, rd, _OP)


def and_(rd, rs1, rs2):
    return _r(0x00, rs2, rs1, 7, rd, _OP)


def mul(rd, rs1, rs2):
    return _r(0x01, rs2, rs1, 0, rd, _OP)


def mv(rd, rs1):
    return addi(rd, rs1, 0)


def nop():
    return addi(0, 0, 0)


def fence():
    """fence iorw, iorw"""
    return 0x0FF0000F


def fence_i():
    return 0x0000100F


def ecall():
    return 0x00000073


def ebreak():
    return 0x00100073


def wfi():
    return 0x10500073


def mret():
    return 0x30200073


def _csr(csr, rs1_or_uimm, funct3, rd):
    _check_reg(rd, rs1_or_uimm)
    if not 0 <= csr < 4096:
        raise ValueError(f"bad CSR {csr:#x}")
    return csr << 20 | rs1_or_uimm << 15 | funct3 << 12 | rd << 7 | _SYSTEM


def csrrw(rd, csr, rs1):
    return _csr(csr, rs1, 1, rd)


def csrrs(rd, csr, rs1):
    return _csr(csr, rs1, 2, rd)


def csrrc(rd, csr, rs1):
    return _csr(csr, rs1, 3, rd)


def csrrsi(rd, csr, uimm):
    return _csr(csr, uimm, 6, rd)


def csrrci(rd, csr, uimm):
    return _csr(csr, uimm, 7, rd)


def split_offset(off):
    """Split a 32-bit offset into (hi20, lo12) for an auipc + 12-bit-immediate pair."""
    hi = (off + 0x800) >> 12
    return hi, off - (hi << 12)
