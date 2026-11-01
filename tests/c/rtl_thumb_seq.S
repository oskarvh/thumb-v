@ Phase 3.1: a Thumb function using the two- to five-op instructions the
@ sequencer runs (still no PUSH/POP: the return address waits in r12).
@
@ int thumb_seq(int a, int b): a mix of everything, as a checksum.

    .syntax unified
    .cpu cortex-m0
    .thumb
    .text
    .globl thumb_seq
    .type thumb_seq, %function
thumb_seq:
    mov   r12, lr
    sub   sp, #16
    ldr   r2, =0x12345678     @ LDR (literal), at one alignment...
    ldr   r3, =0x0badf00d     @ ...and the other
    eors  r0, r2
    adds  r0, r0, r3
    adr   r3, table           @ ADR
    ldr   r3, [r3, #4]
    adds  r0, r0, r3
    @ Loads and stores with a register offset, into the stack frame.
    mov   r1, sp
    movs  r2, #4
    str   r0, [r1, r2]        @ STR
    movs  r3, #8
    strh  r0, [r1, r3]        @ STRH
    movs  r3, #10
    strb  r0, [r1, r3]        @ STRB
    ldr   r3, [r1, r2]        @ LDR
    adds  r0, r0, r3
    movs  r2, #8
    ldrh  r3, [r1, r2]        @ LDRH
    adds  r0, r0, r3
    ldrsh r3, [r1, r2]        @ LDRSH
    adds  r0, r0, r3
    movs  r2, #10
    ldrb  r3, [r1, r2]        @ LDRB
    adds  r0, r0, r3
    ldrsb r3, [r1, r2]        @ LDRSB
    adds  r0, r0, r3
    @ BICS and the extends.
    bics  r0, r1
    sxth  r2, r0              @ SXTH
    sxtb  r3, r0              @ SXTB
    adds  r2, r2, r3
    uxth  r3, r0              @ UXTH
    adds  r0, r2, r3
    @ The PC as an operand: it reads as this instruction's address + 4.
    mov   r2, pc              @ MOV rd, pc
    add   r3, pc              @ ADD rdn, pc
    subs  r3, r3, r2
    adds  r0, r0, r3
    @ ADD pc, rm: jump to this instruction + 4 + r1, over three halfwords.
    movs  r1, #4
    add   pc, r1
    movs  r0, #0              @ skipped
    movs  r0, #1              @ skipped
    movs  r0, #2              @ skipped
    add   sp, #16
    bx    r12
    .ltorg

    .align 2
table:
    .word 0x11111111, 0x00c0ffee
