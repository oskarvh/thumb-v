@ Phase 4.3: the instructions that read the flags: B<cond> under every
@ condition and every NZCV, ADCS/SBCS carry chains, MSR/MRS of the APSR.

    .syntax unified
    .cpu cortex-m0
    .thumb
    .text

@ void thumb_conds(unsigned short *out): for each condition, EQ to LE, a
@ 16-bit mask with bit k set if B<cond> is taken with NZCV = k.
    .globl thumb_conds
    .type thumb_conds, %function
thumb_conds:
    push  {r4-r5, lr}
    .irp cond, eq, ne, cs, cc, mi, pl, vs, vc, hi, ls, ge, lt, gt, le
    movs  r4, #15             @ NZCV, from 15 down to 0
    movs  r5, #0              @ the mask
1:  lsls  r1, r4, #28
    msr   APSR_nzcvq, r1
    b\cond 2f                 @ forward, taken or not
    movs  r2, #0
    b     3f
2:  movs  r2, #1
3:  lsls  r5, r5, #1
    orrs  r5, r2
    subs  r4, #1
    bpl   1b                  @ backward, taken until NZCV = 0 is done
    strh  r5, [r0]
    adds  r0, #2
    .endr
    pop   {r4-r5, pc}

@ unsigned thumb_add128(const unsigned *a, const unsigned *b, unsigned *out):
@ out = a + b over four words, low first; returns the APSR after (MRS).
    .globl thumb_add128
    .type thumb_add128, %function
thumb_add128:
    push  {r4, lr}
    ldr   r3, [r0]
    ldr   r4, [r1]
    adds  r3, r3, r4
    str   r3, [r2]
    .irp off, 4, 8, 12
    ldr   r3, [r0, #\off]
    ldr   r4, [r1, #\off]
    adcs  r3, r4
    str   r3, [r2, #\off]
    .endr
    mrs   r0, APSR
    pop   {r4, pc}

@ unsigned thumb_sub128(const unsigned *a, const unsigned *b, unsigned *out):
@ out = a - b over four words; returns the APSR after.
    .globl thumb_sub128
    .type thumb_sub128, %function
thumb_sub128:
    push  {r4, lr}
    ldr   r3, [r0]
    ldr   r4, [r1]
    subs  r3, r3, r4
    str   r3, [r2]
    .irp off, 4, 8, 12
    ldr   r3, [r0, #\off]
    ldr   r4, [r1, #\off]
    sbcs  r3, r4
    str   r3, [r2, #\off]
    .endr
    mrs   r0, APSR
    pop   {r4, pc}

@ unsigned thumb_apsr(unsigned v): MSR APSR, v, then MRS: v's flags only.
    .globl thumb_apsr
    .type thumb_apsr, %function
thumb_apsr:
    msr   APSR_nzcvq, r0
    mrs   r0, APSR
    bx    lr
