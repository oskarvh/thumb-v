/* Thumb-only test programs and benchmarks. */
ENTRY(_start)

MEMORY
{
    ROM (rx)  : ORIGIN = 0x00010000, LENGTH = 64K
    RAM (rwx) : ORIGIN = 0x20000000, LENGTH = 48K
}

__stack_top = 0x20010000;

SECTIONS
{
    .text : { KEEP(*(.text.start)) *(.text .text.*) *(.rodata .rodata.*) } > ROM
    .data : { *(.data .data.*) } > RAM
    .bss  : { *(.bss .bss.* COMMON) } > RAM
    PROVIDE(end = .);    /* heap start, for newlib's _sbrk */
}
