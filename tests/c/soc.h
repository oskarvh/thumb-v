/* Registers of the Thumb-V SoC (rtl/soc/thumbv_soc.v). */
#ifndef SOC_H
#define SOC_H

#include <stdint.h>

#define UART_DATA   (*(volatile uint32_t *)0x10000000)   /* write: send a byte */
#define UART_STATUS (*(volatile uint32_t *)0x10000004)   /* bit 0: busy */
#define LEDS        (*(volatile uint32_t *)0x10000008)

static inline void soc_putc(char c)
{
    while (UART_STATUS & 1)
        ;
    UART_DATA = (uint8_t)c;
}

static inline void soc_puts(const char *s)
{
    while (*s)
        soc_putc(*s++);
}

static inline void soc_put_hex(uint32_t v)
{
    for (int i = 28; i >= 0; i -= 4)
        soc_putc("0123456789abcdef"[(v >> i) & 0xF]);
}

#endif
