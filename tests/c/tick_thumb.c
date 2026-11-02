/* Phase 5.3: a SysTick handler compiled for Cortex-M0, as Cortex-M code
 * writes one: it counts and shows the count on the LEDs. Used by tick_main.c
 * (make board PROGRAM=tick). */
#include <stdint.h>
#include "thumbv_scs.h"

#define LEDS THUMBV_REG(0x10000008)

static volatile uint32_t ticks;

void SysTick_Handler(void)
{
    ticks++;
    LEDS = ticks;
}

uint32_t t_ticks(void) { return ticks; }
