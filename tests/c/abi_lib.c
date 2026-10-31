/* Thumb side of the ABI test: implements the t_* functions of abi.h and
 * calls the RISC-V rv_* functions by name. */
#include "abi.h"

int t_args6(int a, int b, int c, int d, int e, int f)
{
    return a + 2 * b + 3 * c + 4 * d + 5 * e + 6 * f;
}

int64_t t_mixed(int a, int64_t b, int c)
{
    return a * b + c;
}

int64_t t_wide4(int64_t a, int64_t b, int64_t c, int64_t d)
{
    return a - b + (c ^ d);
}

struct pair t_make_pair(int a, int b)
{
    struct pair p = {a * 3, b - a};
    return p;
}

struct big t_make_big(int seed)
{
    struct big r;
    for (int i = 0; i < 4; i++)
        r.w[i] = (seed * (i + 1)) ^ 0x55;
    return r;
}

int t_sum_big(struct big b)
{
    return b.w[0] - b.w[1] + 3 * b.w[2] + b.w[3];
}

int t_sum_p64(int x, struct p64 p)
{
    return x + (int)(p.v >> 16);
}

struct six t_make_six(int seed)
{
    struct six s;
    for (int i = 0; i < 6; i++)
        s.c[i] = (uint8_t)(seed + 7 * i);
    return s;
}

struct small t_small(int8_t a, int16_t b)
{
    struct small s = {(int8_t)(a * 2), (int16_t)(b - 1)};
    return s;
}

int t_sum_odd(int x, struct odd o, int y)
{
    int s = x * y;
    for (int i = 0; i < 10; i++)
        s += o.c[i] * (i + 1);
    return s;
}

int t_tail(int a, int b, int c, int d, int e, int f, int g, int64_t h)
{
    return a + b + c + d + e + f + g + (int)(h >> 32) * 1000 + (int)h;
}

int t_tail_pair(int a, int b, int c, int d, int e, int f, int g, struct pair p)
{
    return a + b + c + d + e + f + g + p.a * 100 + p.b * 10000;
}

double t_poly(double x, double a, double b, double c)
{
    return (a * x + b) * x + c;
}

uint32_t t_call_imports(void)
{
    uint32_t h = 17;
    h = h * 31 + (uint32_t)rv_args6(1, 2, 3, 4, 5, 6);
    int64_t m = rv_mixed(-3, 0x123456789LL, 7);
    h = h * 31 + (uint32_t)m;
    h = h * 31 + (uint32_t)(m >> 32);
    struct pair p = rv_make_pair(10, 20);
    h = h * 31 + (uint32_t)p.a;
    h = h * 31 + (uint32_t)p.b;
    struct big b = {{1, 2, 3, 4}};
    h = h * 31 + (uint32_t)rv_sum_big(b);
    struct six s = rv_make_six(3);
    for (int i = 0; i < 6; i++)
        h = h * 31 + s.c[i];
    h = h * 31 + (uint32_t)rv_add(100, -58);
    rv_record(h);
    return h;
}
