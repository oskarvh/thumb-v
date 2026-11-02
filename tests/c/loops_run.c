/* Phase 4.4: the RISC-V side of loops.c: calls every function on fixed data
 * and returns a checksum of the results, printing them if asked. Linked with
 * loops_main.c (prints, on the board), irq_loops_main.c (under interrupts)
 * or loops_check_main.c (no SoC needed: the model's lockstep, and with
 * loops.c as all-RISC-V code, the native reference). */
#include "loops.h"
#include "soc.h"

unsigned run_loops(int print);

static unsigned sum;
static int printing;

static void result(const char *what, uint32_t value)
{
    sum = sum * 31 + value;
    if (printing) {
        soc_puts(what);
        soc_put_hex(value);
        soc_putc('\n');
    }
}

static const uint8_t text[] = "The quick brown fox jumps over the lazy dog";
static const int32_t xs[] = {7, -3, 100000, 0, 42, -1001, 8, 123457, -5, 9, 64, 2};
#define NXS (int)(sizeof xs / sizeof xs[0])

unsigned run_loops(int print)
{
    int32_t a[NXS];
    sum = 0;
    printing = print;
    result("crc32(text)        = ", t_crc32(text, sizeof text - 1));
    for (int i = 0; i < NXS; i++)
        a[i] = xs[i];
    t_sort(a, NXS);
    uint32_t sorted = 0;
    for (int i = 0; i < NXS; i++)
        sorted = sorted * 7 + (uint32_t)a[i];
    result("sort(xs)           = ", sorted);
    result("search(42)         = ", (uint32_t)t_search(a, NXS, 42));
    result("search(43)         = ", (uint32_t)t_search(a, NXS, 43));
    result("gcd(1071, 462)     = ", t_gcd(1071, 462));
    result("gcd(2^32-1, 65535) = ", t_gcd(0xFFFFFFFF, 65535));
    result("popcount(...)      = ", (uint32_t)t_popcount(0xF00F1234));
    uint64_t f = t_fib64(90);
    result("fib(90) high       = ", (uint32_t)(f >> 32));
    result("fib(90) low        = ", (uint32_t)f);
    int64_t d = t_dot64(xs, a, NXS);
    result("dot64 high         = ", (uint32_t)((uint64_t)d >> 32));
    result("dot64 low          = ", (uint32_t)d);
    uint32_t classes = 0;
    for (int i = 0; i < NXS; i++)
        classes = classes * 8 + (uint32_t)t_classify(xs[i]);
    result("classify(xs)       = ", classes);
    result("strcmp             = ", (uint32_t)t_strcmp("thumb-v", "thumb-x"));
    result("isqrt(1000000007)  = ", (uint32_t)t_isqrt(1000000007));
    return sum;
}
