/* RISC-V side of the ABI test: implements the rv_* functions of abi.h and
 * calls the Thumb t_* functions. */
#include "abi.h"

static uint32_t recorded;

int rv_args6(int a, int b, int c, int d, int e, int f)
{
    return a - b + c - d + e - 2 * f;
}

int64_t rv_mixed(int a, int64_t b, int c)
{
    return a * b - c;
}

struct pair rv_make_pair(int a, int b)
{
    struct pair p = {a + b, a * b};
    return p;
}

int rv_sum_big(struct big b)
{
    return b.w[0] * 1000 + b.w[1] * 100 + b.w[2] * 10 + b.w[3];
}

struct six rv_make_six(int seed)
{
    struct six s;
    for (int i = 0; i < 6; i++)
        s.c[i] = (uint8_t)(seed * (i + 2));
    return s;
}

int rv_add(int a, int b)
{
    return a + b;
}

void rv_record(uint32_t v)
{
    recorded = v ^ 0xA5A5A5A5;
}

static uint32_t mix(uint32_t h, uint32_t v)
{
    return (h ^ v) * 16777619u;
}

static uint32_t mix64(uint32_t h, int64_t v)
{
    return mix(mix(h, (uint32_t)v), (uint32_t)(v >> 32));
}

int main(void)
{
    uint32_t h = 2166136261u;
    h = mix(h, (uint32_t)t_args6(1, -2, 3, -4, 5, 0x7FFFFFFF));
    h = mix64(h, t_mixed(-7, 0x100000003LL, 11));
    h = mix64(h, t_wide4(1, 0x200000000LL, -3, 0x1234567890LL));
    struct pair p = t_make_pair(6, 50);
    h = mix(mix(h, (uint32_t)p.a), (uint32_t)p.b);
    struct big b = t_make_big(9);
    for (int i = 0; i < 4; i++)
        h = mix(h, (uint32_t)b.w[i]);
    h = mix(h, (uint32_t)t_sum_big(b));
    struct p64 q = {0x123456789ABCLL};
    h = mix(h, (uint32_t)t_sum_p64(-5, q));
    struct six s = t_make_six(40);
    for (int i = 0; i < 6; i++)
        h = mix(h, s.c[i]);
    struct small sm = t_small(-100, 30000);
    h = mix(mix(h, (uint32_t)sm.a), (uint32_t)sm.b);
    struct odd o;
    for (int i = 0; i < 10; i++)
        o.c[i] = (uint8_t)(200 + i);
    h = mix(h, (uint32_t)t_sum_odd(3, o, -4));
    h = mix(h, (uint32_t)t_tail(1, 2, 3, 4, 5, 6, 7, 0x0000000800000009LL));
    struct pair tp = {12, 13};
    h = mix(h, (uint32_t)t_tail_pair(1, 2, 3, 4, 5, 6, 7, tp));
    double d = t_poly(1.5, 2.0, -3.25, 0.125);
    int64_t bits;
    __builtin_memcpy(&bits, &d, sizeof bits);
    h = mix64(h, bits);
    h = mix(h, t_call_imports());
    h = mix(h, recorded);
    return (int)h;
}
