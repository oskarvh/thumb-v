/* Tags for interface headers (see thumbv/interwork.py): which side implements
 * a function. They expand to nothing, so the header is ordinary C for both
 * compilers. */
#ifndef THUMBV_INTERFACE_H
#define THUMBV_INTERFACE_H
#define THUMBV_THUMB  /* implemented in Thumb, callable from RISC-V */
#define THUMBV_RISCV  /* implemented in RISC-V, callable from Thumb */
#endif
