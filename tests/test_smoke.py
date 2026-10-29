"""End-to-end checks that the toolchains, ELF loader, Unicorn and Capstone work."""

import capstone
import unicorn
from unicorn import arm_const, riscv_const

from thumbv import elf

MEM_BASE = 0x0
MEM_SIZE = 0x10000


def _map_image(uc, image):
    uc.mem_map(MEM_BASE, MEM_SIZE)
    for seg in image.segments:
        uc.mem_write(seg.addr, seg.data)


def test_thumb_runs_in_unicorn(build_asm):
    image = elf.load(build_asm("thumb", "smoke_thumb.S"))
    assert image.machine == "EM_ARM"

    uc = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_THUMB | unicorn.UC_MODE_MCLASS)
    uc.ctl_set_cpu_model(arm_const.UC_CPU_ARM_CORTEX_M0)
    _map_image(uc, image)
    # Bit 0 of the start address selects Thumb state.
    uc.emu_start(image.symbols["_start"] | 1, image.symbols["done"])

    assert uc.reg_read(arm_const.UC_ARM_REG_R2) == 12
    xpsr = uc.reg_read(arm_const.UC_ARM_REG_XPSR)
    assert (xpsr >> 28) == 0b0000  # NZCV all clear after 5 + 7


def test_rv32_runs_in_unicorn(build_asm):
    image = elf.load(build_asm("rv32", "smoke_rv32.S"))
    assert image.machine == "EM_RISCV"

    uc = unicorn.Uc(unicorn.UC_ARCH_RISCV, unicorn.UC_MODE_RISCV32)
    _map_image(uc, image)
    uc.emu_start(image.symbols["_start"], image.symbols["done"])

    assert uc.reg_read(riscv_const.UC_RISCV_REG_A2) == 12


def test_capstone_disassembles_thumb(build_asm):
    image = elf.load(build_asm("thumb", "smoke_thumb.S"))
    code = image.segments[0].data
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB | capstone.CS_MODE_MCLASS)
    mnemonics = [insn.mnemonic for insn in md.disasm(code, image.symbols["_start"])]
    assert mnemonics[:3] == ["movs", "movs", "adds"]
