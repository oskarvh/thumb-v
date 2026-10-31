/* Interface for the ABI test: signatures that AAPCS and RISC-V ilp32 pass
 * differently, in both directions, plus a few that they pass the same way. */
#include <stdint.h>
#include "thumbv_interface.h"

struct pair { int32_t a, b; };                 /* 8 bytes: returned in a0:a1, but via memory on ARM */
struct p64 { int64_t v; };                     /* 8-byte aligned: even register pair on ARM */
struct big { int32_t w[4]; };                  /* 16 bytes: by reference on RISC-V */
struct six { uint8_t c[6]; };                  /* 6 bytes, not a multiple of 4 */
struct small { int8_t a; int16_t b; };         /* 4 bytes: the same in both */
struct odd { uint8_t c[10]; };                 /* 10 bytes by value: by reference, partial last word */

/* Thumb implements these; RISC-V calls them. */
THUMBV_THUMB int t_args6(int a, int b, int c, int d, int e, int f);
THUMBV_THUMB int64_t t_mixed(int a, int64_t b, int c);
THUMBV_THUMB int64_t t_wide4(int64_t a, int64_t b, int64_t c, int64_t d);
THUMBV_THUMB struct pair t_make_pair(int a, int b);
THUMBV_THUMB struct big t_make_big(int seed);
THUMBV_THUMB int t_sum_big(struct big b);
THUMBV_THUMB int t_sum_p64(int x, struct p64 p);
THUMBV_THUMB struct six t_make_six(int seed);
THUMBV_THUMB struct small t_small(int8_t a, int16_t b);
THUMBV_THUMB int t_sum_odd(int x, struct odd o, int y);
THUMBV_THUMB int t_tail(int a, int b, int c, int d, int e, int f, int g, int64_t h);
THUMBV_THUMB int t_tail_pair(int a, int b, int c, int d, int e, int f, int g, struct pair p);
THUMBV_THUMB double t_poly(double x, double a, double b, double c);
THUMBV_THUMB uint32_t t_call_imports(void);

/* RISC-V implements these; Thumb calls them by name. */
THUMBV_RISCV int rv_args6(int a, int b, int c, int d, int e, int f);
THUMBV_RISCV int64_t rv_mixed(int a, int64_t b, int c);
THUMBV_RISCV struct pair rv_make_pair(int a, int b);
THUMBV_RISCV int rv_sum_big(struct big b);
THUMBV_RISCV struct six rv_make_six(int seed);
THUMBV_RISCV int rv_add(int a, int b);
THUMBV_RISCV void rv_record(uint32_t v);
