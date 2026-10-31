/* RISC-V side of the interworking test. */
#include <stdint.h>

struct point {
    int32_t x, y;
};

extern int thumb_const(void);
extern int thumb_args4(int a, int b, int c, int d);
extern signed char thumb_narrow(signed char a, unsigned short b);
extern void thumb_minmax(const int32_t *a, int n, int32_t *min, int32_t *max);
extern int64_t thumb_point_dot(const struct point *p, int n);
extern int thumb_fold(int (*f)(int, int, int, int), const int32_t *a, int n);
extern void thumb_set_pong(int (*f)(int));
extern int thumb_ping(int n);

int32_t values[12] = {5, -3, 99, 42, -100, 7, 0, 64, -1, 13, 2, 8};
struct point points[4] = {{1, 2}, {-300000, 400000}, {7, -8}, {123456, 654321}};

static uint32_t mix(uint32_t h, uint32_t v)
{
    return (h ^ v) * 16777619u;
}

/* Uses enough live values to need callee-saved registers. */
__attribute__((noinline)) int rv_combine(int acc, int a, int b, int c)
{
    int t0 = acc * 31, t1 = a ^ b, t2 = b - c, t3 = a * c, t4 = acc + a + b + c;
    int t5 = t0 + t1, t6 = t2 * t3, t7 = t4 ^ t0;
    return t5 + t6 + t7 + (t1 > t2) + (t3 < t4);
}

int rv_pong(int n)
{
    return n <= 0 ? 0 : 5 + thumb_ping(n - 1);
}

int main(void)
{
    uint32_t h = 2166136261u;
    int32_t lo, hi;

    h = mix(h, (uint32_t)thumb_const());
    h = mix(h, (uint32_t)thumb_args4(1000, -20, 3, 0x7FFFFFFF));
    h = mix(h, (uint32_t)thumb_narrow(-77, 0xFFFF));
    thumb_minmax(values, 12, &lo, &hi);
    h = mix(h, (uint32_t)lo);
    h = mix(h, (uint32_t)hi);
    int64_t dot = thumb_point_dot(points, 4);
    h = mix(h, (uint32_t)dot);
    h = mix(h, (uint32_t)(dot >> 32));
    h = mix(h, (uint32_t)thumb_fold(rv_combine, values, 12));
    thumb_set_pong(rv_pong);
    h = mix(h, (uint32_t)thumb_ping(10));
    return (int)h;
}
