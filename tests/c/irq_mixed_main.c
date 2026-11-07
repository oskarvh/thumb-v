/* Phase 5.3: interrupts and traps across both instruction sets, through
 * the firmware's entry routine (firmware/). Prints one line per check;
 * tests/test_rtl.py checks them, in lockstep with the model. */
#include "thumbv.h"
#include "soc.h"

void t_log(uint32_t c);
uint32_t t_log_get(int i);
int t_log_count(void);
uint32_t t_ticks(void);
void t_systick(void);
void t_flags_systick(void);
uint32_t t_busy(uint32_t n);
void t_low(void);
void t_high(void);
uint32_t t_svc_add(uint32_t a, uint32_t b);
uint32_t t_svc_mul(uint32_t a, uint32_t b);

#define N 3000
#define TICK 399                    /* SysTick: every 400 cycles */

static volatile uint32_t rv_ticks, latency;

static uint32_t rv_busy(uint32_t n)
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

static void rv_systick(void) { rv_ticks++; }
static void rv_irq3(void) { t_log(4); }
static void rv_pendsv(void) { t_log(5); }
static void rv_latency(void) { latency = SYST_CVR; thumbv_systick_stop(); }
static uint32_t svc_add(uint32_t *args) { return args[0] + args[1]; }
static uint32_t svc_mul(uint32_t *args) { return args[0] * args[1]; }

static void line(const char *what, uint32_t value)
{
    soc_puts(what);
    soc_put_hex(value);
    soc_putc('\n');
}

static uint32_t under_systick(thumbv_handler handler, uint32_t (*busy)(uint32_t))
{
    thumbv_set_handler(THUMBV_SYSTICK, handler);
    thumbv_systick_start(TICK, 0);
    thumbv_interrupts_on();
    uint32_t r = busy(N);
    thumbv_interrupts_off();
    thumbv_systick_stop();
    return r;
}

int main(void)
{
    thumbv_init();
    uint32_t want_rv = rv_busy(N), want_thumb = t_busy(N);

    /* A Thumb handler interrupting RISC-V code, a RISC-V handler
     * interrupting Thumb code, a Thumb handler interrupting Thumb code. */
    line("thumb handler, riscv code: ", under_systick(t_systick, rv_busy) == want_rv);
    line("  thumb ticks:             ", t_ticks());
    line("riscv handler, thumb code: ", under_systick(rv_systick, t_busy) == want_thumb);
    line("  riscv ticks:             ", rv_ticks);
    uint32_t before = t_ticks();
    line("thumb handler, thumb code: ", under_systick(t_flags_systick, t_busy) == want_thumb);
    line("  thumb ticks:             ", t_ticks() - before);

    /* Preemption by priority, and PendSV. */
    thumbv_irq_priority(1, 2);
    thumbv_irq_priority(2, 1);
    thumbv_irq_priority(3, 2);
    thumbv_pendsv_priority(3);
    thumbv_set_handler(THUMBV_IRQ(1), t_low);
    thumbv_set_handler(THUMBV_IRQ(2), t_high);
    thumbv_set_handler(THUMBV_IRQ(3), rv_irq3);
    thumbv_set_handler(THUMBV_PENDSV, rv_pendsv);
    for (int irq = 1; irq <= 3; irq++)
        thumbv_irq_enable(irq);
    thumbv_interrupts_on();
    thumbv_irq_pend(1);
    while (t_log_count() < 5)
        ;
    thumbv_interrupts_off();
    uint32_t order = 0;
    for (int i = 0; i < t_log_count(); i++)
        order = order << 4 | t_log_get(i);
    line("order (12345):             ", order);

    /* SVC from Thumb, ecall from RISC-V, by number. */
    thumbv_set_svc(1, svc_add);
    thumbv_set_svc(2, svc_mul);
    line("svc #1 (20, 22):           ", t_svc_add(20, 22));
    line("svc #2 (6, 7):             ", t_svc_mul(6, 7));
    register uint32_t a0 __asm__("a0") = 100;
    register uint32_t a1 __asm__("a1") = 23;
    register uint32_t a7 __asm__("a7") = 1;
    __asm__ volatile("ecall" : "+r"(a0) : "r"(a1), "r"(a7) : "memory");
    line("ecall 1 (100, 23):         ", a0);

    /* Latency: SysTick pends as it reaches 0, reloads with 1000 the next
     * cycle and counts down; the handler reads it first thing. */
    thumbv_set_handler(THUMBV_SYSTICK, rv_latency);
    thumbv_systick_start(1000, 0);
    thumbv_interrupts_on();
    while (!latency)
        ;
    thumbv_interrupts_off();
    line("latency (cycles):          ", 1000 - latency + 1);
    return 0;
}
