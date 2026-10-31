/* RISC-V side of the mixed-program test: calls into the Thumb library. */
#include <stdint.h>

extern int thumb_sum(const int32_t *a, int n);
extern uint32_t thumb_crc32(const uint8_t *p, int n);
extern int thumb_apply(int (*f)(int), int x);
extern int64_t thumb_mul64(int64_t a, int64_t b);
extern int thumb_div(int a, int b);
extern int thumb_count(void);

int32_t data[16];
uint8_t bytes[32];

static uint32_t mix(uint32_t h, uint32_t v)
{
    return (h ^ v) * 16777619u;
}

__attribute__((noinline)) int rv_square(int x)
{
    return x * x;
}

int main(void)
{
    uint32_t h = 2166136261u;
    for (int i = 0; i < 16; i++)
        data[i] = i * i - 7 * i;
    for (int i = 0; i < 32; i++)
        bytes[i] = (uint8_t)(i * 37);

    h = mix(h, (uint32_t)thumb_sum(data, 16));
    h = mix(h, thumb_crc32(bytes, 32));
    h = mix(h, (uint32_t)thumb_apply(rv_square, 9));
    int64_t p = thumb_mul64(-123456789012LL, 98765);
    h = mix(h, (uint32_t)p);
    h = mix(h, (uint32_t)(p >> 32));
    h = mix(h, (uint32_t)thumb_div(-1000003, 17));
    for (int i = 0; i < 3; i++)
        h = mix(h, (uint32_t)thumb_count());
    return (int)h;
}
