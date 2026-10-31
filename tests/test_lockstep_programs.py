"""Program-level lockstep: whole programs in the model and the reference."""

import pytest

from thumbv import elf, expander, lockstep
from thumbv import rv32 as r


def test_thumb_selftest(build_c):
    image = elf.load(build_c("thumb", "thumb_selftest.c"))
    result = lockstep.run([image], stop=image.symbols["done"])
    assert result.ok, f"{result.stopped}\n{result.divergence}"
    assert result.thumb_steps > 1000


def test_mixed_program(build_mixed):
    rv_elf, thumb_elf = build_mixed(["mixed_lib.c"], ["mixed_main.c"])
    rv_img, thumb_img = elf.load(rv_elf), elf.load(thumb_elf)
    result = lockstep.run([rv_img, thumb_img], stop=rv_img.symbols["done"])
    assert result.ok, f"{result.stopped}\n{result.divergence}"
    assert 0 < result.thumb_steps < result.steps   # both instruction sets ran


def test_cli(build_c, capsys):
    path = build_c("thumb", "thumb_selftest.c")
    assert lockstep.main([str(path)]) == 0
    assert "stopped: stop address" in capsys.readouterr().out


def test_divergence_is_reported(build_c, monkeypatch):
    """A broken expansion must stop the run at the first wrong instruction."""
    image = elf.load(build_c("thumb", "thumb_selftest.c"))

    def broken_eors(f, pc, o):  # EORS computing OR instead
        rdn, rm = expander.rv(f["d"]), expander.rv(f["m"])
        return [r.or_(rdn, rdn, rm), *expander._nz(rdn)]

    monkeypatch.setitem(expander._HANDLERS, "EORS", broken_eors)
    result = lockstep.run([image], stop=image.symbols["done"])
    assert not result.ok
    assert "eors" in result.divergence.instruction
    assert any(p.startswith("r") for p in result.divergence.problems)


def test_interworking(build_mixed):
    """RISC-V <-> Thumb calls with every ABI-compatible kind of signature."""
    rv_elf, thumb_elf = build_mixed(["interwork_lib.c"], ["interwork_main.c"])
    rv_img, thumb_img = elf.load(rv_elf), elf.load(thumb_elf)
    result = lockstep.run([rv_img, thumb_img], stop=rv_img.symbols["done"])
    assert result.ok, f"{result.stopped}\n{result.divergence}"
    assert 0 < result.thumb_steps < result.steps


@pytest.mark.parametrize("lib, main", [("mixed_lib.c", "mixed_main.c"),
                                       ("interwork_lib.c", "interwork_main.c")])
def test_mixed_matches_native(build_mixed, build_c, lib, main):
    """A mixed build returns the same result as the same sources built all-RISC-V.

    The lockstep reference hands registers over with the same D2 mapping as the
    model, so it can't catch an ABI mismatch; this comparison can.
    """
    rv_elf, thumb_elf = build_mixed([lib], [main])
    rv_img, thumb_img = elf.load(rv_elf), elf.load(thumb_elf)
    mixed = lockstep.simulate([rv_img, thumb_img], stop=rv_img.symbols["done"])
    native_img = elf.load(build_c("rv32", main, lib))
    native = lockstep.simulate([native_img], stop=native_img.symbols["done"])
    assert mixed.ok and native.ok
    assert mixed.final_regs[0] == native.final_regs[0]
