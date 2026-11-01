@ Phase 2.2: a Thumb function using only instructions the RTL expander turns
@ into a single op (results only: no flags until Phase 4). No PUSH/POP (still
@ several ops), so the return address waits in r12.
@
@ int thumb_ops(int a, int b): a mix of everything, as a checksum.

    .syntax unified
    .cpu cortex-m0
    .thumb
    .text
    .globl thumb_ops
    .type thumb_ops, %function
thumb_ops:
    mov   r12, lr             @ MOV (high registers)
    sub   sp, #16             @ SUB sp, #imm
    str   r0, [sp, #0]        @ STR [sp, #imm]
    str   r1, [sp, #4]
    movs  r2, #200            @ MOVS #imm8
    adds  r2, r2, r0          @ ADDS (register)
    subs  r2, #3              @ SUBS #imm8
    adds  r2, #7              @ ADDS #imm8
    adds  r3, r2, #5          @ ADDS #imm3
    subs  r3, r3, #2          @ SUBS #imm3
    subs  r3, r3, r1          @ SUBS (register)
    lsls  r3, r3, #4          @ LSLS #imm
    lsrs  r3, r3, #1          @ LSRS #imm
    asrs  r3, r3, #2          @ ASRS #imm
    eors  r3, r1              @ EORS
    ands  r3, r2              @ ANDS
    orrs  r3, r0              @ ORRS
    muls  r3, r1              @ MULS
    mvns  r2, r3              @ MVNS
    rsbs  r2, r2, #0          @ RSBS (NEGS)
    cmp   r2, r3              @ CMP: a nop without flags
    movs  r0, r2              @ MOVS (register)
    add   r1, sp, #8          @ ADD rd, sp, #imm
    str   r0, [r1, #0]        @ STR, STRH, STRB [rn, #imm]
    strh  r3, [r1, #4]
    strb  r2, [r1, #6]
    ldr   r0, [r1, #0]        @ LDR, LDRH, LDRB [rn, #imm]
    ldrh  r2, [r1, #4]
    ldrb  r3, [r1, #6]
    adds  r0, r0, r2
    adds  r0, r0, r3
    ldr   r1, [sp, #4]        @ LDR [sp, #imm]
    uxtb  r2, r1              @ UXTB
    add   r0, r2              @ ADD (high-register form, low registers)
    bl    helper              @ BL, returns with BX LR
    b     1f                  @ B
    movs  r0, #0              @ skipped
1:  add   sp, #16             @ ADD sp, #imm
    bx    r12                 @ BX (high register)

    .type helper, %function
helper:
    lsls  r1, r1, #3
    adds  r0, r0, r1
    bx    lr
