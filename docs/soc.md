# The SoC and its simulation

A minimal hand-written SoC around the core (decision D6): on-chip RAM, a UART transmitter and the board's LEDs. The SoC is plain Verilog in `rtl/soc/`; it runs in Verilator now, and on the CYC1000 in Phase 1.4.

## Memory map

The map matches the software model's layout ([build.py](../model/thumbv/build.py)), so the same ELF files run in the model and on the RTL.

| Address | Size | What |
|---|---|---|
| `0x0000_0000` | 256 KiB | Code RAM: instructions and read-only data. Also readable and writable as data, for literal pools and `.rodata`. Thumb programs link at `0x1_0000` and the Thumb libraries of mixed programs at `0x1_4000`; RISC-V code at `0x2_0000`, which is also the reset vector: a jump to `_start`, then the import jump table for Thumb code at `0x2_0004` (`tests/link/rv32.ld`). |
| `0x1000_0000` | | UART data: writing sends the low byte |
| `0x1000_0004` | | UART status: bit 0 = busy |
| `0x1000_0008` | | LEDs: bits 7:0, read/write |
| `0x1000_0010` | | Button: bit 0 = held, bit 1 = pressed since last cleared (write 1 to bit 1 to clear). A press drives interrupt line 1, until cleared. On the board, the user button, debounced in `cyc1000_top.v`; in simulation, the testbench's `+button=<period>` |
| `0x1000_1000` | | Interrupt controller: `CLAIM` (read) and `COMPLETE` (write), for software interrupt entry |
| `0x2000_0000` | 64 KiB | Data RAM. The stack starts at the top (`0x2001_0000`). |
| `0xE000_E000` | 4 KiB | System Control Space: the interrupt controller's NVIC, SysTick and SCB registers, as on a Cortex-M0 |

Access faults:
- An instruction fetch outside the code RAM faults.
- A load from an unmapped address faults.
- A store to an unmapped address is dropped.

The 256 KiB code RAM fits in simulation only: the 10CL025 has about 66 KB of block RAM in all. The board uses a 32 KiB code RAM and a 16 KiB data RAM. A RAM smaller than its region repeats (aliases) through it, so the same ELF files run on the board as long as their parts don't land on the same RAM byte ([board.md](board.md)).

`tests/c/soc.h` defines the registers for C programs (`soc_putc`, `soc_puts`, `LEDS`).

## Modules

| File | What |
|---|---|
| `rtl/soc/thumbv_soc.v` | Top level: the core, the address decode and the response mux. Both buses accept a command every cycle, and the response comes one cycle later. |
| `rtl/soc/thumbv_nvic.v` | The interrupt controller (D9, Phase 5.2), see [below](#the-interrupt-controller). |
| `rtl/soc/thumbv_ram.v` | Dual-port RAM with synchronous reads and byte enables, written so that Quartus infers M9K blocks. The code RAM uses both ports (fetch and data); the data RAM uses one. |
| `rtl/soc/thumbv_uart_tx.v` | 8N1 UART transmitter. `CLKS_PER_BIT` sets the baud rate: 104 for 115200 baud at 12 MHz (the CYC1000's clock), and 4 in simulation so programs run fast. |

## Testbench

`sim/tb.sv` is a SystemVerilog testbench, built with `verilator --binary --timing`, so it needs no C++.
- **Loading:** it loads the RAMs from `$readmemh` files.
- **UART:** it decodes the UART line back into characters and prints them.
- **Trace:** it logs every retired instruction from the core's RVFI port (VexRiscv's `FormalPlugin`).
- **Waveforms:** `+wave=<file>` dumps every signal to an FST file, for GTKWave or Surfer. See [Waveforms](#waveforms).
- **Interrupts:** `+irq=<seed>` raises interrupt line 0 of the controller after a pseudo-random delay of 1 to 29 cycles, and holds it until the program acknowledges with a store to `0x1000_000C`. The SoC drops stores to that unmapped address, but the testbench sees it. Then the next delay starts. (Until Phase 5.2 it drove the core's timer interrupt directly.) On the board, the interrupt lines are tied to 0 for now.
- **Stopping:** the run ends when the core retires `j .` or Thumb's `b .` (`0xe7fe`, which no 32-bit RISC-V instruction starts with), the loops the startup code spins in at `done`. The testbench waits for the UART to finish its last byte, then prints `EXIT <a0> <cycles> <instructions>`. If the cycle limit is reached first, it prints `TIMEOUT`.

## Waveforms

`--wave` writes an FST waveform of the whole SoC:

```sh
uv run python -m thumbv.rtlsim build/hello.elf --wave build/sim/hello.fst
gtkwave build/sim/hello.fst      # or: surfer build/sim/hello.fst
```

- **Hierarchy:** `TOP.tb` is the testbench (Verilator adds `TOP`), `TOP.tb.dut` the SoC, and `TOP.tb.dut.cpu` the core.
- **Signal names:** the core's signals are named after their pipeline stage (`decode_`, `execute_`, `memory_`, `writeBack_`, for example `execute_PC` and `execute_INSTRUCTION`), so one instruction can be followed down the pipeline. The bus signals are `iBus_*` and `dBus_*`, and the retire trace is `rvfi_*`.
- **Not dumped:** the RAM contents. Verilator leaves out arrays larger than 32 entries; the RAM ports are there.
- **Cost:** tracing is always compiled in, which makes runs about 8% slower even when not dumping. Dumping itself is slower still, and only happens with `--wave`.

## The interrupt controller

`rtl/soc/thumbv_nvic.v`, with `model/thumbv/nvic.py` as its reference, which documents every register and the cycle model.
- **The ARMv6-M programming model at `0xE000_E000`,** so Cortex-M code drives it unmodified:
  - the NVIC's enable, pending and priority registers for 32 interrupts, 4 priority levels;
  - SysTick, counting core clocks;
  - `ICSR` (PendSV and SysTick pend bits, `VECTPENDING`, `VECTACTIVE`), `SHPR2`/`SHPR3` and `CPUID`.
- **Numbering:** exceptions as on Cortex-M: PendSV 14, SysTick 15, interrupt n is 16 + n. Ties go to the lowest number.
- **Claim and complete (`0x1000_1000`/`0x1000_1004`, Thumb-V's):** software interrupt entry has no hardware exception entry to track the active exception, so the controller does it.
  - **`CLAIM`:** reading it returns the highest-priority pending exception that can preempt the current priority. It clears that exception's pending bit and pushes it onto a stack of active ones, at most 4 deep.
  - **`COMPLETE`:** writing it pops the stack.
- **To the core:** the core's machine external interrupt is high while something could be claimed. The core's timer input is tied off: SysTick is the timer.
- **Interrupt lines** are level-sensitive, as on the NVIC: high, they pend their interrupt unless it's active, so a line still high at `COMPLETE` pends it again. A handler acknowledges its device before completing.
- **Checks:**
  - `tests/test_nvic.py` checks the model against the ARMv6-M rules, with directed tests.
  - `tests/test_nvic_rtl.py` runs random sequences through the RTL alone (`sim/nvic_tb.sv`) and the model, comparing every read and the interrupt line after every cycle: 16 seeds of 20,000 cycles.
  - `test_interrupt_controller` (`tests/test_rtl.py`) drives it from software on the SoC.
- **Words only:** byte and halfword writes act as word writes.

## Lockstep against the model

`model/thumbv/rtlsim.py` builds the testbench when its sources change, converts ELF files into memory images, runs them, and replays the trace against the model. For every retired instruction, the model must have:
- the same PC and instruction word;
- the same destination register and value, and no other register write;
- the same bytes stored;
- in Thumb code, the same NZCV after every op (the core's `thumbNzcv` output, logged beside the RVFI record, Phase 4.2).

Loads from the I/O registers and the interrupt controller are inputs from outside the core, so the model is given whatever value the RTL read. The UART's busy bit depends on timing that the model doesn't simulate.

```sh
uv run python -m thumbv.rtlsim build/hello.elf
# Hello from Thumb-V
# EXIT: a0 = 0xa5, 365 instructions in 870 cycles (CPI 2.38)
# lockstep: 365 instructions match the model
```

`tests/test_rtl.py` runs hello world and the all-RISC-V builds of the interworking test programs. Each must give the model's result and match it instruction by instruction. A mutant trace checks that the lockstep catches a wrong register write.

Limits for now:
- **Traps and interrupts (Phase 5.1):** a trapping instruction doesn't retire on VexRiscv, so the trace goes on at `mtvec`. There, the model runs its next op on a snapshot. If the op traps, the model takes that trap (`mepc`, `mcause`, `mtval`, `mstatus` as VexRiscv sets them). If it doesn't, the model rolls back and takes the interrupt instead (`lockstep(..., interrupt=11)`, the controller's external interrupt), which must come at an instruction boundary with `mstatus.MIE` set. FormalPlugin's own interrupt flag is always 0, so this inference is the only way.
- **Interrupt runs** (`+irq`) are replayed in full since Phase 5.1, handlers included; `tests/test_rtl.py` also checks where each interrupt landed (Phases 3.4, 4.4).

**Thumb-only programs** (linked by `tests/link/thumb.ld`, such as CoreMark and Embench) run behind a boot stub that `rtlsim.thumb_boot` generates: at the reset vector, it marks the program's code as Thumb region 0 and jumps to its entry point (Phase 4.4). `rtlsim.replay` returns the model after a clean lockstep, whose memory is then the RTL's, so a test can read results from it, such as CoreMark's own validation text.
