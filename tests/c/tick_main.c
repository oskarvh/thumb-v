/* Phase 5.3: SysTick at 10 Hz (on the board's 12 MHz clock) with a Thumb
 * handler (tick_thumb.c); RISC-V prints each new count. Runs forever. */
#include "thumbv.h"
#include "soc.h"

void SysTick_Handler(void);
uint32_t t_ticks(void);

int main(void)
{
    thumbv_init();
    thumbv_set_handler(THUMBV_SYSTICK, SysTick_Handler);
    thumbv_systick_start(12000000 / 10 - 1, 0);
    thumbv_interrupts_on();
    soc_puts("SysTick at 10 Hz, Thumb handler\n");
    uint32_t seen = 0;
    for (;;) {
        uint32_t now = t_ticks();
        if (now != seen) {
            seen = now;
            soc_puts("tick ");
            soc_put_hex(now);
            soc_putc('\n');
        }
    }
}
