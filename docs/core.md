# The base core

Thumb-V is VexRiscv (decision D4), generated from SpinalHDL in a fixed configuration, with its instruction fetcher replaced by a Thumb-V copy (D5) and Thumb-V's own plugins added. So far that means the Thumb region CSRs, mode select and the Thumb length rule (Phase 2.1); the expander, sequencer and flags unit come in Phases 2–4. See [Thumb-V changes](#thumb-v-changes), and [architecture.md](architecture.md) for block diagrams.

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
| `IntAluPlugin`, `SrcPlugin` | standard | |
| `FullBarrelShifterPlugin` | one-cycle shifts | Shifts are common in expansions (flags, register shifts). |
| `MulPlugin` | one-cycle-throughput multiplier | The 10CL025 has 66 18×18 multipliers; `MULS` is 1:1. |
| `DivPlugin` | iterative, 1 bit per cycle | ARMv6-M has no divide; only RISC-V code uses it. |
| `HazardSimplePlugin` | full bypassing | Expansions are long chains of dependent ops. |
| `BranchPlugin` | branches resolved in execute, misaligned targets trapped, `fence.i` as a jump | With no I-cache, Thumb `ISB` (`fence.i`) only needs a refetch. |
| `ThumbRegionPlugin` | 2 regions, CSRs `0x7C0`–`0x7C3` | Thumb-V's: see below |
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
- **Expansion:** Thumb instructions go through `Thumb.expand` instead of the RVC decompressor, for op 0 only. The decode stage's `IS_RVC` is set for 16-bit Thumb instructions, so the PC and link values advance by 2, or by 4 for 32-bit ones. The raw instruction and a Thumb flag travel on with op 0 (`FetchRsp.raw`, `FetchRsp.thumb`).

In the injector, the sequencer (Phase 3.1, [vexriscv-notes.md](vexriscv-notes.md#holding-decode-the-sequencer)):
- **Holding the instruction:** it holds a Thumb instruction in the injector register until its last op has gone into decode, by gating `decodeInput.ready` with `last`.
- **Which op:** `step` counts the ops; decode gets op `step` from `Thumb.expand` on the registered instruction.
- **The register file:** its early read address (`INSTRUCTION_ANTICIPATED`) is op `step + 1`, or after the last op, the next instruction's op 0.
- **PC-hold:** `decodePc.injectedDecode` is set on every op but the last, so all ops carry the Thumb instruction's address, and `IS_RVC` advances the PC once at the end.
- **Flushes:** `step` returns to 0 when decode is flushed (a jump or a trap).
- **Interrupts:** held off (`InterruptionInhibitor`) while op 1 or later is in decode, so they land between Thumb instructions (D3). The test comes in 3.4.
- **Timing:** expanding in decode puts the expander on the path into execute (Fmax 38.9 MHz, [resources.md](resources.md)). If that ever matters, op `step + 1` can be computed a cycle early and registered.

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

**The expander** (`Thumb.scala`, Phase 2.2) turns each Thumb instruction into one RV32 op.
- **What it covers:** every instruction whose expansion in the model is a single op, with the model's `Options(flags="none")`, bit for bit. That is 39,056 of the 63,488 16-bit halfwords, `BL` within ±1 MiB, and the barriers. It includes:
  - all loads and stores with an immediate offset, SP-relative included;
  - moves, adds and subtracts in every form;
  - shifts by an immediate, the logical ops, `MULS`, `MVNS` and `RSBS`;
  - `UXTB`, `ADD`/`SUB sp` and `ADD rd, sp`;
  - high-register `MOV`/`ADD`, `B`, `BX`, `BLX`;
  - `SVC`, `BKPT`, `CPSID`/`CPSIE`, `WFI` and the hints.
- **Results only:** there's no flags unit until Phase 4. Flag-setting instructions compute their result only, compares are `nop`s, and instructions that read the flags (`ADCS`, `SBCS`, `B<cond>`, `MRS`/`MSR` of the APSR) are illegal. So code that depends on flags traps, rather than going wrong.
- **Multi-op instructions (Phase 3.1):** the register-offset loads and stores, `LDR` (literal), `ADR`, `BICS`, `SXTH`/`SXTB`/`UXTH`, `BL` beyond ±1 MiB, and `MOV`/`ADD`/`BX`/`BLX` with the PC as an operand: two to five ops each.
- **Everything else:** the remaining multi-op instructions (`PUSH`, `POP`, `LDM`, `STM` until 3.2; the register shifts, `REV`/`REV16`/`REVSH`, `MRS`/`MSR` of PRIMASK until 3.3), undefined encodings and `UDF` become the all-zero illegal instruction. They trap with `mepc` at their own address.
- **The check:** `tests/test_expander_rtl.py` compares the expander, generated on its own as `ThumbExpander.v`, against the model op by op: every 16-bit instruction at both PC alignments and about 518,000 32-bit instructions ([architecture.md](architecture.md)).

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
