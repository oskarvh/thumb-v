@ Startup for Thumb-only test programs: set SP, call main, spin at `done` with
@ main's return value in r0.
    .syntax unified
    .thumb
    .section .text.start, "ax"
    .global _start
    .thumb_func
_start:
    ldr r0, =__stack_top
    mov sp, r0
    bl main
    .global done
done:
    b done
    .ltorg
