/* Phase 5.2: the interrupt controller from software, on the SoC. Pends an
 * interrupt (priority 1) and PendSV (priority 3), starts SysTick (priority
 * 0), then enables interrupts: the handler (trap_handler.S calls trap_c)
 * claims and completes each, recording the exception numbers and what the
 * controller showed while it was active. tests/test_rtl.py checks the order. */
#include <stdint.h>

#define REG(a) (*(volatile uint32_t *)(a))
#define SYST_CSR REG(0xE000E010)
#define SYST_RVR REG(0xE000E014)
#define ISER     REG(0xE000E100)
#define ISPR     REG(0xE000E200)
#define IPR0     REG(0xE000E400)
#define ICSR     REG(0xE000ED04)
#define SHPR3    REG(0xE000ED20)
#define CLAIM    REG(0x10001000)
#define COMPLETE REG(0x10001004)

#define CSR_SET(csr, v) __asm__ volatile(".option push\n.option arch, +zicsr\ncsrs " #csr ", %0\n.option pop" : : "r"(v))
#define CSR_CLR(csr, v) __asm__ volatile(".option push\n.option arch, +zicsr\ncsrc " #csr ", %0\n.option pop" : : "r"(v))

void trap_entry(void);

uint32_t claimed[16], active_seen[16];
volatile int nclaimed, ticks;

uint32_t trap_c(uint32_t cause, uint32_t epc, uint32_t tval)
{
    (void)tval;
    if (cause == 0x8000000b) {                 /* machine external: the controller */
        uint32_t n = CLAIM;
        if (nclaimed < 16) {
            claimed[nclaimed] = n;
            active_seen[nclaimed] = ICSR & 0x1ff;    /* VECTACTIVE */
            nclaimed++;
        }
        if (n == 15 && ++ticks == 5)
            SYST_CSR = 0;                      /* five ticks are enough */
        COMPLETE = n;
    }
    return epc;
}

int main(void)
{
    __asm__ volatile(".option push\n.option arch, +zicsr\ncsrw mtvec, %0\n.option pop" : : "r"(trap_entry));
    IPR0 = 1u << 30;                           /* interrupt 3: priority 1 */
    SHPR3 = 0u << 30 | 3u << 22;               /* SysTick 0, PendSV 3 */
    ISER = 1u << 3;
    ISPR = 1u << 3;
    ICSR = 1u << 28;                           /* PENDSVSET */
    SYST_RVR = 300;
    SYST_CSR = 3;                              /* ENABLE, TICKINT */
    CSR_SET(mie, 1u << 11);                    /* MEIE */
    CSR_SET(mstatus, 1u << 3);                 /* MIE */
    while (ticks < 5)
        ;
    CSR_CLR(mstatus, 1u << 3);
    uint32_t sum = 0;
    for (int i = 0; i < nclaimed; i++)
        sum = sum * 31 + claimed[i];
    return (int)sum;
}
