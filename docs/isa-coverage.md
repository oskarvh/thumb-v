# ARMv6-M ISA coverage

The checklist for every ARMv6-M instruction encoding: what it does, which flags it touches, how it expands to RV32, and how far each one has got. This is the source of truth for the expander; the README's instruction table is a summary of it.

Encodings follow the ARMv6-M Architecture Reference Manual (ARM DDI 0419). The bit patterns below were checked against the GNU assembler from the arm-none-eabi 13.2.rel1 toolchain.

The model implements this table: the decode table in `model/thumbv/isa.py` (kept identical to the patterns here by `tests/test_isa.py`) and the expansions in `model/thumbv/expander.py`. `tests/test_lockstep_single.py` runs random instances of every encoding against Unicorn as a Cortex-M0 and compares registers, flags, next PC, memory and PRIMASK.

## Conventions

- **Encoding:** `0`/`1` are fixed bits, letters are fields. `ddd`, `nnn`, `mmm`, `ttt` are 3-bit low registers (r0–r7). `mmmm` is a 4-bit register (r0–r15). `D`/`N` is the top bit of a split 4-bit register field. `i…` is an immediate, `r…` a register list, `cccc` a condition. 32-bit encodings show both halfwords, first halfword first.
- **Flags:** `W:` lists the flags written, `R:` the flags read. Flags not listed are unchanged.
- **RV32 expansion:** register names refer to the mapped RISC-V registers (D2: r0–r3 → a0–a3, r4–r11 → s0–s7, r12 → t0, SP → sp, LR → ra). `PC` is the address of the Thumb instruction, which every op in the sequence carries. `t`, `u`, `m` are expander temporaries. `off` is an offset the expander computes from the encoding and `PC`.
- **Ops:** RV32 ops for the result only, without flag computation, with plain RV32IM. Flag costs depend on the strategy (D1) and are listed separately under [Flag computation](#flag-computation). `n` is the number of registers in a list.
- **Status:** `planned` → `modelled` (expansion in the model, passing single-instruction lockstep against Unicorn) → `RTL` (Phase 2+) → `verified` (RTL passes the exhaustive and lockstep tests).

### Expansion rules

Every sequence the expander emits follows these rules, which the hardware relies on:

- **PC-hold.** Every op executes with pc = the Thumb instruction's address, so `auipc` yields that address. ARM's "PC reads as PC+4" is added explicitly.
- **Only the last op may transfer control.** The ops of a sequence share one PC, so a sequence can't branch within itself. All flag logic is branch-free for this reason.
- **Link values** (`jal`/`jalr` with rd ≠ x0) are the Thumb address plus the Thumb instruction's length: PC+2 for `BLX`, PC+4 for `BL` (Q2). LR bit 0 stays clear unless the model's `exact_lr` option is set (Q1).
- **Temporaries** are t1, t2 and a4–a7, only live within one sequence. Flags live in t3–t6 (see [Flag computation](#flag-computation)).
- **No ordering constraint on ARM-visible writes,** since interrupts are only taken between Thumb instructions (D3). Where the destination is also a source, the result goes to a temporary first so the flags can still read the original operands.

## Shift (immediate), add, subtract, move, compare

| Encoding | Instruction | Flags | RV32 expansion | Ops | Notes | Status |
|---|---|---|---|---|---|---|
| `00000 iiiii mmm ddd` | `LSLS rd, rm, #imm5` (imm5 ≠ 0) | W: NZC | `slli rd, rm, imm5` | 1 | C = rm[32−imm5] | modelled |
| `00000 00000 mmm ddd` | `MOVS rd, rm` | W: NZ | `addi rd, rm, 0` | 1 | The LSLS #0 encoding | modelled |
| `00001 iiiii mmm ddd` | `LSRS rd, rm, #imm5` | W: NZC | `srli rd, rm, imm5`; imm5 = 0 means #32: `addi rd, x0, 0` | 1 | C = rm[imm5−1], or rm[31] for #32 | modelled |
| `00010 iiiii mmm ddd` | `ASRS rd, rm, #imm5` | W: NZC | `srai rd, rm, imm5`; #32: `srai rd, rm, 31` | 1 | C as for LSRS | modelled |
| `0001100 mmm nnn ddd` | `ADDS rd, rn, rm` | W: NZCV | `add rd, rn, rm` | 1 | | modelled |
| `0001101 mmm nnn ddd` | `SUBS rd, rn, rm` | W: NZCV | `sub rd, rn, rm` | 1 | | modelled |
| `0001110 iii nnn ddd` | `ADDS rd, rn, #imm3` | W: NZCV | `addi rd, rn, imm3` | 1 | | modelled |
| `0001111 iii nnn ddd` | `SUBS rd, rn, #imm3` | W: NZCV | `addi rd, rn, -imm3` | 1 | | modelled |
| `00100 ddd iiiiiiii` | `MOVS rd, #imm8` | W: NZ | `addi rd, x0, imm8` | 1 | | modelled |
| `00101 nnn iiiiiiii` | `CMP rn, #imm8` | W: NZCV | — | 0 | Result only feeds the flags | modelled |
| `00110 ddd iiiiiiii` | `ADDS rdn, #imm8` | W: NZCV | `addi rdn, rdn, imm8` | 1 | | modelled |
| `00111 ddd iiiiiiii` | `SUBS rdn, #imm8` | W: NZCV | `addi rdn, rdn, -imm8` | 1 | | modelled |

## Data processing (register)

All of these are `010000 oooo mmm ddd` with a 4-bit opcode.

| Encoding | Instruction | Flags | RV32 expansion | Ops | Notes | Status |
|---|---|---|---|---|---|---|
| `0100000000 mmm ddd` | `ANDS rdn, rm` | W: NZ | `and rdn, rdn, rm` | 1 | | modelled |
| `0100000001 mmm ddd` | `EORS rdn, rm` | W: NZ | `xor rdn, rdn, rm` | 1 | | modelled |
| `0100000010 mmm ddd` | `LSLS rdn, rm` | W: NZC | `andi t, rm, 255; sll u, rdn, t; sltiu t, t, 32; sub t, x0, t; and rdn, u, t` | 5 | ARM shifts by rm[7:0]; ≥ 32 gives 0. C unchanged if rm[7:0] = 0 | modelled |
| `0100000011 mmm ddd` | `LSRS rdn, rm` | W: NZC | as LSLS with `srl` | 5 | As LSLS | modelled |
| `0100000100 mmm ddd` | `ASRS rdn, rm` | W: NZC | `andi t, rm, 255; sltiu u, t, 32; addi u, u, -1; or t, t, u; sra rdn, rdn, t` | 5 | Amounts ≥ 32 saturate to 31 | modelled |
| `0100000101 mmm ddd` | `ADCS rdn, rm` | R: C, W: NZCV | `add rdn, rdn, rm; add rdn, rdn, C` | 2 | Assumes C held as 0/1 | modelled |
| `0100000110 mmm ddd` | `SBCS rdn, rm` | R: C, W: NZCV | `sub rdn, rdn, rm; add rdn, rdn, C; addi rdn, rdn, -1` | 3 | rdn − rm − NOT(C) | modelled |
| `0100000111 mmm ddd` | `RORS rdn, rm` | W: NZC | `andi t, rm, 31; srl u, rdn, t; sub t, x0, t; sll t, rdn, t; or rdn, u, t` | 5 | 1 with Zbb `ror`. C = result[31] if rm[7:0] ≠ 0 | modelled |
| `0100001000 mmm nnn` | `TST rn, rm` | W: NZ | — | 0 | Result only feeds the flags | modelled |
| `0100001001 nnn ddd` | `RSBS rd, rn, #0` | W: NZCV | `sub rd, x0, rn` | 1 | Also written `NEGS` | modelled |
| `0100001010 mmm nnn` | `CMP rn, rm` | W: NZCV | — | 0 | | modelled |
| `0100001011 mmm nnn` | `CMN rn, rm` | W: NZCV | — | 0 | | modelled |
| `0100001100 mmm ddd` | `ORRS rdn, rm` | W: NZ | `or rdn, rdn, rm` | 1 | | modelled |
| `0100001101 nnn ddd` | `MULS rdm, rn, rdm` | W: NZ | `mul rdm, rn, rdm` | 1 | Needs M. C and V unchanged | modelled |
| `0100001110 mmm ddd` | `BICS rdn, rm` | W: NZ | `xori t, rm, -1; and rdn, rdn, t` | 2 | 1 with Zbb `andn` | modelled |
| `0100001111 mmm ddd` | `MVNS rd, rm` | W: NZ | `xori rd, rm, -1` | 1 | | modelled |

## Special data processing and branch exchange

| Encoding | Instruction | Flags | RV32 expansion | Ops | Notes | Status |
|---|---|---|---|---|---|---|
| `01000100 D mmmm ddd` | `ADD rdn, rm` (rdn = D:ddd) | — | `add rdn, rdn, rm` | 1 | rm = PC: `auipc t, 0; addi t, t, 4; add rdn, rdn, t` (3). rdn = PC is a branch: `auipc t, 0; add t, t, rm; jalr x0, 4(t)` (3). Both PC: UNPREDICTABLE | modelled |
| `01000101 N mmmm nnn` | `CMP rn, rm` (high registers) | W: NZCV | — | 0 | UNPREDICTABLE if both low or either is PC | modelled |
| `01000110 D mmmm ddd` | `MOV rd, rm` (rd = D:ddd) | — | `addi rd, rm, 0` | 1 | rm = PC: `auipc rd, 0; addi rd, rd, 4` (2). rd = PC: `jalr x0, 0(rm)` (1). GAS emits `MOV r8, r8` (0x46C0) for `NOP` on Cortex-M0 | modelled |
| `010001110 mmmm 000` | `BX rm` | — | `jalr x0, 0(rm)` | 1 | Thumb-V ignores bit 0 (a real Cortex-M faults on bit 0 = 0); the address decides the decoder. ARM-only: EXC_RETURN values fault on fetch and enter the firmware | modelled |
| `010001111 mmmm 000` | `BLX rm` | — | `jalr ra, 0(rm)` | 1 | LR = PC+2, bit 0 clear (Q1). Needs a PC+2 link value from the core (Q2); fallback `addi t, rm, 0; auipc ra, 0; addi ra, ra, 2; jalr x0, 0(t)` (4). rm = PC: UNPREDICTABLE | modelled |

## Loads and stores

| Encoding | Instruction | Flags | RV32 expansion | Ops | Notes | Status |
|---|---|---|---|---|---|---|
| `01001 ttt iiiiiiii` | `LDR rt, [PC, #imm8*4]` | — | `auipc t, 0; lw rt, off(t)` | 2 | off = Align(PC+4, 4) − PC + imm8·4 ≤ 1024 | modelled |
| `0101000 mmm nnn ttt` | `STR rt, [rn, rm]` | — | `add t, rn, rm; sw rt, 0(t)` | 2 | | modelled |
| `0101001 mmm nnn ttt` | `STRH rt, [rn, rm]` | — | `add t, rn, rm; sh rt, 0(t)` | 2 | | modelled |
| `0101010 mmm nnn ttt` | `STRB rt, [rn, rm]` | — | `add t, rn, rm; sb rt, 0(t)` | 2 | | modelled |
| `0101011 mmm nnn ttt` | `LDRSB rt, [rn, rm]` | — | `add t, rn, rm; lb rt, 0(t)` | 2 | | modelled |
| `0101100 mmm nnn ttt` | `LDR rt, [rn, rm]` | — | `add t, rn, rm; lw rt, 0(t)` | 2 | | modelled |
| `0101101 mmm nnn ttt` | `LDRH rt, [rn, rm]` | — | `add t, rn, rm; lhu rt, 0(t)` | 2 | | modelled |
| `0101110 mmm nnn ttt` | `LDRB rt, [rn, rm]` | — | `add t, rn, rm; lbu rt, 0(t)` | 2 | | modelled |
| `0101111 mmm nnn ttt` | `LDRSH rt, [rn, rm]` | — | `add t, rn, rm; lh rt, 0(t)` | 2 | | modelled |
| `01100 iiiii nnn ttt` | `STR rt, [rn, #imm5*4]` | — | `sw rt, imm(rn)` | 1 | | modelled |
| `01101 iiiii nnn ttt` | `LDR rt, [rn, #imm5*4]` | — | `lw rt, imm(rn)` | 1 | | modelled |
| `01110 iiiii nnn ttt` | `STRB rt, [rn, #imm5]` | — | `sb rt, imm(rn)` | 1 | | modelled |
| `01111 iiiii nnn ttt` | `LDRB rt, [rn, #imm5]` | — | `lbu rt, imm(rn)` | 1 | | modelled |
| `10000 iiiii nnn ttt` | `STRH rt, [rn, #imm5*2]` | — | `sh rt, imm(rn)` | 1 | | modelled |
| `10001 iiiii nnn ttt` | `LDRH rt, [rn, #imm5*2]` | — | `lhu rt, imm(rn)` | 1 | | modelled |
| `10010 ttt iiiiiiii` | `STR rt, [SP, #imm8*4]` | — | `sw rt, imm(sp)` | 1 | | modelled |
| `10011 ttt iiiiiiii` | `LDR rt, [SP, #imm8*4]` | — | `lw rt, imm(sp)` | 1 | | modelled |

ARMv6-M faults on unaligned word and halfword accesses. VexRiscv can be configured to trap on misaligned accesses too, and the trap handler turns that into a HardFault in ARM-only mode.

## Address generation and stack adjustment

| Encoding | Instruction | Flags | RV32 expansion | Ops | Notes | Status |
|---|---|---|---|---|---|---|
| `10100 ddd iiiiiiii` | `ADR rd, label` (`ADD rd, PC, #imm8*4`) | — | `auipc rd, 0; addi rd, rd, off` | 2 | off as for `LDR [PC]` | modelled |
| `10101 ddd iiiiiiii` | `ADD rd, SP, #imm8*4` | — | `addi rd, sp, imm` | 1 | | modelled |
| `101100000 iiiiiii` | `ADD SP, SP, #imm7*4` | — | `addi sp, sp, imm` | 1 | | modelled |
| `101100001 iiiiiii` | `SUB SP, SP, #imm7*4` | — | `addi sp, sp, -imm` | 1 | | modelled |

## Miscellaneous

| Encoding | Instruction | Flags | RV32 expansion | Ops | Notes | Status |
|---|---|---|---|---|---|---|
| `1011001000 mmm ddd` | `SXTH rd, rm` | — | `slli rd, rm, 16; srai rd, rd, 16` | 2 | 1 with Zbb `sext.h` | modelled |
| `1011001001 mmm ddd` | `SXTB rd, rm` | — | `slli rd, rm, 24; srai rd, rd, 24` | 2 | 1 with Zbb `sext.b` | modelled |
| `1011001010 mmm ddd` | `UXTH rd, rm` | — | `slli rd, rm, 16; srli rd, rd, 16` | 2 | 1 with Zbb `zext.h` | modelled |
| `1011001011 mmm ddd` | `UXTB rd, rm` | — | `andi rd, rm, 255` | 1 | | modelled |
| `1011010 M rrrrrrrr` | `PUSH {list}` (M: also LR) | — | `sw` each register below SP, then `addi sp, sp, -4n` | n+1 | Lowest register at the lowest address. SP is written last | modelled |
| `10110110011 1 0010` | `CPSID i` | — | `csrci mstatus, 8` | 1 | Sets PRIMASK = clears `mstatus.MIE` (Q6) | modelled |
| `10110110011 0 0010` | `CPSIE i` | — | `csrsi mstatus, 8` | 1 | | modelled |
| `1011101000 mmm ddd` | `REV rd, rm` | — | byte swap with shifts, masks and ORs | ~11 | 1 with Zbb `rev8` | modelled |
| `1011101001 mmm ddd` | `REV16 rd, rm` | — | `((x >> 8) & 0x00FF00FF) \| ((x & 0x00FF00FF) << 8)` | ~7 | 2 with Zbb (`rev8; rori 16`) | modelled |
| `1011101011 mmm ddd` | `REVSH rd, rm` | — | `slli t, rm, 24; srai t, t, 16; srli u, rm, 8; andi u, u, 255; or rd, t, u` | 5 | 2 with Zbb (`rev8; srai 16`) | modelled |
| `1011110 P rrrrrrrr` | `POP {list}` (P: also PC) | — | `lw` each register, then `addi sp, sp, 4n`; with PC: load PC into `t`, then `jalr x0, 0(t)` | n+1, +1 with PC | ARM-only: PC may be an EXC_RETURN value | modelled |
| `10111110 iiiiiiii` | `BKPT #imm8` | — | `ebreak` | 1 | | modelled |
| `1011111100000000` | `NOP` | — | `addi x0, x0, 0` | 1 | | modelled |
| `1011111100010000` | `YIELD` | — | `addi x0, x0, 0` | 1 | | modelled |
| `1011111100100000` | `WFE` | — | `addi x0, x0, 0` | 1 | Q5 | modelled |
| `1011111100110000` | `WFI` | — | `wfi` | 1 | | modelled |
| `1011111101000000` | `SEV` | — | `addi x0, x0, 0` | 1 | Single core, so no other observer | modelled |

The other `1011` encodings are ARMv7-M instructions (`CBZ`/`CBNZ`, `IT`) or unallocated, and are undefined on ARMv6-M. Compilers targeting Cortex-M0 never emit them.

## Load and store multiple

| Encoding | Instruction | Flags | RV32 expansion | Ops | Notes | Status |
|---|---|---|---|---|---|---|
| `11000 nnn rrrrrrrr` | `STM rn!, {list}` | — | `sw` each register, then `addi rn, rn, 4n` | n+1 | If rn is in the list it must be the lowest; the original value is stored | modelled |
| `11001 nnn rrrrrrrr` | `LDM rn{!}, {list}` | — | `lw` each register, then `addi rn, rn, 4n` | n+1, or n if rn is in the list | Writeback only if rn isn't in the list; then rn is loaded last | modelled |

## Branches and exception generation

| Encoding | Instruction | Flags | RV32 expansion | Ops | Notes | Status |
|---|---|---|---|---|---|---|
| `1101 cccc iiiiiiii` (cccc ≠ 111x) | `B<cond> label` | R: per condition | strategy A: `bne`/`beq`/`bltu`/`bgeu` on the flag registers | 1–3 | Target PC + 4 + imm8·2, within RISC-V's ±4 KiB branch range. See [Flag computation](#flag-computation) | modelled |
| `11011110 iiiiiiii` | `UDF #imm8` | — | an illegal RV32 encoding (e.g. `0x00000000`) | 1 | Illegal-instruction trap | modelled |
| `11011111 iiiiiiii` | `SVC #imm8` | — | `ecall` | 1 | The handler reads imm8 from the instruction at `mepc` and resumes at `mepc`+2 | modelled |
| `11100 iiiiiiiiiii` | `B label` | — | `jal x0, off` | 1 | Target PC + 4 + imm11·2 (±2 KiB) | modelled |

## 32-bit instructions

| Encoding | Instruction | Flags | RV32 expansion | Ops | Notes | Status |
|---|---|---|---|---|---|---|
| `11110 s iiiiiiiiii`, `11 j 1 k iiiiiiiiiii` | `BL label` | — | `jal ra, off` | 1–2 | ±16 MiB. LR = PC+4, bit 0 clear (Q1). Beyond `jal`'s ±1 MiB: `auipc t, hi; jalr ra, lo(t)` (2). With `exact_lr`: `auipc ra, 0; addi ra, ra, 5` and a non-linking jump (3–4) | modelled |
| `111100111000 nnnn`, `10001000 ssssssss` | `MSR spec_reg, rn` | W: NZCV (APSR) | APSR: unpack into the flag registers. PRIMASK: update `mstatus.MIE`. Others: trap to the handler | 7 / 5 / 1 | Q7 | modelled |
| `1111001111101111`, `1000 dddd ssssssss` | `MRS rd, spec_reg` | R: NZCV (APSR) | APSR: pack the flags into bits 31:28. PRIMASK: read `mstatus.MIE`. Others: trap to the handler | 7 / 4 / 1 | Q7 | modelled |
| `1111001110111111`, `100011110100 oooo` | `DSB` | — | `fence` | 1 | | modelled |
| `1111001110111111`, `100011110101 oooo` | `DMB` | — | `fence` | 1 | | modelled |
| `1111001110111111`, `100011110110 oooo` | `ISB` | — | `fence.i` | 1 | | modelled |

All other 32-bit encodings (first halfword `11101`, `11110` or `11111` not matching the above) are undefined on ARMv6-M and raise an illegal-instruction trap. ARMv6-M has no 32-bit `UDF.W`; the assembler rejects it for Cortex-M0.

## Summary

83 encodings. Counting the result only, with plain RV32IM:

| Result cost | Encodings |
|---|---|
| 0 ops (only the flags are needed) | 5 (`CMP` ×3, `CMN`, `TST`) |
| 1 op | 46 |
| 1 op or more, depending on branch range, Q2 or the flag strategy | 3 (`BL`, `BLX`, `B<cond>`) |
| 2 or more ops | 29 (register-offset loads and stores, register shifts, `PUSH`/`POP`/`LDM`/`STM`, byte reversal, extends, `ADCS`/`SBCS`, `BICS`, `ADR`, `LDR [PC]`, `MSR`/`MRS`) |

This is a static count. What matters for performance is the dynamic mix, which Phase 0.7 measures on CoreMark and Embench.

## Flag computation

The model implements strategy A (eager software flags) with each flag held as 0 or 1 in its own register: N in t3, Z in t4, C in t5, V in t6. This is a reference for correctness, not tuned for speed. The 0/1 form makes conditional branches cheap and `MRS`/`MSR APSR` a simple pack/unpack.

| Flags | Ops | Sequence |
|---|---|---|
| N, Z | 2 | `srli N, res, 31; sltiu Z, res, 1` |
| C after add | 1 | `sltu C, res, a` |
| C after subtract or compare | 2 | `sltu C, a, b; xori C, C, 1` (ARM's C is NOT borrow) |
| V after add | 4 | `xor t, res, a; xor u, res, b; and t, t, u; srli V, t, 31` |
| V after subtract or compare | 4 | `xor t, a, b; xor u, a, res; and t, t, u; srli V, t, 31` |
| C after a shift by an immediate | 2 | `srli C, rm, k; andi C, C, 1` |
| C after a shift by a register | ~10 | candidate bit, masked for amounts > 32, kept unchanged for an amount of 0 |
| C and V after `ADCS` | ~9 | carry out of both additions, then V as for add. `SBCS` is `ADCS` with NOT(rm) |

Measured totals per instruction, result plus flags:

| Instruction | Ops | Result only |
|---|---|---|
| `MOVS`, `ANDS`, `EORS`, `ORRS`, `MVNS`, `MULS`, `TST` | 3 | 1 (0 for `TST`) |
| `LSLS`/`LSRS`/`ASRS` by an immediate | 5 | 1 |
| `ADDS`, `CMN` | 8–9 | 1 (0 for `CMN`) |
| `SUBS`, `CMP`, `RSBS` | 9–10 | 1 (0 for `CMP`) |
| `ADCS` / `SBCS` | 12 / 13 | 2 / 3 |
| `RORS` | 15 | 5 |
| `LSLS`/`LSRS`/`ASRS` by a register | 18–19 | 5 |

The extra op in the ranges is a move from a temporary when the destination is also a source. An `ADDS` costs 8–9 ops against 1 for the result alone; this is the main input to D1.

Conditional branches:

| Condition | Ops | Sequence |
|---|---|---|
| EQ, NE, CS, CC, MI, PL, VS, VC | 1 | `bne`/`beq` of one flag against x0 |
| HI, LS | 1 | `bltu Z, C` / `bgeu Z, C` (C = 1 and Z = 0 is the only case with Z < C) |
| GE, LT | 1 | `beq N, V` / `bne N, V` |
| GT, LE | 3 | `xor t, N, V; or t, t, Z; beq`/`bne t, x0` |

## Register shifts

`LSLS`, `LSRS`, `ASRS` and `RORS` with a register amount (`rdn, rm`) differ from RISC-V's `sll`/`srl`/`sra`. ARM uses the low byte of `rm` as the amount (0–255); RISC-V uses only the low 5 bits (0–31).

| Amount (rm[7:0]) | ARM `LSLS`/`LSRS` | ARM `ASRS` | ARM `RORS` | RISC-V |
|---|---|---|---|---|
| 0 | unchanged, C unchanged | unchanged, C unchanged | unchanged, C unchanged | unchanged |
| 1–31 | normal shift | normal shift | normal rotate | same as ARM |
| 32 | 0 (C = bit 0 or bit 31 of rdn) | sign fill (C = sign) | unchanged (C = bit 31) | shift by 0: wrong for shifts |
| 33–255 | 0 (C = 0) | sign fill (C = sign) | rotate by amount mod 32 | shift by amount mod 32: wrong for shifts |

Amounts of 32 and more can't be ignored. C code rarely produces them (shifting by ≥ 32 is undefined behaviour in C), but ARM's hand-written runtime relies on them: libgcc's 64-bit shifts (`__aeabi_llsl` and friends) shift by `n − 32` and count on a "negative" amount giving 0.

**Current plan: plain RV32I, 5 ops for the result.** For `LSLS rdn, rm`:

```
andi  t, rm, 255      # ARM's amount: low byte
sll   u, rdn, t       # RISC-V shift (uses t mod 32)
sltiu t, t, 32        # 1 if amount < 32, else 0
sub   t, x0, t        # all ones or all zeros
and   rdn, u, t       # zero the result if amount >= 32
```

Under strategy A the C flag adds roughly 5 more ops (amounts of 0, 32 and > 32 are special cases).

### Alternative: an ARM-shift micro-op

A custom instruction in the `custom-0` opcode space with ARM semantics: amount from rs2[7:0], result forced to 0 (or to the sign fill for `ASRS`) when any of amount bits 7:5 are set. Only the expander emits it; RISC-V software never sees it.

| Option | Result ops | Notes |
|---|---|---|
| Plain RV32I | 5 | No core change. **Current choice.** |
| Zbb `minu` | 3 for `ASRS`, ~5 for `LSLS`/`LSRS` | Only worth it if Zbb is added for other reasons (Q4) |
| Zbb + Zicond `czero.eqz` | ~4 | Two extensions for a small gain |
| ARM-shift micro-op | 1 | Core change in the shifter. With the hardware flags unit (D1 option C), the shifter would also supply C, making it 1 op including flags |

The micro-op is only worth doing if both of these come out in its favour:

1. **Dynamic frequency (Phase 0.7).** Count register shifts per benchmark, with integer and soft-float code separately. The Cortex-M0 has no FPU, so floating-point code runs libgcc's soft-float routines, which use variable shifts heavily for normalisation; 64-bit integer shifts also go through libgcc. Embench's float-heavy programs (`nbody`, `minver`, `cubic`, `st`) are the likely worst case. From the counts, estimate the overall slowdown of the 5-op expansion.
2. **Hardware cost (Phase 1, once VexRiscv's shifter is known).** The logic is small (an OR of three bits and a mux after the shifter), but it needs measuring:
   - **LEs:** synthesise VexRiscv's shifter with and without the change, and record the difference in `docs/resources.md`.
   - **Fmax:** the extra mux sits after the shifter, which may be on the critical path. Compare timing reports with and without.
   - **Decode:** whether VexRiscv's plugin structure lets a custom opcode reuse the existing shifter cleanly, or needs a separate unit.
   - **Verification:** another op the exhaustive expander test and the lockstep tests must cover.

Unless the measured slowdown is significant and the hardware cost is clearly small, the 5-op expansion stays.

## UNPREDICTABLE encodings

ARMv6-M leaves some encodings UNPREDICTABLE, e.g. `ADD PC, PC`, `BLX PC`, a high-register `CMP` with two low registers, or empty register lists. Thumb-V does whatever is cheapest in the expander and documents it here once modelled. The lockstep tests don't generate them, since Unicorn's behaviour for them isn't a meaningful reference.

## Open questions

| # | Question | Notes |
|---|---|---|
| Q1 | Must `BL`/`BLX` set bit 0 of LR? | **Decided: no.** `BL` and `BLX` are function calls (Branch with Link, and Branch with Link and Exchange): they write the return address to LR. On ARM, bit 0 of a code address selects Thumb, so a Cortex-M stores `return \| 1`. With address-based mode, bit 0 is never needed to return correctly, and leaving it clear makes `BL` a single `jal`. Only code that inspects LR's value sees a difference. The model keeps an `exact_lr` option (off by default) that sets bit 0, used by the lockstep tests to compare exactly against Unicorn; switching later means making it the default. |
| Q2 | Can the core produce a PC+2 link value for `BLX rm`? | The model's rule: a link value is the Thumb instruction's address plus its length (PC+2 for `BLX`, PC+4 for `BL`). VexRiscv computes the link as `pc + (isRvc ? 2 : 4)`, so marking 16-bit Thumb ops as RVC-like should give this for free. Confirm in Phase 1.3; doesn't block the model. |
| Q3 | Are register shifts common enough to need a better expansion? | **Open, leaning towards the 5-op expansion.** The ARM-shift micro-op is documented under [Register shifts](#register-shifts), with what has to be measured first: dynamic frequency in 0.7, hardware cost (LEs, Fmax) in Phase 1. |
| Q4 | Add Zbb to the core? | Reduces extends, `REV*`, `RORS` and `BICS` to 1–2 ops. Check whether VexRiscv has a bit-manipulation plugin, and its LE cost. |
| Q5 | `WFE`: `nop` or `wfi`? | **Modelled as `nop`.** Always correct for a single core with no event sources, at the cost of busy-waiting. Revisit if power matters. |
| Q6 | Is `mstatus.MIE` a faithful PRIMASK? | PRIMASK masks all configurable-priority interrupts but not NMI or HardFault. Fine for mixed mode; check for ARM-only mode. |
| Q7 | Which special registers does `MRS`/`MSR` handle inline? | **Modelled as proposed:** APSR (SYSm 0) and PRIMASK (SYSm 16) inline, 7 and 4–5 ops. Everything else (the other xPSR views, MSP, PSP, CONTROL) emits an illegal instruction and traps to the handler, which emulates it. Revisit for ARM-only mode in Phase 6. |
