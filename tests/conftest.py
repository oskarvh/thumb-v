import os
import shutil
import subprocess
from pathlib import Path

import pytest

from thumbv import elf

TESTS = Path(__file__).parent
ASM_DIR = TESTS / "asm"
C_DIR = TESTS / "c"
LINK_DIR = TESTS / "link"

# Missing cross toolchains skip the tests that need them, unless
# THUMBV_REQUIRE_TOOLS=1 (set in CI), where they fail instead.
REQUIRE_TOOLS = os.environ.get("THUMBV_REQUIRE_TOOLS") == "1"

TOOLCHAINS = {
    "thumb": ("arm-none-eabi-gcc", ["-mcpu=cortex-m0", "-mthumb"]),
    "rv32": ("riscv64-unknown-elf-gcc", ["-march=rv32im", "-mabi=ilp32"]),
}

C_FLAGS = {
    "thumb": ["-O2", "-ffreestanding", "-fno-builtin"],
    "rv32": ["-O2", "-ffreestanding", "-fno-builtin", "-msmall-data-limit=0", "-Wl,--no-relax"],
}


def require_tool(cc: str):
    if shutil.which(cc) is None:
        if REQUIRE_TOOLS:
            pytest.fail(f"{cc} not found")
        pytest.skip(f"{cc} not found")


def compile_and_link(kind: str, sources, out: Path, extra=(), libs=()) -> Path:
    cc, arch_flags = TOOLCHAINS[kind]
    require_tool(cc)
    subprocess.run([cc, *arch_flags, "-nostdlib", *extra, "-o", str(out), *map(str, sources), *libs],
                   check=True)
    return out


@pytest.fixture
def build_asm(tmp_path):
    """Assemble and link a file from tests/asm/ for the given toolchain."""

    def build(kind: str, name: str, text_addr: int = 0x1000) -> Path:
        source = ASM_DIR / name
        return compile_and_link(kind, [source], tmp_path / (source.stem + ".elf"),
                                ["-Wl,-e,_start", f"-Wl,-Ttext={text_addr:#x}"])

    return build


@pytest.fixture
def build_c(tmp_path):
    """Build a C program from tests/c/ with its startup file and linker script."""

    def build(kind: str, *names: str) -> Path:
        sources = [C_DIR / f"crt_{kind}.S", *(C_DIR / n for n in names)]
        out = tmp_path / (Path(names[0]).stem + ".elf")
        return compile_and_link(kind, sources, out,
                                [*C_FLAGS[kind], f"-Wl,-T,{LINK_DIR / (kind + '.ld')}"], ["-lgcc"])

    return build


@pytest.fixture
def build_mixed(tmp_path):
    """Build a mixed program: a Thumb library, then a RISC-V program linked against it.

    The Thumb library is linked first; its global functions are passed to the
    RISC-V link as absolute symbols. Reserved names (`__aeabi_idiv`,
    `__divsi3`, ...) stay private: they are the Thumb side's libgcc, and
    RISC-V's libgcc has functions of the same names. Returns (rv_elf, thumb_elf).
    """

    def build(thumb_names, rv_names):
        thumb = compile_and_link(
            "thumb", [C_DIR / n for n in thumb_names], tmp_path / "lib_thumb.elf",
            [*C_FLAGS["thumb"], f"-Wl,-T,{LINK_DIR / 'thumb.ld'}", "-Wl,--entry=0"], ["-lgcc"])
        defsyms = [f"-Wl,--defsym={name}={value & ~1:#x}"
                   for name, value in elf.load(thumb).functions.items() if not name.startswith("__")]
        rv = compile_and_link(
            "rv32", [C_DIR / "crt_rv32.S", *(C_DIR / n for n in rv_names)], tmp_path / "main_rv32.elf",
            [*C_FLAGS["rv32"], f"-Wl,-T,{LINK_DIR / 'rv32.ld'}", *defsyms], ["-lgcc"])
        return rv, thumb

    return build
