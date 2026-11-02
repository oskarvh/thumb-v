/* Phase 5.3: the firmware's default trap reports. BKPT from Thumb and
 * ebreak from RISC-V are reported and resumed; then a load from an
 * unmapped address in Thumb code is reported and stops the program. Uses
 * trap_lib.S's Thumb functions. */
#include "thumbv.h"

void t_bkpt(void);
int t_load(int *p);

int main(void)
{
    thumbv_init();
    t_bkpt();
    __asm__ volatile("ebreak");
    t_load((int *)0x30000000);
    return 1;                       /* not reached */
}
