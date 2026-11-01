/* Thumb libraries for mixed programs. RAM leaves room for the RV32 side's data.
   ROM is the Thumb window that the RV32 startup code marks as a Thumb region
   (tests/link/rv32.ld). It starts at 0x1_4000, not 0x1_0000, so that on the
   board, whose 32 KiB code RAM repeats through the code region, it lands in
   the RAM's upper half and the RV32 side (0x2_0000) in its lower half. */
ENTRY(_start)

MEMORY
{
    ROM (rx)  : ORIGIN = 0x00014000, LENGTH = 48K
    RAM (rwx) : ORIGIN = 0x20000000, LENGTH = 16K
}

__stack_top = 0x20010000;

SECTIONS
{
    .text : { KEEP(*(.text.start)) *(.text .text.*) *(.rodata .rodata.*) } > ROM
    .data : { *(.data .data.*) } > RAM
    .bss  : { *(.bss .bss.* COMMON) } > RAM
}
