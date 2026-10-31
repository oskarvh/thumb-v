import os
import shutil
from pathlib import Path

import pytest

from thumbv import build

ASM_DIR = Path(__file__).parent / "asm"

# Missing cross toolchains skip the tests that need them, unless
# THUMBV_REQUIRE_TOOLS=1 (set in CI), where they fail instead.
REQUIRE_TOOLS = os.environ.get("THUMBV_REQUIRE_TOOLS") == "1"
# Likewise for the RTL tools (sbt, Verilator), which CI installs in its own job.
REQUIRE_RTL = os.environ.get("THUMBV_REQUIRE_RTL") == "1"


def pytest_addoption(parser):
    parser.addoption("--slow", action="store_true", help="also run slow tests (benchmarks)")


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: long-running test, only run with --slow")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--slow"):
        return
    skip = pytest.mark.skip(reason="slow test: run with --slow")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)


def require_tool(cc: str):
    if shutil.which(cc) is None:
        if REQUIRE_TOOLS:
            pytest.fail(f"{cc} not found")
        pytest.skip(f"{cc} not found")


def _tools(fn):
    """Wrap a build recipe so a missing toolchain skips (or fails) the test."""

    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except build.ToolMissing as missing:
            if REQUIRE_TOOLS:
                pytest.fail(f"{missing} not found")
            pytest.skip(f"{missing} not found")

    return wrapped


@pytest.fixture(scope="session")
def rtl_simulator():
    """The Verilator testbench, built once per session (and the core generated if needed)."""
    from thumbv import rtlsim
    try:
        return rtlsim.simulator()
    except build.ToolMissing as missing:
        if REQUIRE_RTL:
            pytest.fail(f"{missing} not found")
        pytest.skip(f"{missing} not found")


@pytest.fixture
def build_asm(tmp_path):
    """Assemble and link a file from tests/asm/ for the given toolchain."""

    def run(kind: str, name: str, text_addr: int = 0x1000) -> Path:
        source = ASM_DIR / name
        return build.compile_and_link(kind, [source], tmp_path / (source.stem + ".elf"),
                                      ["-Wl,-e,_start", f"-Wl,-Ttext={text_addr:#x}"])

    return _tools(run)


@pytest.fixture
def build_c(tmp_path):
    """Build a C program from tests/c/: build_c("thumb", "prog.c")."""
    return _tools(lambda kind, *names: build.c_program(kind, names, tmp_path))


@pytest.fixture
def build_thumb_asm(tmp_path):
    """Link generated Thumb assembly text: build_thumb_asm("name", text)."""

    def run(name: str, text: str) -> Path:
        source = tmp_path / f"{name}.S"
        source.write_text(text)
        return build.thumb_asm_program(source, tmp_path / f"{name}.elf")

    return _tools(run)


@pytest.fixture
def build_mixed(tmp_path):
    """Build a mixed program: build_mixed(["lib.c"], ["main.c"]) -> (rv_elf, thumb_elf)."""
    return _tools(lambda thumb_names, rv_names: build.mixed_program(thumb_names, rv_names, tmp_path))


@pytest.fixture
def build_bench(tmp_path):
    """Build benchmarks: build_bench.coremark(), .embench(name) or .float_kernels()."""

    class Bench:
        coremark = staticmethod(_tools(lambda **kw: build.coremark(tmp_path, **kw)))
        embench = staticmethod(_tools(lambda name: build.embench(name, tmp_path)))
        float_kernels = staticmethod(_tools(lambda: build.float_kernels(tmp_path)))

    return Bench
