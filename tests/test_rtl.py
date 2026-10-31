"""The SoC in Verilator (Phase 1.2): RISC-V programs run on the RTL in lockstep with the model.

Needs Verilator, and sbt to generate the core (`make core`); the tests skip
without them unless THUMBV_REQUIRE_RTL=1.
"""

import dataclasses

import pytest

from thumbv import elf, lockstep, rtlsim


def run(images, tmp_path, **kwargs):
    result = rtlsim.run(images, tmp_path, **kwargs)
    assert result.status == rtlsim.EXIT, result.uart
    return result


def test_hello(rtl_simulator, build_c, tmp_path):
    image = elf.load(build_c("rv32", "hello.c"))
    result = run([image], tmp_path)
    assert result.uart == "Hello from Thumb-V\n"
    assert result.a0 == 0xA5                      # the LED register reads back
    assert rtlsim.lockstep([image], result) is None


@pytest.mark.parametrize("names", [
    ("abi_main.c", "abi_lib.c", "string_min.c"),
    ("interwork_main.c", "interwork_lib.c"),
    ("mixed_main.c", "mixed_lib.c"),
])
def test_programs_match_model(rtl_simulator, build_c, tmp_path, names):
    """The all-RISC-V builds of the interworking test programs."""
    image = elf.load(build_c("rv32", *names))
    result = run([image], tmp_path)
    model = lockstep.simulate([image], stop=image.symbols["done"])
    assert result.a0 == model.final_regs[0]
    divergence = rtlsim.lockstep([image], result)
    assert divergence is None, str(divergence)


def test_lockstep_catches_a_wrong_write(rtl_simulator, build_c, tmp_path):
    image = elf.load(build_c("rv32", "hello.c"))
    result = run([image], tmp_path)
    i = next(i for i, r in enumerate(result.trace) if r.rd)
    result.trace[i] = dataclasses.replace(result.trace[i], rd_wdata=result.trace[i].rd_wdata ^ 1)
    divergence = rtlsim.lockstep([image], result)
    assert divergence is not None and divergence.step == i
    assert f"x{result.trace[i].rd}: model" in divergence.problems[0]


def test_wave(rtl_simulator, build_c, tmp_path):
    image = elf.load(build_c("rv32", "hello.c"))
    wave = tmp_path / "hello.fst"
    run([image], tmp_path, wave=wave)
    assert wave.stat().st_size > 1000


def test_timeout(rtl_simulator, build_c, tmp_path):
    image = elf.load(build_c("rv32", "hello.c"))
    result = rtlsim.run([image], tmp_path, max_cycles=100)
    assert result.status == rtlsim.TIMEOUT
