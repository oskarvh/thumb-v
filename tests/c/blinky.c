/* Board smoke test: counts on the LEDs and prints the count, forever. */

#include "soc.h"

static void put_hex(uint32_t v)
{
    for (int i = 28; i >= 0; i -= 4)
        soc_putc("0123456789abcdef"[(v >> i) & 0xF]);
}

int main(void)
{
    for (uint32_t n = 0;; n++) {
        LEDS = n;
        soc_puts("tick ");
        put_hex(n);
        soc_putc('\n');
        for (volatile uint32_t i = 0; i < 300000; i++)   /* about 0.25 s at 12 MHz */
            ;
    }
}
