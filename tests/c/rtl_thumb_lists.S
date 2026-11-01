@ Phase 3.2: a Thumb function using register lists: PUSH/POP (with LR and
@ PC), LDM/STM with write-back, and LDM with the base register in the list.
@
@ int thumb_lists(int a, int b): a mix of everything, as a checksum.

    .syntax unified
    .cpu cortex-m0
    .thumb
    .text
    .globl thumb_lists
    .type thumb_lists, %function
thumb_lists:
    push  {r4-r7, lr}         @ PUSH with LR: 6 ops
    movs  r4, #11
    movs  r5, #22
    adds  r6, r0, r1
    subs  r7, r0, r1
    sub   sp, #32
    mov   r2, sp
    stmia r2!, {r4-r7}        @ STM with write-back: 5 ops
    subs  r2, #16
    ldmia r2!, {r0, r1, r3}   @ LDM with write-back: 4 ops
    adds  r0, r0, r1
    adds  r0, r0, r3
    mov   r3, sp
    str   r3, [sp, #16]
    add   r3, sp, #12
    ldmia r3, {r1, r3}        @ LDM with the base in the list: loaded last
    adds  r0, r0, r1
    mov   r1, sp
    subs  r3, r3, r1          @ r3 = the pointer stored above: sp, so r3 - sp = 0
    adds  r0, r0, r3
    bl    helper              @ a nested call with its own PUSH/POP
    add   sp, #32
    adds  r0, r0, r4          @ r4-r7 are callee-saved: the helper restored them
    adds  r0, r0, r7
    pop   {r4-r7, pc}         @ POP with PC: 7 ops, the jump last

    .type helper, %function
helper:
    push  {r4, r7, lr}
    movs  r4, #0
    movs  r7, #0
    lsls  r0, r0, #1
    pop   {r4, r7}            @ POP without PC
    pop   {r1}
    bx    r1
