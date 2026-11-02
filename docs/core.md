# The base core

Thumb-V is VexRiscv (decision D4), generated from SpinalHDL in a fixed configuration, with its instruction fetcher replaced by a Thumb-V copy (D5) and Thumb-V's own plugins added. That means the Thumb region CSRs, mode select and the Thumb length rule (Phase 2.1), the expander (2.2–3.3), the sequencer (3.1) and the flags unit (4.2, with its readers in 4.3). See [Thumb-V changes](#thumb-v-changes), and [architecture.md](architecture.md) for block diagrams.

- **Source:** `rtl/core/src/main/scala/thumbv/Core.scala`, an sbt project that depends on the VexRiscv submodule (`third_party/VexRiscv`, pinned at `baf7dc82`).
- **Output:** `make core` writes `build/rtl/VexRiscv.v`, one Verilog file of about 5,000 lines. Generated files aren't committed: regenerate them with `make core`.

## Configuration

VexRiscv is built from plugins. The choices, and why:

| Plugin | Setting | Why |
|---|---|---|
| `ThumbIBusSimplePlugin` (a copy of `IBusSimplePlugin`) | RVC on (`compressedGen`), no branch prediction, access faults trapped | The Thumb expander goes where the RVC decompressor sits, and Thumb shares RVC's 2-byte fetch granularity (plan section 1). No I-cache for now. |
| `DBusSimplePlugin` | misaligned and access faults trapped | The model traps on misaligned accesses, as ARMv6-M faults on them. |
| `CsrPlugin` | machine mode only; `mstatus`, `mtvec`, `mepc`, `mcause`, `mtval`, `mscratch` read-write; `ecall`, `ebreak`, `wfi` | Thumb `SVC`/`BKPT` become `ecall`/`ebreak`, `CPSID`/`CPSIE` toggle `mstatus.MIE` (PRIMASK), and the trap handler needs all of these. `misa` reads RV32IMC. |
| `DecoderSimplePlugin` | illegal instructions trapped | The expander emits an illegal instruction for `UDF` and unhandled `MRS`/`MSR`, and the trap handler emulates them (Q7). |
| `RegFilePlugin` | synchronous read | Maps to M9K block RAM on the Cyclone 10 LP. |
| `IntAluPlugin` | standard | |
| `ThumbSrcPlugin` (a copy of `SrcPlugin`) | adder in execute | Thumb-V's: the flags kinds force subtraction and take C as the carry-in (below) |
| `FullBarrelShifterPlugin` | one-cycle shifts | Shifts are common in expansions (flags, register shifts). |
| `MulPlugin` | one-cycle-throughput multiplier | The 10CL025 has 66 18×18 multipliers; `MULS` is 1:1. |
| `DivPlugin` | iterative, 1 bit per cycle | ARMv6-M has no divide; only RISC-V code uses it. |
| `HazardSimplePlugin` | full bypassing | Expansions are long chains of dependent ops. |
| `BranchPlugin` | branches resolved in execute, misaligned targets trapped, `fence.i` as a jump | With no I-cache, Thumb `ISB` (`fence.i`) only needs a refetch. |
| `ThumbRegionPlugin` | 2 regions, CSRs `0x7C0`–`0x7C3` | Thumb-V's: see below |
| `ThumbFlagsPlugin` | NZCV, CSR `0x7C4` | Thumb-V's flags unit (D1): see below |
| `FormalPlugin` | RVFI retire trace | Lockstep against the model in simulation ([soc.md](soc.md)). |

Reset vector `0x0002_0000`, where `tests/link/rv32.ld` puts `_start` (see [soc.md](soc.md)). Trap vector `0x0000_0020` is a placeholder until there is a trap handler; programs can set `mtvec` themselves. Both are parameters of `Core()`.

The core also has an RVFI retire trace port (`FormalPlugin`), which the simulation testbench logs to lockstep the core against the model. The SoC leaves it unconnected, so synthesis prunes it.

## Thumb-V changes

**The fetcher (D5).** `rtl/core/src/main/scala/thumbv/ThumbFetcher.scala` and `ThumbIBusSimplePlugin.scala` are copies of VexRiscv's `Fetcher.scala` and `IBusSimplePlugin` class at the pinned commit. The first commit of the copy generated the same Verilog as the stock core, apart from names. Every change since is marked `THUMBV`, so the changes are:
```sh
diff third_party/VexRiscv/src/main/scala/vexriscv/plugin/Fetcher.scala rtl/core/src/main/scala/thumbv/ThumbFetcher.scala
```
In the decompressor ([vexriscv-notes.md](vexriscv-notes.md#instruction-length-and-the-aligner)):
- **Mode:** the fetch word's address decides Thumb or RISC-V (`ThumbRegionPlugin.inThumb`).
- **Length:** in Thumb mode, the instruction length comes from the Thumb rule (`Thumb.is32`: the first halfword's bits 15:11 are `11101`, `11110` or `11111`) instead of bits 1:0. "RVC" in the fetcher means 16-bit in either instruction set.
- **Expansion:** Thumb instructions go through `Thumb.expand` instead of the RVC decompressor, for op 0 only. The decode stage's `IS_RVC` is set for 16-bit Thumb instructions, so the PC and link values advance by 2, or by 4 for 32-bit ones. The raw instruction, a Thumb flag and op 0's flags side-band travel on with op 0 (`FetchRsp.raw`, `FetchRsp.thumb`, `FetchRsp.side0`).

In the injector, the sequencer (Phase 3.1, [vexriscv-notes.md](vexriscv-notes.md#holding-decode-the-sequencer)):
- **Holding the instruction:** it holds a Thumb instruction in the injector register until its last op has gone into decode, by gating `decodeInput.ready` with `last`.
- **Which op:** `step` counts the ops.
  - **Op 0:** decode takes it, and whether it's the last, from the injector register; the decompressor expands both.
  - **Op 1 and up:** when decode accepts an op, the sequencer expands the next one from the registered instruction into `nextOp`/`nextLast`/`nextSide`.
  - **The side-band:** decode inserts the op's flags side-band as `ThumbFlagsPlugin.SIDE` (0 for RISC-V instructions).
  - **Why registers:** decode's op and `last` therefore never come straight from an expander. `last` gates `decodeInput.ready`, which passes combinationally back to the fetch PC, and decode's op feeds the hazard check that stalls decode. Expanding into either was the critical path in 3.2 (31 MHz).
- **The register file:** its early read address (`INSTRUCTION_ANTICIPATED`) is op `step + 1`, or after the last op, the next instruction's op 0.
- **PC-hold:** `decodePc.injectedDecode` is set on every op but the last, so all ops carry the Thumb instruction's address, and `IS_RVC` advances the PC once at the end.
- **Flushes:** `step` returns to 0 when decode is flushed (a jump or a trap).
- **Interrupts:** held off (`InterruptionInhibitor`) while op 1 or later is in decode, so they land between Thumb instructions (D3). The test comes in 3.4.
- **Timing:** the critical path is code RAM → aligner → op 0's expansion → the register file's read address (Fmax 33.9 MHz, [resources.md](resources.md)).

**The Thumb region CSRs (D7)** (`ThumbRegionPlugin.scala`):

| CSR | Name | |
|---|---|---|
| `0x7C0` | `base0` | Region 0 is `[base0, limit0)` |
| `0x7C1` | `limit0` | |
| `0x7C2` | `base1` | Region 1 is `[base1, limit1)` |
| `0x7C3` | `limit1` | |

- **Type:** custom machine-mode read/write CSRs.
- **Alignment:** word-aligned. The low two bits read as zero, so both halves of a fetched word are always in the same mode.
- **Reset:** all zero, which means empty regions, so the core starts as a plain RISC-V core.
- **After a write:** instructions already fetched were decoded in the old mode, so software follows a write with `fence.i`.
- **Reference:** the model's `Machine.region_csrs` (`model/thumbv/machine.py`).

**The flags unit (D1, Phase 4.2)** (`ThumbFlagsPlugin.scala`, `ThumbSrcPlugin.scala`):
- **NZCV:** a 4-bit register, reset to 0, also CSR `0x7C4` with the flags in bits 31:28 as in the APSR.
- **The side-band:** each op from the expander carries a flags kind (bits 3:0) and a condition (bits 7:4); the kinds are in `Flags` (`Thumb.scala`) and [isa-coverage.md](isa-coverage.md#strategy-c-the-hardware-flags-unit).
- **The adder:** `ThumbSrcPlugin` is `SrcPlugin` with two changes, marked `THUMBV`: kinds `SUB` and `SBC` make `add`/`addi` subtract (so `SUBS rd, rn, #imm` is `addi rd, rn, imm`), and `ADC` and `SBC` take C as the carry-in. No second adder and no result mux.
- **New flags, in execute:**
  - C and V from the adder's operand and result sign bits;
  - C of an immediate shift from the shifter's operand, bit `-shamt` (left) or `shamt - 1` (right), mod 32;
  - N and Z from `SHIFT_RIGHT` for any shift op (the shifter writes its result into `REGFILE_WRITE_DATA` only in memory), else from `REGFILE_WRITE_DATA`;
  - kind `CW` writes C from the result's bit 0 if its bit 1 is set.

  NZCV is written when execute fires, for flag-writing kinds only (a CSR write has kind 0).
- **No hazards:** flags are written in execute, and every reader (the carry-in, CSR reads, and from 4.3 conditional branches) is in execute too. In order, a reader always sees every older instruction's write, with no stall.
- **Trace:** the core's `thumbNzcv` output is NZCV after the op retiring in writeback (sampled in memory, where the register holds exactly that), logged by the testbench beside the RVFI record. The lockstep compares it after every op. The SoC leaves it unconnected.
- **Still illegal (until 4.3):** the instructions that read the flags: `ADCS`, `SBCS`, `B<cond>`, `MRS`/`MSR` of the APSR. The reference is the model's `rtlsim.HARDWARE`, `Options(flags="C", flag_readers=False)`.
- **Cost:** 267 LEs; Fmax 32.95 MHz, with the same critical path as before ([resources.md](resources.md)).

**The expander** (`Thumb.scala`, Phase 2.2) turns each Thumb instruction into one RV32 op.
- **What it covers:** every instruction whose expansion in the model is a single op, with the model's `Options(flags="none")`, bit for bit. That is 39,056 of the 63,488 16-bit halfwords, `BL` within ±1 MiB, and the barriers. It includes:
  - all loads and stores with an immediate offset, SP-relative included;
  - moves, adds and subtracts in every form;
  - shifts by an immediate, the logical ops, `MULS`, `MVNS` and `RSBS`;
  - `UXTB`, `ADD`/`SUB sp` and `ADD rd, sp`;
  - high-register `MOV`/`ADD`, `B`, `BX`, `BLX`;
  - `SVC`, `BKPT`, `CPSID`/`CPSIE`, `WFI` and the hints.
- **Results only (until Phase 4.2):** flag-setting instructions computed their result only, compares were `nop`s, and instructions that read the flags were illegal. Since 4.2 the flag writers are strategy C, with the flags side-band (see the flags unit above).
- **Multi-op instructions (Phase 3.1):** the register-offset loads and stores, `LDR` (literal), `ADR`, `BICS`, `SXTH`/`SXTB`/`UXTH`, `BL` beyond ±1 MiB, and `MOV`/`ADD`/`BX`/`BLX` with the PC as an operand: two to five ops each.
- **Register lists (Phase 3.2):**
  - **`PUSH`:** stores the registers below SP, then moves SP.
  - **`POP`:** loads them, then moves SP. With the PC, it loads the PC's word into T1, moves SP, then jumps, last.
  - **`STM`:** stores, then writes back the base.
  - **`LDM`:** loads each register from its own slot. With the base register in the list, there's no write-back and the base is loaded last.

  Each takes one op per register plus one. Op k uses the k-th register in the list: a population count per list position, compared with `step`.
- **The rest (Phase 3.3):**
  - shifts by a register (5 ops each, results only; the amount is `rm[7:0]`);
  - `REV` (11 ops), `REV16` (7) and `REVSH` (5);
  - `MSR`/`MRS` of PRIMASK, through `mstatus.MIE` (5 and 4 ops).

  With these, the RTL expands every instruction the model does in result-only mode.
- **Everything else:** the instructions that read the flags (`ADCS`, `SBCS`, `B<cond>`, `MRS`/`MSR` of the APSR) until Phase 4.3, `MRS`/`MSR` of the other special registers (the trap handler's job, Q7), undefined encodings and `UDF` become the all-zero illegal instruction. They trap with `mepc` at their own address.
- **Strategy C (Phase 4.2):** every flag-writing instruction, as the model's strategy C: one op with a flags kind for most, two for `MULS`, `BICS` and `LSRS`/`ASRS` by 32, 10–14 for the shifts by a register (C in software, then kind `CW`), and `CMP` with a high register reads the PC as the model does.
- **The check:** `tests/test_expander_rtl.py` compares the expander, generated on its own as `ThumbExpander.v`, against the model op by op, side-band included (40 bits): every 16-bit instruction at both PC alignments and about 518,000 32-bit instructions ([architecture.md](architecture.md)).

Not included yet:
- A debug module (JTAG). Useful for board bring-up in Phase 1.4.

## Interface

```verilog
module VexRiscv (
  input         clk, reset,                       // reset is active high
  // Instruction bus: one request per word, any number in flight
  output        iBus_cmd_valid,   input  iBus_cmd_ready,
  output [31:0] iBus_cmd_payload_pc,
  input         iBus_rsp_valid,   input  iBus_rsp_payload_error,
  input  [31:0] iBus_rsp_payload_inst,
  // Data bus
  output        dBus_cmd_valid,   input  dBus_cmd_ready,
  output        dBus_cmd_payload_wr,
  output [3:0]  dBus_cmd_payload_mask,
  output [31:0] dBus_cmd_payload_address, dBus_cmd_payload_data,
  output [1:0]  dBus_cmd_payload_size,
  input         dBus_rsp_ready,   input  dBus_rsp_error,
  input  [31:0] dBus_rsp_data,
  // Interrupts (machine timer, external and software)
  input         timerInterrupt, externalInterrupt, softwareInterrupt,
  // Retire trace: rvfi_valid, rvfi_pc_rdata, rvfi_insn, rvfi_rd_*, rvfi_mem_*, ...
  output        rvfi_valid, ...
);
```

Both buses are valid/ready commands with separate responses, so they are easy to connect to on-chip RAM. A response's `error` raises an access fault.

## Lint

`make core` lints with Verilator at its default warning level, and any warning fails the build. With `-Wall` there are about 140 warnings, all generator artefacts:
- Unused debug strings (`*_string`).
- Unused bits of intermediate signals.
- An undriven `IBusSimplePlugin_decompressor_output_payload_rsp_error`. This one is harmless: fetch errors are trapped before the decompressor, and the signal only feeds an unused register.
