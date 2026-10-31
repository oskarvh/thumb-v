/* Soft-float kernels for the Phase 0.7 measurements.
 *
 * Cortex-M0 has no FPU: float and double arithmetic compiles to calls into
 * libgcc (__aeabi_fmul, __aeabi_dadd, ...) and sqrt into newlib's libm.
 * Correctness is checked by lockstep against Unicorn, so main() only has to
 * return something that depends on every result.
 */

#include <math.h>
#include <stdint.h>

#define N 6

static float a[N][N], b[N][N], c[N][N];

static uint32_t float_bits(float f)
{
    union { float f; uint32_t u; } v = { f };
    return v.u;
}

static uint32_t double_bits(double d)
{
    union { double d; uint64_t u; } v = { d };
    return (uint32_t)v.u ^ (uint32_t)(v.u >> 32);
}

static uint32_t mix(uint32_t sum, uint32_t v)
{
    return (sum << 5 | sum >> 27) ^ v;
}

/* Single precision: a small matrix multiply. */
static uint32_t matmul(void)
{
    for (int i = 0; i < N; i++)
        for (int j = 0; j < N; j++) {
            a[i][j] = (float)(i * N + j) * 0.25f - 3.0f;
            b[i][j] = 1.0f / (float)(i + j + 1);
        }
    uint32_t sum = 0;
    for (int i = 0; i < N; i++)
        for (int j = 0; j < N; j++) {
            float acc = 0.0f;
            for (int k = 0; k < N; k++)
                acc += a[i][k] * b[k][j];
            c[i][j] = acc;
            sum = mix(sum, float_bits(acc));
        }
    return sum;
}

/* Double precision: polynomial evaluation, comparisons and conversions. */
static uint32_t polynomial(void)
{
    uint32_t sum = 0;
    for (int k = -16; k < 16; k++) {
        double x = k * 0.125;
        double y = (((1.5 * x - 2.25) * x + 0.75) * x - 1.0) * x + 4.0;
        if (y > 4.0)
            y = 8.0 - y;
        sum = mix(sum, double_bits(y));
        sum = mix(sum, (uint32_t)(int32_t)(y * 1000.0));
    }
    return sum;
}

/* libm: square roots in both precisions, and a Newton iteration to compare. */
static uint32_t roots(void)
{
    uint32_t sum = 0;
    for (int k = 1; k <= 16; k++) {
        double r = sqrt(k * 3.0);
        float rf = sqrtf((float)k);
        double g = k;
        for (int i = 0; i < 4; i++)
            g = 0.5 * (g + k * 3.0 / g);
        sum = mix(sum, double_bits(r));
        sum = mix(sum, float_bits(rf));
        sum = mix(sum, (uint32_t)(fabs(g - r) < 1e-3));
    }
    return sum;
}

int main(void)
{
    return (int)(matmul() ^ polynomial() ^ roots());
}
