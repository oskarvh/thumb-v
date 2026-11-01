/* Phase 2.4: RISC-V main calling the leaf Thumb functions in thumb_leaf.c and
 * printing their results over the UART. */

#include "soc.h"

int mix(int a, int b);
unsigned xorshift(unsigned x, unsigned y);

static unsigned show(const char *what, unsigned value)
{
    soc_puts(what);
    soc_put_hex(value);
    soc_putc('\n');
    return value;
}

int main(void)
{
    unsigned sum = 0;
    soc_puts("RISC-V calls Thumb\n");
    sum += show("mix(1234, 567)     = ", mix(1234, 567));
    sum += show("mix(-5, 99)        = ", mix(-5, 99));
    unsigned x = 1;
    for (int i = 0; i < 4; i++)
        x = xorshift(x, i);
    sum += show("xorshift, 4 rounds = ", x);
    LEDS = sum;
    return (int)sum;
}
