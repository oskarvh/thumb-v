"""The interrupt controller's model (model/thumbv/nvic.py, Phase 5.2) against
the ARMv6-M rules it implements, directed. tests/test_nvic_rtl.py then checks
the RTL against this model."""

from thumbv import nvic as n


def configured(**prios):
    c = n.Nvic()
    for irq, p in prios.items():
        k = int(irq[3:])
        c.step(write=(n.IPR + k // 4 * 4, c.read(n.IPR + k // 4 * 4) | p << (8 * (k % 4) + 6)))
    return c


def test_reset_state():
    c = n.Nvic()
    assert not c.irq
    assert c.read(n.CPUID) == 0x410C_C200
    assert c.read(n.SYST_CALIB) == 0xC000_0000
    assert c.read(n.SYST_CSR) == 1 << 2          # CLKSOURCE: the processor clock
    assert c.read(n.CLAIM) == 0


def test_enable_and_pend():
    c = n.Nvic()
    c.step(write=(n.ISPR, 1 << 3))
    assert c.read(n.ISPR) == 8 and not c.irq     # pending, but not enabled
    assert c.read(n.ICSR) >> 22 & 1               # ISRPENDING regardless
    c.step(write=(n.ISER, 1 << 3))
    assert c.irq and c.read(n.ICSR) >> 12 & 0x1FF == 19
    c.step(write=(n.ICER, 1 << 3))
    assert not c.irq and c.read(n.ISER) == 0


def test_claim_complete_and_preemption():
    c = configured(irq0=2, irq1=1, irq2=2)
    c.step(write=(n.ISER, 0b111))
    c.step(write=(n.ISPR, 0b101))                 # irq0 and irq2, both priority 2
    assert c.step(read=n.CLAIM) == 16             # tie: the lowest number
    assert c.read(n.ICSR) & 0x1FF == 16           # VECTACTIVE
    assert not c.irq                              # irq2 can't preempt equal priority
    assert c.read(n.CLAIM) == 0
    c.step(write=(n.ISPR, 0b010))                 # irq1, priority 1: preempts
    assert c.irq and c.step(read=n.CLAIM) == 17
    c.step(write=(n.COMPLETE, 0))                 # back in irq0's handler
    assert not c.irq
    c.step(write=(n.COMPLETE, 0))                 # back in thread mode: irq2 now
    assert c.irq and c.step(read=n.CLAIM) == 18


def test_level_lines_repend_after_complete():
    c = n.Nvic()
    c.step(write=(n.ISER, 1))
    c.step(lines=1)
    assert c.irq
    assert c.step(lines=1, read=n.CLAIM) == 16
    for _ in range(3):
        c.step(lines=1)                           # still high, but active: no pend
    assert c.read(n.ISPR) == 0
    c.step(lines=1, write=(n.COMPLETE, 0))        # completes with the line high
    assert c.read(n.ISPR) == 1 and c.irq
    c.step(lines=0, read=n.CLAIM)
    c.step(lines=0, write=(n.COMPLETE, 0))        # acknowledged before completing
    assert c.read(n.ISPR) == 0 and not c.irq


def test_system_exceptions_win_ties():
    c = n.Nvic()
    c.step(write=(n.ISER, 1))
    c.step(write=(n.ISPR, 1))
    c.step(write=(n.ICSR, 1 << 28 | 1 << 26))     # PENDSVSET, PENDSTSET
    assert c.step(read=n.CLAIM) == n.PENDSV       # all priority 0: 14 < 15 < 16
    c.step(write=(n.COMPLETE, 0))
    assert c.step(read=n.CLAIM) == n.SYSTICK
    c.step(write=(n.COMPLETE, 0))
    c.step(write=(n.SHPR3, 3 << 30 | 1 << 22))    # SysTick 3, PendSV 1
    c.step(write=(n.ICSR, 1 << 28 | 1 << 26 | 1 << 27))   # set and clear: clear wins
    assert c.read(n.ICSR) >> 28 & 1 == 0 and c.read(n.ICSR) >> 26 & 1


def test_systick_period_and_countflag():
    c = n.Nvic()
    c.step(write=(n.SYST_RVR, 3))
    c.step(write=(n.SYST_CSR, 0b011))             # ENABLE, TICKINT; CVR is 0: reload first
    values, pends = [], []
    for _ in range(9):
        c.step()
        values.append(c.cvr)
        pends.append(c.pendst)
    assert values == [3, 2, 1, 0, 3, 2, 1, 0, 3]  # RVR + 1 cycles per period
    assert pends.index(True) == 3                 # pended as it reaches 0
    assert c.read(n.SYST_CSR) >> 16 & 1           # COUNTFLAG
    c.step(read=n.SYST_CSR)
    assert not c.read(n.SYST_CSR) >> 16 & 1       # cleared by the read
    c.step(write=(n.SYST_CVR, 0x1234))
    assert c.cvr == 0


def test_priority_registers_keep_two_bits():
    c = n.Nvic()
    c.step(write=(n.IPR + 4, 0xFFFF_FFFF))
    assert c.read(n.IPR + 4) == 0xC0C0_C0C0
    assert c.prio[4:8] == [3, 3, 3, 3]
