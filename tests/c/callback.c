/* Phase 3.5: gcc-compiled Thumb code the hardware runs since Phase 3: calls
 * into RISC-V (PUSH/POP of LR and PC around a BL through the import table),
 * a table read through a literal pool, a string passed to RISC-V.
 *
 * Still no conditional branches, so no loops or ifs: no flags until Phase 4.
 * tests/test_rtl.py checks that every instruction gcc emitted can run.
 */
#include "callback.h"

static const unsigned char digits[16] = {3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5, 8, 9, 7, 9, 3};

int t_lookup(int i)
{
    return digits[i & 15];
}

int t_callback(int x)
{
    return rv_square(x + 1) + x;
}

int t_report(int x)
{
    int v = t_lookup(x) * 1000 + t_callback(x);
    rv_print("Thumb reports      = ", v);
    return v;
}
