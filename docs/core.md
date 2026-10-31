# The base core

Thumb-V starts from a stock VexRiscv (decision D4), generated from SpinalHDL in a fixed configuration. Nothing in it is patched yet: the Thumb expander, region CSRs and flags unit come in Phases 2–4.

- **Source:** `rtl/core/src/main/scala/thumbv/Core.scala`, an sbt project that depends on the VexRiscv submodule (`third_party/VexRiscv`, pinned at `baf7dc82`).
- **Output:** `make core` writes `build/rtl/VexRiscv.v`, one Verilog file of about 5,000 lines. Generated files aren't committed: regenerate them with `make core`.

## Configuration

VexRiscv is built from plugins. The choices, and why:

| Plugin | Setting | Why |
|---|---|---|
| `IBusSimplePlugin` | RVC on (`compressedGen`), no branch prediction, access faults trapped | The Thumb expander goes where the RVC decompressor sits, and Thumb shares RVC's 2-byte fetch granularity (plan section 1). No I-cache for now. |
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

Reset vector `0x0000_0000` and trap vector `0x0000_0020` for now. Both are parameters of `Core()`; the simulation SoC (Phase 1.2) sets them from its memory map.

Not included yet:
- A debug module (JTAG). Useful for board bring-up in Phase 1.4.
- The retire trace port (`FormalPlugin`'s RVFI), which Phase 1.2 adds for lockstep against the model.

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
  input         timerInterrupt, externalInterrupt, softwareInterrupt
);
```

Both buses are valid/ready commands with separate responses, so they are easy to connect to on-chip RAM. A response's `error` raises an access fault.

## Lint

`make core` lints with Verilator at its default warning level, and any warning fails the build. With `-Wall` there are about 140 warnings, all generator artefacts:
- Unused debug strings (`*_string`).
- Unused bits of intermediate signals.
- An undriven `IBusSimplePlugin_decompressor_output_payload_rsp_error`. This one is harmless: fetch errors are trapped before the decompressor, and the signal only feeds an unused register.
