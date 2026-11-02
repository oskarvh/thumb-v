/* Phase 4.4: prints what gcc-compiled Thumb loops compute (loops.c). */
#include "soc.h"

unsigned run_loops(int print);

int main(void)
{
    soc_puts("Thumb loops and conditions\n");
    unsigned sum = run_loops(1);
    soc_puts("checksum           = ");
    soc_put_hex(sum);
    soc_putc('\n');
    LEDS = sum;
    return (int)sum;
}
