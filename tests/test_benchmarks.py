"""CoreMark, Embench IoT and the soft-float kernels built for Cortex-M0, in the model and in lockstep.

CoreMark checks its own results (list, matrix and state CRCs for the standard
seeds); Embench benchmarks verify their result and main() returns 0. Lockstep
runs at about 10,000 instructions/s, so only the smallest benchmarks run in
lockstep by default; the rest need --slow.
"""

import pytest

from thumbv import build, elf, lockstep

SMALL = ["statemate", "ud", "nsichneu", "depthconv"]            # < 5,000 instructions
LARGE = ["picojpeg", "qrduino", "wikisort", "xgboost"]          # 0.7-4.3 million instructions
MEDIUM = [n for n in build.embench_names() if n not in SMALL + LARGE]


def coremark_output(result, image):
    n = int.from_bytes(result.read_symbol(image, "coremark_output_len", 4), "little")
    return result.read_symbol(image, "coremark_output", n).decode()


def check_coremark(result, image):
    assert result.ok, f"{result.stopped}\n{result.divergence}"
    out = coremark_output(result, image)
    assert "Correct operation validated" in out, out
    assert "ERROR" not in out, out


def test_coremark_model(build_bench):
    image = elf.load(build_bench.coremark())
    check_coremark(lockstep.simulate([image], stop=image.symbols["done"]), image)


@pytest.mark.slow
def test_coremark_lockstep(build_bench):
    image = elf.load(build_bench.coremark())
    check_coremark(lockstep.run([image], stop=image.symbols["done"]), image)


def check_embench(result, name):
    assert result.ok, f"{name}: {result.stopped}\n{result.divergence}"
    assert result.final_regs[0] == 0, f"{name}: benchmark did not verify"


@pytest.mark.parametrize("name", SMALL)
def test_embench_lockstep_small(build_bench, name):
    image = elf.load(build_bench.embench(name))
    check_embench(lockstep.run([image], stop=image.symbols["done"]), name)


@pytest.mark.slow
@pytest.mark.parametrize("name", MEDIUM)
def test_embench_lockstep(build_bench, name):
    image = elf.load(build_bench.embench(name))
    check_embench(lockstep.run([image], stop=image.symbols["done"]), name)


@pytest.mark.slow
def test_float_kernels_lockstep(build_bench):
    image = elf.load(build_bench.float_kernels())
    result = lockstep.run([image], stop=image.symbols["done"], max_steps=1_000_000)
    assert result.ok, f"{result.stopped}\n{result.divergence}"


@pytest.mark.slow
@pytest.mark.parametrize("name", LARGE)
def test_embench_model(build_bench, name):
    image = elf.load(build_bench.embench(name))
    check_embench(lockstep.simulate([image], stop=image.symbols["done"]), name)
