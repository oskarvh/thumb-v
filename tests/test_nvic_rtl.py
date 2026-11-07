"""The interrupt controller's RTL (rtl/soc/thumbv_nvic.v) against its model
(model/thumbv/nvic.py), cycle by cycle (Phase 5.2): random sequences of
register reads and writes, claims and completes, with random interrupt
lines, run through both; every read's value and the interrupt line must
agree after every cycle."""

import random

import pytest

from thumbv import nvic as n, rtlsim
from thumbv.build import ToolMissing

from conftest import REQUIRE_RTL

READABLE = [n.CLAIM, n.SYST_CSR, n.SYST_RVR, n.SYST_CVR, n.SYST_CALIB, n.ISER, n.ICER, n.ISPR,
            n.ICPR, n.CPUID, n.ICSR, n.SHPR2, n.SHPR3, 0xE000_E000, 0xE000_ED08,
            *(n.IPR + 4 * k for k in range(8))]


@pytest.fixture(scope="module")
def nvic_sim():
    try:
        return rtlsim.nvic_simulator()
    except ToolMissing as missing:
        if REQUIRE_RTL:
            pytest.fail(f"{missing} not found")
        pytest.skip(f"{missing} not found")


def random_cycles(rng, count):
    """Mostly a few interrupts, so that they collide: claims, completes,
    preemption, level lines held across their handlers."""
    hot = rng.getrandbits(32) | 0b1111          # the interrupts this sequence uses most
    mask = lambda: rng.getrandbits(32) & (hot if rng.random() < 0.8 else 0xFFFF_FFFF)
    lines, cycles = 0, []
    for _ in range(count):
        if rng.random() < 0.05:
            lines = mask() & rng.getrandbits(32)
        roll = rng.random()
        if roll < 0.30:
            op = (0, 0, 0)
        elif roll < 0.42:
            op = (1, n.CLAIM, 0)
        elif roll < 0.52:
            op = (2, n.COMPLETE, rng.getrandbits(32))
        elif roll < 0.70:
            op = (1, rng.choice(READABLE), 0)
        else:
            addr, data = rng.choice([
                (n.ISER, mask()), (n.ICER, mask()), (n.ISPR, mask()), (n.ICPR, mask()),
                (n.IPR + 4 * rng.randrange(8), rng.getrandbits(32)),
                (n.SHPR2, rng.getrandbits(32)), (n.SHPR3, rng.getrandbits(32)),
                (n.ICSR, rng.getrandbits(4) << 25),
                (n.SYST_CSR, rng.getrandbits(32)), (n.SYST_RVR, rng.choice([0, 1, 2, rng.randrange(40)])),
                (n.SYST_CVR, rng.getrandbits(32)), (n.SYST_CALIB, rng.getrandbits(32)),
                (n.CPUID, rng.getrandbits(32)),
            ])
            op = (2, addr, data)
        cycles.append((*op, lines))
    return cycles


@pytest.mark.parametrize("seed", range(16))
def test_rtl_matches_model(nvic_sim, tmp_path, seed):
    rng = random.Random(seed)
    cycles = random_cycles(rng, 20_000)
    got = rtlsim.run_nvic(cycles, tmp_path)
    assert len(got) == len(cycles)
    model = n.Nvic()
    claims = preempted = 0
    for k, ((op, addr, data, lines), (rdata, irq)) in enumerate(zip(cycles, got)):
        before = len(model.active)
        value = model.step(lines, read=addr if op == 1 else None, write=(addr, data) if op == 2 else None)
        where = f"cycle {k}: op {op} {addr:#010x} {data:#x}, lines {lines:#x}"
        if op == 1:
            assert rdata == value, f"{where}: read RTL {rdata:#x}, model {value:#x}"
        assert irq == model.irq, f"{where}: irq RTL {irq}, model {model.irq}"
        if op == 1 and addr == n.CLAIM and value:
            claims += 1
            preempted += before > 0
    # The sequence did exercise the interesting cases.
    assert claims > 300 and preempted > 30, (claims, preempted)
