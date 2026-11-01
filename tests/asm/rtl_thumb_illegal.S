# Phase 2.1: a Thumb instruction the 2.1 stub doesn't expand traps as an
# illegal instruction at its own address. Returns a0 = mepc if mcause is 2
# (illegal instruction), else 0.
    .option arch, +zicsr, +zifencei
    .section .text.start, "ax"
    .globl _start
_start:
    la    sp, __stack_top
    la    t0, handler
    csrw  mtvec, t0
    la    t0, thumb_start
    csrw  0x7c0, t0
    la    t0, thumb_end
    csrw  0x7c1, t0
    fence.i
    call  thumb_start
    li    a0, 0               # not reached
    j     done

handler:
    csrr  a0, mepc
    csrr  t0, mcause
    li    t1, 2
    beq   t0, t1, done
    li    a0, 0
    .globl done
done:
    j     done

    .balign 4
thumb_start:
    .2byte 0xbf00             # nop
    .globl thumb_movs
thumb_movs:
    .2byte 0x2001             # movs r0, #1: not in the stub, traps
    .2byte 0x4770             # bx lr
    .2byte 0xbf00
thumb_end:
