/* Thumb libraries for mixed programs. RAM leaves room for the RV32 side's data. */
ENTRY(_start)

MEMORY
{
    ROM (rx)  : ORIGIN = 0x00010000, LENGTH = 64K
    RAM (rwx) : ORIGIN = 0x20000000, LENGTH = 16K
}

__stack_top = 0x20010000;

SECTIONS
{
    .text : { KEEP(*(.text.start)) *(.text .text.*) *(.rodata .rodata.*) } > ROM
    .data : { *(.data .data.*) } > RAM
    .bss  : { *(.bss .bss.* COMMON) } > RAM
}
