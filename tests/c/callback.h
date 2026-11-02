/* Phase 3.5: the interface between callback.c (Thumb) and callback_main.c
 * (RISC-V): calls in both directions. All signatures are ones the two ABIs
 * pass the same way, so the calls are direct, with no thunks. */
#include "thumbv_interface.h"

/* Thumb implements these; RISC-V calls them. */
THUMBV_THUMB int t_lookup(int i);
THUMBV_THUMB int t_callback(int x);
THUMBV_THUMB int t_report(int x);

/* RISC-V implements these; Thumb calls them by name. */
THUMBV_RISCV int rv_square(int x);
THUMBV_RISCV void rv_print(const char *what, unsigned value);
