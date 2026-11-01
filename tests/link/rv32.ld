/* RV32 test programs. RAM starts above the Thumb side's, and the stack is shared. */
ENTRY(_start)

MEMORY
{
    ROM (rx)  : ORIGIN = 0x00020000, LENGTH = 64K
    RAM (rwx) : ORIGIN = 0x20004000, LENGTH = 16K
}

__stack_top = 0x20010000;

/* The Thumb window of mixed programs (tests/link/thumb_lib.ld): the startup
   code marks it as Thumb region 0. */
__thumb_region_base = 0x00014000;
__thumb_region_limit = 0x00020000;

SECTIONS
{
    /* The import jump table for Thumb code comes first, at a fixed address
       (thumbv.build.IMPORT_BASE), so the Thumb side can be linked first. */
    .imports : { KEEP(*(.thumbv.imports)) } > ROM
    .text : { KEEP(*(.text.start)) *(.text .text.*) *(.rodata .rodata.* .srodata .srodata.*) } > ROM
    .data : { *(.data .data.* .sdata .sdata.*) } > RAM
    .bss  : { *(.bss .bss.* .sbss .sbss.* COMMON) } > RAM
}
