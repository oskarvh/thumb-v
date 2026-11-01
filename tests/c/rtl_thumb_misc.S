@ Phase 3.3: shifts by a register (amounts 0, 1, 31, 32, 33 and 256, whose
@ low byte is 0), RORS, REV/REV16/REVSH, and PRIMASK through MSR/MRS and
@ CPSID/CPSIE.
@
@ int thumb_misc(int a, int b): a mix of everything, as a checksum.

    .syntax unified
    .cpu cortex-m0
    .thumb

@ All four shifts of r4 by r1, folded into the checksum in r6.
.macro shifts
    movs  r2, r4
    lsls  r2, r1              @ LSLS rdn, rm
    adds  r6, r6, r2
    movs  r2, r4
    lsrs  r2, r1              @ LSRS rdn, rm
    adds  r6, r6, r2
    movs  r2, r4
    asrs  r2, r1              @ ASRS rdn, rm
    adds  r6, r6, r2
    movs  r2, r4
    rors  r2, r1              @ RORS rdn, rm
    eors  r6, r2
    lsls  r6, r6, #1
.endm

    .text
    .globl thumb_misc
    .type thumb_misc, %function
thumb_misc:
    push  {r4-r6, lr}
    movs  r4, r0              @ the value to shift
    movs  r6, r1              @ the checksum
    movs  r1, #0
    shifts
    movs  r1, #1
    shifts
    movs  r1, #31
    shifts
    movs  r1, #32
    shifts
    movs  r1, #33
    shifts
    movs  r1, #1
    lsls  r1, r1, #8          @ 256: the amount is its low byte, 0
    shifts
    rev   r2, r4              @ REV
    adds  r6, r6, r2
    rev16 r2, r4              @ REV16
    adds  r6, r6, r2
    revsh r2, r4              @ REVSH
    adds  r6, r6, r2
    @ PRIMASK: MSR, MRS, CPSID, CPSIE (no interrupts are raised anyway).
    movs  r1, #1
    msr   primask, r1         @ MSR PRIMASK
    mrs   r2, primask         @ MRS PRIMASK: 1
    adds  r6, r6, r2
    cpsie i
    mrs   r2, primask         @ 0
    lsls  r2, r2, #4
    adds  r6, r6, r2
    cpsid i
    mrs   r2, primask         @ 1
    lsls  r2, r2, #8
    adds  r6, r6, r2
    movs  r1, #0
    msr   primask, r1
    movs  r0, r6
    pop   {r4-r6, pc}
