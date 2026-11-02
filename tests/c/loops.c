/* Phase 4.4: Thumb library of loops and conditions (see loops.h). gcc turns
 * these into CMP/TST + B<cond>, ADCS/SBCS for 64-bit arithmetic, and calls
 * into libgcc for division and 64-bit multiplication. */
#include "loops.h"

uint32_t t_crc32(const uint8_t *p, int n)
{
    uint32_t crc = 0xFFFFFFFF;
    while (n-- > 0) {
        crc ^= *p++;
        for (int k = 0; k < 8; k++)
            crc = (crc & 1) ? (crc >> 1) ^ 0xEDB88320 : crc >> 1;
    }
    return ~crc;
}

void t_sort(int32_t *a, int n)          /* insertion sort: signed compares */
{
    for (int i = 1; i < n; i++) {
        int32_t v = a[i];
        int j = i - 1;
        while (j >= 0 && a[j] > v) {
            a[j + 1] = a[j];
            j--;
        }
        a[j + 1] = v;
    }
}

int t_search(const int32_t *a, int n, int32_t key)   /* binary search, -1 if absent */
{
    int lo = 0, hi = n - 1;
    while (lo <= hi) {
        int mid = lo + (hi - lo) / 2;
        if (a[mid] == key)
            return mid;
        if (a[mid] < key)
            lo = mid + 1;
        else
            hi = mid - 1;
    }
    return -1;
}

uint32_t t_gcd(uint32_t a, uint32_t b)  /* unsigned division in libgcc */
{
    while (b != 0) {
        uint32_t t = a % b;
        a = b;
        b = t;
    }
    return a;
}

int t_popcount(uint32_t x)
{
    int n = 0;
    while (x) {
        x &= x - 1;
        n++;
    }
    return n;
}

uint64_t t_fib64(int n)                 /* 64-bit adds: ADDS + ADCS */
{
    uint64_t a = 0, b = 1;
    for (int i = 0; i < n; i++) {
        uint64_t t = a + b;
        a = b;
        b = t;
    }
    return a;
}

int64_t t_dot64(const int32_t *a, const int32_t *b, int n)   /* 64-bit products: libgcc */
{
    int64_t s = 0;
    for (int i = 0; i < n; i++)
        s += (int64_t)a[i] * b[i];
    return s;
}

int t_classify(int32_t x)               /* a chain of signed and unsigned conditions */
{
    if (x < -1000)
        return 0;
    if (x < 0)
        return 1;
    if (x == 0)
        return 2;
    if ((uint32_t)x <= 9)
        return 3;
    if (x & 1)
        return 4;
    return x > 100000 ? 5 : 6;
}

int t_strcmp(const char *a, const char *b)
{
    while (*a && *a == *b) {
        a++;
        b++;
    }
    return (unsigned char)*a - (unsigned char)*b;
}

int t_isqrt(uint32_t x)                 /* bit by bit: unsigned compares, shifts */
{
    uint32_t r = 0, bit = 1u << 30;
    while (bit > x)
        bit >>= 2;
    while (bit) {
        if (x >= r + bit) {
            x -= r + bit;
            r = (r >> 1) + bit;
        } else {
            r >>= 1;
        }
        bit >>= 2;
    }
    return (int)r;
}
