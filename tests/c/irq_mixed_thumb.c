/* Phase 5.3: Thumb code for irq_mixed_main.c, compiled for Cortex-M0:
 * interrupt handlers written as Cortex-M code writes them (plain functions,
 * the SCS registers directly), flag-heavy code to interrupt, SVC callers. */
#include <stdint.h>
#include "thumbv_scs.h"

static volatile uint32_t ticks;
static volatile uint32_t log_[16];
static volatile int nlog;

void t_log(uint32_t c)
{
    if (nlog < 16)
        log_[nlog++] = c;
}

uint32_t t_log_get(int i) { return i < nlog ? log_[i] : 0; }
int t_log_count(void) { return nlog; }
uint32_t t_ticks(void) { return ticks; }

/* SysTick handlers. */
void t_systick(void)
{
    ticks++;
}

/* Leaves N set and Z, C, V clear, whatever the code it interrupted had: if
 * the entry routine didn't save NZCV, a branch after the interrupt would
 * see these. */
void t_flags_systick(void)
{
    ticks++;
    __asm__ volatile("movs r3, #0\n\tcmp r3, #1" : : : "r3", "cc");
}

/* Compares and branches all the way: interrupts land between them. */
uint32_t t_busy(uint32_t n)
{
    uint32_t h = 0x811c9dc5;
    for (uint32_t i = 0; i < n; i++) {
        h = (h ^ i) * 16777619u;
        if ((int32_t)h < 0)
            h += 7;
        else if (h > 0x40000000u)
            h -= 3;
    }
    return h;
}

/* Nesting: interrupt 1 (priority 2) pends 3 (priority 2: waits) and 2
 * (priority 1: preempts at once); 2 pends PendSV (priority 3: waits).
 * Logged as 1 (enter 1), 2 (2), 3 (leave 1), then 4 (3) and 5 (PendSV)
 * from RISC-V. */
void t_low(void)
{
    t_log(1);
    NVIC_ISPR = 1u << 3;
    NVIC_ISPR = 1u << 2;
    __asm__ volatile("dsb\n\tisb" : : : "memory");
    t_log(3);
}

void t_high(void)
{
    t_log(2);
    SCB_ICSR = SCB_ICSR_PENDSVSET;
}

/* SVC #1 and #2 with two arguments, the result in r0. */
uint32_t t_svc_add(uint32_t a, uint32_t b)
{
    register uint32_t r0 __asm__("r0") = a;
    register uint32_t r1 __asm__("r1") = b;
    __asm__ volatile("svc #1" : "+r"(r0) : "r"(r1) : "memory");
    return r0;
}

uint32_t t_svc_mul(uint32_t a, uint32_t b)
{
    register uint32_t r0 __asm__("r0") = a;
    register uint32_t r1 __asm__("r1") = b;
    __asm__ volatile("svc #2" : "+r"(r0) : "r"(r1) : "memory");
    return r0;
}
