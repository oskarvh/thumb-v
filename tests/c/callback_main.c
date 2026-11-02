/* Phase 3.5: RISC-V main for callback.c: calls into Thumb code, which calls
 * back into the two RISC-V functions here. */
#include "callback.h"
#include "soc.h"

int rv_square(int x)
{
    return x * x;
}

void rv_print(const char *what, unsigned value)
{
    soc_puts(what);
    soc_put_hex(value);
    soc_putc('\n');
}

int main(void)
{
    unsigned sum = 0;
    soc_puts("RISC-V and Thumb call each other\n");
    sum += t_lookup(5);
    rv_print("t_lookup(5)        = ", t_lookup(5));
    sum += t_callback(11);
    rv_print("t_callback(11)     = ", t_callback(11));
    sum += t_report(7);
    LEDS = sum;
    return (int)sum;
}
