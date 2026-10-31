"""Check the RV32 encoders against the GNU RISC-V assembler."""

import subprocess

import pytest

from conftest import require_tool
from thumbv import rv32

# (encoder output, assembly for the same instruction)
CASES = [
    (rv32.lui(5, 0xABCDE), "lui t0, 0xabcde"),
    (rv32.lui(5, -1), "lui t0, 0xfffff"),
    (rv32.auipc(6, 0x12345), "auipc t1, 0x12345"),
    (rv32.jal(1, 2046), "jal ra, .+2046"),
    (rv32.jal(0, -1048576), "jal x0, .-1048576"),
    (rv32.jal(0, 1048574), "jal x0, .+1048574"),
    (rv32.jalr(0, 10, 4), "jalr x0, 4(a0)"),
    (rv32.jalr(1, 6, -2048), "jalr ra, -2048(t1)"),
    (rv32.beq(28, 0, 8), "beq t3, x0, .+8"),
    (rv32.bne(29, 0, -4096), "bne t4, x0, .-4096"),
    (rv32.blt(10, 11, 4094), "blt a0, a1, .+4094"),
    (rv32.bge(10, 11, -2), "bge a0, a1, .-2"),
    (rv32.bltu(29, 30, 100), "bltu t4, t5, .+100"),
    (rv32.bgeu(29, 30, -100), "bgeu t4, t5, .-100"),
    (rv32.lb(10, 2, -1), "lb a0, -1(sp)"),
    (rv32.lh(10, 2, 2047), "lh a0, 2047(sp)"),
    (rv32.lw(10, 6, 1024), "lw a0, 1024(t1)"),
    (rv32.lbu(18, 9, 31), "lbu s2, 31(s1)"),
    (rv32.lhu(18, 9, 62), "lhu s2, 62(s1)"),
    (rv32.sb(11, 2, -2048), "sb a1, -2048(sp)"),
    (rv32.sh(11, 2, 33), "sh a1, 33(sp)"),
    (rv32.sw(1, 2, -36), "sw ra, -36(sp)"),
    (rv32.addi(10, 0, 255), "addi a0, x0, 255"),
    (rv32.addi(10, 10, -255), "addi a0, a0, -255"),
    (rv32.slti(6, 7, -5), "slti t1, t2, -5"),
    (rv32.sltiu(29, 10, 1), "sltiu t4, a0, 1"),
    (rv32.xori(6, 11, -1), "xori t1, a1, -1"),
    (rv32.ori(6, 11, 0x7FF), "ori t1, a1, 0x7ff"),
    (rv32.andi(6, 11, 255), "andi t1, a1, 255"),
    (rv32.slli(10, 11, 31), "slli a0, a1, 31"),
    (rv32.srli(30, 11, 1), "srli t5, a1, 1"),
    (rv32.srai(10, 11, 16), "srai a0, a1, 16"),
    (rv32.add(10, 11, 12), "add a0, a1, a2"),
    (rv32.sub(10, 0, 12), "sub a0, x0, a2"),
    (rv32.sll(10, 11, 6), "sll a0, a1, t1"),
    (rv32.slt(10, 11, 12), "slt a0, a1, a2"),
    (rv32.sltu(30, 6, 10), "sltu t5, t1, a0"),
    (rv32.xor(6, 28, 31), "xor t1, t3, t6"),
    (rv32.srl(10, 11, 6), "srl a0, a1, t1"),
    (rv32.sra(10, 11, 6), "sra a0, a1, t1"),
    (rv32.or_(10, 11, 12), "or a0, a1, a2"),
    (rv32.and_(10, 11, 12), "and a0, a1, a2"),
    (rv32.mul(10, 11, 10), "mul a0, a1, a0"),
    (rv32.fence(), "fence iorw, iorw"),
    (rv32.fence_i(), "fence.i"),
    (rv32.ecall(), "ecall"),
    (rv32.ebreak(), "ebreak"),
    (rv32.wfi(), "wfi"),
    (rv32.mret(), "mret"),
    (rv32.csrrs(6, rv32.MSTATUS, 0), "csrrs t1, mstatus, x0"),
    (rv32.csrrc(0, rv32.MSTATUS, 6), "csrrc x0, mstatus, t1"),
    (rv32.csrrw(6, rv32.MSTATUS, 7), "csrrw t1, mstatus, t2"),
    (rv32.csrrsi(0, rv32.MSTATUS, 8), "csrrsi x0, mstatus, 8"),
    (rv32.csrrci(0, rv32.MSTATUS, 8), "csrrci x0, mstatus, 8"),
]


def test_encoders_match_assembler(tmp_path):
    cc = "riscv64-unknown-elf-as"
    require_tool(cc)
    src = tmp_path / "enc.S"
    src.write_text(".option norvc\n.text\n" + "".join(f"{asm}\n" for _, asm in CASES))
    obj = tmp_path / "enc.o"
    subprocess.run([cc, "-march=rv32im_zicsr_zifencei", "-mabi=ilp32", "-o", str(obj), str(src)],
                   check=True)
    text = subprocess.run(["riscv64-unknown-elf-objcopy", "-O", "binary", "-j", ".text",
                           str(obj), "/dev/stdout"], capture_output=True, check=True).stdout
    words = [int.from_bytes(text[i:i + 4], "little") for i in range(0, len(text), 4)]
    assert len(words) == len(CASES)
    for (ours, asm), theirs in zip(CASES, words):
        assert ours == theirs, f"{asm}: ours {ours:#010x}, assembler {theirs:#010x}"


@pytest.mark.parametrize("bad", [
    lambda: rv32.addi(1, 1, 2048),
    lambda: rv32.beq(1, 2, 3),
    lambda: rv32.beq(1, 2, 4096),
    lambda: rv32.jal(0, 1 << 20),
    lambda: rv32.slli(1, 1, 32),
    lambda: rv32.add(32, 1, 1),
])
def test_encoders_reject_out_of_range(bad):
    with pytest.raises(ValueError):
        bad()


def test_split_offset():
    for off in (0, 1, 0x7FF, 0x800, -0x800, -0x801, 0x123456, -0x123456, (1 << 24) - 2, -(1 << 24)):
        hi, lo = rv32.split_offset(off)
        assert -2048 <= lo < 2048
        assert (hi << 12) + lo == off
