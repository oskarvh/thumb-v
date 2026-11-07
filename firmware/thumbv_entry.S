# Thumb-V's shared trap entry routine (Phase 5.3, plan section 6): mtvec for
# every interrupt and trap, from either instruction set.
#
# Frame (80 bytes): ra, t0-t2, a0-a7, t3-t6 (0-60), mepc (64), mstatus (68),
# NZCV (72, CSR 0x7C4: a Thumb handler can change the flags), the claimed
# exception (76). Callee-saved registers are the handlers' to save: with the
# D2 register mapping, that is so for Thumb handlers as well.
#
# Interrupts (mcause bit 31): claim the exception from the controller,
# enable interrupts so that higher priorities preempt, call
# thumbv_dispatch(exception), disable them, complete it, return.
# Synchronous traps: thumbv_trap(mcause, frame) returns where to resume.
    .option arch, +zicsr

    .equ CLAIM, 0x10001000          # COMPLETE at + 4
    .equ NZCV, 0x7c4

    .text
    .balign 4
    .globl thumbv_trap_entry
thumbv_trap_entry:
    addi  sp, sp, -80
    sw    ra, 0(sp)
    sw    t0, 4(sp)
    sw    t1, 8(sp)
    sw    t2, 12(sp)
    sw    a0, 16(sp)
    sw    a1, 20(sp)
    sw    a2, 24(sp)
    sw    a3, 28(sp)
    sw    a4, 32(sp)
    sw    a5, 36(sp)
    sw    a6, 40(sp)
    sw    a7, 44(sp)
    sw    t3, 48(sp)
    sw    t4, 52(sp)
    sw    t5, 56(sp)
    sw    t6, 60(sp)
    csrr  t0, mepc
    sw    t0, 64(sp)
    csrr  t0, mstatus
    sw    t0, 68(sp)
    csrr  t0, NZCV
    sw    t0, 72(sp)
    csrr  a0, mcause
    bltz  a0, .Linterrupt

    mv    a1, sp                    # synchronous: thumbv_trap(mcause, frame)
    call  thumbv_trap
    sw    a0, 64(sp)                # where to resume
    j     .Lreturn

.Linterrupt:
    li    t0, CLAIM
    lw    a0, 0(t0)
    sw    a0, 76(sp)
    beqz  a0, .Lreturn              # nothing to claim (any more)
    csrsi mstatus, 8                # MIE: higher priorities preempt the handler
    call  thumbv_dispatch
    csrci mstatus, 8
    lw    a0, 76(sp)
    li    t0, CLAIM
    sw    a0, 4(t0)                 # COMPLETE

.Lreturn:
    lw    t0, 64(sp)
    csrw  mepc, t0
    lw    t0, 68(sp)
    csrw  mstatus, t0
    lw    t0, 72(sp)
    csrw  NZCV, t0
    lw    ra, 0(sp)
    lw    t0, 4(sp)
    lw    t1, 8(sp)
    lw    t2, 12(sp)
    lw    a0, 16(sp)
    lw    a1, 20(sp)
    lw    a2, 24(sp)
    lw    a3, 28(sp)
    lw    a4, 32(sp)
    lw    a5, 36(sp)
    lw    a6, 40(sp)
    lw    a7, 44(sp)
    lw    t3, 48(sp)
    lw    t4, 52(sp)
    lw    t5, 56(sp)
    lw    t6, 60(sp)
    addi  sp, sp, 80
    mret
