import os
import shutil
import subprocess
from pathlib import Path

import pytest

ASM_DIR = Path(__file__).parent / "asm"

# Missing cross toolchains skip the tests that need them, unless
# THUMBV_REQUIRE_TOOLS=1 (set in CI), where they fail instead.
REQUIRE_TOOLS = os.environ.get("THUMBV_REQUIRE_TOOLS") == "1"

TOOLCHAINS = {
    "thumb": ("arm-none-eabi-gcc", ["-mcpu=cortex-m0", "-mthumb"]),
    "rv32": ("riscv64-unknown-elf-gcc", ["-march=rv32im", "-mabi=ilp32"]),
}


def _build(kind: str, source: Path, out: Path, text_addr: int) -> Path:
    cc, arch_flags = TOOLCHAINS[kind]
    if shutil.which(cc) is None:
        if REQUIRE_TOOLS:
            pytest.fail(f"{cc} not found")
        pytest.skip(f"{cc} not found")
    subprocess.run(
        [cc, *arch_flags, "-nostdlib", "-Wl,-e,_start", f"-Wl,-Ttext={text_addr:#x}",
         "-o", str(out), str(source)],
        check=True,
    )
    return out


@pytest.fixture
def build_asm(tmp_path):
    """Assemble and link a file from tests/asm/ for the given toolchain."""

    def build(kind: str, name: str, text_addr: int = 0x1000) -> Path:
        source = ASM_DIR / name
        return _build(kind, source, tmp_path / (source.stem + ".elf"), text_addr)

    return build
