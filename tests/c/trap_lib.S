@ Phase 5.1: Thumb instructions that trap, for trap_main.c. Each function
@ runs one; the RISC-V handler (trap_handler.S, trap_main.c) records the
@ trap and resumes after the instruction, so a skipped load leaves its
@ destination as it was.

    .syntax unified
    .cpu cortex-m0
    .thumb
    .text

.macro func name
    .globl \name
    .type \name, %function
    .thumb_func
\name:
.endm

func t_svc                    @ SVC #42: ecall
    svc   #42
    bx    lr

func t_bkpt                   @ BKPT #7: ebreak
    bkpt  #7
    bx    lr

func t_udf                    @ UDF #3: the illegal instruction
    udf   #3
    bx    lr

func t_mrs_msp                @ MRS r0, MSP: 32 bits, traps for the handler (Q7)
    movs  r0, #0
    mrs   r0, msp
    bx    lr

func t_load                   @ int t_load(int *p): LDR r0, [r0], one op
    ldr   r0, [r0]
    bx    lr

func t_load_reg               @ int t_load_reg(char *p, int off): LDR r0, [r0, r1]: traps at op 1
    ldr   r0, [r0, r1]
    bx    lr

func t_store                  @ void t_store(int *p, int v): STR r1, [r0]
    str   r1, [r0]
    bx    lr
