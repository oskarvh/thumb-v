/* Board smoke test: counts on the LEDs and prints the count, forever. */

#include "soc.h"

int main(void)
{
    for (uint32_t n = 0;; n++) {
        LEDS = n;
        soc_puts("tick ");
        soc_put_hex(n);
        soc_putc('\n');
        for (volatile uint32_t i = 0; i < 300000; i++)   /* about 0.25 s at 12 MHz */
            ;
    }
}
