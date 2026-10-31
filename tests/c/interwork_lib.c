/* Thumb side of the interworking test. Every signature passes arguments the
 * same way under AAPCS and RISC-V ilp32; signatures that differ need thunks
 * (Phase 0.6). */
#include <stdint.h>

struct point {
    int32_t x, y;
};

int thumb_const(void)
{
    return 0x1234567;
}

int thumb_args4(int a, int b, int c, int d)
{
    return a - 2 * b + 3 * c - 4 * d;
}

/* Narrow types: both ABIs extend arguments in the caller and results in the callee. */
signed char thumb_narrow(signed char a, unsigned short b)
{
    return (signed char)(a * 3 + (b >> 4));
}

/* Writes through pointers into the RISC-V side's data. */
void thumb_minmax(const int32_t *a, int n, int32_t *min, int32_t *max)
{
    int32_t lo = a[0], hi = a[0];
    for (int i = 1; i < n; i++) {
        if (a[i] < lo)
            lo = a[i];
        if (a[i] > hi)
            hi = a[i];
    }
    *min = lo;
    *max = hi;
}

int64_t thumb_point_dot(const struct point *p, int n)
{
    int64_t sum = 0;
    for (int i = 0; i < n; i++)
        sum += (int64_t)p[i].x * p[i].y;
    return sum;
}

/* A callback with four arguments, into code that uses many callee-saved registers. */
int thumb_fold(int (*f)(int, int, int, int), const int32_t *a, int n)
{
    int acc = 0;
    for (int i = 0; i + 2 < n; i += 3)
        acc = f(acc, a[i], a[i + 1], a[i + 2]);
    return acc;
}

/* Recursion that alternates between the two instruction sets. */
static int (*pong)(int);

void thumb_set_pong(int (*f)(int))
{
    pong = f;
}

int thumb_ping(int n)
{
    return n <= 0 ? 0 : 3 + pong(n - 1);
}
