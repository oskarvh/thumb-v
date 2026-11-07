/* The board demo's blinky: a scanner on LEDs 0-6. This one source is built
 * twice, by arm-none-eabi-gcc for Cortex-M0 (t_blinky) and by
 * riscv64-unknown-elf-gcc (rv_blinky); demo_main.c runs one at a time. */
#include "demo.h"

#ifdef __thumb__
#define BLINKY t_blinky
#else
#define BLINKY rv_blinky
#endif

#define LEDS (*(volatile uint32_t *)0x10000008)

void BLINKY(void *arg)
{
    struct blinky *b = arg;
    struct scanner *s = b->scan;
    for (;;) {
        /* One step, with the scheduler suspended: the other build must not
         * take over half-way through it and have its position overwritten. */
        vTaskSuspendAll();
        LEDS = (1u << s->pos) | b->mark;
        if ((s->pos == 6 && s->dir > 0) || (s->pos == 0 && s->dir < 0))
            s->dir = -s->dir;
        s->pos += s->dir;
        b->steps++;
        xTaskResumeAll();
        vTaskDelay(b->delay);
    }
}
