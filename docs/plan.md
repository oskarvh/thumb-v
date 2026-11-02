# Thumb-V: Plan

Status: draft, 2026-10-28. This plan reviews the design in the [README](../README.md) and [`architecture.puml`](../architecture.puml), lists what needs deciding first, and breaks the first phases into concrete steps with exit criteria.

## Use cases

Thumb-V targets two ways of running Thumb code. Both share the same hardware; they differ only in the software around it.

1. **Mixed execution (primary).** A native RISC-V program or RTOS calls into Thumb code at function or task granularity. Examples: a closed-source vendor library shipped only as a Cortex-M0 `.a` (BLE stack, DSP routines), or a legacy ARM task scheduled alongside native ones. Calls go both ways (Thumb code can call back into RISC-V, e.g. `memcpy`, `malloc`, callbacks). Interrupts are handled by ordinary RISC-V handlers; no ARM exception model is needed.
2. **ARM-only (Cortex-M0 replacement).** An unmodified Cortex-M0 firmware image owns the system. A small RISC-V firmware layer emulates the ARM exception model: reset, NVIC, the stacked exception frame, EXC_RETURN, SysTick.

Instruction-level interleaving of the two instruction sets is not a goal: switches happen at function calls, returns, traps and task switches.

**No sandboxing.** Both instruction sets share one register file, one stack and one address space, so Thumb code is as trusted as the RISC-V code that calls it. If isolation is ever needed, RISC-V PMP plus running Thumb code in U-mode is the natural route; it is out of scope for now.

## Guiding principles

1. **One machine, two decoders.** The Thumb front end maps onto the RISC-V machine as directly as possible: the same register file following both calling conventions, the same stack, the same PC, the same trap mechanism. Anything shared doesn't need translating at a boundary.
2. **Model before RTL.** Every Thumb→RV32 expansion is first written and verified in a software model. The RTL expander is then checked bit-for-bit against that model.
3. **Simulation before silicon.** Verilator is the main development loop. The CYC1000 is used early to prove the toolchain, then to confirm milestones.
4. **Measure before optimising.** Flag handling decides performance. Choose a strategy using measured expansion ratios on real compiled code, not guesses.
5. **Lockstep against a reference.** Thumb code is compared against an ARMv6-M reference model (Unicorn): r0–r15 and NZCV after every Thumb instruction where possible, and results at call boundaries for mixed programs.

## Design review: issues to resolve early

### 1. Register mapping: follow both calling conventions

For calls between the two instruction sets to need no glue code, ARM registers sit in RISC-V registers with the same role in the two ABIs (AAPCS and RISC-V ilp32):

| ARM | Role (AAPCS) | RISC-V | Role (ilp32) |
|---|---|---|---|
| r0–r3 | arguments, return value, caller-saved | x10–x13 (a0–a3) | arguments, return value, caller-saved |
| r4–r11 | callee-saved | x8, x9, x18–x23 (s0–s7) | callee-saved |
| r12 (IP) | scratch, caller-saved | x5 (t0) | scratch, caller-saved |
| SP | stack pointer | x2 (sp) | stack pointer |
| LR | return address | x1 (ra) | return address |
| PC | — | the core's real PC | — |

Registers Thumb code never touches as ARM state:
- **Expander temporaries and flag state** go in caller-saved registers (t1–t6, a4–a7). Temporaries are only live inside one sequence. Flags aren't preserved across calls under AAPCS, so keeping flag state in caller-saved registers is safe across calls into RISC-V. Interrupt handlers save whatever they clobber, as usual.
- **x3/x4 (gp/tp)** stay reserved for the RISC-V side.
- **s8–s11** are untouched by Thumb code, so they are preserved automatically.

Decode cost: a 3-bit Thumb register field needs an 8-entry lookup (r0–r7 → x10, x11, x12, x13, x8, x9, x18, x19) and a 4-bit field a 16-entry one. That's a handful of logic elements per field.

Consequence for the ARM-only case: the exception firmware is ordinary RV32I C. Its trap entry saves registers like any RISC-V interrupt handler, then builds the ARM exception frame from them.

### 2. Mode by programmable address range

The README already selects the decoder by fetch address. Keep that, because it makes switching free:
- A RISC-V `jal`/`jalr` into a Thumb region simply starts decoding Thumb.
- A Thumb `BX LR` or `POP {pc}` to an address outside the region returns to RISC-V decoding. `jalr` clears bit 0, so the Thumb-style return address `ret|1` that `BL` puts in LR works unchanged when a RISC-V function returns to Thumb code.
- Traps need no saved mode state: `mepc` alone decides which decoder resumes on `mret`.

The change from the README: the region must be **programmable** instead of a fixed firmware window, so that both instruction sets can live in ordinary memory. Start with a small number (2–4) of base/limit CSRs set by the loader or startup code. In ARM-only mode, everything except the firmware region is marked Thumb.

### 3. Interworking software

Matching registers covers most calls, but the two calling conventions still differ:
- More than 4 arguments: AAPCS puts the 5th onward on the stack, RISC-V uses a4–a7 first.
- 64-bit arguments: AAPCS aligns them to even register pairs (r0:r1, r2:r3), RISC-V doesn't for non-variadic calls.
- Varargs and structs passed or returned by value.
- Stack alignment: AAPCS guarantees 8 bytes, RISC-V ilp32 expects 16.

These are handled by **thunks** generated per imported function from its C prototype. Simple signatures (≤4 word-sized arguments) need none.

Build flow (decided, see [interworking.md](interworking.md)): the two halves can't be linked by one linker because they are different ELF machine types.
1. Link the Thumb part with `arm-none-eabi-ld` first. Its imports (calls into RISC-V) resolve to slots of a jump table at a fixed address at the start of the RISC-V image.
2. A generator reads the interface header and emits the jump table and the thunks; the RISC-V link gets the Thumb exports' addresses as absolute symbols.
3. Both images are loaded side by side. (Combining them into one ELF file is a packaging step for later.)

### 4. Flags: fusion alone isn't safe, which argues for doing the hardware flags unit early

`CMP` + `B<cond>` fusion only removes flag computation if nothing reads the flags afterwards. After a branch, a one-instruction lookahead can't see the code that runs next, and the code at both the target and the fall-through may legally read the flags set by the `CMP`. So a fused branch still has to leave NZCV recoverable.

| Strategy | Cost per flag-setting op | Core change | Notes |
|---|---|---|---|
| A. Eager software flags | +3–6 RV ops (C and V are the costly ones) | none | Simplest and slowest. A good correctness baseline. |
| B. Lazy flags (QEMU-style) | +1–2 ops: record op kind, result and operands in reserved registers | none | N/Z branches become `blt`/`beq` on the saved result. C/V are computed on demand. |
| C. Hardware NZCV unit | +0 | ALU tap, a 4-bit register, a branch-on-condition micro-op | Fusion and dead-flag lookahead become unnecessary. |

A and B both make the expander more complicated (lookahead buffers, fusion logic, sequences for every ADDS/SUBS), and that work is thrown away once C exists. **Recommendation:** implement A in the software model only, as the reference. Use the Phase 0 measurements to decide whether the RTL goes straight to C. With C, NZCV is a CSR that an RTOS saves on a context switch away from a Thumb task.

**Measured in 0.7** ([flags-decision.md](flags-decision.md)): A costs 3.92 RV32 ops per Thumb instruction, B 2.67 (the estimate above was too low: saving operands on every write costs about as much as computing N and Z), and C 1.25. A with even a perfect dead-flag elimination (1.47) loses to C.

### 5. Thumb-specific details the expander must handle

- **Instruction length.** In Thumb regions the fetch aligner must use the Thumb length rule (`hw[15:11]` ∈ {`11101`, `11110`, `11111`} → 32-bit), not the RVC rule. ARMv6-M's 32-bit instructions are `BL`, `MSR`, `MRS`, `DSB`, `DMB` and `ISB`.
- **PC reads return PC+4.** Branch offsets, `ADR`, `ADD rd, pc`, `MOV rd, pc` and `LDR [pc]` (which also uses `Align(PC,4)`) need the offset adjusted. Every op in a sequence carries the *Thumb* instruction's address as its PC (the PC-hold patch), so `auipc` returns the Thumb address.
- **`BL` range.** `BL` reaches ±16 MiB but `jal` only ±1 MiB. The expander picks `jal` when the offset fits and `auipc`+`jalr` otherwise. LR must be `(PC+4)|1`; a stock `jal` link value lacks bit 0.
- **`BLX rm`** exists in ARMv6-M: LR = `(PC+2)|1`. With address-based mode, `BLX` to a RISC-V function needs no special handling.
- **`BX` with bit 0 clear** faults on a real Cortex-M (attempted switch to ARM state). Thumb-V ignores bit 0 and lets the address decide, which is what makes returns to RISC-V callers work.
- **Hi-register ops writing PC** (`MOV pc, rm`, `ADD pc, rm`) are branches. `POP {.., pc}` is a branch that may load an EXC_RETURN value in ARM-only mode.
- **Restartable sequences.** If interrupts could arrive mid-sequence, `LDM rn!, {.., rn, ..}` would have to load the base register last, and peripheral reads with side effects could not be replayed. See 6.
- **System instructions.** In mixed mode, `SVC`, `BKPT`, `UDF`, `CPSID`/`CPSIE` and `MRS`/`MSR` trap to the RISC-V handler (or map to `ecall`/`ebreak`/CSR ops). In ARM-only mode the firmware gives them ARM semantics: `SVC`'s stacked return address is the next instruction (`ecall`'s `mepc` is the `SVC` itself, so add 2), MSP/PSP banking via `CONTROL.SPSEL` (the firmware swaps x2 with a stored copy), 8-byte stack alignment on exception entry, and xPSR's T bit reading as 1.
- **NOP-like hints.** `WFE`, `SEV`, `YIELD` and `NOP` become `addi x0, x0, 0`, or `wfi` for `WFE`.

### 6. Interrupts and exceptions

#### One controller for both instruction sets

RISC-V has no NVIC equivalent in the base architecture: each privilege level has a software, a timer and one external interrupt input, a trap vector (`mtvec`) and a cause register (`mcause`). Richer controllers (CLINT, PLIC, CLIC) are optional add-ons. Cortex-M code, on the other hand, expects the NVIC register interface at fixed addresses.

So Thumb-V has **one interrupt controller with the ARMv6-M NVIC programming model**, used by both instruction sets:
- Up to 32 interrupts, 4 priority levels, and enable / pending / priority registers at the standard NVIC addresses (`0xE000_E100` onward). ARM code uses them unmodified; RISC-V drivers are our own code and use the same registers.
- Every pending bit is software-writable, which provides PendSV-style software interrupts (needed by Cortex-M RTOS ports) and RISC-V software interrupts through the same mechanism.
- The controller drives the core's single machine external-interrupt line and exposes the number of the highest-priority pending interrupt. Hardware vectoring (jumping straight to the handler) is a later optimisation.
- One timer serves as both SysTick (`0xE000_E010`) and RISC-V `mtime`/`mtimecmp`, through two register views of the same hardware.

The vector table holds plain handler addresses. Which instruction set a handler is written in is decided by the programmable Thumb regions (section 2), so the controller never needs to know. An interrupt can arrive while Thumb or RISC-V code is running, and `mret` resumes in the right decoder from the address in `mepc`.

#### Entering a handler

Cortex-M hardware stacks r0–r3, r12, LR, PC and xPSR on interrupt entry, so its handlers are ordinary C functions that return with `BX LR` and the magic EXC_RETURN value. RISC-V hardware saves only the PC and the interrupt-enable bit, so its handlers must save what they use and end with `mret`.

In mixed mode, a **shared RISC-V entry routine** bridges the two:
1. Save the caller-saved registers (and NZCV, if flags are in a hardware register, since a Thumb handler could change them).
2. Read the active interrupt number from the controller and look up the handler.
3. Call the handler as an ordinary function. Thanks to the aligned calling conventions (section 1), this works for RISC-V and Thumb handlers alike; a Thumb handler returns with `BX LR` back into the routine.
4. Restore the registers and `mret`.

No EXC_RETURN values or xPSR frames exist in mixed mode. ARM-only mode adds exact Cortex-M frame emulation on top of the same controller and entry path, because unmodified code inspects and changes the frame (PendSV context switches, HardFault handlers reading the stacked PC).

#### Asynchronous interrupts vs synchronous traps

- **Interrupts** (from hardware or pended by software, which behave the same once pending) go through the controller, have priorities, can be masked, and are taken **only at Thumb instruction boundaries**: interrupt-allowed is asserted only when the op in the trap-taking stage is the last op of its sequence. This is simpler than proving every sequence restartable, and it is always correct.
- **Synchronous traps** (`SVC` → `ecall`, `BKPT` → `ebreak`, undefined instructions, memory faults) are caused by one instruction. They bypass the controller, can't be masked, and are precise: `mepc` is the Thumb instruction's address even mid-sequence. The trap handler uses the Thumb regions to tell which instruction set trapped, so it knows whether to resume 2 or 4 bytes later and where to find the `SVC` number (the Thumb instruction's 8-bit immediate). Only a fault handler that fixes the cause and retries needs the sequence to be safe to replay, which is rare without an MMU. In ARM-only mode the firmware also applies ARM's priority rules, e.g. an `SVC` while interrupts are masked escalates to HardFault.

### 7. Exhaustive verification is possible

The 16-bit Thumb encoding space has only 65,536 values, and the 32-bit instructions are few. The RTL expander can be checked against the Python model for **every** encoding at several PC alignments. Plan the testbench around this from day one.

### 8. Memory map

In ARM-only mode, Cortex-M binaries assume code/flash at `0x0000_0000`, SRAM at `0x2000_0000`, peripherals at `0x4000_0000` and the System Control Space (SysTick, NVIC, SCB) at `0xE000_E000`. The firmware and any SoC-internal peripherals (debug UART) must sit elsewhere, e.g. `0xF000_0000`. In mixed mode the map is the RISC-V program's own; Thumb images are placed wherever the build flow puts them. The System Control Space stays at `0xE000_E000` in both modes, since the unified interrupt controller and timer live there.

For the early phases, use on-chip M9K RAM (~66 KB on the 10CL025) and defer the SDRAM controller.

## Decisions

| # | Decision | Status |
|---|---|---|
| D1 | Flags strategy for the RTL | **Decided:** C, a plain hardware NZCV unit, keeping custom hardware to a minimum: 1.25 RV32 ops per Thumb instruction over 21 programs, against 3.92 for A, 2.34 for the best realisable A variant and 2.67 for B. The ARM-shift micro-op (Q3) and fused `CMP` + `B<cond>` (together 1.05) are not adopted, but stay options for Phase 7 ([flags-decision.md](flags-decision.md)) |
| D2 | Register mapping | **Decided:** ABI-aligned mapping (section 1) |
| D3 | When interrupts are taken | **Decided:** Thumb instruction boundaries only (section 6) |
| D4 | Base core | **Decided** after 1.3: VexRiscv. Every patch point exists, and the PC-hold spike worked in about 30 lines. VexiiRiscv was not evaluated in depth; NEORV32 stays the fallback ([vexriscv-notes.md](vexriscv-notes.md#decisions)) |
| D5 | Where the expander lives | **Decided** after 1.3: a Thumb-V copy of VexRiscv's fetcher (`Fetcher.scala` + `IBusSimplePlugin.scala`) in `rtl/core`, with changes marked; the region CSRs, NZCV unit and interrupt gating as separate plugins through VexRiscv's services. A separate plugin can't reach the fetcher's internals ([vexriscv-notes.md](vexriscv-notes.md#decisions)) |
| D6 | SoC wrapper | Proposed: a minimal hand-written SoC around the core. LiteX for a first board smoke test only. |
| D7 | Mode selection | **Decided:** programmable Thumb address regions (section 2). 2 regions, as base/limit CSRs `0x7C0`–`0x7C3`, word-aligned, followed by `fence.i` ([core.md](core.md#thumb-v-changes)) |
| D8 | Interworking build flow | **Decided:** link the Thumb side first; Thumb calls into RISC-V go through a jump table at a fixed address; RISC-V thunks are generated from an interface header only where the ABIs differ ([interworking.md](interworking.md)) |
| D9 | Interrupt controller | **Decided:** one controller with the ARMv6-M NVIC programming model, shared by both instruction sets, with a shared RISC-V entry routine that calls handlers of either instruction set as ordinary functions (section 6). Hardware vectoring later. |

## Phase 0: Specification and golden model (software only)

Goal: a software implementation of Thumb-V that runs real Thumb code correctly, both on its own and called from RISC-V, plus the data to choose a flags strategy.

**0.1 Repo skeleton and toolchains**
- Directory layout (see below), `Makefile` or `justfile`, CI running the model tests.
- Tools: `arm-none-eabi-gcc` (`-mcpu=cortex-m0 -mthumb`), `riscv32`/`riscv64-unknown-elf-gcc`, Python 3 with `unicorn` and `capstone`, Verilator, and later cocotb.

**0.2 ISA coverage document: `docs/isa-coverage.md`**
- One row per ARMv6-M encoding (83 rows, from the ARMv6-M Architecture Reference Manual). Done; open questions Q1–Q7 there feed into 0.3 and Phase 1.3.
- Columns: encoding, semantics, flags read and written, RV32 expansion (op count), special cases (PC, SP, rd = rn …), behaviour in mixed vs ARM-only mode, status (modelled / RTL / verified).

**0.3 Expansion model: `model/thumbv/expander.py`** (done)
- Pure function: `expand(hw1, hw2, pc, options) -> Expansion(ops, length)`. The last op is the last of the sequence; `length` is the PC advance.
- Emits real RV32 machine code, not an IR, so RTL comparison is bit-exact. The encoders in `rv32.py` are checked against the GNU assembler.
- All 83 encodings, with flags strategy A (each flag as 0/1 in its own register). B and C can be added as switchable variants for measurement.
- Uses no custom micro-ops so far. Any that are added later (e.g. branch-on-NZCV for strategy C, the ARM-shift op from Q3) get encodings in the `custom-0`/`custom-1` opcode space and are documented in `docs/microops.md`.
- Expansion rules and measured op counts are in `docs/isa-coverage.md`.

**0.4 Executor and lockstep harness: `model/thumbv/machine.py`, `model/thumbv/lockstep.py`** (done)
- A minimal RV32IM interpreter that runs native RISC-V code directly and Thumb code through the expander, choosing by the fetch address against the programmable regions. Every op in a Thumb sequence executes with `pc` = the Thumb address.
- Single-instruction lockstep (`tests/test_lockstep_single.py`): 300 random instances of each encoding run in Unicorn and in the model, comparing registers, flags, next PC, RAM and PRIMASK.
- Program lockstep (`tests/test_lockstep_programs.py`, also `python -m thumbv.lockstep`), for Thumb-only and mixed programs alike. The reference is a hybrid: Unicorn runs Thumb code as a Cortex-M0, and a second RV32 executor runs RISC-V code on Unicorn's memory, with ARM registers handed over through the D2 mapping at each switch between instruction sets. This replaces the planned per-call comparison for mixed programs with a per-instruction one, including callbacks from Thumb into RISC-V.
  - After every step it compares the PC, r0–r14, NZCV (after Thumb instructions), the memory writes of that step, and the RISC-V registers Thumb code must preserve (gp, tp, s8–s11). Memory is compared in full at the end. The first divergence is reported with disassembly, the expansion, and the preceding instructions.
  - Where Thumb-V deliberately differs from a Cortex-M, the reference is adjusted: a `BX`/`BLX`/`POP {pc}` to an even RISC-V address gets bit 0 set for that instruction (Q1), and on entry to Thumb code from RISC-V the reference adopts the model's flags (they are UNKNOWN after a call under AAPCS).
- Test programs: a Thumb-only C self-test (21,100 Thumb instructions, including 27 libgcc helpers: division, 64-bit shifts and multiply, soft-float, switch tables) and a mixed program (RISC-V `main` calling a Thumb library, with a callback into RISC-V; 20 switches between instruction sets). Both match the reference throughout.
- First data point for D1: the self-test executes 5.4 RV32 ops per Thumb instruction under strategy A.

**0.5 Test corpus: `tests/`** (done)

Everything below runs in program lockstep unless noted, and all of it passes.

- Directed (`tests/gen_directed.py`, `test_directed.py`): generated programs per instruction class with edge-case operands: all ALU ops over 15 edge values pairwise with varied carry-in, immediate and register shifts by 0/31/32/33/255/256 and more, every condition code against all 16 flag states, sign/zero-extending loads at every offset, push/pop/LDM/STM including the base-in-list cases, high registers and PC reads at both alignments, `ADD pc`/`MOV pc`/`BX`/`BLX`, byte reversal and extends, `MRS`/`MSR`. About 20,000 instructions.
- Random (`tests/gen_random.py`, `test_random.py`): random instruction sequences whose state carries over (flags into `ADCS`/`SBCS` and branches, loads of earlier stores), with forward branches, push/pop pairs, LDM/STM and calls. 20 programs by default, 500 more with `--slow` (about 160,000 instructions).
- Real code (`test_benchmarks.py`), built with newlib and libgcc for Cortex-M0:
  - CoreMark (submodule, port in `tests/bench/coremark/`): one iteration with the standard performance seeds, 423,292 Thumb instructions; CoreMark's own CRC checks pass ("Correct operation validated"). Model-only by default, full lockstep with `--slow`.
  - Embench IoT (submodule, run once each by setting `LOCAL_SCALE_FACTOR` to 1): all 19 benchmarks verify. The 4 smallest run in lockstep by default; the 11 mid-sized ones in lockstep and the 4 largest (0.7–4.3 million instructions) model-only with `--slow`.
- Interworking (`tests/c/interwork_*.c`): RISC-V calling Thumb with 0–4 arguments, narrow types, pointers into the other side's data, a struct array, 64-bit results, a 4-argument callback into RISC-V, and recursion alternating between the instruction sets. Signatures that differ between the ABIs (5+ arguments, misaligned 64-bit arguments, structs by value) need thunks and move to 0.6.
- ABI check (`test_mixed_matches_native`): each mixed program must give the same result as the same sources built all-RISC-V. The lockstep can't catch an ABI mismatch, because its reference hands registers over with the same mapping as the model; this check can, and it does flag a 5-argument call.

**0.6 Interworking prototype → `docs/interworking.md`** (done)
- Call rules, the jump-table layout and the build flow are in [interworking.md](interworking.md) (D8).
- `model/thumbv/interwork.py` (instead of the planned `tools/thunkgen`, so the build recipes can import it): parses an interface header (C prototypes tagged `THUMBV_THUMB`/`THUMBV_RISCV`), computes both ABIs' layouts, and generates RISC-V thunks only where they differ. `python -m thumbv.interwork header.h` reports how each function crosses.
- Thumb code calls RISC-V functions by name through a jump table at a fixed address, so the Thumb library is linked first and there's no circular dependency between the links.
- Checked by building the ABI test program three ways (mixed with thunks, all-RISC-V, all-Thumb) and requiring equal results, by program lockstep of the mixed build, and by a mutant layout.

**0.7 Measurement → `docs/flags-decision.md`** (done)
- `model/thumbv/measure.py` (`make measure`) traces CoreMark, all of Embench and a soft-float workload (`tests/bench/float/`) in the model. It follows every flag write to its reads, and costs strategies A, A with a k-instruction lookahead, A with perfect dead-flag elimination, B and C (plus fusion and the ARM-shift micro-op) from the trace.
- Results: 71% of flag-setting instructions have no flag read; strategy A spends 69% of its ops on flags; C costs 1.25 ops per Thumb instruction against A's 3.92. 90% of `B<cond>` are fusable with the preceding `CMP`. No `BL` needs the long form. Register shifts are 0.9% of instructions (up to 8.5% in SHA-256), 95% of them in integer code.
- Decided: D1 = C (plain hardware NZCV unit), Q3 = no micro-op for now. See [flags-decision.md](flags-decision.md).

**Phase 0 closed (2026-10-31):** all exit criteria are met.

**Exit criteria:** every ARMv6-M instruction is modelled; directed and random tests pass lockstep against Unicorn; CoreMark built for Cortex-M0 completes with the correct CRC; a RISC-V program calls Thumb library functions (and is called back) correctly in the model; D1 and D8 are decided.

## Phase 1: Core bring-up and code-reading spike

Goal: an unmodified RISC-V core running in Verilator and on the CYC1000, and a precise map of where the patches go.

**1.1 Build the core.** (done) VexRiscv generated from SpinalHDL in a fixed configuration: RV32IMC, machine mode only, no MMU, simple instruction bus or a small I-cache. Pin the VexRiscv commit as a git submodule.
- VexRiscv pinned at `baf7dc82` (SpinalHDL 1.13.0). The configuration is `rtl/core/` ([core.md](core.md)): RV32IMC, machine mode, no MMU or caches, simple buses, traps for illegal instructions, misaligned accesses and `ecall`/`ebreak` like the model.
- `make core` generates `build/rtl/VexRiscv.v` and lints it with Verilator; CI runs it.

**1.2 Simulation SoC.** (done) A Verilator testbench with on-chip RAM, a UART model and a RISC-V hello world. Add an instruction-retire trace port (VexRiscv's RVFI-style/formal hooks) so later phases can lockstep against the model.
- `rtl/soc/` ([soc.md](soc.md)): code RAM at 0, data RAM at `0x2000_0000`, a UART transmitter and LEDs, with the model's memory map so the same ELF files run on both. `sim/tb.sv` is an all-SystemVerilog testbench (`verilator --binary --timing`) that decodes the UART line and logs the RVFI trace.
- `thumbv.rtlsim` replays the trace against the model: PC, instruction, register write and stored bytes for every retired instruction. Hello world and the all-RISC-V builds of the interworking programs match the model (CPI 1.4–1.7 without the UART polling). `make test-rtl`, also in CI.

**1.3 Code-reading spike → `docs/vexriscv-notes.md`.** (done) Find and document:
- The RVC decompressor and halfword aligner (`IBusFetcherImpl` / `RvcDecompressor`), and how the instruction length is decided.
- How each instruction's PC travels with it, and confirm that emitting N ops with the same PC payload (stalling the input stream) gives PC-hold behaviour with no other changes.
- Link-value calculation (`BranchPlugin`: `pc + (isRvc ? 2 : 4)`).
- Where interrupts are sampled and how to gate them on a last-of-sequence bit.
- How to add CSRs (Thumb region registers, later NZCV) through the CSR plugin.
- How external interrupts reach the core (single line, or VexRiscv's interrupt-array plugin) and what hardware vectoring would take.
- Settle D4 and D5 from this.
- Done ([vexriscv-notes.md](vexriscv-notes.md)), confirmed by a simulation spike that ran 4-op sequences held at one PC, one op per cycle, with correct register reads, bypassing and flushes:
  - **Expander:** sits in the fetcher's injector, before decode.
  - **PC-hold:** decode's PC is its own register, and the fetcher's existing `injectedDecode` flag stops it advancing.
  - **Register file reads:** the synchronous register file's anticipated read address must be the next op's.
  - **Link value (Q2):** `pc + (IS_RVC ? 2 : 4)`, answered.
  - **Interrupt gating:** through the existing `InterruptionInhibitor` service.
  - **CSRs:** added through `CsrInterface`.
  - **Vectoring:** up to 16 hardware-vectored interrupts with stock plugins.

**1.4 Board bring-up.** (done) Quartus Prime Lite project for the 10CL025, programmed with `openFPGALoader` (which supports the CYC1000's on-board Arrow USB Blaster). LED blinky plus UART hello from the same binary as in simulation. Record a resource and Fmax baseline (LEs, M9Ks, MHz) in `docs/resources.md`.
- `rtl/board/` and `make board` ([board.md](board.md)): hello world and a blinky run on the CYC1000 at 12 MHz, from the same ELF files as in simulation. The board's RAMs (32 KiB code, 16 KiB data) alias through the simulation's memory regions, and `rtlsim --board` simulates that configuration.
- Baseline ([resources.md](resources.md)): 2,966 LEs (12%), 50 of 66 M9K, 8 multipliers, Fmax 50.5 MHz.
- **Lessons:**
  - openFPGALoader must load the SVF, not the RBF.
  - Its exit status can't be trusted.
  - The FT2232H needs a moment between loads.

**Exit criteria:** the same RISC-V binary runs in Verilator and on the board; the patch points are documented; LE/Fmax baseline recorded.

## Phase 2: Mode switch and single-op expander

Goal: a RISC-V program calls its first Thumb function in hardware.

1. Thumb region CSRs and address-range mode select in the fetch stage, plus the Thumb length rule in the aligner. (done)
   - VexRiscv's fetcher is copied into `rtl/core` (D5); the copy alone generates the stock core's Verilog. The Thumb changes are marked `THUMBV` ([core.md](core.md#thumb-v-changes)).
   - 2 region CSRs at `0x7C0`–`0x7C3`, in the RTL and the model.
   - A stub expander (`NOP`, `BX LR`, barriers) is enough for a RISC-V program to call Thumb code and return. That test covers 16- and 32-bit instructions at both alignments, a 32-bit instruction straddling two words, and entry at a halfword. It runs in lockstep with the model.
   - Unexpanded Thumb instructions trap at their own address.
   - Cost: 385 LEs.
2. Combinational expander for the 1:1 subset: loads and stores with immediate offset, hi-register `MOV`/`ADD`, SP-relative ops, `B`, `BX`, `BL`/`BLX`. Flag-setting instructions compute their result only; flags come in Phase 4. (done)
   - **The rule:** every instruction whose model expansion is a single op, bit for bit; the illegal instruction for the rest.
   - **"Results only" is in the model:** `Options(flags="none")`, checked against strategy A. Instructions that read the flags are illegal in that mode, so they trap instead of computing wrong values.
   - **Coverage:** 39,056 of the 63,488 16-bit halfwords ([core.md](core.md#thumb-v-changes)).
   - **In the core:** an assembled Thumb function of 82 single-op instructions, called from RISC-V, runs on the RTL in lockstep with the model.
   - **Cost:** about 600 LEs, and Fmax 42.8 MHz. The critical path is now code RAM → aligner → expander → register file read address, as predicted in the risks.
3. **Exhaustive equivalence test.** Drive all 65,536 halfwords (plus the 32-bit encodings), at both PC alignments, through the RTL expander and compare against `model/expander.py`. (done)
   - **16-bit:** all of the 16-bit space, with random second halfwords.
   - **32-bit:** about 518,000 instructions:
     - every first halfword with 16 random second halfwords;
     - every second halfword for the `BL`, barrier, `MSR`/`MRS` and undefined first halfwords;
     - `BL`'s range boundary.
   - **PC alignment:** the model is checked at both alignments, and single-op expansions don't depend on it.
   - **Speed:** 9 s, so it runs in every `make test` (`tests/test_expander_rtl.py`).
4. Integration test: a RISC-V `main` calls a Thumb function compiled by `arm-none-eabi-gcc` that uses only this subset (e.g. a memory copy or table lookup without conditional branches). The Thumb function calls back into a RISC-V function, and the result is printed over UART. Runs in Verilator against the model, then on the board. (done, without the callback)
   - **Scope change (decided before 2.4):** the callback moves to Phase 3. gcc saves LR with `PUSH`/`POP` in every Thumb function that calls another, even a tail call on Cortex-M0, and those are multi-op instructions. It also loads constants and table addresses from literal pools (`LDR` literal, two ops), and loops need conditional branches (flags).
   - **What 2.4 is now:** a gcc-compiled *leaf* Thumb function that works on its arguments, called from RISC-V, with the result printed over the UART, in Verilator against the model and on the board. It also brings in the shared memory layout for mixed programs on the board, and startup code that sets the Thumb region CSRs.
   - **Done:**
     - **Layout:** the Thumb library of mixed programs links at `0x1_4000`, so on the board it shares the 32 KiB code RAM with the RISC-V side.
     - **Startup code:** `crt_rv32.S` marks `0x1_4000`–`0x2_0000` as Thumb region 0.
     - **The program:** `tests/c/thumb_leaf.c` (two gcc-compiled functions, 20 Thumb instructions) is called from `thumb_leaf_main.c`, which prints the results. The test checks:
       - that every instruction gcc emitted is a single op;
       - the lockstep against the model;
       - the printed values against a Python version of the functions.
     - **On the board:** the same output, with `make board PROGRAM=leaf`.

**Exit criteria:** exhaustive expander check passes; the mixed call test (a leaf Thumb function, see 2.4) runs in simulation and on the board.

## Phase 3: Sequencer

Goal: every Thumb instruction that doesn't need the flags runs in hardware, however many RV32 ops it takes, and interrupts land only between Thumb instructions (D3). Still results only (`Options(flags="none")`). `ADCS`, `SBCS`, `B<cond>` and `MRS`/`MSR` of the APSR stay illegal until the flags unit (Phase 4).

**Design** (from the 1.3 spike, [vexriscv-notes.md](vexriscv-notes.md#holding-decode-the-sequencer)):
- **The expander becomes `expand(hw1, hw2, pc[1], step) → (op, last)`.** Expansions are at most 11 ops (`POP {r0-r7, pc}`, `REV`), so `step` is 4 bits.
- **The sequencer** sits in the fetcher's injector:
  - it holds the Thumb instruction in the injector register until its last op has gone into decode;
  - it sets `injectedDecode` on every op but the last, so all ops carry the Thumb instruction's PC (PC-hold);
  - it resets `step` when decode is flushed.
- **Timing: no new path from the code RAM.**
  - **Op 0:** stays expanded before the injector register, as now, so the register file's early read address for op 0 comes from the same path as today.
  - **Ops 1 and up:** come from the registered Thumb instruction in decode, and the early read address for op `step + 1` comes from the same register. Only the `rs1`/`rs2` fields of that second expansion are used, so synthesis prunes the rest.
- **Ready when empty:** the sequencer only holds while the injector register is valid. The stages pass `ready` straight through, and the spike deadlocked without this.
- **Interrupt gating:** `InterruptionInhibitor` while decode holds op 1 or later. An interrupt can then only halt decode at op 0, so `mepc` is always a Thumb instruction's address.
- **Faults partway through** an instruction restart it from op 0. Expansions must stay restartable: the base register or SP is updated last. A test checks every expansion for this.

**Steps:**
1. **Sequencer, PC-hold and the two-op instructions.** (done) The register-offset loads and stores, `LDR` (literal), `ADR`, `BICS`, `SXTH`/`SXTB`/`UXTH`, long `BL`, and `MOV`/`ADD`/`BX`/`BLX` with the PC. These are short, fixed sequences, enough to build and prove the sequencer on.
   - The lockstep compares Thumb code one op at a time: the RTL retires each op as its own record with the Thumb instruction's PC, and the model gains a per-op step to match.
   - The exhaustive check extends to whole sequences: the standalone expander gets `step` and `pc[1]` inputs, and every 16-bit instruction is compared op by op, `last` included, at both PC alignments.
   - **Done:**
     - The sequencer and PC-hold, as designed, in the fetcher's injector. Interrupt gating is in too; its test comes in step 4.
     - The 3.1 instructions pass the exhaustive check op by op, and op 0 never depends on the PC's alignment.
     - An assembled Thumb function of 3.1 instructions runs on the RTL in lockstep with the model, op by op. It covers `LDR` literal at both alignments, `ADR`, all eight register-offset loads and stores, `BICS`, the extends, the PC as an operand, and `ADD pc, rm`.
     - Cost: about 1,100 LEs (5,038 in all), Fmax 38.9 MHz. The expander in decode is now on the path into execute.
2. **Register lists:** `PUSH`, `POP` (including `POP {pc}`), `LDM`, `STM`. Op `k` needs the `k`-th register in the list, a priority encoder over the list with the first `k` registers masked. (done)
   - **Exhaustive check:** all four pass, op by op. The check now also requires an expansion's length not to depend on the PC's alignment.
   - **Restartability:** `tests/test_restartable.py` checks that every 16-bit expansion can restart from op 0 after a fault: no op before a load or store overwrites an input.
   - **In the core:** an assembled Thumb function runs in lockstep, with:
     - `PUSH {r4-r7, lr}` / `POP {r4-r7, pc}`;
     - a nested call with its own `PUSH`/`POP`;
     - `STM`/`LDM` with write-back, and `LDM` with its base in the list.
   - **Timing fix:** the sequencer now takes decode's op and `last` from registers. The new population counts had made `last` the critical path (31 MHz), through `decodeInput.ready` to the fetch PC. Now 33.9 MHz and 5,275 LEs.
3. **The rest:** the register shifts (5 ops each without flags), `REV`/`REV16`/`REVSH`, `MRS`/`MSR` of PRIMASK. (done)
   - **Coverage:** the RTL now expands every instruction exactly as the model does in result-only mode. The exhaustive check no longer has a list of what's implemented; everything must match.
   - **In the core:** an assembled Thumb function runs in lockstep, with all four register shifts at amounts 0, 1, 31, 32, 33 and 256, the three byte reversals, and PRIMASK through `MSR`, `MRS`, `CPSID` and `CPSIE`.
   - **A model fix the lockstep found:** `mstatus.MPP` now reads as machine mode (`0x1800`), as on VexRiscv, a machine-mode-only core.
   - **Cost:** 5,614 LEs, Fmax 33.3 MHz.
4. **Interrupts at Thumb boundaries.** (done)
   - **Interrupt source:** the testbench drives the core's timer interrupt from a plusarg schedule, in simulation only. The interrupt controller comes in Phase 5.
   - **Test:** a program with a trap handler that records `mepc` runs Thumb code under interrupts every few cycles. It must give the same result as without interrupts, and every recorded `mepc` must be the start of a Thumb instruction (or a RISC-V instruction).
   - **Done** (`test_interrupts_land_between_thumb_instructions`, three seeds):
     - **The interrupt source:** the SoC gained a timer interrupt input, and the testbench raises it every 1 to 29 cycles (`+irq`).
     - **The program:** the 3.1–3.3 Thumb functions run under about 500 interrupts per run, over 150 of them in Thumb code and over 30 in front of multi-op instructions.
     - **What's checked:**
       - the same result as without interrupts (that run is in lockstep with the model);
       - the instruction retired before each handler entry is never the interrupted one;
       - execution resumes at `mepc`.
     - **Negative control:** with the gating removed by hand, the program doesn't finish.
     - **Model:** it now stores the machine trap CSRs (`mtvec`, `mie`, `mepc`, ...) so that programs can set them up. It still takes no interrupts.
5. **Integration, the exit criterion moved from 2.4:** (done)
   - a gcc-compiled Thumb function calls back into a RISC-V function (`PUSH {r4, lr}` … `BL` … `POP {r4, pc}`);
   - plus a table lookup through a literal pool;
   - in Verilator against the model, then on the board.

   Loops still wait for Phase 4: gcc compiles them with conditional branches.
   - **The program:** `tests/c/callback.c` (Thumb) and `callback_main.c` (RISC-V) call each other through the interface header `callback.h`.
     - The Thumb side runs gcc's `PUSH {r4-r6, lr}` … `BL` (to the import table) … `POP {r4-r6, pc}`.
     - It reads a `const` table through a literal pool, with a register-offset `LDRB`.
     - It passes RISC-V a string from its own `.rodata` to print.
   - **Results:** it runs in lockstep with the model, with the UART text checked against values worked out by hand. `make board PROGRAM=callback` prints the same on the CYC1000.
   - **A layout bug it found:** the import table sat at `0x2_0000`, the core's reset vector, so with an interface header the core booted into the first import slot. The model starts at the ELF's entry point and never saw it, and no earlier RTL program had an import table. Now:
     - `0x2_0000` holds a jump to `_start` (`_reset`, which is also the ELF's entry point, so the model starts where the core does);
     - the import table follows at `0x2_0004`.

**Phase 3 is done** (2026-11-01). The RTL expands every instruction the model does in result-only mode. Interrupts land only between Thumb instructions. gcc-compiled Thumb code with calls in both directions runs in simulation and on the board. 5,614 LEs (23%), Fmax 33.3 MHz.

**Exit criteria:**
- The exhaustive check passes for whole sequences.
- The callback program runs in simulation and on the board.
- The interrupt test shows no interrupt inside a Thumb instruction.
- Resources and Fmax are logged.

## Phase 4: Flags

Goal: every Thumb instruction runs in hardware with its ARM flags, using the hardware NZCV unit decided in D1 ([flags-decision.md](flags-decision.md)). Ordinary gcc-compiled code with loops and conditions runs on the RTL and the board.

**Design** (from reading VexRiscv's `SrcPlugin`, `IntAluPlugin`, `FullBarrelShifterPlugin`, `BranchPlugin` and `CsrPlugin`):
- **Side-band, not new encodings.** Each expanded op carries a 4-bit flags kind and a 4-bit condition beside its 32-bit RV32 word, like `last`. RISC-V code always has kind 0. In the model, an op is an int with the side-band in bits 32–39, so expansions stay tuples of ints and the exhaustive check compares 40 bits. This replaces the `custom-0` micro-op idea in 0.3.

  | Kind | On | Effect |
  |---|---|---|
  | `NZ` | any ALU op | N, Z from the result |
  | `ADD`, `SUB` | `add`, `sub`, `addi` | the result is `rs1 + src2` or `rs1 - src2`; NZCV from the adder (C = NOT borrow for subtraction) |
  | `ADC`, `SBC` | `add`, `sub` | the same, with C as the carry-in |
  | `SHL`, `SHR` | `slli`, `srli`, `srai` | N, Z from the result; C = `rs1[-shamt mod 32]` or `rs1[shamt - 1 mod 32]` |
  | `CW` | any ALU op | if result bit 1 is set, C = result bit 0 (the register shifts' software C, which leaves C alone for an amount of 0) |
  | `BRANCH` | `beq x0, x0, off` | taken only if the condition holds on NZCV |

- **Where it plugs in:**
  - **Kind and condition:** decode inserts them from the sequencer, op 0's through the injector register like `last0`.
  - **The adder:** a Thumb-V copy of `SrcPlugin`, because the stock adder can't take a carry-in. Kinds `SUB` and `SBC` force subtraction, and `ADC` and `SBC` replace the constant carry-in with C. So `SUBS rd, rn, #imm` is `addi rd, rn, imm` with kind `SUB`, and no extra adder or result mux is needed. Nothing looks `SrcPlugin` up by class, so the copy is a drop-in.
  - **A new `ThumbFlagsPlugin`:**
    - holds NZCV;
    - computes the new flags in execute: from the adder's operand and result sign bits; from `SHIFT_RIGHT` for shifts (the shifter's result reaches the register file only in memory, but `SHIFT_RIGHT` exists in execute); from `REGFILE_WRITE_DATA` otherwise;
    - writes NZCV when execute fires;
    - overrides `BRANCH_DO` in execute for `BRANCH` ops (the stock stage mechanism allows that without a copy, as the shifter does for `REGFILE_WRITE_DATA`).
  - **NZCV as CSR `0x7C4`**, bits 31:28 like the APSR, for `MRS`/`MSR APSR` and later for interrupt entry and RTOS context switches. `CsrPlugin` also reads and writes in execute, and waits for the stages after it to drain.
- **No hazards:** every flag write and every flag read (`BRANCH`, the carry-in, the CSR) happens in execute. The pipeline is in order, so a reader in execute always sees the writes of all older instructions. `CMP` + `B<cond>` back to back runs without a stall.
- **`MULS`:** the product only exists in writeback, so `MULS` becomes `mul` then `addi rd, rd, 0` with kind `NZ`. That's one extra op, and all flag writes stay in execute.
- **Expansions under C:**
  - **One op:** `ADDS`, `SUBS`, `CMP`, `CMN`, `RSBS`, `ADCS`, `SBCS`, the logical ops, `MOVS`, `MVNS`, `TST`, the immediate shifts (except by 32), and `B<cond>`. Compares write `x0`.
  - **Two ops:** `MULS`, `BICS`, and `LSRS`/`ASRS` by 32 (C from bit 31 by `SHR` with shamt 0, then the result).
  - **Register shifts:** 11–13 ops. The 5-op result, the carry candidate in software, then a `CW` op (Q3).
  - **`MRS`/`MSR APSR`:** one CSR op each.
- **Restartability:** no load or store may follow a flag-writing op in an expansion. Otherwise a fault there would restart the instruction with its flag inputs already changed (`ADCS`). `tests/test_restartable.py` gains the rule.
- **Interrupts:** RISC-V code never writes NZCV, so a RISC-V handler interrupting Thumb code leaves it intact. Saving it around a Thumb handler is Phase 5.

**Steps:**
1. **Model: strategy C.** (done)
   - **The mode:** `Options(flags="C")`, with the side-band op format; `Machine` gains NZCV, the side-band semantics and CSR `0x7C4`.
   - **Checked:**
     - against strategy A for every 16-bit instruction, registers and flags, as `test_flags_none.py` does for results only;
     - the Phase 0 corpus in lockstep against Unicorn in mode C.
   - **Measurement:** `measure.py` costs C from the real expansions instead of the two assumptions in flags-decision.md, which is updated with the result.
   - **Done:**
     - **Model:** `Options(flags="C")` in the expander; `Machine` has NZCV, the side-band semantics and CSR `0x7C4`. The expansions are listed in [isa-coverage.md](isa-coverage.md#strategy-c-the-hardware-flags-unit). The longest is `ASRS` by a register, at 14 ops, within the sequencer's 16.
     - **Against strategy A:** `tests/test_flags_c.py` checks about 21,000 16-bit instructions (every one whose expansion differs), registers, PC and NZCV, plus `MRS`/`MSR APSR`.
     - **Against Unicorn:** every encoding in single-instruction lockstep (`test_lockstep_single.py`), and every program-level lockstep test, now in both modes. That covers directed, random, mixed and interworking programs, and with `--slow` CoreMark, Embench and the soft-float kernels.
     - **Restartability:** `test_restartable.py` checks that no load or store follows a flag write, in all three modes.
     - **Measurement:** C costed from real expansions is still 1.25 ops per Thumb instruction. Register shifts got cheaper (SHA-256 2.07 → 1.81), and `MULS` dearer (`edn` 1.25 → 1.37, 13% `MULS`).
2. **Flags unit and flag-setting instructions in the RTL.** (done)
   - **The pieces:** the side-band through the fetcher and decode, the `SrcPlugin` copy, `ThumbFlagsPlugin` with the CSR, and every flag-writing expansion.
   - **Checking the flags:** the trace gains NZCV after each op, piped to writeback beside the RVFI record, so the lockstep compares flags op by op.
   - **Interim mode:** until step 3, instructions that read the flags stay illegal.
   - **Exhaustive check:** extends to the side-band.
   - **Done:**
     - **The unit:** `ThumbFlagsPlugin` (NZCV, CSR `0x7C4`, flags computed in execute) and `ThumbSrcPlugin` (the `SrcPlugin` copy with forced subtraction and the carry-in), with the side-band through the fetcher and decode as designed ([core.md](core.md#thumb-v-changes)).
     - **Interim mode:** the model had `Options(flags="C", flag_readers=False)` as `rtlsim.HARDWARE`, removed again in 4.3.
     - **Exhaustive check:** passed first time with the 40-bit ops.
     - **Lockstep with flags:** the core's `thumbNzcv` output is logged with every retired op and compared with the model's NZCV. Its first run found a real bug: N and Z of a shift op with kind `NZ` (the last op of `ASRS` by a register) came from `REGFILE_WRITE_DATA`, which VexRiscv's shifter only fills in memory. They now come from `SHIFT_RIGHT` for any shift. The exhaustive check can't see this; only running the core can.
     - **Directed test:** `test_thumb_flag_writers` runs every flag writer on nine edge-case operand pairs, with all 27 flag-writing encodings executed. A deliberately wrong V in the RTL fails it.
     - **On the board:** the callback program still runs. 5,881 LEs (+267), Fmax 33.0 MHz.
3. **Instructions that read flags:** (done) `B<cond>` (all 14 conditions), `ADCS`/`SBCS`, `MRS`/`MSR APSR`. The RTL then expands exactly strategy C, and `rtlsim.HARDWARE` becomes `Options(flags="C")`. Directed assembly tests, in lockstep:
   - every condition taken and not taken;
   - carry chains through `ADCS`/`SBCS` (64-bit add and subtract);
   - flags across `MSR`/`MRS`.
   - **Done:**
     - **RTL:** `B<cond>` is `beq x0, x0` with kind `BRANCH`, whose `BRANCH_DO` the flags unit overrides in execute with the condition on NZCV, through VexRiscv's stage mechanism, with no change to `BranchPlugin`. `ADCS`/`SBCS` use the carry-in from 4.2, `MRS`/`MSR APSR` the CSR. `rtlsim.HARDWARE` is `Options(flags="C")`. The exhaustive check passed first time.
     - **Directed test:** `test_thumb_flag_readers` (`tests/c/rtl_thumb_readers.S`), in lockstep, and its result against ARM's definitions computed independently in Python:
       - all 14 conditions under all 16 NZCV values, taken and not, forward and backward;
       - 128-bit add and subtract (`ADDS` + 3 `ADCS`, `SUBS` + 3 `SBCS`) on 25 operand pairs, with the APSR read back by `MRS`;
       - `MSR`/`MRS` round trips.
     - **The oracle found its own bug,** not the core's: Z after an `ADCS` chain is the last word's, not the whole value's.
     - **Negative control:** a wrong HI condition in the RTL fails the test (wrong branch at the first HI).
     - **Cost:** 6,015 LEs (+134), Fmax 35.0 MHz; the board still runs the callback program.
4. **gcc code with loops and conditions.** (done)
   - **What runs:**
     - Phase 0 corpus programs, Thumb-only and mixed, on the RTL in lockstep;
     - the 3.4 interrupt test, rerun over a loop, so that interrupts land between `CMP` and `B<cond>`;
     - a program on the board (e.g. CRC or a sort, printing results).
   - **Resources and Fmax** are logged.
   - **Done:**
     - **Thumb-only programs on the RTL:** a boot stub (`rtlsim.thumb_boot`) marks a Thumb program's code as a region and jumps to it, and the testbench also stops on Thumb's `b .`. In lockstep with the model, op by op with NZCV:
       - the Phase 0 self-test;
       - CoreMark, one iteration: it validates its own results, read from the model's memory after the clean lockstep;
       - all 19 Embench benchmarks: each verifies its result; the four large ones, up to 5.4 million ops (`xgboost`), with `--slow`;
       - the soft-float kernels, with `--slow`.
     - **Mixed programs on the RTL:** the Phase 0 mixed, interworking and ABI (with thunks) programs, in lockstep.
     - **gcc loops** (`tests/c/loops.c`): CRC-32, a sort, binary search, GCD (libgcc division), 64-bit Fibonacci (`ADCS`) and dot product (libgcc multiplication), a chain of signed and unsigned comparisons, `strcmp`, an integer square root.
       - **Checks:** in lockstep on the RTL, and against Unicorn in the model, in both modes. Its checksum matches the same sources built all-RISC-V.
       - **On the board:** `make board PROGRAM=loops` prints the same as the simulation.
     - **Under interrupts:** the 3.4 test, over the loops, with three seeds. About 1,900 interrupts per run land in Thumb code, about 170 of them between a flag-setting instruction and its `B<cond>`. The results are unchanged, and every interrupt lands between instructions.
     - **Performance:** CoreMark runs at 1.15 RV32 ops and 1.85 cycles per Thumb instruction (423,292 instructions, 782,844 cycles). That is in simulation, with the zero-wait-state RAMs of the board.
     - **Resources:** unchanged from 4.3 (no RTL change): 6,015 LEs, Fmax 35.0 MHz.

**Phase 4 is done** (2026-11-01). The hardware flags unit runs every Thumb instruction with its flags. gcc-compiled code with loops and conditions, CoreMark and all of Embench run on the RTL in lockstep with the model; the gcc loops also run under interrupts and on the board. 6,015 LEs (24%), Fmax 35.0 MHz.

**Exit criteria:**
- The exhaustive check passes with the side-band.
- Corpus programs with loops run on the RTL in lockstep with the model, under interrupts.
- A loop-heavy program runs on the board.
- Resources and Fmax are logged.

## Phase 5: Interrupts and mixed execution in practice

Goal: interrupts and traps work across both instruction sets through one controller (D9) and one entry routine, and real software uses them: a Thumb interrupt handler from a Cortex-M-compiled object interrupting RISC-V code and the reverse, a prebuilt Cortex-M0 library called from RISC-V, and an RTOS running a Thumb task beside RISC-V tasks.

**Design** (from section 6, D9 and [vexriscv-notes.md](vexriscv-notes.md#external-interrupts-and-vectoring-d9)):
- **The controller** is a SoC block at the System Control Space, `0xE000_E000`, with the ARMv6-M programming model, so Cortex-M code drives it unmodified:
  - **NVIC:** 32 interrupts, `ISER`/`ICER`/`ISPR`/`ICPR` at `0xE000_E100`–`0xE000_E280`, and 4 priority levels (`IPR0`–`IPR7` at `0xE000_E400`, the top 2 bits of each byte).
  - **System exceptions:**
    - SysTick (exception 15), PendSV (14), with their priorities in `SHPR3`;
    - `ICSR` (`0xE000_ED04`): `PENDSVSET`/`PENDSVCLR`, `PENDSTSET`/`PENDSTCLR`, `VECTPENDING`.
  - **Software interrupts:** every pending bit is writable, so software interrupts, RISC-V's included, are just pended interrupts.
- **SysTick** is the standard ARMv6-M SysTick at `0xE000_E010` (`CSR`, `RVR`, `CVR`, `CALIB`), counting core clocks.
  - **A change from section 6:** no second, `mtime`/`mtimecmp` view of the same timer. In mixed mode every interrupt goes through the one controller, RISC-V code included, so a CLINT-style timer would be a second path that nothing needs. The core's own timer input is tied off.
- **To the core:** one line, the machine external interrupt (`mip.MEIP`, cause 11). It is raised while an enabled interrupt is pending above the current priority. No hardware vectoring yet: the entry routine dispatches.
- **Claim and complete:** with software entry there's no hardware exception entry to track which interrupt is active, so the controller adds two Thumb-V registers outside the SCS, at `0x1000_1000`:
  - **`CLAIM`** returns the number of the highest-priority pending interrupt above the current priority (0 if none), clears its pending bit and makes it active. Its priority becomes the current one, so only higher priorities can preempt.
  - **`COMPLETE`** ends the active one.
  - **Nesting:** active interrupts form a stack, at most 4 deep with 4 levels. Edge and level sources behave as on the NVIC: a level source still asserted when its handler completes pends again.
  - **Ties:** equal priorities resolve to the lowest number, as on Cortex-M.
- **The entry routine** (`firmware/`, RISC-V assembly and C) is `mtvec` for every trap.
  - **Interrupts** (cause 11):
    1. save the caller-saved registers, `mepc`, `mstatus` and NZCV (CSR `0x7C4`);
    2. `CLAIM`, re-enable interrupts so higher priorities can preempt;
    3. call the handler from a vector table of plain addresses (Thumb handlers return with `BX LR` into the routine);
    4. disable interrupts, `COMPLETE`, restore, `mret`.
  - **Synchronous traps:**
    - `ecall` is `SVC` if `mepc` is in a Thumb region, with the number from the instruction's low byte, resuming 2 bytes on; from RISC-V it resumes 4 bytes on;
    - `ebreak` (`BKPT`), illegal instructions and faults go to handlers that report and stop, for now.
  - Interrupts are still taken only between Thumb instructions (D3, Phase 3.4).
- **Verification:**
  - **The controller** is checked on its own against a Python model of its registers (`model/thumbv/nvic.py`), like the expander: random sequences of register reads and writes, interrupt lines, claims and completes, in a Verilator testbench.
  - **Whole programs:** the model takes traps and returns from them, so the lockstep covers interrupt-driven programs too. The model enters a trap where the RTL's trace jumps to `mtvec`, and reads the controller's registers as device inputs, as it does the UART's.

**Steps:**
1. **The model takes traps.** (done)
   - **Traps and `mret`:** synchronous traps go to `mtvec` with `mepc`, `mcause` and `mtval`, instead of stopping the run; `mret` returns.
   - **Asynchronous ones:** the RTL lockstep enters them where the RTL did. FormalPlugin doesn't flag interrupts (`rvfi_intr` is always 0), so this is where the trace reaches `mtvec` while the model expected another instruction, which must be an instruction boundary.
   - **Checks:** the 3.4 and 4.4 interrupt tests are replayed in full in lockstep, handler included.
   - **Done:**
     - **Model:** `Machine.take_trap`, `interrupt` and `mret`, with `mepc`, `mcause`, `mtval` and `mstatus` as VexRiscv sets them; `Machine(traps=True)` takes synchronous traps instead of stopping (`lockstep.simulate(..., traps=True)`). Instruction fetch faults are now `instruction_access_fault`.
     - **RTL lockstep:** where the trace reaches `mtvec` instead of the next op, the model tries that op on a snapshot. If it traps, the model takes the same trap; otherwise it rolls back and takes the interrupt, which must be at op 0 with `MIE` set.
     - **What it found:** `mstatus.MPP` on VexRiscv is cleared by `mret`, not hard-wired to 3 as the model had it since 3.3, and only MIE, MPIE and MPP exist. The first replay of an interrupt run diverged at an `MRS PRIMASK` after the first `mret`.
     - **Interrupt runs:** the 3.4 and 4.4 tests now replay their `+irq` runs in full, handler included, all three seeds each (about 2,000 interrupts per run).
     - **Synchronous traps:** `test_synchronous_traps` (`tests/c/trap_lib.S`, `trap_main.c`) traps from Thumb code (`SVC`, `BKPT`, `UDF`, `MRS MSP`, misaligned and faulting loads, a misaligned store, one load at op 1 of its expansion) and from RISC-V (`ecall`, `ebreak`). It resumes after each, in lockstep, and against the model running alone with traps. The handler's records (cause, `mepc`, `mtval`, the `SVC`/`BKPT` number) are checked against the architecture.
     - **Negative control:** a wrong `ecall` cause in the model diverges at the handler's `csrr mcause`.
2. **The controller and SysTick in the RTL**, in the SoC, driving the core's external interrupt.
   - **The testbench's `+irq`** drives interrupt lines of the controller instead of the core's timer input.
   - **Unit check:** `tests/test_nvic_rtl.py` against `model/thumbv/nvic.py`.
   - **Resources and Fmax** are logged, and the architecture diagram updated.
3. **The entry routine and trap handler** (`firmware/`), with a small C API (vector table, enable, priority, pend).
   - **Tests on the RTL, in lockstep:**
     - a SysTick handler compiled for Cortex-M0 (Thumb) interrupting RISC-V code, and a RISC-V handler interrupting Thumb code, NZCV preserved;
     - preemption by priority, with pended software interrupts;
     - PendSV;
     - `SVC` from Thumb and `ecall` from RISC-V, with their numbers;
     - a `BKPT` and a fault reported.
   - **Latency** (interrupt line to the handler's first instruction) is measured against the Cortex-M0's 16 cycles.
   - **On the board:** a SysTick-driven Thumb handler blinks the LEDs and counts over the UART.
4. **A prebuilt Cortex-M0 library from RISC-V.**
   - **The library:** built separately as a Cortex-M0 static library and used only as a binary with its header, through the Phase 0 thunk generator and build flow ([interworking.md](interworking.md)). Candidate: CMSIS-DSP (Apache-2.0), chosen at the start of the step.
   - **Checked:** its results against the same functions compiled for RISC-V, in lockstep on the RTL and on the board.
5. **An RTOS with a Thumb task.**
   - **The RTOS:** FreeRTOS (MIT), RISC-V port, ticked by SysTick through the controller.
   - **The context switch** also saves NZCV, so a Thumb task can be preempted between a compare and its branch.
   - **The tasks:** one Thumb task (compiled for Cortex-M0) and RISC-V tasks, exchanging data through a queue.
   - **Checked:** on the RTL, then on the board.

**Exit criteria:**
- The controller matches its model.
- Thumb and RISC-V handlers interrupt each other's code on the RTL in lockstep and on the board.
- The prebuilt library gives the same results as its RISC-V build.
- The RTOS runs a Thumb task beside RISC-V tasks on the board.
- Latency, resources and Fmax are logged.

## Later phases (outline)

Each will get its own detailed section when it starts.
- **Phase 6: ARM-only mode.** Cortex-M exception emulation on top of the Phase 5 controller and entry path: the stacked frame, EXC_RETURN, MSP/PSP banking, PendSV, ARM fault escalation, an SCB subset and a GPIO shim on the LEDs. Milestone: an unmodified Cortex-M0 blinky ELF runs on the board.
- **Phase 7: performance and scale.** SDRAM controller, CoreMark on the board, Zbb for `REV`/`UXT*`/`ROR`, and comparison against the Phase 0 model's predicted ratio. If needed, the options left open by D1: the ARM-shift micro-op and fused `CMP` + `B<cond>`.

## Proposed repository layout

```
docs/          plan, ISA coverage, interworking, decisions, core notes, resource log
model/         Python expansion model, RV32 executor, lockstep harness
tools/         thunk generator, image-combining build tools
tests/
  asm/         directed Thumb tests
  random/      random sequence generator
  bench/       CoreMark / Embench builds for Cortex-M0
  interwork/   RISC-V ↔ Thumb call tests
firmware/      shared trap entry routine, ARM-only exception firmware (C + startup asm)
rtl/           expander, flags unit, region CSRs, interrupt controller, timer, SoC wrapper, peripheral shim
third_party/   VexRiscv, CoreMark, Embench (submodules)
sim/           Verilator testbenches
fpga/cyc1000/  Quartus project, pin constraints
```

## Risks

| Risk | Mitigation |
|---|---|
| Flag overhead makes the "near-native" goal unreachable without core changes | Measure in Phase 0, and be ready to do hardware NZCV early |
| VexRiscv's fetch pipeline is harder to patch than expected | Phase 1.3 spike before any RTL; NEORV32 fallback |
| The expander lengthens the fetch→decode critical path and lowers Fmax on Cyclone 10 LP | Track Fmax from Phase 1; register the expander output if needed (one extra pipeline stage) |
| 25K LEs is tight once the SDRAM controller, peripheral shim and I-cache are added | Resource log from Phase 1; keep the shim minimal |
| The interworking build flow gets complicated (two linkers, relocations across images) | Prototype it in Phase 0 against the model before any hardware depends on it; keep the jump-table approach simple |
| Interrupt latency: a software entry routine saving registers is slower than Cortex-M's hardware stacking (16 cycles on an M0) | Measure in Phase 5; hardware vectoring or hardware register stacking if it matters |
| Subtle ARMv6-M semantics (exceptions, SP banking, unaligned faults) | Lockstep against Unicorn on every test; the ISA coverage doc as the checklist |

## Immediate next actions

Done: 0.1 (repo and toolchains), 0.2 (ISA coverage), 0.3 (expander), 0.4 (executor and lockstep), 0.5 (test corpus), 0.6 (interworking), 0.7 (measurements).

Phase 0 is closed. Phase 1 is done: 1.1 (core generated), 1.2 (simulation SoC and RTL lockstep), 1.3 (code-reading spike, [vexriscv-notes.md](vexriscv-notes.md)), 1.4 (board bring-up, [board.md](board.md)). Phase 2 is done: 2.1 (mode switch in fetch), 2.2 (single-op expander), 2.3 (exhaustive check), 2.4 (RISC-V calls gcc-compiled Thumb code, in simulation and on the board). Phase 3 is done: 3.1–3.3 (the sequencer and every multi-op expansion), 3.4 (interrupts at Thumb boundaries), 3.5 (calls in both directions, in simulation and on the board). Phase 4: 4.1 (strategy C in the model), 4.2 (the flags unit and flag writers in the RTL), 4.3 (the flag readers: the RTL is now all of strategy C), 4.4 (gcc code with loops, CoreMark and Embench on the RTL; loops on the board). Phase 5: 5.1 (the model takes traps; the RTL lockstep follows the core into them).

1. Phase 5, step 2: the controller (NVIC programming model) and SysTick in the RTL.
