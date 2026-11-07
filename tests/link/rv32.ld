/* RV32 test programs. RAM starts above the Thumb side's, and the stack is shared. */
ENTRY(_reset)   /* the core's reset vector, crt_rv32.S */

MEMORY
{
    ROM (rx)  : ORIGIN = 0x00020000, LENGTH = 64K
    /* Above the Thumb library's 8 KiB, so that on the board's 16 KiB data RAM
       the two sides' data don't share bytes (docs/board.md). */
    RAM (rwx) : ORIGIN = 0x20002000, LENGTH = 24K
}

__stack_top = 0x20010000;

/* The Thumb window of mixed programs (tests/link/thumb_lib.ld): the startup
   code marks it as Thumb region 0. */
__thumb_region_base = 0x00014000;
__thumb_region_limit = 0x00020000;

SECTIONS
{
    /* The core starts at 0x2_0000 (its reset vector): a jump to _start
       (crt_rv32.S). Then the import jump table for Thumb code, at a fixed
       address (thumbv.build.IMPORT_BASE), so the Thumb side can be linked
       first. */
    .reset : { KEEP(*(.text.reset)) } > ROM
    .imports : { KEEP(*(.thumbv.imports)) } > ROM
    .text : { KEEP(*(.text.start)) *(.text .text.*) *(.rodata .rodata.* .srodata .srodata.*) } > ROM
    .data : { *(.data .data.* .sdata .sdata.*) } > RAM
    .bss  : { *(.bss .bss.* .sbss .sbss.* COMMON) } > RAM
}
