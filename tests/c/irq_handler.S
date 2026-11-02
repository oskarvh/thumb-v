# The interrupt handler for irq_main.c and irq_loops_main.c (Phases 3.4,
# 4.4). The testbench's interrupt comes through the controller as interrupt
# 0 (Phase 5.2): claim it, acknowledge the testbench (a store to
# 0x1000_000C, see sim/tb.sv), count it, complete it and return. Acknowledge
# before completing: the line is level-sensitive, so still high at the
# complete it would pend again. The test reads mepc from the trace record of
# `irq_mepc`.
    .option arch, +zicsr
    .text
    .balign 4                 # mtvec needs a 4-byte aligned base
    .globl irq_handler
irq_handler:
    addi  sp, sp, -16
    sw    t0, 0(sp)
    sw    t1, 4(sp)
    .globl irq_mepc
irq_mepc:
    csrr  t0, mepc
    li    t0, 0x10001000
    lw    t1, 0(t0)           # CLAIM: interrupt 0 is exception 16
    li    t0, 0x10000000
    sw    zero, 12(t0)        # acknowledge: the testbench drops the line
    la    t0, irq_count
    lw    t1, 0(t0)
    addi  t1, t1, 1
    sw    t1, 0(t0)
    li    t0, 0x10001000
    sw    zero, 4(t0)         # COMPLETE
    lw    t0, 0(sp)
    lw    t1, 4(sp)
    addi  sp, sp, 16
    .globl irq_mret
irq_mret:
    mret
