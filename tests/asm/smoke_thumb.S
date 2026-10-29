@ Toolchain smoke test: r2 = 5 + 7, then spin at `done`.
    .syntax unified
    .thumb
    .global _start
    .thumb_func
_start:
    movs r0, #5
    movs r1, #7
    adds r2, r0, r1
    .global done
done:
    b done
