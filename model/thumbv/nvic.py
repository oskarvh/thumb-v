"""The interrupt controller (D9, Phase 5.2): the reference for rtl/soc/thumbv_nvic.v.

The ARMv6-M programming model at the System Control Space, so Cortex-M code
drives it unmodified, plus two Thumb-V registers for software entry:

  0xE000_E010  SYST_CSR    SysTick: ENABLE (0), TICKINT (1), CLKSOURCE (2, reads 1),
                           COUNTFLAG (16, read-only, cleared by reading)
  0xE000_E014  SYST_RVR    reload value, 24 bits
  0xE000_E018  SYST_CVR    current value, 24 bits; any write clears it and COUNTFLAG
  0xE000_E01C  SYST_CALIB  0xC000_0000: no reference clock, no calibration
  0xE000_E100  NVIC_ISER   enables; write 1 to set
  0xE000_E180  NVIC_ICER   enables; write 1 to clear
  0xE000_E200  NVIC_ISPR   pending; write 1 to set
  0xE000_E280  NVIC_ICPR   pending; write 1 to clear
  0xE000_E400  NVIC_IPR0-7 priorities: byte n for interrupt n, bits 7:6
  0xE000_ED00  CPUID       0x410C_C200 (Cortex-M0 r0p0)
  0xE000_ED04  ICSR        PENDSVSET (28), PENDSVCLR (27), PENDSTSET (26), PENDSTCLR (25),
                           ISRPENDING (22), VECTPENDING (20:12), VECTACTIVE (8:0)
  0xE000_ED1C  SHPR2       SVCall priority, bits 31:30 (stored only: SVC is a trap)
  0xE000_ED20  SHPR3       SysTick priority 31:30, PendSV priority 23:22
  0x1000_1000  CLAIM       read: the exception to handle, made active (0 if none)
  0x1000_1004  COMPLETE    write: the active exception is done

Exceptions are numbered as on Cortex-M: interrupt n is 16 + n, SysTick 15,
PendSV 14. Priorities are 0 (highest) to 3; ties go to the lowest number.

Claim and complete: with entry in software (the shared entry routine), the
controller tracks what is active itself. A read of CLAIM returns the
highest-priority pending exception that can preempt the current priority
(that of the most recent active one, or none), clears its pending bit and
makes it active. A write to COMPLETE ends the most recent active one. Active
exceptions form a stack, at most 4 deep. The core's interrupt line is high
while some pending exception could be claimed.

Interrupt lines are level-sensitive, as on the NVIC: a line pends its
interrupt while high, except while that interrupt is active; so a line still
high when its handler completes pends it again.

Accesses are words; byte and halfword writes act as word writes.

Cycle model, shared with the RTL (tests/test_nvic_rtl.py drives both): in
each cycle the bus carries at most one access and the lines have a value.
A read returns the state at the start of the cycle; everything changes at
the clock edge at its end, in the order of step().
"""

SCS = 0xE000_E000
CLAIM, COMPLETE = 0x1000_1000, 0x1000_1004
SYST_CSR, SYST_RVR, SYST_CVR, SYST_CALIB = 0xE000_E010, 0xE000_E014, 0xE000_E018, 0xE000_E01C
ISER, ICER, ISPR, ICPR, IPR = 0xE000_E100, 0xE000_E180, 0xE000_E200, 0xE000_E280, 0xE000_E400
CPUID, ICSR, SHPR2, SHPR3 = 0xE000_ED00, 0xE000_ED04, 0xE000_ED1C, 0xE000_ED20

PENDSV, SYSTICK, IRQ0 = 14, 15, 16
NUM_IRQS = 32
CPUID_VALUE = 0x410C_C200
CALIB_VALUE = 0xC000_0000
MASK24 = 0xFF_FFFF


class Nvic:
    def __init__(self):
        self.enabled = 0            # interrupt enables, bit n
        self.pending = 0            # interrupt pending, bit n
        self.prio = [0] * NUM_IRQS  # 2-bit priorities
        self.pendsv = self.pendst = False
        self.prio_svcall = self.prio_pendsv = self.prio_systick = 0
        self.syst_enable = self.syst_tickint = self.countflag = False
        self.rvr = self.cvr = 0
        self.active = []            # [(exception, priority)], the most recent last

    # --- What the core and software see ------------------------------------------

    def priority(self, exc):
        return {PENDSV: self.prio_pendsv, SYSTICK: self.prio_systick}.get(exc) \
            if exc < IRQ0 else self.prio[exc - IRQ0]

    def _pending(self):
        """Pending and enabled exceptions, in number order."""
        out = [PENDSV] if self.pendsv else []
        out += [SYSTICK] if self.pendst else []
        both = self.pending & self.enabled
        return out + [IRQ0 + n for n in range(NUM_IRQS) if both >> n & 1]

    def best(self, below=4):
        """The highest-priority pending exception with priority < `below`, or 0."""
        candidates = [e for e in self._pending() if self.priority(e) < below]
        return min(candidates, key=lambda e: (self.priority(e), e)) if candidates else 0

    @property
    def current_priority(self):
        return self.active[-1][1] if self.active else 4

    @property
    def irq(self) -> bool:
        """The core's machine external interrupt line."""
        return self.best(self.current_priority) != 0

    def read(self, addr):
        """A read's value (no side effects: those are in step())."""
        if addr == CLAIM:
            return self.best(self.current_priority)
        if addr in (ISER, ICER):
            return self.enabled
        if addr in (ISPR, ICPR):
            return self.pending
        if IPR <= addr < IPR + 4 * NUM_IRQS // 4:
            base = (addr - IPR) // 4 * 4
            return sum(self.prio[base + k] << (8 * k + 6) for k in range(4))
        return {
            SYST_CSR: self.syst_enable | self.syst_tickint << 1 | 1 << 2 | self.countflag << 16,
            SYST_RVR: self.rvr, SYST_CVR: self.cvr, SYST_CALIB: CALIB_VALUE, CPUID: CPUID_VALUE,
            ICSR: (self.pendsv << 28 | self.pendst << 26 | (self.pending != 0) << 22
                   | self.best() << 12 | (self.active[-1][0] if self.active else 0)),
            SHPR2: self.prio_svcall << 30, SHPR3: self.prio_systick << 30 | self.prio_pendsv << 22,
        }.get(addr, 0)

    # --- One clock cycle ---------------------------------------------------------

    def step(self, lines=0, read=None, write=None):
        """One cycle: `read` an address, or `write` (address, value), with the
        interrupt lines at `lines`. Returns the read's value (or None)."""
        value = self.read(read) if read is not None else None
        waddr, wdata = write if write is not None else (None, 0)

        # SysTick counts, unless CVR is written (cleared, with COUNTFLAG).
        countflag, pendst = self.countflag, self.pendst
        if read == SYST_CSR:
            countflag = False
        if waddr == SYST_CVR:
            cvr, countflag = 0, False
        elif self.syst_enable:
            if self.cvr == 0:
                cvr = self.rvr
            else:
                cvr = self.cvr - 1
                if cvr == 0:
                    countflag = True
                    pendst = pendst or self.syst_tickint
        else:
            cvr = self.cvr

        # Pending and enables. A claim clears its pending bit and makes it active.
        pending, pendsv, enabled = self.pending, self.pendsv, self.enabled
        active = list(self.active)
        if read == CLAIM and value:
            active.append((value, self.priority(value)))
            if value == PENDSV:
                pendsv = False
            elif value == SYSTICK:
                pendst = False
            else:
                pending &= ~(1 << value - IRQ0)
        if waddr == COMPLETE and active:
            active.pop()
        if waddr == ISER:
            enabled |= wdata
        elif waddr == ICER:
            enabled &= ~wdata
        elif waddr == ISPR:
            pending |= wdata
        elif waddr == ICPR:
            pending &= ~wdata
        elif waddr == ICSR:
            if wdata >> 28 & 1:
                pendsv = True
            if wdata >> 27 & 1:
                pendsv = False
            if wdata >> 26 & 1:
                pendst = True
            if wdata >> 25 & 1:
                pendst = False
        # Lines pend their interrupt while high, unless it is active.
        # (An interrupt can be active twice: pended again and raised in priority,
        # it preempts its own handler.)
        active_irqs = 0
        for e, _ in active:
            if e >= IRQ0:
                active_irqs |= 1 << e - IRQ0
        pending |= lines & ~active_irqs

        # Configuration.
        if waddr == SYST_CSR:
            self.syst_enable, self.syst_tickint = bool(wdata & 1), bool(wdata & 2)
        elif waddr == SYST_RVR:
            self.rvr = wdata & MASK24
        elif waddr is not None and IPR <= waddr < IPR + NUM_IRQS:
            base = (waddr - IPR) // 4 * 4
            for k in range(4):
                self.prio[base + k] = wdata >> (8 * k + 6) & 3
        elif waddr == SHPR2:
            self.prio_svcall = wdata >> 30 & 3
        elif waddr == SHPR3:
            self.prio_systick, self.prio_pendsv = wdata >> 30 & 3, wdata >> 22 & 3

        self.cvr, self.countflag, self.pendst = cvr, countflag, pendst
        self.pending, self.pendsv, self.enabled = pending & 0xFFFF_FFFF, pendsv, enabled & 0xFFFF_FFFF
        self.active = active
        return value
