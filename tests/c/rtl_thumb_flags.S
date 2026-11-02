@ Phase 4.2: every instruction that writes the flags, on edge-case operands.
@ No instruction here reads the flags yet (B<cond>, ADCS/SBCS and MRS APSR
@ come in 4.3): the lockstep compares NZCV after every op, from the trace.
@
@ int thumb_flags(void): a checksum of the results.

    .syntax unified
    .cpu cortex-m0
    .thumb

.macro case a, b
    ldr   r0, =\a
    ldr   r1, =\b
    bl    flag_ops
.endm

@ Shift r0 by each amount in turn, by a register, folding results into r7.
.macro by_register op
    .irp amount, 0, 1, 31, 32, 33
    movs  r3, #\amount
    movs  r2, r0
    \op   r2, r3
    adds  r7, r7, r2
    .endr
.endm

    .text
    .globl thumb_flags
    .type thumb_flags, %function
thumb_flags:
    push  {r4-r7, lr}
    movs  r7, #0
    case  0, 0
    case  1, 1
    case  0x7fffffff, 1
    case  0x80000000, 1
    case  0xffffffff, 1
    case  0x80000000, 0x80000000
    case  5, 7
    case  0x12345678, 0x9abcdef0
    case  0xfffffffe, 0xffffffff
    movs  r0, r7
    pop   {r4-r7, pc}
    .ltorg

@ The flag writers on r0 and r1; results go into r7.
    .type flag_ops, %function
flag_ops:
    push  {lr}
    adds  r2, r0, r1          @ ADDS rd, rn, rm
    adds  r7, r7, r2
    subs  r2, r0, r1          @ SUBS rd, rn, rm
    adds  r7, r7, r2
    adds  r2, r0, #0          @ ADDS rd, rn, #imm3
    adds  r2, r0, #7
    subs  r2, r0, #0          @ SUBS rd, rn, #imm3: C = 1 for #0
    subs  r2, r0, #1
    adds  r7, r7, r2
    movs  r2, r0
    adds  r2, #255            @ ADDS rdn, #imm8
    subs  r2, #255            @ SUBS rdn, #imm8
    subs  r2, #0
    cmp   r0, #0              @ CMP rn, #imm8
    cmp   r0, #1
    cmp   r0, #255
    cmp   r0, r1              @ CMP rn, rm
    cmp   r1, r0
    cmn   r0, r1              @ CMN
    rsbs  r2, r0, #0          @ RSBS rd, rn, #0
    adds  r7, r7, r2
    tst   r0, r1              @ TST
    movs  r2, r0
    ands  r2, r1              @ ANDS
    movs  r2, r0
    eors  r2, r1              @ EORS
    adds  r7, r7, r2
    movs  r2, r0
    orrs  r2, r1              @ ORRS
    movs  r2, r0
    bics  r2, r1              @ BICS
    adds  r7, r7, r2
    mvns  r2, r0              @ MVNS
    movs  r2, #0              @ MOVS rd, #imm8
    movs  r2, #128
    movs  r2, r0              @ MOVS rd, rm (LSLS #0: C unchanged)
    muls  r2, r1              @ MULS
    adds  r7, r7, r2
    lsls  r2, r0, #1          @ shifts by an immediate
    lsls  r2, r0, #31
    lsrs  r2, r0, #1
    lsrs  r2, r0, #31
    lsrs  r2, r0, #32
    asrs  r2, r0, #1
    asrs  r2, r0, #31
    asrs  r2, r0, #32
    adds  r7, r7, r2
    by_register lsls          @ shifts by a register
    by_register lsrs
    by_register asrs
    by_register rors
    mov   r8, r0              @ CMP with a high register
    cmp   r8, r1
    cmp   r1, r8
    pop   {pc}
