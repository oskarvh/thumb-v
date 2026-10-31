/* RV32 test programs. RAM starts above the Thumb side's, and the stack is shared. */
ENTRY(_start)

MEMORY
{
    ROM (rx)  : ORIGIN = 0x00020000, LENGTH = 64K
    RAM (rwx) : ORIGIN = 0x20004000, LENGTH = 16K
}

__stack_top = 0x20010000;

SECTIONS
{
    .text : { KEEP(*(.text.start)) *(.text .text.*) *(.rodata .rodata.* .srodata .srodata.*) } > ROM
    .data : { *(.data .data.* .sdata .sdata.*) } > RAM
    .bss  : { *(.bss .bss.* .sbss .sbss.* COMMON) } > RAM
}
