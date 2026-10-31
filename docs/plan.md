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

Build flow (to be worked out in `docs/interworking.md`): the two halves can't be linked by one linker because they are different ELF machine types. Proposed approach:
1. Link the Thumb part with `arm-none-eabi-ld` at a fixed address inside a Thumb region. Its imports (calls into RISC-V) go through a jump table at a known address.
2. A tool reads both symbol tables, generates RISC-V-side stubs for the Thumb exports and fills the Thumb image's import table.
3. The Thumb image is included in the final RISC-V ELF as a binary section.

### 4. Flags: fusion alone isn't safe, which argues for doing the hardware flags unit early

`CMP` + `B<cond>` fusion only removes flag computation if nothing reads the flags afterwards. After a branch, a one-instruction lookahead can't see the code that runs next, and the code at both the target and the fall-through may legally read the flags set by the `CMP`. So a fused branch still has to leave NZCV recoverable.

| Strategy | Cost per flag-setting op | Core change | Notes |
|---|---|---|---|
| A. Eager software flags | +3–6 RV ops (C and V are the costly ones) | none | Simplest and slowest. A good correctness baseline. |
| B. Lazy flags (QEMU-style) | +1–2 ops: record op kind, result and operands in reserved registers | none | N/Z branches become `blt`/`beq` on the saved result. C/V are computed on demand. |
| C. Hardware NZCV unit | +0 | ALU tap, a 4-bit register, a branch-on-condition micro-op | Fusion and dead-flag lookahead become unnecessary. |

A and B both make the expander more complicated (lookahead buffers, fusion logic, sequences for every ADDS/SUBS), and that work is thrown away once C exists. **Recommendation:** implement A in the software model only, as the reference. Use the Phase 0 measurements to decide whether the RTL goes straight to C. With C, NZCV is a CSR that an RTOS saves on a context switch away from a Thumb task.

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
| D1 | Flags strategy for the RTL | Open: decide after Phase 0 measurements, leaning towards hardware NZCV (C) |
| D2 | Register mapping | **Decided:** ABI-aligned mapping (section 1) |
| D3 | When interrupts are taken | **Decided:** Thumb instruction boundaries only (section 6) |
| D4 | Base core | Proposed: VexRiscv, confirmed by the Phase 1 code-reading spike. VexiiRiscv is the newer successor and worth a look. NEORV32 is the fallback. |
| D5 | Where the expander lives | Proposed: a VexRiscv plugin or patch in SpinalHDL, since it must sit inside the fetch pipeline. Decide in Phase 1.3. |
| D6 | SoC wrapper | Proposed: a minimal hand-written SoC around the core. LiteX for a first board smoke test only. |
| D7 | Mode selection | **Decided:** programmable Thumb address regions (section 2). Number of regions and the CSR layout still open. |
| D8 | Interworking build flow | Open: work out in `docs/interworking.md` during Phase 0 (section 3) |
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

**0.5 Test corpus: `tests/`**
- Directed: one small assembly test per instruction class, including flag edge cases (`0x7FFFFFFF + 1`, `0 - 1`, `SBCS` with carry in/out, shifts by 0, 32 and >32).
- Random: a generator for random straight-line Thumb sequences with valid memory operands.
- Real code: CoreMark and a few Embench programs built for Cortex-M0.
- Interworking: a RISC-V `main` calling Thumb functions with various signatures (0–8 arguments, 64-bit arguments, struct return, callbacks into RISC-V).

**0.6 Interworking prototype → `docs/interworking.md`**
- Write down the call rules, the jump-table layout and the build flow (D8).
- A first thunk generator, `tools/thunkgen`, driven by C prototypes, exercised by the interworking tests in the model.

**0.7 Measurement**
- Dynamic expansion ratio (RV ops retired per Thumb instruction retired) for CoreMark/Embench under strategies A, B and C. Also: how often flags are dead, how often `CMP`+`B<cond>` is fusable, how often `BL` exceeds ±1 MiB, and how often register shifts run, split into integer and soft-float code (Q3).
- Write the results and the D1 decision into `docs/flags-decision.md`.

**Exit criteria:** every ARMv6-M instruction is modelled; directed and random tests pass lockstep against Unicorn; CoreMark built for Cortex-M0 completes with the correct CRC; a RISC-V program calls Thumb library functions (and is called back) correctly in the model; D1 and D8 are decided.

## Phase 1: Core bring-up and code-reading spike

Goal: an unmodified RISC-V core running in Verilator and on the CYC1000, and a precise map of where the patches go.

**1.1 Build the core.** VexRiscv generated from SpinalHDL in a fixed configuration: RV32IMC, machine mode only, no MMU, simple instruction bus or a small I-cache. Pin the VexRiscv commit as a git submodule.

**1.2 Simulation SoC.** A Verilator testbench with on-chip RAM, a UART model and a RISC-V hello world. Add an instruction-retire trace port (VexRiscv's RVFI-style/formal hooks) so later phases can lockstep against the model.

**1.3 Code-reading spike → `docs/vexriscv-notes.md`.** Find and document:
- The RVC decompressor and halfword aligner (`IBusFetcherImpl` / `RvcDecompressor`), and how the instruction length is decided.
- How each instruction's PC travels with it, and confirm that emitting N ops with the same PC payload (stalling the input stream) gives PC-hold behaviour with no other changes.
- Link-value calculation (`BranchPlugin`: `pc + (isRvc ? 2 : 4)`).
- Where interrupts are sampled and how to gate them on a last-of-sequence bit.
- How to add CSRs (Thumb region registers, later NZCV) through the CSR plugin.
- How external interrupts reach the core (single line, or VexRiscv's interrupt-array plugin) and what hardware vectoring would take.
- Settle D4 and D5 from this.

**1.4 Board bring-up.** Quartus Prime Lite project for the 10CL025, programmed with `openFPGALoader` (which supports the CYC1000's on-board Arrow USB Blaster). LED blinky plus UART hello from the same binary as in simulation. Record a resource and Fmax baseline (LEs, M9Ks, MHz) in `docs/resources.md`. If 0.7 shows register shifts are frequent, also synthesise the ARM-shift micro-op variant of the shifter and record its LE and Fmax cost (Q3).

**Exit criteria:** the same RISC-V binary runs in Verilator and on the board; the patch points are documented; LE/Fmax baseline recorded.

## Phase 2: Mode switch and single-op expander

Goal: a RISC-V program calls its first Thumb function in hardware.

1. Thumb region CSRs and address-range mode select in the fetch stage, plus the Thumb length rule in the aligner.
2. Combinational expander for the 1:1 subset: loads and stores with immediate offset, hi-register `MOV`/`ADD`, SP-relative ops, `B`, `BX`, `BL`/`BLX`. Flag-setting instructions compute their result only; flags come in Phase 4.
3. **Exhaustive equivalence test.** Drive all 65,536 halfwords (plus the 32-bit encodings), at both PC alignments, through the RTL expander and compare against `model/expander.py`.
4. Integration test: a RISC-V `main` calls a Thumb function compiled by `arm-none-eabi-gcc` that uses only this subset (e.g. a memory copy or table lookup without conditional branches). The Thumb function calls back into a RISC-V function, and the result is printed over UART. Runs in Verilator against the model, then on the board.

**Exit criteria:** exhaustive expander check passes; the mixed call test runs in simulation and on the board.

## Later phases (outline)

Each will get its own detailed section once Phase 2 is done.

- **Phase 3: sequencer.** Multi-op expansions (`PUSH`/`POP`/`LDM`/`STM`, register-offset loads, long `BL`, register shifts, `REV`, `ADCS`/`SBCS`), the last-of-sequence bit and boundary-only interrupt gating.
- **Phase 4: flags,** using the strategy chosen in D1. If it is hardware NZCV, this replaces the README's phases 4 and 6.
- **Phase 5: interrupts and mixed execution in practice.**
  - The unified controller (NVIC programming model) and the shared timer (SysTick / `mtime` views) in RTL, verified in simulation against a model of the controller.
  - The shared RISC-V entry routine and synchronous trap handler (`SVC`/`ecall` from either instruction set). Milestone: a timer interrupt handled by a Thumb ISR from a Cortex-M-compiled object, interrupting RISC-V code, and the reverse.
  - The thunk generator and build flow from Phase 0 applied to a real ARM-only library (e.g. a prebuilt Cortex-M0 DSP or crypto library) called from RISC-V.
  - An RTOS (FreeRTOS or Zephyr) with a Thumb task alongside native tasks, including NZCV in the context switch.
- **Phase 6: ARM-only mode.** Cortex-M exception emulation on top of the Phase 5 controller and entry path: the stacked frame, EXC_RETURN, MSP/PSP banking, PendSV, ARM fault escalation, an SCB subset and a GPIO shim on the LEDs. Milestone: an unmodified Cortex-M0 blinky ELF runs on the board.
- **Phase 7: performance and scale.** SDRAM controller, CoreMark on the board, Zbb for `REV`/`UXT*`/`ROR`, and comparison against the Phase 0 model's predicted ratio.

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
third_party/   VexRiscv (submodule)
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

Done: 0.1 (repo and toolchains), 0.2 (ISA coverage), 0.3 (expander), 0.4 (executor and lockstep).

1. Test corpus (0.5): directed tests, random instruction sequences, CoreMark and Embench. Larger C programs will need a C library (newlib for ARM, picolibc for RISC-V).
2. Interworking prototype (0.6): the build flow and thunks for signatures that differ between the ABIs. The test fixture `build_mixed` is a first, minimal version of the build flow.
3. Measurements (0.7).
