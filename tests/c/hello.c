/* Hello world for the simulation SoC: prints over the UART, sets the LEDs. */

#include "soc.h"

int main(void)
{
    soc_puts("Hello from Thumb-V\n");
    LEDS = 0xA5;
    return (int)LEDS;   /* reads back 0xa5 */
}
