"""The SoC in Verilator (Phase 1.2): RISC-V programs run on the RTL in lockstep with the model.

Needs Verilator, and sbt to generate the core (`make core`); the tests skip
without them unless THUMBV_REQUIRE_RTL=1.
"""

import dataclasses
from pathlib import Path
from types import SimpleNamespace

import pytest

from thumbv import build, elf, lockstep, rtlsim


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


def build_rv_asm(name, tmp_path):
    """An RV32 program from tests/asm/ with its own _start, linked like the C programs."""
    source = Path(__file__).parent / "asm" / name
    return elf.load(build.compile_and_link("rv32", [source], tmp_path / (source.stem + ".elf"),
                                           [*build.C_FLAGS["rv32"], build._linker_script("rv32.ld")]))


def test_thumb_mode_switch(rtl_simulator, tmp_path):
    """Phase 2.1: a call into a Thumb region and back. The region comes from the
    program's own CSR writes, in the RTL and in the model."""
    image = build_rv_asm("rtl_thumb_mode.S", tmp_path)
    result = run([image], tmp_path)
    assert result.a0 == 2
    thumb = [r.pc for r in result.trace if r.pc >= image.symbols["thumb_start"] and r.pc < image.symbols["thumb_end"]]
    start = image.symbols["thumb_start"]
    assert [pc - start for pc in thumb] == [0, 2, 6, 8, 12, 16, 18, 20, 18, 20]
    assert rtlsim.lockstep([image], result) is None


def test_thumb_illegal_traps_at_its_address(rtl_simulator, tmp_path):
    image = build_rv_asm("rtl_thumb_illegal.S", tmp_path)
    result = run([image], tmp_path)
    assert result.a0 == image.symbols["thumb_udf"]


def test_thumb_single_ops(rtl_simulator, build_mixed, tmp_path):
    """Phase 2.2: an assembled Thumb function of single-op instructions, called
    from RISC-V, in lockstep with the model (results only, no flags)."""
    rv_elf, thumb_elf = build_mixed(["rtl_thumb_ops.S"], ["rtl_thumb_ops_main.c"])
    images = [elf.load(rv_elf), elf.load(thumb_elf)]
    result = run(images, tmp_path)
    model = lockstep.simulate(images, stop=images[0].symbols["done"], options=rtlsim.HARDWARE)
    assert result.a0 == model.final_regs[0]
    in_thumb = sum(1 for r in result.trace if 0x1_0000 <= r.pc < 0x2_0000)
    assert in_thumb > 80                    # both calls ran in Thumb mode
    divergence = rtlsim.lockstep(images, result)
    assert divergence is None, str(divergence)


def test_board_memories(rtl_simulator, build_c, tmp_path):
    """The board's smaller RAMs run the same binary: the stack at the top of the
    data region aliases into the 16 KiB data RAM."""
    image = elf.load(build_c("rv32", "hello.c"))
    result = run([image], tmp_path, memories=rtlsim.BOARD)
    assert result.uart == "Hello from Thumb-V\n"
    assert rtlsim.lockstep([image], result) is None


def test_board_memories_collide(tmp_path):
    """Thumb code at 0x1_0000 and RISC-V code at 0x2_0000 share the board's 32 KiB code RAM."""
    image = SimpleNamespace(segments=[SimpleNamespace(addr=0x1_0000, data=b"\x01"),
                                      SimpleNamespace(addr=0x2_0000, data=b"\x02")])
    rtlsim.memory_images([image], tmp_path)   # fine with the simulation's RAMs
    with pytest.raises(ValueError, match="share a byte"):
        rtlsim.memory_images([image], tmp_path, rtlsim.BOARD)


def test_timeout(rtl_simulator, build_c, tmp_path):
    image = elf.load(build_c("rv32", "hello.c"))
    result = rtlsim.run([image], tmp_path, max_cycles=100)
    assert result.status == rtlsim.TIMEOUT
