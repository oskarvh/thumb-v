# Startup for RV32 test programs: set SP, mark the Thumb window of mixed
# programs as Thumb region 0 (CSRs 0x7C0-0x7C1, see tests/link/rv32.ld), call
# main, spin at `done` with main's return value in a0.
    .option arch, +zicsr, +zifencei

# The reset vector (0x2_0000, tests/link/rv32.ld): the import table for Thumb
# code follows it, so start somewhere else.
    .section .text.reset, "ax"
    .global _reset
_reset:
    j _start

    .section .text.start, "ax"
    .global _start
_start:
    la sp, __stack_top
    la t0, __thumb_region_base
    csrw 0x7c0, t0
    la t0, __thumb_region_limit
    csrw 0x7c1, t0
    fence.i
    call main
    .global done
done:
    j done
