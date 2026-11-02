/* Phase 5.4: RISC-V code calling CMSIS-DSP (arm_math.h). Linked against the
 * library's Cortex-M0 build, through the interface in cmsis_dsp.h, and
 * against its RISC-V build, the reference: both must print the same. */
#include "arm_math.h"
#include "soc.h"

#define N 32
#define TAPS 16
#define STAGES 2

static uint32_t sum;

static void result(const char *what, uint32_t value)
{
    sum = sum * 31 + value;
    soc_puts(what);
    soc_put_hex(value);
    soc_putc('\n');
}

static uint32_t hash(const void *p, uint32_t bytes)
{
    const uint8_t *b = p;
    uint32_t h = 2166136261u;
    while (bytes--)
        h = (h ^ *b++) * 16777619u;
    return h;
}

static uint32_t bits(float32_t f)
{
    union { float32_t f; uint32_t u; } v = {f};
    return v.u;
}

static uint32_t seed = 12345;
static int32_t next(void)
{
    seed = seed * 1103515245u + 12345u;
    return (int32_t)seed;
}

static q15_t x15[N], y15[N], out15[N], state15[TAPS + N - 1], coeff15[TAPS];
static q31_t x31[N], out31[N], state31[4 * STAGES];
static float32_t outf[N];

int main(void)
{
    for (int i = 0; i < N; i++) {
        x15[i] = (q15_t)(next() >> 17);
        y15[i] = (q15_t)(next() >> 17);
        x31[i] = next() >> 2;
    }
    soc_puts("CMSIS-DSP from RISC-V\n");

    arm_add_q15(x15, y15, out15, N);
    result("arm_add_q15       ", hash(out15, sizeof out15));
    arm_scale_q31(x31, 0x40000000, 1, out31, N);
    result("arm_scale_q31     ", hash(out31, sizeof out31));
    q63_t dot;
    arm_dot_prod_q31(x31, x31, N, &dot);
    result("arm_dot_prod_q31 h", (uint32_t)((uint64_t)dot >> 32));
    result("arm_dot_prod_q31 l", (uint32_t)dot);
    q15_t mean, max;
    uint32_t index;
    arm_mean_q15(x15, N, &mean);
    result("arm_mean_q15      ", (uint16_t)mean);
    q31_t var;
    arm_var_q31(x31, N, &var);
    result("arm_var_q31       ", (uint32_t)var);
    arm_max_q15(x15, N, &max, &index);
    result("arm_max_q15       ", (uint32_t)(uint16_t)max << 16 | index);

    /* A 16-tap low-pass FIR (a triangle, sum 1.0 in Q15) */
    for (int i = 0; i < TAPS; i++)
        coeff15[i] = (q15_t)((i < TAPS / 2 ? i + 1 : TAPS - i) * 32767 / 72);
    arm_fir_instance_q15 fir;
    arm_status st = arm_fir_init_q15(&fir, TAPS, coeff15, state15, N);
    result("arm_fir_init_q15  ", (uint32_t)(int32_t)st);
    arm_fir_q15(&fir, x15, out15, N);
    result("arm_fir_q15       ", hash(out15, sizeof out15));

    /* Two biquad stages: b0 b1 b2 a1 a2, in Q30 (postShift 1) */
    static const q31_t biquad[5 * STAGES] = {
        0x10000000, 0x20000000, 0x10000000, 0x40000000, -0x14000000,
        0x08000000, 0x10000000, 0x08000000, 0x30000000, -0x0c000000,
    };
    arm_biquad_casd_df1_inst_q31 iir;
    arm_biquad_cascade_df1_init_q31(&iir, STAGES, biquad, state31, 1);
    arm_biquad_cascade_df1_q31(&iir, x31, out31, N);
    result("arm_biquad_q31    ", hash(out31, sizeof out31));

    /* 3x3 matrices in single precision */
    float32_t a[9], b[9], c[9];
    for (int i = 0; i < 9; i++) {
        a[i] = (float32_t)(i + 1) * 0.5f;
        b[i] = (float32_t)(9 - i) / 3.0f;
    }
    arm_matrix_instance_f32 ma, mb, mc;
    arm_mat_init_f32(&ma, 3, 3, a);
    arm_mat_init_f32(&mb, 3, 3, b);
    arm_mat_init_f32(&mc, 3, 3, c);
    st = arm_mat_mult_f32(&ma, &mb, &mc);
    result("arm_mat_mult_f32  ", (uint32_t)(int32_t)st);
    result("  product         ", hash(c, sizeof c));
    arm_mat_init_f32(&mc, 2, 2, c);              /* wrong size: ARM_MATH_SIZE_MISMATCH, -3 */
    result("  size mismatch   ", (uint32_t)(int32_t)arm_mat_mult_f32(&ma, &mb, &mc));

    result("arm_sin_f32(0.5)  ", bits(arm_sin_f32(0.5f)));
    result("arm_sin_f32(-2)   ", bits(arm_sin_f32(-2.0f)));
    q31_t root;
    st = arm_sqrt_q31(0x20000000, &root);        /* sqrt(0.25) = 0.5 */
    result("arm_sqrt_q31      ", (uint32_t)root);
    result("  status          ", (uint32_t)(int32_t)st);
    result("  negative        ", (uint32_t)(int32_t)arm_sqrt_q31(-5, &root));   /* ARM_MATH_ARGUMENT_ERROR, -1 */
    arm_cmplx_mag_q15(x15, out15, N / 2);
    result("arm_cmplx_mag_q15 ", hash(out15, N));
    arm_q15_to_float(x15, outf, N);
    result("arm_q15_to_float  ", hash(outf, sizeof outf));

    result("checksum          ", sum);
    LEDS = sum;
    return (int)sum;
}
