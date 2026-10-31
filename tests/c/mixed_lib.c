/* Thumb library called from RISC-V in the mixed-program test. All signatures
 * pass arguments the same way under AAPCS and RISC-V ilp32, so no thunks. */
#include <stdint.h>

int32_t thumb_counter;  /* Thumb-side data in RAM */

int thumb_sum(const int32_t *a, int n)
{
    int s = 0;
    for (int i = 0; i < n; i++)
        s += a[i];
    return s;
}

uint32_t thumb_crc32(const uint8_t *p, int n)
{
    uint32_t crc = 0xFFFFFFFF;
    while (n--) {
        crc ^= *p++;
        for (int k = 0; k < 8; k++)
            crc = (crc >> 1) ^ (0xEDB88320 & -(crc & 1));
    }
    return ~crc;
}

/* Calls back into RISC-V through a function pointer (BLX to an even address). */
int thumb_apply(int (*f)(int), int x)
{
    return f(x) * 2 + f(x + 1);
}

int64_t thumb_mul64(int64_t a, int64_t b)
{
    return a * b;
}

int thumb_div(int a, int b)
{
    return a / b;
}

int thumb_count(void)
{
    return ++thumb_counter;
}
