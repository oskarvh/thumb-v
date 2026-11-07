/* Phase 5.4: the interface to CMSIS-DSP, a Cortex-M0 library linked as a
 * binary (build.cmsis_dsp_library), for thumbv/interwork.py: the library's
 * own prototypes from its headers (Include/dsp/*.h), restated in the
 * interface syntax. RISC-V code includes arm_math.h itself; this file is
 * only read by the interworking generator.
 *
 * The typedefs are the library's, by their sizes on the Thumb side. arm_status
 * is an enum, and arm-none-eabi uses short enums (Tag_ABI_enum_size: small):
 * one byte, where RISC-V's is four. As a return value that is the same in
 * both ABIs (AAPCS extends results to a word), but in a struct it wouldn't
 * be. */
#include "thumbv_interface.h"

typedef int16_t q15_t;
typedef int32_t q31_t;
typedef int64_t q63_t;
typedef float float32_t;
typedef int8_t arm_status;

/* Basic maths and statistics */
THUMBV_THUMB void arm_add_q15(const q15_t *pSrcA, const q15_t *pSrcB, q15_t *pDst, uint32_t blockSize);
THUMBV_THUMB void arm_scale_q31(const q31_t *pSrc, q31_t scaleFract, int8_t shift, q31_t *pDst, uint32_t blockSize);
THUMBV_THUMB void arm_dot_prod_q31(const q31_t *pSrcA, const q31_t *pSrcB, uint32_t blockSize, q63_t *result);
THUMBV_THUMB void arm_mean_q15(const q15_t *pSrc, uint32_t blockSize, q15_t *pResult);
THUMBV_THUMB void arm_var_q31(const q31_t *pSrc, uint32_t blockSize, q31_t *pResult);
THUMBV_THUMB void arm_max_q15(const q15_t *pSrc, uint32_t blockSize, q15_t *pResult, uint32_t *pIndex);

/* Filters: instance structs passed by pointer */
THUMBV_THUMB arm_status arm_fir_init_q15(arm_fir_instance_q15 *S, uint16_t numTaps, const q15_t *pCoeffs,
                                         q15_t *pState, uint32_t blockSize);
THUMBV_THUMB void arm_fir_q15(const arm_fir_instance_q15 *S, const q15_t *pSrc, q15_t *pDst, uint32_t blockSize);
THUMBV_THUMB void arm_biquad_cascade_df1_init_q31(arm_biquad_casd_df1_inst_q31 *S, uint8_t numStages,
                                                  const q31_t *pCoeffs, q31_t *pState, int8_t postShift);
THUMBV_THUMB void arm_biquad_cascade_df1_q31(const arm_biquad_casd_df1_inst_q31 *S, const q31_t *pSrc,
                                             q31_t *pDst, uint32_t blockSize);

/* Matrices and fast maths: single precision in software on both sides */
THUMBV_THUMB void arm_mat_init_f32(arm_matrix_instance_f32 *S, uint16_t nRows, uint16_t nColumns, float32_t *pData);
THUMBV_THUMB arm_status arm_mat_mult_f32(const arm_matrix_instance_f32 *pSrcA, const arm_matrix_instance_f32 *pSrcB,
                                         arm_matrix_instance_f32 *pDst);
THUMBV_THUMB float32_t arm_sin_f32(float32_t x);
THUMBV_THUMB arm_status arm_sqrt_q31(q31_t in, q31_t *pOut);
THUMBV_THUMB void arm_cmplx_mag_q15(const q15_t *pSrc, q15_t *pDst, uint32_t numSamples);
THUMBV_THUMB void arm_q15_to_float(const q15_t *pSrc, float32_t *pDst, uint32_t blockSize);
