# Flags strategy: measurements and decision (D1)

Phase 0.7 measures what each way of handling ARM's NZCV flags would cost on real compiled code, to settle decision D1 in [plan.md](plan.md), and answers Q3 (register shifts) from [isa-coverage.md](isa-coverage.md) along the way.

**Recommendation: strategy C, a hardware NZCV unit.** Add fused compare-and-branch and an ARM-shift micro-op (Q3) on top of it. Over 21 programs, C costs 1.25 RV32 ops per Thumb instruction, or 1.03 with both additions. Eager software flags (A) cost 3.92. The best software scheme that hardware could realistically implement costs 2.34. Even a perfect, unrealisable dead-flag elimination costs 1.47, which is still worse than plain C.

## How it was measured

`model/thumbv/measure.py` (run with `make measure`) runs each program once in the model, under strategy A as modelled.
- **What is recorded.** For every Thumb instruction it executes, it records which flags the instruction reads and writes. It follows every flag write until the flag is overwritten, so each write is known to be read (live) or never read (dead).
- **Costing.** Every strategy is then costed from this trace. The ops strategy A spends on each instruction are split into the result, each flag, and a final move out of a temporary. For each flag-setting encoding, that split is checked to add up to what the expander actually emits.
- **Programs.** CoreMark, all 19 Embench IoT benchmarks, and `float`: soft-float kernels in `tests/bench/float/` covering libgcc's float and double routines and libm's `sqrt`. Embench IoT 2 is integer-only, so `float` is the soft-float workload. Everything is built with GCC 13 at `-O2` for Cortex-M0. That is 8.1 million Thumb instructions in all.
- **Unit.** Costs are RV32 ops retired per Thumb instruction retired. That approximates cycles on a single-issue core, but ignores load-use stalls and taken-branch penalties, which are the same under every strategy.

The strategies:

| Column | Strategy | Realisable? |
|---|---|---|
| A | Eager flags, as modelled: every flag computed after every flag-setting instruction | yes (it's the model) |
| A peek-k | A, but skip the flags that the next k instructions in the fetch stream overwrite before reading them. The lookahead stops at branches. Calls and returns end the flags' lifetime (AAPCS: flags are UNKNOWN across a call) | yes, with a k-instruction window in the expander |
| A oracle | A, computing only the flags that are actually read | no: a lower bound for any dead-flag elimination, static or dynamic |
| A fused | A oracle, plus `CMP` + `B<cond>` as one RV32 branch when the compare's flags die at the branch | no: needs the oracle |
| B | Lazy flags: each flag-setting instruction saves its operands, result and kind; a read computes only what it needs. Optimistic: the read knows the producer's kind for free, where hardware would need branch-free code for every kind | partly |
| C | Hardware NZCV: ALU ops latch the flags, `B<cond>` is one custom branch, `ADCS`/`SBCS` take C as carry-in. Register shifts still compute C in software (see Q3) | yes |
| C fused | C, plus `CMP` + `B<cond>` as one compare-and-branch op that also latches the flags. `CMP #imm` with imm ≠ 0 also fuses, given an immediate form of the op | yes |
| C shift | C fused, plus an ARM-shift micro-op for register shifts that also hands its carry-out to the flags unit | yes |

## Results

RV32 ops per Thumb instruction (the mean is unweighted, so the longest benchmarks don't dominate):

| Benchmark | Thumb instr. | A | A peek-1 | A peek-4 | A oracle | A fused | B | C | C fused | C shift |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| coremark | 423,292 | 4.02 | 3.01 | 2.44 | 1.36 | 1.02 | 2.68 | 1.13 | 1.01 | 0.98 |
| float | 252,421 | 4.25 | 2.83 | 2.24 | 1.52 | 1.17 | 2.99 | 1.21 | 1.13 | 1.03 |
| aha-mont64 | 20,459 | 4.08 | 2.70 | 2.01 | 1.38 | 1.32 | 3.07 | 1.04 | 1.01 | 1.01 |
| crc32 | 24,657 | 3.21 | 2.21 | 1.50 | 1.21 | 1.13 | 2.58 | 1.17 | 1.13 | 1.13 |
| depthconv | 4,664 | 4.37 | 3.30 | 2.19 | 1.50 | 1.33 | 3.01 | 1.53 | 1.49 | 1.15 |
| edn | 50,415 | 4.59 | 2.87 | 2.11 | 1.32 | 1.18 | 3.05 | 1.25 | 1.21 | 1.12 |
| huffbench | 291,047 | 4.23 | 3.04 | 2.42 | 1.33 | 0.95 | 2.61 | 1.08 | 0.95 | 0.91 |
| matmult-int | 126,107 | 4.89 | 3.68 | 2.43 | 1.42 | 1.13 | 3.12 | 1.08 | 0.94 | 0.93 |
| md5sum | 44,095 | 4.23 | 3.01 | 2.53 | 1.40 | 1.16 | 2.81 | 1.37 | 1.35 | 0.99 |
| nettle-aes | 90,525 | 3.44 | 2.57 | 1.68 | 1.16 | 1.12 | 2.69 | 1.12 | 1.11 | 1.08 |
| nettle-sha256 | 13,527 | 3.54 | 2.91 | 2.22 | 1.40 | 1.38 | 2.72 | 2.07 | 2.06 | 1.04 |
| nsichneu | 3,023 | 2.95 | 2.92 | 2.90 | 1.99 | 0.89 | 1.69 | 1.02 | 0.89 | 0.81 |
| picojpeg | 766,493 | 3.73 | 2.73 | 1.93 | 1.35 | 1.20 | 2.58 | 1.24 | 1.22 | 1.14 |
| qrduino | 699,989 | 4.17 | 3.59 | 2.71 | 1.53 | 1.22 | 2.69 | 1.76 | 1.68 | 1.02 |
| sglib-combined | 108,521 | 3.88 | 3.29 | 2.86 | 1.68 | 1.09 | 2.48 | 1.18 | 1.02 | 1.00 |
| slre | 26,838 | 3.80 | 3.22 | 2.86 | 1.85 | 1.23 | 2.43 | 1.21 | 1.14 | 1.06 |
| statemate | 1,586 | 3.57 | 3.05 | 2.56 | 1.43 | 1.23 | 2.42 | 1.30 | 1.22 | 1.18 |
| tarfind | 82,171 | 5.23 | 3.46 | 2.81 | 1.64 | 1.33 | 3.47 | 1.03 | 0.87 | 0.87 |
| ud | 2,510 | 4.36 | 2.92 | 2.35 | 1.34 | 1.06 | 2.76 | 1.12 | 1.01 | 1.00 |
| wikisort | 818,325 | 3.38 | 2.61 | 2.14 | 1.44 | 1.06 | 2.32 | 1.17 | 1.06 | 1.06 |
| xgboost | 4,282,396 | 2.43 | 2.38 | 2.30 | 1.58 | 1.16 | 1.84 | 1.26 | 1.16 | 1.16 |
| **mean** | | **3.92** | **2.97** | **2.34** | **1.47** | **1.16** | **2.67** | **1.25** | **1.17** | **1.03** |

Values below 1 occur because a fused compare-and-branch retires two Thumb instructions as one op.

### What the numbers say

- **Flags dominate strategy A.** On average, 69% of all RV32 ops compute flags.
- **Most flags are never read.** 71% of flag-setting instructions have none of their flags read; the compiler has no choice, because almost every 16-bit Thumb data-processing instruction sets flags.

  | Flag | N | Z | C | V |
  |---|---:|---:|---:|---:|
  | Writes never read | 93% | 80% | 89% | 92% |

- **Dead flags are hard to see in hardware.** A one-instruction lookahead finds all of an instruction's flags dead only 36% of the time. A four-instruction lookahead still leaves A at 2.34.
- **Even perfect elimination isn't enough.** The oracle (1.47) is still worse than plain C (1.25), because the flags that are read cost 7–9 ops each time a compare feeds a branch.
- **Lazy flags pay on every write.** B (2.67) saves operands on every flag-setting instruction, which is about as costly as computing N and Z eagerly. Even with its read side idealised, it lands between A peek-1 and A peek-4. It would also be the most complex expander of all.
- **C is close to native.** What C has left above 1.0 is the inherent multi-op instructions: `PUSH`/`POP`, register-offset loads, `LDR` literal and hi-register forms.
- **The outlier is register shifts, not flags.** C's worst cases are `nettle-sha256` (2.07), `qrduino` (1.76) and `md5sum` (1.37): `RORS` and `ASRS` by register with C computed in software. The ARM-shift micro-op brings all three to about 1.0 (Q3 below).

### Checks on the method

- **Lookahead safety.** Every dynamic instance was checked against the oracle: the peek analysis never marked a flag dead that was later read (0 violations in 8.1 million instructions).
- **Flags across calls.** No program reads flags across a call or return (0 such reads). This backs the AAPCS assumption that peek relies on.
- **Shift by zero.** A register shift by 0 leaves C untouched. It is treated as not writing C, so it doesn't make an earlier C look live.

## Fusing `CMP` with `B<cond>`

- **How common.** `B<cond>` is 11.6% of Thumb instructions. 90% of them follow directly after a `CMP` whose flags they read, with a condition that one RV32 branch can test. MI, PL, VS and VC can't be tested that way.
- **Under C, it's always safe.** The fused op latches the flags as well as branching, so code after the branch still sees correct flags. It saves 0.08 ops per instruction (1.25 → 1.17), and 0.10 with an immediate form for `CMP #imm`.
- **Under A, it's unsafe without liveness.** Fusing under A needs to know that the flags die at the branch. That requires seeing both successors of the branch, which a fetch-stream lookahead can't (plan section 4).

Fusion is an optimisation on top of C, not a requirement: it can come after the basic flags unit works.

## `BL` range

None of the 17,780 `BL`s executed (822 static) needs the 2-op `auipc` + `jalr` form. That is by construction: Thumb code here is under 64 KiB, and `jal` reaches ±1 MiB. The long form stays for big images in SDRAM, but costs nothing in practice.

## Q3: register shifts

- **Frequency.** Register shifts are 0.9% of Thumb instructions on average, but 8.5% in `nettle-sha256`, 4.1% in `qrduino`, 2.3% in `md5sum` and 2.1% in `depthconv`. CoreMark has almost none.
- **Where they come from:** integer code, not soft-float.

  | Origin | Share of register shifts |
  |---|---:|
  | Program code | 95% (`RORS` in SHA-256 and MD5, `ASRS` in qrduino) |
  | libgcc soft-float | 4% |
  | Other libgcc | 0.2% |

  In `float`, soft-float routines account for 88% of the register shifts, but those are only 0.6% of its instructions.
- **Shift amounts:**

  | Amount | Share |
  |---|---:|
  | 1–31 | 89% |
  | 0 | 11% |
  | > 32 | 0.1% (`depthconv`) |
  | exactly 32 | none |

  The ≥ 32 cases are rare but real, so the special-casing has to stay.
- **Cost under C.** The 5-op result expansion in isa-coverage.md assumed software flags. Under C, the flags unit still needs the shifter's carry-out, which RISC-V's `sll`/`srl`/`sra` don't produce. Computing C in software keeps register shifts at 13–17 ops, and that is what makes `nettle-sha256` cost 2.07.
- **With the micro-op.** The ARM-shift micro-op from isa-coverage.md produces the ARM result and hands its carry-out to the flags unit in one op. Over all programs that is 0.12 ops per instruction (1.15 → 1.03). On the crypto and qrduino code it is the difference between about 2.0 and 1.0.

**Recommendation for Q3: the ARM-shift micro-op, as part of the flags unit.** The LE and Fmax cost still has to be measured when the core is synthesised (Phase 1.4). If it is too expensive, the fallback is a 5-op result plus a micro-op that only computes the carry-out.

## Decision

**Proposed for D1: strategy C, a hardware NZCV unit,** in this order:
1. **The unit itself:**
   - A 4-bit NZCV register, readable and writable as a CSR (for `MRS`/`MSR APSR`, the interrupt entry routine and RTOS context switches).
   - Flag-setting ALU ops carry a side-band "set flags" bit from the expander, like the last-of-sequence bit, so no new RISC-V encodings are needed for `ADDS`/`SUBS`/….
   - The ALU latches N and Z from the result, and C and V from the adder (C as NOT borrow for subtraction) or from the shifter for immediate shifts.
   - A branch-on-condition op for `B<cond>`.
   - C as carry-in for `ADCS`/`SBCS`.
2. **The ARM-shift micro-op (Q3),** with its carry-out into the unit.
3. **Fused `CMP` + `B<cond>`** as a later optimisation (0.08–0.10 ops per instruction).

Strategy A stays in the software model as the reference that lockstep checks against. The RTL skips A and B: they would need lookahead buffers, liveness logic and long sequences for every flag-setting instruction, all thrown away once C exists.

Consequences:
- **Interrupt entry** must save and restore NZCV, since a Thumb handler can change it (plan section 6).
- **RTOS context switches** must save NZCV for Thumb tasks.
- **Flag registers.** t3–t6 are no longer flag registers in the RTL, and are free for the expander or for RISC-V code.
- **Model.** The model gains a strategy C expansion and an NZCV register, so that the RTL expander can be checked against it bit-exactly (Phase 4).

## Caveats

- **One compiler, one input.** GCC 13 at `-O2` only; other compilers (Clang, Arm Compiler) schedule flags differently. Each benchmark runs once with one input.
- **Ops, not cycles.** Loads, taken branches and multi-cycle ops cost the same under every strategy, so they don't change the ranking, but the absolute numbers aren't cycle counts.
- **B is optimistic.** Its read side assumes the producer's kind is known for free. The real number would be higher, which only strengthens the conclusion.
- **Assumptions behind C.** Two C-family costs are assumptions rather than expansions the model emits. Without the micro-op, a register shift is costed as A's expansion minus the two N/Z ops. Fused `CMP #imm` with imm ≠ 0 is costed as one op, assuming an immediate form exists. Phase 4 replaces these with real expansions.

## Reproducing

```sh
make measure                                  # all programs, about 20 s on 8 cores
uv run python -m thumbv.measure coremark qrduino --json results.json
```

`--json` writes everything per benchmark: all costs, per-flag dead rates, fusion and `BL` counts, and register shifts by origin, amount and function. `tests/test_measure.py` checks the cost breakdown against the expander for every 16-bit encoding, and checks liveness on a hand-written program.
