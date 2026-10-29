# Toolchain smoke test: a2 = 5 + 7, then spin at `done`.
    .global _start
_start:
    li a0, 5
    li a1, 7
    add a2, a0, a1
    .global done
done:
    j done
