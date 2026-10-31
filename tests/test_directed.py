"""Directed tests: edge-case programs from gen_directed.py, run in program lockstep."""

import pytest

import gen_directed
from thumbv import elf, lockstep


@pytest.mark.parametrize("group", gen_directed.GROUPS)
def test_directed(build_thumb_asm, group):
    image = elf.load(build_thumb_asm(group, gen_directed.GROUPS[group]()))
    result = lockstep.run([image], stop=image.symbols["done"])
    assert result.ok, f"{result.stopped}\n{result.divergence}"
    assert result.thumb_steps > 50
