# VexRiscv: where the Thumb patches go

Phase 1.3: a read of VexRiscv at `baf7dc82` (the submodule), confirmed by a simulation spike. File references are to `third_party/VexRiscv/src/main/scala/vexriscv/`; line numbers are at that commit.

**Summary.**
- **Position:** the expander belongs in the fetcher's decode-stage injector, next to the RVC decompressor.
- **PC hold:** holding the instruction in decode for N cycles gives PC-hold almost for free. The decode stage's PC is a register that only advances when an instruction is consumed, and the fetcher already has a flag to stop it advancing.
- **Spike:** a 30-line spike ran 4-op sequences at full speed (one op per cycle) with the right PC, the right register file reads and bypassing, across jumps and flushes. See [The spike](#the-spike).
- **Q2 (link value):** answered. The link value is `pc + (IS_RVC ? 2 : 4)`, so marking 16-bit Thumb ops as RVC-like gives `BLX`'s PC+2.
- **Interrupts:** gating them to Thumb boundaries takes one call to an existing service, `inhibateInterrupts()`.
- **CSRs:** the region and NZCV registers can be added from separate plugins through `CsrInterface`.
- **One complication:** the fetcher's state lives inside an anonymous `FetchArea` that no other plugin can reach, and SpinalHDL rejects a second full assignment to a signal. So the expander can't be bolted on from outside, and the fetcher has to be modified (D5).

## Fetch pipeline

With this configuration (`IBusSimplePlugin`, `compressedGen = true`, `busLatencyMin = 1`, `injectorStage = true`, no prediction), an instruction passes through:

| Step | Where | What happens |
|---|---|---|
| `fetchPc` | `plugin/Fetcher.scala:124` | The fetch PC register. Jumps load it through `jump.pcLoad`. |
| `iBusRsp.stages(0..1)` | `Fetcher.scala:208`, `plugin/IBusSimplePlugin.scala:286` | Stage 0 sends the word-aligned command, stage 1 waits for the response. |
| `decompressor` | `Fetcher.scala:245` | The halfword aligner and RVC decompressor. Outputs one 32-bit instruction, `isRvc` and the fetch-word PC. |
| `injector` | `Fetcher.scala:305` | `decompressor.output` → an `m2sPipe` register (`decodeInput`) → the decode stage's `INSTRUCTION`, `PC` and `IS_RVC`. |
| decode → execute → memory → writeBack | `VexRiscv.scala` | The 5-stage pipeline. Branches resolve in memory (`earlyBranch = false`). |

The stages between `fetchPc` and decode are streams with `collapsBubble = false`. That means `ready` passes straight through even when a stage is empty. **An empty stage must still say ready.** The first version of the spike deadlocked because it held `ready` low while looking at a stale, invalid payload.

### Instruction length and the aligner

`decompressor` (`Fetcher.scala:245-301`) decides the length from bits 1:0 of each halfword (`=/= 3` is RVC):
- `isInputLowRvc` and `isInputHighRvc` look at the two halves of the fetched word.
- `bufferValid`/`bufferData` hold the low half of a 32-bit instruction that straddles two words.
- `throw2Bytes` skips the low half after a jump to a `pc[1] = 1` address, or after an RVC instruction in the low half.
- `raw` is the instruction after alignment. `decompressed` is `RvcDecompressor(raw)`, used when `isRvc`.

For Thumb, the length rule changes: a halfword starts a 32-bit instruction if bits 15:11 are `11101`, `11110` or `11111` (`BL`, `MRS`, `MSR`, `DSB`, ...). The rule is used in three places, `isInputLowRvc`, `isInputHighRvc` and `isRvc`, and each picks the RVC or the Thumb rule by the mode of that halfword's address. The mode comes from comparing the address with the Thumb region CSRs. `input.pc` is the fetch word's address, so the comparator sees one address per word, and both halves are in the same region unless a region boundary is 2-byte aligned. Proposal: make region boundaries at least word-aligned.

### Where the PC comes from: PC-hold for free

With RVC on, the decode stage's PC isn't carried down from fetch. The `decodePc` area keeps its own register (`Fetcher.scala:171-198`):
```scala
val pcPlus = pcReg + (decode.input(IS_RVC) ? U(2) | U(4))
when(decode.arbitration.isFiring && !injectedDecode) { pcReg := pcPlus }
when(jump.pcLoad.valid && ...) { pcReg := jump.pcLoad.payload }
...
decode.insert(PC) := decodePc.pcReg                      // Fetcher.scala:352
```
From decode on, `PC` is a normal stageable that travels with each instruction to writeBack. So:
- **PC hold:** while the expander keeps the same Thumb instruction in decode and feeds it op after op, set `injectedDecode` on every op but the last. Every op then gets the Thumb instruction's address as its `PC`. This is what the debug plugin's injection port already does (`Fetcher.scala:373`).
- **Advance:** on the last op, `pcReg` advances by 2 or 4 depending on `IS_RVC`. Set `IS_RVC = True` for 16-bit Thumb instructions and `False` for 32-bit ones (`BL`).
- **What follows:** `auipc` returns the Thumb address on every op, as the model assumes (`model/thumbv/expander.py`: "Every op executes with pc = the Thumb instruction's address"). Exceptions capture it as `mepc`, and the RVFI trace reports it for every op.

### Holding decode: the sequencer

The spike's sequencer sits in the injector, on the registered instruction (`decodeInput`):
- **Counter:** `step` counts the ops of the instruction in decode. `last` is true on the final op, and also when `decodeInput` is invalid (see the ready rule above).
- **Instruction:** `decode.insert(INSTRUCTION)` becomes op number `step` of the expansion.
- **Handshake:** `decodeInput.ready := !decode.arbitration.isStuck && last`, so the injector register holds the Thumb instruction until its last op has gone.
- **Advancing:** `step` advances when decode fires, returns to 0 after the last op, and resets when `decode.arbitration.isRemoved` (a flush from a jump or a trap).
- **PC:** `decodePc.injectedDecode` is set while `!last`.
- **Register file address:** the register file is synchronous, so its read address comes one cycle early from `INSTRUCTION_ANTICIPATED` (`Fetcher.scala:314`, `plugin/RegFilePlugin.scala:77`). It must be the next op: op `step + 1` of the same instruction, or op 0 of the incoming instruction (`inputBeforeStage`) after the last op. If this is wrong, ops read stale registers. The spike's `add t1, s0, s1` in the middle of a sequence checks it.

The register file only needs the `rs1` and `rs2` fields of the anticipated op. So the second expander that looks at the incoming instruction can be cut down to the register fields.

**Timing.** In the spike, the expander is combinational between the injector register and the decoder, which lengthens decode's path. The alternatives are to expand before the injector register and register the op list, or to add a pipeline stage. We decide in Phase 2 with real numbers, using the 1.4 Fmax baseline.

## Link values and branches (Q2)

- **Link value:** `jal`/`jalr` write `SRC1 + SRC2` with `SRC1 = PC_INCREMENT = IS_RVC ? 2 : 4` and `SRC2 = PC` (`plugin/SrcPlugin.scala:32`, `plugin/BranchPlugin.scala:110`). With PC-hold and the `IS_RVC` rule above:
  - `BL` (32-bit, `IS_RVC = False`) as one `jal ra` links PC+4;
  - `BLX rm` (16-bit, `IS_RVC = True`) as one `jalr ra, 0(rm)` links PC+2.

  **Q2 is answered: yes, for free.** The model's 1-op expansions of `BL` and `BLX` hold.
- **Bit 0 of targets:** all branch targets have bit 0 cleared (`branchAdder(31 downto 1) @@ U"0"`, `BranchPlugin.scala:208`). So a `BX` to an address with the Thumb bit set lands on the right halfword with no extra op.
- **Misaligned targets:** with RVC on, misaligned jump targets never trap (`catchAddressMisalignedForReal`, `BranchPlugin.scala:61`). That's right for Thumb too.
- **Jumps from the middle of a sequence:** a jump issued by op k of a sequence flushes decode. That resets `step` and loads `pcReg` with the target. The spike's sequences didn't jump, but `POP {pc}` and `BX` do this. It needs a test in Phase 2.

## Interrupts (D3)

How an interrupt is taken (`plugin/CsrPlugin.scala:1286-1352`):
1. `interrupt.valid` is registered from `mip & mie` and `mstatus.MIE` (`pipelinedInterrupt`).
2. `pipelineLiberator` (`CsrPlugin.scala:1329`): when `interrupt.valid && allowInterrupts && decode.arbitration.isValid`, decode is halted (`haltByOther`). Then the pipeline drains until decode's `PC` has passed into every later stage.
3. `interruptJump` (`CsrPlugin.scala:1350`) jumps to `mtvec`, with `mepc := writeBack.input(PC)`. That is the PC of the halted instruction in decode, which hasn't run.

**Gating to Thumb boundaries:** call `service(classOf[InterruptionInhibitor]).inhibateInterrupts()` (`Services.scala:76`, `CsrPlugin.scala:658`) whenever decode holds op 1 or later of a sequence (`decodeInput.valid && step =/= 0`). The `allowInterrupts` condition is checked both when the liberator starts and when it jumps. So an interrupt can only halt decode at op 0, after every op of the previous Thumb instruction has gone. `mepc` is then the Thumb instruction's address, and the handler returns to it. The debug plugin uses the same service for single-stepping (`plugin/DebugPlugin.scala:343`).

**Exceptions partway through a sequence:** a fault on op k (a load fault, a misaligned access) traps with `mepc` = the Thumb instruction's address. Ops 0 to k-1 have already written their results, and the handler returns to the start of the instruction. Expansions must therefore be restartable: the base register and SP are updated last.
- **Status in the model:** PUSH, POP, LDM and STM already do this (LDM loads the base register last).
- **Matches ARM:** ARMv6-M also abandons and restarts a multiple load or store that faults.
- **Next step:** a check that every expansion is restartable belongs with the expander's tests (Phase 2).

**`ecall`/`ebreak`:** both capture `mepc` = the Thumb address. On return, the handler must skip 2 bytes for `SVC`, not the 4 it skips for an RV32 `ecall`. It can tell which by checking the Thumb regions against `mepc`. This is a Phase 5 item.

## CSRs (D7, D1)

New CSRs can be added from any plugin through `CsrInterface` (`CsrPlugin.scala:387-416`):
```scala
val csr = pipeline.service(classOf[CsrInterface])
csr.rw(0x7C0, regionBase)         // read/write register
csr.r(0x7C8, nzcv)                // read-only view
csr.onWrite(0x7C8) { ... }        // side effect on write
```
- **Addresses:** custom machine-mode read/write CSRs go in `0x7C0–0x7FF`.
- **Stage:** CSR accesses happen in execute (`duringAny`, `CsrPlugin.scala:542`).
- **Hazards:** a write to a region CSR changes how fetch interprets the following instructions, which are already in the pipeline. Region CSR writes therefore need a refetch: a `fence.i` after them, which is a jump in this configuration, or flush on write. Phase 2.
- **The NZCV unit (Phase 4):** the expander can pass extra information next to each op as stageables inserted at decode. For example, a "set flags" bit for D1's side-band, which then doesn't need its own RISC-V encoding. The flags register must not be written in execute: an older branch in memory can still flush the instruction. Write it in memory or writeBack, and bypass to execute for `B<cond>` and `ADCS`/`SBCS`, as the register file does.

## External interrupts and vectoring (D9)

- **Inputs:** the core has three interrupt inputs: `timerInterrupt`, `externalInterrupt` and `softwareInterrupt` (`CsrPlugin.scala:615`).
- **Interrupt array:** `ExternalInterruptArrayPlugin` adds a 32-bit `externalInterruptArray` input with mask and pending CSRs (`0xBC0`, `0xFC0`), ORed into the single machine external interrupt. All of them share cause 11, so the handler reads the pending CSR to find the source (software dispatch).
- **Hardware vectoring without patches:**
  - `UserInterruptPlugin(name, code)` (`CsrPlugin.scala:1742`) adds an interrupt input with its own cause code and `mie`/`mip` bit. Codes 16–31 are free for platform interrupts.
  - With `xtvecModeGen = true` and `mtvec.MODE = 1`, interrupts jump to `mtvec.base + 4 * cause` (`CsrPlugin.scala:1395`).
  - Together these give up to 16 hardware-vectored interrupts. Priority is fixed: the last interrupt added wins.
  - The NVIC programming model (D9) would sit on top as a memory-mapped block that drives these inputs.
- **Beyond that:** an NVIC-style vector table read from memory, or programmable priorities, would mean patching CsrPlugin's trap entry. That decision belongs to Phase 5.

## Other findings

- **No Zbb plugin** in this VexRiscv (Q4). Zbb would need a custom plugin; VexiiRiscv has one.
- **RVFI for Thumb:** with PC-hold, each op retires as its own RVFI record, with `rvfi_pc_rdata` = the Thumb address and `rvfi_insn` = the raw Thumb halfwords (`FORMAL_INSTRUCTION`, `Fetcher.scala:431`). The lockstep in `thumbv.rtlsim` compares one op at a time, so it extends to Thumb code by grouping consecutive records with the same PC against the model's expansion.
- **`c.j .`:** the testbench only stops on the 32-bit `j .`. Programs built with RVC would need it to recognise `c.j .` too. Not needed so far, since the C test programs are `rv32im`.

## Decisions

**D4 (base core): VexRiscv, confirmed.**
- **Fit:** the patch points all exist and are small, and the spike shows the hard part (PC-hold with correct register reads and bypassing) works with about 30 lines.
- **Alternatives:** VexiiRiscv wasn't evaluated in depth. Switching would mean redoing 1.1 and 1.2, for a core aimed at higher performance and Linux-class systems, with no specific benefit here other than Zbb. NEORV32 stays the fallback but isn't needed.

**D5 (where the expander lives): in a Thumb-V copy of VexRiscv's fetcher, with the rest as separate plugins.**
- **Why the fetcher:** the expander, the Thumb length rule and the sequencer must change the inside of `IBusFetcherImpl`'s `FetchArea`: the aligner, the injector and `decodePc`. No other plugin can reach that area, because `IBusSimplePlugin.build` creates it as an anonymous object and doesn't keep a reference. Overriding its signals needs `allowOverride` on each one.
- **Options:**
  - **(a) Copy the fetcher (recommended).** Copy `Fetcher.scala` and `IBusSimplePlugin.scala` (about 1,070 lines) into `rtl/core/src/main/scala/thumbv/` as `ThumbFetcher`, marking every change with `// THUMBV`. The submodule stays stock, `diff` against it shows exactly what changed, and everything stays in this repository.
  - **(b) Fork VexRiscv** on GitHub with the patch on a branch, and point the submodule at the fork. The diff is just as clean, and rebasing onto new upstream versions is easier, but it means a second repository to maintain.
  - **(c) Override from a subclass** with `allowOverride`, as the spike did. It's fragile, because every override silently depends on upstream's code, and it still needs a copy of `IBusSimplePlugin.build`.
- **Separate plugins for the rest,** through VexRiscv's services, with no copies:
  - the Thumb region CSRs and the NZCV unit (`CsrInterface`, stageables);
  - flag-setting ops (`DecoderService`);
  - interrupt gating (`InterruptionInhibitor`, called from the fetcher).

## The spike

A temporary patch to `Fetcher.scala`, now reverted. It turns the `c.nop` hint `0x0011` (`addi x0, x0, 4` after decompression) into 4 ops held at one PC:
1. `auipc t0, 0`
2. `addi t0, t0, 1`
3. `add t1, s0, s1`
4. `auipc t2, 0`

The test program, with `s0 = 0x100` and `s1 = 0x23`, runs:
- two sequences back to back;
- `add a0, t1, t2`, which uses their results right away;
- a jump over a sequence to one at a `pc[1] = 1` address;
- `mv a1, t0`;
- `jal`;
- a sequence right after the `jal`.

The retire trace (pc, raw instruction, rd, value):
```
0002000a 00110011 05 0002000a   auipc t0      = the held PC
0002000a 00110011 05 0002000b   addi t0       PC+1
0002000a 00110011 06 00000123   add t1,s0,s1  register file read mid-sequence
0002000a 00110011 07 0002000a   auipc t2
0002000c 05330011 05 0002000c   second sequence, back to back
...
0002000e 00730533 0a 0002012f   add a0,t1,t2  = 0x123 + 0x2000c, bypassed
00020012 a011a011 00 00000000   j             (the sequence at 0x20014 is skipped)
00020016 00110011 05 00020016   sequence at a pc[1] = 1 address
...
00020018 00ef8596 0b 00020017   mv a1,t0
0002001a 004000ef 01 0002001e   jal: link = PC+4
0002001e 00110011 05 0002001e   sequence after the jal
```

The patch, applied after `decode.insert(IS_RVC)` in the injector (`Fetcher.scala:354`):
```scala
val spike = new Area {
  val step = RegInit(U(0, 3 bits))
  def seqLen(inst: Bits): UInt = {
    val isHint = inst(31 downto 20) =/= 0 && inst(19 downto 0) === B"x00013"
    Mux(isHint, inst(22 downto 20).asUInt, U(0, 3 bits))
  }
  def op(inst: Bits, k: UInt): Bits = {
    val r = Bits(32 bits)
    r := inst
    when(seqLen(inst) =/= 0) {
      switch(k) {
        is(0) { r := B"x00000297" }   // auipc t0, 0
        is(1) { r := B"x00128293" }   // addi  t0, t0, 1
        is(2) { r := B"x00940333" }   // add   t1, s0, s1
        default { r := B"x00000397" } // auipc t2, 0
      }
    }
    r
  }
  val orig = decodeInput.rsp.inst
  val n = seqLen(orig)
  val last = !decodeInput.valid || n === 0 || step === n - 1
  decode.insert(INSTRUCTION).allowOverride := op(orig, step)
  decodeInput.ready.allowOverride := !decode.arbitration.isStuck && last
  decodePc.injectedDecode setWhen(!last)
  when(decode.arbitration.isFiring) { step := (last ? U(0, 3 bits) | step + 1) }
  when(decode.arbitration.isRemoved) { step := 0 }
  decode.insert(INSTRUCTION_ANTICIPATED).allowOverride := Mux(decode.arbitration.isStuck, decode.input(INSTRUCTION),
    Mux(last, op(inputBeforeStage.rsp.inst, U(0, 3 bits)), op(orig, step + 1)))
}
```

What the spike didn't cover, and Phase 2 must:
- an interrupt arriving partway through a sequence (the SoC has no interrupt source yet);
- a jump issued from inside a sequence;
- a fault partway through a sequence;
- 32-bit Thumb instructions in the aligner.
