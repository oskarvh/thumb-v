# The SoC and its simulation

A minimal hand-written SoC around the core (decision D6): on-chip RAM, a UART transmitter and the board's LEDs. The SoC is plain Verilog in `rtl/soc/`; it runs in Verilator now, and on the CYC1000 in Phase 1.4.

## Memory map

The map matches the software model's layout ([build.py](../model/thumbv/build.py)), so the same ELF files run in the model and on the RTL.

| Address | Size | What |
|---|---|---|
| `0x0000_0000` | 256 KiB | Code RAM: instructions and read-only data. Also readable and writable as data, for literal pools and `.rodata`. Thumb programs link at `0x1_0000` and the Thumb libraries of mixed programs at `0x1_4000`; RISC-V code at `0x2_0000`, which is also the reset vector. |
| `0x1000_0000` | | UART data: writing sends the low byte |
| `0x1000_0004` | | UART status: bit 0 = busy |
| `0x1000_0008` | | LEDs: bits 7:0, read/write |
| `0x2000_0000` | 64 KiB | Data RAM. The stack starts at the top (`0x2001_0000`). |

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
| `rtl/soc/thumbv_ram.v` | Dual-port RAM with synchronous reads and byte enables, written so that Quartus infers M9K blocks. The code RAM uses both ports (fetch and data); the data RAM uses one. |
| `rtl/soc/thumbv_uart_tx.v` | 8N1 UART transmitter. `CLKS_PER_BIT` sets the baud rate: 104 for 115200 baud at 12 MHz (the CYC1000's clock), and 4 in simulation so programs run fast. |

## Testbench

`sim/tb.sv` is a SystemVerilog testbench, built with `verilator --binary --timing`, so it needs no C++.
- **Loading:** it loads the RAMs from `$readmemh` files.
- **UART:** it decodes the UART line back into characters and prints them.
- **Trace:** it logs every retired instruction from the core's RVFI port (VexRiscv's `FormalPlugin`).
- **Waveforms:** `+wave=<file>` dumps every signal to an FST file, for GTKWave or Surfer. See [Waveforms](#waveforms).
- **Interrupts:** `+irq=<seed>` raises the core's timer interrupt (the SoC's `irq_timer` input) after a pseudo-random delay of 1 to 29 cycles, and holds it until the program acknowledges with a store to `0x1000_000C`. The SoC drops stores to that unmapped address, but the testbench sees it. Then the next delay starts. On the board, `irq_timer` is tied to 0 until the interrupt controller (Phase 5).
- **Stopping:** the run ends when the core retires `j .`, the loop the startup code spins in at `done`. The testbench waits for the UART to finish its last byte, then prints `EXIT <a0> <cycles> <instructions>`. If the cycle limit is reached first, it prints `TIMEOUT`.

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

## Lockstep against the model

`model/thumbv/rtlsim.py` builds the testbench when its sources change, converts ELF files into memory images, runs them, and replays the trace against the model. For every retired instruction, the model must have:
- the same PC and instruction word;
- the same destination register and value, and no other register write;
- the same bytes stored.

Loads from the I/O registers are inputs from outside the core, so the model is given whatever value the RTL read. The UART's busy bit depends on timing that the model doesn't simulate.

```sh
uv run python -m thumbv.rtlsim build/hello.elf
# Hello from Thumb-V
# EXIT: a0 = 0xa5, 365 instructions in 870 cycles (CPI 2.38)
# lockstep: 365 instructions match the model
```

`tests/test_rtl.py` runs hello world and the all-RISC-V builds of the interworking test programs. Each must give the model's result and match it instruction by instruction. A mutant trace checks that the lockstep catches a wrong register write.

Limits for now:
- **No trap handling.** The model doesn't model taking a trap: it stops with `Trap`. So the lockstep covers programs that don't trap. Trap handling comes with the trap entry routine (Phase 5).
- **RISC-V code only.** Thumb code needs the expander in the RTL (Phase 2). The model side is ready: the same lockstep will then check Thumb instructions, with each one retiring as several RV32 ops.
