# Startup for RV32 test programs: set SP, call main, spin at `done` with
# main's return value in a0.
    .section .text.start, "ax"
    .global _start
_start:
    la sp, __stack_top
    call main
    .global done
done:
    j done
