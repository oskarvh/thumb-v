/* Thumb-V's chip-specific extension to FreeRTOS's RISC-V port (Phase 5.5):
 * NZCV (CSR 0x7C4, the Thumb flags) is part of every task's context.
 *
 * RISC-V code never touches NZCV, but two Thumb tasks share it: a Thumb task
 * preempted between a compare and its branch must get its own flags back,
 * whatever the other ran meanwhile. The port calls these macros on every trap
 * and in xPortStartFirstTask; the extra word sits between mepc and mstatus
 * (portContext.h), and pxPortInitialiseStack starts it at 0.
 *
 * No mtime: the tick is SysTick, through the interrupt controller
 * (thumbv_freertos.c). */
#ifndef __FREERTOS_RISC_V_EXTENSIONS_H__
#define __FREERTOS_RISC_V_EXTENSIONS_H__

#define portasmHAS_SIFIVE_CLINT           0
#define portasmHAS_MTIME                  0
/* One word: with the port's 31, a 128-byte frame. */
#define portasmADDITIONAL_CONTEXT_SIZE    1

#define portasmNZCV                       0x7c4

#ifdef THUMBV_FREERTOS_NO_NZCV   /* the tests' negative control: flags not saved */
.macro portasmSAVE_ADDITIONAL_REGISTERS
    addi sp, sp, -( portasmADDITIONAL_CONTEXT_SIZE * portWORD_SIZE )
    .endm
.macro portasmRESTORE_ADDITIONAL_REGISTERS
    addi sp, sp, ( portasmADDITIONAL_CONTEXT_SIZE * portWORD_SIZE )
    .endm
#else
.macro portasmSAVE_ADDITIONAL_REGISTERS
    addi sp, sp, -( portasmADDITIONAL_CONTEXT_SIZE * portWORD_SIZE )
    csrr t0, portasmNZCV
    sw   t0, 1 * portWORD_SIZE( sp )
    .endm

.macro portasmRESTORE_ADDITIONAL_REGISTERS
    lw   t0, 1 * portWORD_SIZE( sp )
    csrw portasmNZCV, t0
    addi sp, sp, ( portasmADDITIONAL_CONTEXT_SIZE * portWORD_SIZE )
    .endm
#endif

#endif /* __FREERTOS_RISC_V_EXTENSIONS_H__ */
