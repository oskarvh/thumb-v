/* Thumb-only self-test. Besides ordinary integer code it pulls in libgcc's
 * hand-written Thumb-1 helpers: division, 64-bit shifts and multiply,
 * switch tables and soft-float. */
#include <stdint.h>

void *memcpy(void *dst, const void *src, unsigned n)
{
    uint8_t *d = dst;
    const uint8_t *s = src;
    while (n--)
        *d++ = *s++;
    return dst;
}

void *memset(void *dst, int c, unsigned n)
{
    uint8_t *d = dst;
    while (n--)
        *d++ = (uint8_t)c;
    return dst;
}

/* Inputs the compiler can't constant-fold. */
volatile int32_t in[4] = {123456789, -987654, 31, 7};

static uint32_t mix(uint32_t h, uint32_t v)
{
    return (h ^ v) * 16777619u;
}

__attribute__((noinline)) static uint32_t fib(uint32_t n)
{
    return n < 2 ? n : fib(n - 1) + fib(n - 2);
}

__attribute__((noinline)) static uint32_t crc32(const uint8_t *p, int n)
{
    uint32_t crc = 0xFFFFFFFF;
    while (n--) {
        crc ^= *p++;
        for (int k = 0; k < 8; k++)
            crc = (crc >> 1) ^ (0xEDB88320 & -(crc & 1));
    }
    return ~crc;
}

__attribute__((noinline)) static int classify(int x)
{
    switch (x) {
    case 0: return 11;
    case 1: return 22;
    case 2: return 33;
    case 3: return 44;
    case 4: return 55;
    case 5: return 66;
    case 6: return 77;
    case 7: return 88;
    default: return -1;
    }
}

__attribute__((noinline)) static void sort(int32_t *a, int n)
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

int main(void)
{
    uint32_t h = 2166136261u;
    int32_t a = in[0], b = in[1], s = in[2], t = in[3];

    h = mix(h, fib(t + 8));                        /* recursion: PUSH/POP, BL/BX */
    h = mix(h, (uint32_t)(a / b));                 /* __aeabi_idiv */
    h = mix(h, (uint32_t)a % (uint32_t)t);         /* __aeabi_uidivmod */

    uint64_t wide = (uint64_t)(uint32_t)a * (uint32_t)b;   /* __aeabi_lmul */
    h = mix(h, (uint32_t)wide);
    h = mix(h, (uint32_t)(wide >> 32));

    uint64_t x64 = (uint64_t)(uint32_t)a << 32 | (uint32_t)b;
    h = mix(h, (uint32_t)(x64 << s));              /* __aeabi_llsl */
    h = mix(h, (uint32_t)((x64 << s) >> 32));
    int64_t y64 = (int64_t)x64 >> (s + 2);         /* __aeabi_lasr */
    h = mix(h, (uint32_t)y64);
    h = mix(h, (uint32_t)(y64 >> 32));
    h = mix(h, (uint32_t)(x64 / (uint32_t)t));     /* __aeabi_uldivmod */

    for (int i = 0; i < 10; i++)
        h = mix(h, (uint32_t)classify(i - 1));     /* switch table */

    uint8_t bytes[32];
    for (int i = 0; i < 32; i++)
        bytes[i] = (uint8_t)((uint32_t)a >> (i & 31)) + (uint8_t)i;   /* register shifts */
    h = mix(h, crc32(bytes, 32));

    int32_t arr[12];
    for (int i = 0; i < 12; i++)
        arr[i] = (int32_t)mix((uint32_t)i, (uint32_t)a) >> (i & 7);
    sort(arr, 12);
    for (int i = 0; i < 12; i++)
        h = mix(h, (uint32_t)arr[i]);

    float f = (float)a * 1.5f + (float)b / 3.0f;   /* soft-float */
    h = mix(h, (uint32_t)(int32_t)f);
    double d = (double)a * (double)b + 0.25;       /* soft double */
    h = mix(h, (uint32_t)(int64_t)d);

    h = mix(h, (uint32_t)(a > b) | (uint32_t)(a < 0) << 1 | (uint32_t)((uint32_t)a > (uint32_t)b) << 2);
    return (int)h;
}
