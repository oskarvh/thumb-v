# Phase 2.1: switching to Thumb by address, in the RTL and the model.
#
# The Thumb code is written as raw halfwords, using only what the 2.1 stub
# expander handles (NOP, DMB/DSB/ISB, BX LR). It covers 16- and 32-bit
# instructions at both alignments, a 32-bit instruction straddling two words,
# and a call into the region at a pc[1] = 1 address. Returns a0 = 2.
    .option arch, +zicsr, +zifencei
    .section .text.start, "ax"
    .globl _start
_start:
    la    sp, __stack_top
    la    t0, thumb_start
    csrw  0x7c0, t0           # region 0: [thumb_start, thumb_end)
    la    t0, thumb_end
    csrw  0x7c1, t0
    fence.i                   # refetch with the new regions
    li    s0, 0
    call  thumb_func          # word-aligned entry
    addi  s0, s0, 1
    call  thumb_func_odd      # halfword entry
    addi  s0, s0, 1
    mv    a0, s0
    .globl done
done:
    j     done

    .balign 4
thumb_start:
thumb_func:
    .2byte 0xbf00             #  +0  nop
    .2byte 0xf3bf, 0x8f5f     #  +2  dmb sy    (straddles two words)
    .2byte 0xbf00             #  +6  nop
    .2byte 0xf3bf, 0x8f4f     #  +8  dsb sy
    .2byte 0xf3bf, 0x8f6f     # +12  isb sy
    .2byte 0xbf00             # +16  nop
thumb_func_odd:
    .2byte 0xbf00             # +18  nop
    .2byte 0x4770             # +20  bx lr
    .2byte 0xbf00             # +22  (padding)
thumb_end:
