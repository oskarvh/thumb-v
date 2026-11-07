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

## FreeRTOS

`firmware/freertos/` runs the FreeRTOS kernel (`third_party/FreeRTOS-Kernel`, V11.3.3, unmodified) on Thumb-V with its own RISC-V port (Phase 5.5). The port's trap handler replaces the entry routine as `mtvec`. The firmware still provides the API, the dispatch and the fault reports.

| File | What |
|---|---|
| `freertos_risc_v_chip_specific_extensions.h` | The port's hook for chip registers: NZCV in every task's context |
| `thumbv_freertos.c` | The tick, the interrupt and exception handlers, and the kernel's hooks |
| `FreeRTOSConfig.h` | Sized for the board; programs can override the tick rate and heap size |

Programs build with `build.freertos_sources()` and `build.freertos_flags()`. `build.rtos_program()` is the demo.

- **The tick** is SysTick, at the lowest priority, as on Cortex-M. There's no `mtime`. `vPortSetupTimerInterrupt` sets `mtvec` to the port's handler, enables `mie.MEIE` and starts SysTick at `configCPU_CLOCK_HZ / configTICK_RATE_HZ`.
- **Interrupts:** the controller's line reaches the port as an application interrupt. `freertos_risc_v_application_interrupt_handler` then:
  1. claims the exception;
  2. for SysTick, calls `xTaskIncrementTick` and switches tasks if it says to; for anything else, calls the handler set with `thumbv_set_handler` (either instruction set);
  3. completes the exception.

  The port doesn't nest interrupts: handlers run on the interrupt stack (main's old stack) with interrupts disabled.
- **NZCV:** the port saves one extra word per task, between `mepc` and `mstatus`, so its frame is 128 bytes. RISC-V code never touches the flags. A Thumb task preempted between a compare and its branch would otherwise resume with the flags of whichever Thumb task ran last.
- **Thumb tasks** are Cortex-M0 functions, `void task(void *)`, created with `xTaskCreate` like any other. They call the kernel's API by name through the import table: the kernel is RISC-V code, and its signatures pass arguments the same way in both ABIs (`tests/c/rtos.h`).
  - They don't use the kernel's headers, which belong to the RISC-V port.
  - They must not execute `SVC`: the port treats every `ecall` as a yield and resumes 4 bytes on. They yield through the API instead, which `ecall`s from RISC-V code.
- **Faults,** failed assertions, stack overflows and a full heap are reported over the UART, and the program stops.
- **The idle hook** counts (`thumbv_idle_count`), and it's weak, so programs can replace it. Without it, the idle task's empty loop compiles to `j .`, which the simulation testbench takes as the end of the program.

**The demo** (`tests/c/rtos_main.c`, `rtos_thumb.c`, `rtos_work.h`):
- a RISC-V producer puts 8 jobs a round on a queue;
- two Thumb tasks running the same function take the jobs, compute (a loop of signed and unsigned compares and branches), and put the results on a second queue;
- a RISC-V checker at a higher priority recomputes each result in RISC-V and prints a line a round;
- a RISC-V spinner computes too, with a one-tick delay each step, so the idle task runs as well.

Everything else runs at the same priority, time-sliced by the tick.
- **On the RTL** (`test_freertos`): two rounds, ticking every 3,000 cycles, with the board's RAMs, in lockstep with the model (262,000 instructions). There are 252 traps, 82 of them in Thumb code, and no wrong results.
- **The negative control** (`test_freertos_needs_nzcv_in_the_context`): built without the NZCV save, 5 of 16 results are wrong.
- **On the board:** `make board PROGRAM=rtos`, at a 1 kHz tick, prints a round every 0.5 s with no errors, both Thumb tasks taking jobs.
- **Size:** 13.8 KB of RISC-V code with unused kernel functions dropped, which fits the board's 16 KiB. 6.6 KB of RISC-V data, 6 KiB of which is the heap. The Thumb task is 148 bytes.
