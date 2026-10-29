# Thumb-V: ARMv6-M on RISC-V

A hardware translation layer that runs ARMv6-M (Cortex-M0/M0+) Thumb code on an off-the-shelf RISC-V soft core, as close to native speed as possible. Target board: Trenz CYC1000 (Intel Cyclone 10 LP 10CL025, ~25K LEs, 8 MB SDRAM).

Think "Rosetta in silicon": instead of translating in software, a hardware expander in the core's front end turns each Thumb instruction into one or more RV32 instructions that the stock pipeline executes.

Two use cases share the same hardware:

1. **Mixed execution.** A native RISC-V program or RTOS calls Thumb code (e.g. a vendor library shipped only for Cortex-M0) and is called back, at function or task granularity.
2. **ARM-only.** An unmodified Cortex-M0 firmware image owns the system, with a small RISC-V firmware layer emulating the Cortex-M exception model.

Both instruction sets share one register file, stack and address space, so there is no sandboxing between them.

See [`architecture.puml`](architecture.puml) for the pipeline diagram and [`docs/plan.md`](docs/plan.md) for the plan and design decisions.

## Quick start

On Ubuntu 24.04:

```sh
sudo apt-get install gcc-arm-none-eabi gcc-riscv64-unknown-elf
make setup        # Python environment (needs uv)
make check-tools  # see what is installed
make test
```

[`docs/setup.md`](docs/setup.md) covers installation and how to run, select and add tests. All dependencies are listed in [`docs/dependencies.md`](docs/dependencies.md).

## Architecture

- **Insertion point.** The Thumb expander sits where the RVC decompressor sits (between fetch and decode). Thumb-1 is 16-bit like RVC, so the core already fetches it and advances the PC in 2-byte steps. In Thumb regions the aligner uses Thumb's rule for telling 16-bit from 32-bit instructions.
- **Shared vs injected.** Where a Thumb instruction maps 1:1 to RV32, the expander emits one instruction. Otherwise a sequencer emits a short sequence of RV32 instructions.
- **Stock core, two small patches.**
  1. Hold the PC during a sequence: every injected instruction carries the Thumb instruction's address, and only the last advances the PC (by 2, or 4 for `BL`).
  2. Take interrupts only at Thumb instruction boundaries.
- **Mode by programmable address range.** A few region CSRs mark which address ranges decode as Thumb; everything else decodes as RISC-V. No mode bit is needed: a `jal` into a Thumb region starts decoding Thumb, a `BX LR` back to a RISC-V caller switches back, and `mret` resumes in the right decoder from `mepc`.
- **Core.** VexRiscv (pipelined, plugin-based, has RVC) is the preferred base. NEORV32 (VHDL, readable, separate decompressor) is the alternative.

## Register mapping

ARM registers sit in the RISC-V registers with the same role in both calling conventions (AAPCS and RISC-V ilp32), so calls between the two instruction sets need no glue code.

| ARM | RISC-V | Role in both ABIs |
|---|---|---|
| r0–r3 | x10–x13 (a0–a3) | arguments, return value, caller-saved |
| r4–r11 | x8, x9, x18–x23 (s0–s7) | callee-saved |
| r12 | x5 (t0) | scratch |
| SP | x2 (sp) | stack pointer (one shared stack) |
| LR | x1 (ra) | return address |
| PC | the core's real PC (the binary runs at its own addresses) | |
| — | t1–t6, a4–a7 | expander temporaries and flag state |
| — | x3, x4 (gp, tp), s8–s11 | never touched by Thumb code |

Calls whose signatures differ between the ABIs (more than 4 arguments, 64-bit arguments, structs, varargs) go through generated thunks.

## Instruction mapping (RV32IM)

| Thumb | Expansion |
|---|---|
| `LDR/STR/LDRB/LDRH [rn, #imm]` | 1 |
| `LDR [rn, rm]` | 2 (`add` + load) |
| `LDR [pc, #imm]` | 2 (`auipc` + `lw`; expander computes the word-aligned offset) |
| `MULS` | 1 + flags |
| `BX rm` | 1 (`jalr x0, 0(rm)`; `jalr` already clears bit 0) |
| `CMP` + `B<cond>` | 1 when fused (`beq`/`blt`/`bltu`/…), plus whatever keeps NZCV recoverable |
| `BL` | 2–3 (LR gets bit 0 set; `auipc` + `jalr` beyond `jal`'s ±1 MiB) |
| `CPSID`/`CPSIE`, `WFI`, `SVC`, `BKPT` | 1 (`csrci`/`csrsi`, `wfi`, `ecall`, `ebreak`) |
| `UXTB/UXTH`, `SXTB/SXTH` | 1–2 (1 with Zbb) |
| `REV`, `RORS` | 4–8 (1 with Zbb) |
| Shift by register | 3–4 (ARM uses the low byte; shifts ≥ 32 need a range check) |
| `PUSH`/`POP`/`LDM`/`STM` | 1 per register + 1 |
| `ADCS`/`SBCS` | 4–6 |

## Flags (NZCV)

Nearly every 16-bit Thumb data-processing instruction sets flags, so flag handling decides performance. Code after a branch may read flags set before it, so fusing `CMP` + `B<cond>` doesn't by itself make the flags dead. Three strategies are being compared on real compiled code before choosing one for the RTL:

1. **Eager software flags:** compute NZCV after every flag-setting instruction.
2. **Lazy flags:** record the operation and operands, and compute flags only when read.
3. **Hardware flags unit:** latch NZCV from the ALU and add a custom branch-on-condition instruction.

## Interrupts and exceptions

- **One interrupt controller** with the ARMv6-M NVIC programming model (32 interrupts, 4 priority levels, at `0xE000_E100`), used by both instruction sets. Every pending bit is software-writable (PendSV, RISC-V software interrupts). One timer serves as both SysTick and RISC-V `mtime`/`mtimecmp`.
- **Handler entry.** A shared RISC-V entry routine saves the caller-saved registers, looks up the handler and calls it as an ordinary function. Because the register mapping follows both ABIs, the handler can be RISC-V or Thumb; the handler's address decides how it decodes.
- **Synchronous traps** (`SVC`/`ecall`, `BKPT`/`ebreak`, undefined instructions, faults) bypass the controller. The trap handler checks whether `mepc` is in a Thumb region to know which instruction set trapped.
- **ARM-only mode** adds exact Cortex-M behaviour on top: reset (load SP from `0x0`, jump to the reset vector at `0x4`), the stacked 8-word frame (r0–r3, r12, LR, PC, xPSR), EXC_RETURN (the bus faults on instruction fetches from `0xFFFFFFxx`; the firmware catches the fault, unstacks the frame and resumes), and MSP/PSP banking.

## Peripherals

The NVIC and SysTick are real hardware (see above). In ARM-only mode, vendor peripheral registers are emulated by a bus-level shim that responds at the expected addresses (e.g. STM32 GPIO mapped onto the board's LEDs).

## Roadmap

See [`docs/plan.md`](docs/plan.md) for details and exit criteria.

0. Software golden model: Thumb→RV32 expander, executor, lockstep against Unicorn, interworking prototype, flags measurements.
1. Bring up a stock RISC-V soft core in Verilator and on the CYC1000 with UART and LEDs.
2. Thumb region CSRs and a combinational expander for 1:1 instructions plus `B`/`BX`/`BL`; a RISC-V program calls a Thumb function.
3. Sequencer for multi-instruction expansions; PC-hold and interrupt-boundary patches.
4. Flag handling, using the chosen strategy.
5. Unified interrupt controller and shared entry routine; real ARM libraries and an RTOS with Thumb tasks.
6. ARM-only mode: Cortex-M exception emulation and a GPIO shim; run an unmodified Cortex-M0 blinky.
7. Performance: SDRAM, CoreMark on the board, Zbb.

## Verification

Run Thumb programs in Verilator and in a reference ARMv6-M model (Unicorn) and compare register and flag state after every instruction. For mixed programs, compare return values and memory at each RISC-V→Thumb call. Use random instruction sequences to catch flag edge cases (`SUBS`/`SBCS` carry and overflow especially), and check the RTL expander against the software model for every 16-bit encoding.
