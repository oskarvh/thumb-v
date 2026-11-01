# Architecture

Block diagrams of Thumb-V as built so far, and of what the plan adds. They show where every block comes from:

- **Stock (grey):** VexRiscv as published, used unchanged through its plugin interface.
- **Copied (blue):** VexRiscv code that Thumb-V carries its own copy of (the fetcher, D5), unchanged so far.
- **Thumb-V (green):** written or changed for Thumb-V.
- **Planned (white, dashed):** in the plan, not built yet. The label says which phase.

**Keep this current.** Any change to the RTL's structure updates these diagrams in the same commit: a new block, a block that changes colour (planned → built, copied → changed), or a new connection. The [status table](#status) at the end follows the same rule.

## The system

The SoC is the same in simulation and on the board; only the RAM sizes and the top level differ ([soc.md](soc.md), [board.md](board.md)).

```mermaid
flowchart LR
    classDef stock fill:#eeeeee,stroke:#777777,color:#222222
    classDef thumbv fill:#d8f0d4,stroke:#3a8a35,color:#14321a
    classDef planned fill:#ffffff,stroke:#c77d00,stroke-dasharray:5 4,color:#7a4a00

    subgraph TOP["Top level: rtl/board/cyc1000_top.v on the board, sim/tb.sv in Verilator"]
        CLK["12 MHz clock<br/>reset: 1.4 s after configuration, user button"]:::thumbv
        TBIRQ["testbench interrupt source (+irq)<br/>simulation only; tied off on the board"]:::thumbv
        subgraph SOC["SoC: rtl/soc/thumbv_soc.v"]
            CORE["Thumb-V core<br/>VexRiscv + Thumb-V plugins<br/>(next diagram)"]:::thumbv
            DEC["address decode<br/>RAMs alias through their regions"]:::thumbv
            CODE["code RAM, 0x0000_0000<br/>256 KiB sim / 32 KiB board<br/>dual port: fetch + data"]:::thumbv
            DATA["data RAM, 0x2000_0000<br/>64 KiB sim / 16 KiB board"]:::thumbv
            IO["I/O, 0x1000_0000<br/>UART TX 115200 · LEDs"]:::thumbv
            NVIC["interrupt controller, NVIC model (D9)<br/>SysTick timer<br/>Phase 5"]:::planned
            SHIM["peripheral shim for ARM-only mode<br/>Phase 6"]:::planned
            SDRAM["SDRAM controller, 8 MB<br/>Phase 7"]:::planned
        end
    end

    CORE -- "iBus: fetch" --> CODE
    CORE -- "dBus: loads, stores" --> DEC
    DEC --> CODE
    DEC --> DATA
    DEC --> IO
    DEC -.-> SHIM
    DEC -.-> SDRAM
    NVIC -. "interrupts" .-> CORE
    TBIRQ -- "irq_timer: timer interrupt" --> CORE
    CLK --> SOC
```

The RVFI retire trace (VexRiscv's `FormalPlugin`) leaves the core only in simulation, where the testbench logs it for the lockstep against the model ([soc.md](soc.md#lockstep-against-the-model)).

## The core

The VexRiscv pipeline with its plugins, in the stage where each one acts. Instructions flow down; jumps and traps go back up to the fetch PC.

```mermaid
flowchart TB
    classDef stock fill:#eeeeee,stroke:#777777,color:#222222
    classDef copied fill:#dde8f5,stroke:#4a78b0,color:#10243d
    classDef thumbv fill:#d8f0d4,stroke:#3a8a35,color:#14321a
    classDef planned fill:#ffffff,stroke:#c77d00,stroke-dasharray:5 4,color:#7a4a00

    subgraph FETCH["Fetch: ThumbIBusSimplePlugin + ThumbFetcher, copied from VexRiscv (D5)"]
        PC["fetchPc<br/>fetch PC, jump arbitration"]:::copied
        CMD["iBusRsp stage 0<br/>iBus command, one word"]:::copied
        RSP["iBusRsp stage 1<br/>response buffer, access faults"]:::copied
        MODE["mode select<br/>inThumb: fetch word in a region?"]:::thumbv
        ALIGN["aligner<br/>halfword buffer, length rule:<br/>RVC bits 1:0 or Thumb.is32"]:::thumbv
        RVCD["RVC decompressor"]:::copied
        EXP["Thumb.expand, op 0 and whether it's the last<br/>(results only: no flags yet)"]:::thumbv
        INJ["injector register<br/>decodeInput"]:::copied
        SEQ["sequencer<br/>op 0 from the injector register; Thumb.expand of op step + 1<br/>into nextOp/nextLast and the register file's early address<br/>holds decodeInput until the last op; PC hold (injectedDecode)"]:::thumbv
        DPC["decodePc<br/>decode PC += IS_RVC ? 2 : 4"]:::copied
    end

    REGIONS["ThumbRegionPlugin<br/>2 regions, CSRs 0x7C0-0x7C3"]:::thumbv

    subgraph PIPE["Pipeline: VexRiscv plugins, stock"]
        DECODE["Decode<br/>DecoderSimplePlugin: decode, illegal instructions<br/>RegFilePlugin: register file, synchronous read<br/>HazardSimplePlugin: full bypassing"]:::stock
        EXEC["Execute<br/>SrcPlugin · IntAluPlugin · FullBarrelShifterPlugin<br/>MulPlugin, DivPlugin: start<br/>CsrPlugin: CSR reads and writes<br/>DBusSimplePlugin: load/store command"]:::stock
        MEMORY["Memory<br/>BranchPlugin: branches and jumps resolve<br/>DBusSimplePlugin: load response"]:::stock
        WB["WriteBack<br/>register file write<br/>CsrPlugin: trap and interrupt entry, mepc<br/>FormalPlugin: RVFI retire trace"]:::stock
    end

    NZCV["NZCV flags unit (D1)<br/>set-flags side-band, carry in, B#lt;cond#gt;<br/>Phase 4"]:::planned
    GATE["interrupt gating<br/>InterruptionInhibitor while op 1+ is in decode"]:::thumbv

    PC --> CMD --> RSP --> ALIGN
    MODE --> ALIGN
    ALIGN --> RVCD
    ALIGN --> EXP
    RVCD --> INJ
    EXP --> INJ
    INJ -- "raw Thumb instruction, op 0" --> SEQ
    SEQ -- "op, next op's rs1/rs2" --> DECODE
    DPC -- "PC, IS_RVC" --> DECODE
    REGIONS --> MODE
    DECODE --> EXEC --> MEMORY --> WB
    EXEC -- "csrw 0x7C0-0x7C3" --> REGIONS
    MEMORY -- "jump target" --> PC
    WB -- "trap target: mtvec" --> PC
    SEQ --> GATE
    GATE -- "allowInterrupts" --> WB
    EXEC -.-> NZCV
    NZCV -.-> EXEC
```

**Where the PC comes from.** The decode stage's PC isn't carried down from fetch: `decodePc` keeps its own register, which advances by 2 or 4 (`IS_RVC`) when decode consumes an instruction, and is reloaded on jumps. That is what makes PC-hold cheap for multi-op Thumb instructions ([vexriscv-notes.md](vexriscv-notes.md#where-the-pc-comes-from-pc-hold-for-free)).

**The expander is checked on its own.** `make core` also generates `ThumbExpander.v`, the same `Thumb.expand` function as a module of its own. `tests/test_expander_rtl.py` runs every 16-bit Thumb instruction and a large sweep of 32-bit ones through it in Verilator and compares each op with the model. The core uses the function directly, in the fetcher, so the two can't differ.

**Thumb instructions in the pipeline.** After the aligner, a Thumb instruction is an ordinary RV32 op (or, from Phase 3, a short sequence of them), so the pipeline's stock plugins run it unchanged. What Thumb-V adds downstream of fetch is small: the region CSRs, the flags unit and the interrupt gating, each a separate plugin through VexRiscv's services (D5).

## Status

| Block | Source | State | Since |
|---|---|---|---|
| Pipeline plugins (decode to writeBack) | `third_party/VexRiscv`, stock | built | 1.1 |
| Fetcher: fetch PC, iBus stages, RVC decompressor, injector, `decodePc` | `rtl/core/.../ThumbFetcher.scala`, copied | built, unchanged | 2.1 |
| Mode select, Thumb length rule in the aligner | `ThumbFetcher.scala`, marked `THUMBV` | built | 2.1 |
| Thumb region CSRs | `rtl/core/.../ThumbRegionPlugin.scala` | built | 2.1 |
| Expander, single ops | `rtl/core/.../Thumb.scala` | built: every instruction whose expansion is one op, results only; checked exhaustively against the model | 2.2 (2.1: a stub) |
| Expander, multi-op | `Thumb.scala` | built: every result-only expansion (3.1–3.3), checked op by op against the model | 3.1 |
| Expander alone, for the exhaustive check | `ThumbExpander` in `Thumb.scala`, `sim/expander_tb.sv` | built, simulation only | 2.3 |
| Sequencer, PC hold | `ThumbFetcher.scala`, marked `THUMBV` | built | 3.1 |
| Interrupt gating | `ThumbFetcher.scala`, through `InterruptionInhibitor` | built; tested under interrupts every few cycles (3.4) | 3.1 |
| SoC timer interrupt input, testbench interrupt source | `rtl/soc/thumbv_soc.v` (`irq_timer`), `sim/tb.sv` (`+irq`) | built; the board ties it to 0 | 3.4 |
| NZCV flags unit | plugin | planned | Phase 4 |
| Interrupt controller, SysTick | SoC | planned | Phase 5 |
| Peripheral shim | SoC | planned | Phase 6 |
| SDRAM controller | SoC | planned | Phase 7 |
| SoC: RAMs, address decode, UART, LEDs | `rtl/soc/` | built | 1.2 |
| Board top level | `rtl/board/` | built | 1.4 |
