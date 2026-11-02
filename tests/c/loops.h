/* Phase 4.4: gcc-compiled Thumb functions with loops and conditions
 * (loops.c), called from RISC-V. Every signature passes arguments the same
 * way under AAPCS and ilp32, so no thunks are needed. */
#ifndef LOOPS_H
#define LOOPS_H

#include <stdint.h>

uint32_t t_crc32(const uint8_t *p, int n);
void t_sort(int32_t *a, int n);
int t_search(const int32_t *a, int n, int32_t key);
uint32_t t_gcd(uint32_t a, uint32_t b);
int t_popcount(uint32_t x);
uint64_t t_fib64(int n);
int64_t t_dot64(const int32_t *a, const int32_t *b, int n);
int t_classify(int32_t x);
int t_strcmp(const char *a, const char *b);
int t_isqrt(uint32_t x);

#endif
