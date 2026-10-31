"""Program-level lockstep: whole programs in the model and the reference."""

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
