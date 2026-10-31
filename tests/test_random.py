"""Random instruction sequences from gen_random.py, run in program lockstep."""

import pytest

import gen_random
from thumbv import elf, lockstep


def check(build_thumb_asm, seed):
    image = elf.load(build_thumb_asm(f"random{seed}", gen_random.program(seed)))
    result = lockstep.run([image], stop=image.symbols["done"])
    assert result.ok, f"seed {seed}: {result.stopped}\n{result.divergence}"
    assert result.thumb_steps > 200


@pytest.mark.parametrize("seed", range(20))
def test_random_program(build_thumb_asm, seed):
    check(build_thumb_asm, seed)


@pytest.mark.slow
@pytest.mark.parametrize("seed", range(1000, 1500))
def test_random_program_many(build_thumb_asm, seed):
    check(build_thumb_asm, seed)
