# Firmware

`firmware/` holds the RISC-V code that mixed programs link for interrupts and traps (Phase 5.3, plan section 6). One entry routine handles every interrupt and trap, from code of either instruction set, and calls handlers of either instruction set as ordinary functions.

| File | What |
|---|---|
| `thumbv_entry.S` | The trap entry routine: `mtvec` |
| `thumbv.c` | Its C side (dispatch, SVC, fault reports) and the API |
| `thumbv.h` | The API, for RISC-V code |
| `thumbv_scs.h` | The System Control Space and controller registers, for C code of either instruction set |

Programs get it with `build.mixed_program(..., firmware=True)` or `build.c_program(..., firmware=True)` (the test fixtures take the same flag). The board programs always link it. It costs nothing unless a program calls `thumbv_init()`.

## The entry routine

On any trap it saves the caller-saved registers (`ra`, `t0`–`t6`, `a0`–`a7`), `mepc`, `mstatus` and NZCV (CSR `0x7C4`) in an 80-byte frame on the current stack. Then, by `mcause`:
- **Interrupts** (the controller's line, cause 11 with bit 31):
  1. read `CLAIM`: the highest-priority pending exception that can preempt the current priority (0 if none any more);
  2. enable interrupts, so that higher priorities preempt the handler;
  3. call `thumbv_dispatch(exception)`, which calls the handler set with `thumbv_set_handler`;
  4. disable interrupts and write `COMPLETE`.
- **Synchronous traps:** `thumbv_trap(mcause, frame)` returns where to resume:
  - **`ecall`** is `SVC` if `mepc` is in a Thumb region. The number is the instruction's low byte, and the routine resumes 2 bytes on. From RISC-V the number is in `a7` and it resumes 4 bytes on. The handler set with `thumbv_set_svc` gets the saved `r0`–`r3` / `a0`–`a3` and returns the new `r0` / `a0`.
  - **Everything else,** and an `SVC` without a handler, goes to `thumbv_fault`. That is a weak function, so programs can replace it. By default it reports the trap over the UART (`thumbv: breakpoint at 00014000 (Thumb), mtval 00100073`), resumes after a `BKPT`/`ebreak`, and stops for anything else.

Then it restores everything, NZCV included, and returns with `mret`.

**Why NZCV:** a Thumb handler changes the flags, and the code it interrupted may be between a compare and its branch. RISC-V handlers never touch NZCV. `test_firmware_interrupts` shows the difference: without the restore, a flag-changing Thumb handler breaks the Thumb code it interrupts.

**Handlers in Thumb** are compiled for Cortex-M0 as Cortex-M handlers are: `void SysTick_Handler(void)`, writing the SCS registers directly. The entry routine calls them with `jalr`; the Thumb regions select the decoder, and they return with `BX LR` into the routine. Callee-saved registers are theirs to save, and with the D2 register mapping that holds for Thumb code too.

**Devices** acknowledge before their handler returns: interrupt lines are level-sensitive, so a line still high at `COMPLETE` pends again.

## The API (`thumbv.h`)

```c
thumbv_init();                                   // mtvec, mie.MEIE; interrupts stay off
thumbv_set_handler(THUMBV_SYSTICK, SysTick_Handler);   // 14 PendSV, 15 SysTick, 16 + n
thumbv_systick_start(reload, priority);          // a tick every reload + 1 cycles
thumbv_irq_priority(n, p); thumbv_irq_enable(n); thumbv_irq_pend(n);
thumbv_pendsv_priority(p); thumbv_pendsv();
thumbv_set_svc(1, handler);                      // uint32_t handler(uint32_t *r0_to_r3)
thumbv_interrupts_on();                          // mstatus.MIE, PRIMASK's RISC-V side
```

## Latency

80 cycles, from SysTick pending to the first load in the C handler (`test_firmware_interrupts`). The path is:
- the pipeline draining;
- 16 register stores;
- three CSR reads, each of which waits for the pipeline to drain;
- the claim (a load);
- `thumbv_dispatch`;
- the handler's prologue.

A Cortex-M0 takes 16 cycles to its handler's first instruction, with hardware stacking. Hardware vectoring, or saving fewer registers for handlers known to be RISC-V, would shorten this if it matters (plan, Risks).

## Tests

All in `tests/test_rtl.py`, on the RTL in lockstep with the model:
- **`test_firmware_interrupts`** (`tests/c/irq_mixed_main.c`, `irq_mixed_thumb.c`):
  - SysTick handlers: Thumb interrupting RISC-V, RISC-V interrupting Thumb, and Thumb interrupting Thumb, with more than 100 interrupts each and results unchanged;
  - preemption by priority, an equal priority waiting, and PendSV;
  - `SVC #1`/`#2` from Thumb and `ecall` from RISC-V;
  - the latency.
- **`test_firmware_faults`** (`fault_main.c`): the default reports for `BKPT`, `ebreak` and a Thumb load fault.
- **`test_firmware_systick_tick`** (`tick_main.c`, `tick_thumb.c`): the board program for its first two ticks. On the board it's `make board PROGRAM=tick`: a Thumb SysTick handler at 10 Hz counts on the LEDs, and RISC-V prints each tick.
