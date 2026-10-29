# ARMv6-M ISA coverage

The checklist for every ARMv6-M instruction encoding: what it does, which flags it touches, how it expands to RV32, and how far each one has got. This is the source of truth for the expander; the README's instruction table is a summary of it.

Encodings follow the ARMv6-M Architecture Reference Manual (ARM DDI 0419). The bit patterns below were checked against the GNU assembler from the arm-none-eabi 13.2.rel1 toolchain. Phase 0.3 turns this table into the model's decode table, with a test that keeps the two in sync.

## Conventions

- **Encoding:** `0`/`1` are fixed bits, letters are fields. `ddd`, `nnn`, `mmm`, `ttt` are 3-bit low registers (r0–r7). `mmmm` is a 4-bit register (r0–r15). `D`/`N` is the top bit of a split 4-bit register field. `i…` is an immediate, `r…` a register list, `cccc` a condition. 32-bit encodings show both halfwords, first halfword first.
- **Flags:** `W:` lists the flags written, `R:` the flags read. Flags not listed are unchanged.
- **RV32 expansion:** register names refer to the mapped RISC-V registers (D2: r0–r3 → a0–a3, r4–r11 → s0–s7, r12 → t0, SP → sp, LR → ra). `PC` is the address of the Thumb instruction, which every op in the sequence carries. `t`, `u`, `m` are expander temporaries. `off` is an offset the expander computes from the encoding and `PC`.
- **Ops:** RV32 ops for the result only, without flag computation, with plain RV32IM. Flag costs depend on the strategy (D1) and are listed separately under [Flag computation](#flag-computation). `n` is the number of registers in a list.
- **Status:** `planned` → `modelled` (0.3) → `RTL` (Phase 2+) → `verified` (exhaustive and lockstep tests pass).

## Shift (immediate), add, subtract, move, compare

| Encoding | Instruction | Flags | RV32 expansion | Ops | Notes | Status |
|---|---|---|---|---|---|---|
| `00000 iiiii mmm ddd` | `LSLS rd, rm, #imm5` (imm5 ≠ 0) | W: NZC | `slli rd, rm, imm5` | 1 | C = rm[32−imm5] | planned |
| `00000 00000 mmm ddd` | `MOVS rd, rm` | W: NZ | `addi rd, rm, 0` | 1 | The LSLS #0 encoding | planned |
| `00001 iiiii mmm ddd` | `LSRS rd, rm, #imm5` | W: NZC | `srli rd, rm, imm5`; imm5 = 0 means #32: `addi rd, x0, 0` | 1 | C = rm[imm5−1], or rm[31] for #32 | planned |
| `00010 iiiii mmm ddd` | `ASRS rd, rm, #imm5` | W: NZC | `srai rd, rm, imm5`; #32: `srai rd, rm, 31` | 1 | C as for LSRS | planned |
| `0001100 mmm nnn ddd` | `ADDS rd, rn, rm` | W: NZCV | `add rd, rn, rm` | 1 | | planned |
| `0001101 mmm nnn ddd` | `SUBS rd, rn, rm` | W: NZCV | `sub rd, rn, rm` | 1 | | planned |
| `0001110 iii nnn ddd` | `ADDS rd, rn, #imm3` | W: NZCV | `addi rd, rn, imm3` | 1 | | planned |
| `0001111 iii nnn ddd` | `SUBS rd, rn, #imm3` | W: NZCV | `addi rd, rn, -imm3` | 1 | | planned |
| `00100 ddd iiiiiiii` | `MOVS rd, #imm8` | W: NZ | `addi rd, x0, imm8` | 1 | | planned |
| `00101 nnn iiiiiiii` | `CMP rn, #imm8` | W: NZCV | — | 0 | Result only feeds the flags | planned |
| `00110 ddd iiiiiiii` | `ADDS rdn, #imm8` | W: NZCV | `addi rdn, rdn, imm8` | 1 | | planned |
| `00111 ddd iiiiiiii` | `SUBS rdn, #imm8` | W: NZCV | `addi rdn, rdn, -imm8` | 1 | | planned |

## Data processing (register)

All of these are `010000 oooo mmm ddd` with a 4-bit opcode.

| Encoding | Instruction | Flags | RV32 expansion | Ops | Notes | Status |
|---|---|---|---|---|---|---|
| `0100000000 mmm ddd` | `ANDS rdn, rm` | W: NZ | `and rdn, rdn, rm` | 1 | | planned |
| `0100000001 mmm ddd` | `EORS rdn, rm` | W: NZ | `xor rdn, rdn, rm` | 1 | | planned |
| `0100000010 mmm ddd` | `LSLS rdn, rm` | W: NZC | `andi t, rm, 255; sll u, rdn, t; sltiu t, t, 32; sub t, x0, t; and rdn, u, t` | 5 | ARM shifts by rm[7:0]; ≥ 32 gives 0. C unchanged if rm[7:0] = 0 | planned |
| `0100000011 mmm ddd` | `LSRS rdn, rm` | W: NZC | as LSLS with `srl` | 5 | As LSLS | planned |
| `0100000100 mmm ddd` | `ASRS rdn, rm` | W: NZC | `andi t, rm, 255; sltiu u, t, 32; addi u, u, -1; or t, t, u; sra rdn, rdn, t` | 5 | Amounts ≥ 32 saturate to 31 | planned |
| `0100000101 mmm ddd` | `ADCS rdn, rm` | R: C, W: NZCV | `add rdn, rdn, rm; add rdn, rdn, C` | 2 | Assumes C held as 0/1 | planned |
| `0100000110 mmm ddd` | `SBCS rdn, rm` | R: C, W: NZCV | `sub rdn, rdn, rm; add rdn, rdn, C; addi rdn, rdn, -1` | 3 | rdn − rm − NOT(C) | planned |
| `0100000111 mmm ddd` | `RORS rdn, rm` | W: NZC | `andi t, rm, 31; srl u, rdn, t; sub t, x0, t; sll t, rdn, t; or rdn, u, t` | 5 | 1 with Zbb `ror`. C = result[31] if rm[7:0] ≠ 0 | planned |
| `0100001000 mmm nnn` | `TST rn, rm` | W: NZ | — | 0 | Result only feeds the flags | planned |
| `0100001001 nnn ddd` | `RSBS rd, rn, #0` | W: NZCV | `sub rd, x0, rn` | 1 | Also written `NEGS` | planned |
| `0100001010 mmm nnn` | `CMP rn, rm` | W: NZCV | — | 0 | | planned |
| `0100001011 mmm nnn` | `CMN rn, rm` | W: NZCV | — | 0 | | planned |
| `0100001100 mmm ddd` | `ORRS rdn, rm` | W: NZ | `or rdn, rdn, rm` | 1 | | planned |
| `0100001101 nnn ddd` | `MULS rdm, rn, rdm` | W: NZ | `mul rdm, rn, rdm` | 1 | Needs M. C and V unchanged | planned |
| `0100001110 mmm ddd` | `BICS rdn, rm` | W: NZ | `xori t, rm, -1; and rdn, rdn, t` | 2 | 1 with Zbb `andn` | planned |
| `0100001111 mmm ddd` | `MVNS rd, rm` | W: NZ | `xori rd, rm, -1` | 1 | | planned |

## Special data processing and branch exchange

| Encoding | Instruction | Flags | RV32 expansion | Ops | Notes | Status |
|---|---|---|---|---|---|---|
| `01000100 D mmmm ddd` | `ADD rdn, rm` (rdn = D:ddd) | — | `add rdn, rdn, rm` | 1 | rm = PC: `auipc t, 0; addi t, t, 4; add rdn, rdn, t` (3). rdn = PC is a branch: `auipc t, 0; add t, t, rm; jalr x0, 4(t)` (3). Both PC: UNPREDICTABLE | planned |
| `01000101 N mmmm nnn` | `CMP rn, rm` (high registers) | W: NZCV | — | 0 | UNPREDICTABLE if both low or either is PC | planned |
| `01000110 D mmmm ddd` | `MOV rd, rm` (rd = D:ddd) | — | `addi rd, rm, 0` | 1 | rm = PC: `auipc rd, 0; addi rd, rd, 4` (2). rd = PC: `jalr x0, 0(rm)` (1). GAS emits `MOV r8, r8` (0x46C0) for `NOP` on Cortex-M0 | planned |
| `010001110 mmmm 000` | `BX rm` | — | `jalr x0, 0(rm)` | 1 | Thumb-V ignores bit 0 (a real Cortex-M faults on bit 0 = 0); the address decides the decoder. ARM-only: EXC_RETURN values fault on fetch and enter the firmware | planned |
| `010001111 mmmm 000` | `BLX rm` | — | `jalr ra, 0(rm)` | 1–4 | LR = (PC+2)\|1. 1 op if the link is PC+2 and bit 0 may stay clear (Q1, Q2); otherwise `addi t, rm, 0; auipc ra, 0; addi ra, ra, 3; jalr x0, 0(t)` (4). rm = PC: UNPREDICTABLE | planned |

## Loads and stores

| Encoding | Instruction | Flags | RV32 expansion | Ops | Notes | Status |
|---|---|---|---|---|---|---|
| `01001 ttt iiiiiiii` | `LDR rt, [PC, #imm8*4]` | — | `auipc t, 0; lw rt, off(t)` | 2 | off = Align(PC+4, 4) − PC + imm8·4 ≤ 1024 | planned |
| `0101000 mmm nnn ttt` | `STR rt, [rn, rm]` | — | `add t, rn, rm; sw rt, 0(t)` | 2 | | planned |
| `0101001 mmm nnn ttt` | `STRH rt, [rn, rm]` | — | `add t, rn, rm; sh rt, 0(t)` | 2 | | planned |
| `0101010 mmm nnn ttt` | `STRB rt, [rn, rm]` | — | `add t, rn, rm; sb rt, 0(t)` | 2 | | planned |
| `0101011 mmm nnn ttt` | `LDRSB rt, [rn, rm]` | — | `add t, rn, rm; lb rt, 0(t)` | 2 | | planned |
| `0101100 mmm nnn ttt` | `LDR rt, [rn, rm]` | — | `add t, rn, rm; lw rt, 0(t)` | 2 | | planned |
| `0101101 mmm nnn ttt` | `LDRH rt, [rn, rm]` | — | `add t, rn, rm; lhu rt, 0(t)` | 2 | | planned |
| `0101110 mmm nnn ttt` | `LDRB rt, [rn, rm]` | — | `add t, rn, rm; lbu rt, 0(t)` | 2 | | planned |
| `0101111 mmm nnn ttt` | `LDRSH rt, [rn, rm]` | — | `add t, rn, rm; lh rt, 0(t)` | 2 | | planned |
| `01100 iiiii nnn ttt` | `STR rt, [rn, #imm5*4]` | — | `sw rt, imm(rn)` | 1 | | planned |
| `01101 iiiii nnn ttt` | `LDR rt, [rn, #imm5*4]` | — | `lw rt, imm(rn)` | 1 | | planned |
| `01110 iiiii nnn ttt` | `STRB rt, [rn, #imm5]` | — | `sb rt, imm(rn)` | 1 | | planned |
| `01111 iiiii nnn ttt` | `LDRB rt, [rn, #imm5]` | — | `lbu rt, imm(rn)` | 1 | | planned |
| `10000 iiiii nnn ttt` | `STRH rt, [rn, #imm5*2]` | — | `sh rt, imm(rn)` | 1 | | planned |
| `10001 iiiii nnn ttt` | `LDRH rt, [rn, #imm5*2]` | — | `lhu rt, imm(rn)` | 1 | | planned |
| `10010 ttt iiiiiiii` | `STR rt, [SP, #imm8*4]` | — | `sw rt, imm(sp)` | 1 | | planned |
| `10011 ttt iiiiiiii` | `LDR rt, [SP, #imm8*4]` | — | `lw rt, imm(sp)` | 1 | | planned |

ARMv6-M faults on unaligned word and halfword accesses. VexRiscv can be configured to trap on misaligned accesses too, and the trap handler turns that into a HardFault in ARM-only mode.

## Address generation and stack adjustment

| Encoding | Instruction | Flags | RV32 expansion | Ops | Notes | Status |
|---|---|---|---|---|---|---|
| `10100 ddd iiiiiiii` | `ADR rd, label` (`ADD rd, PC, #imm8*4`) | — | `auipc rd, 0; addi rd, rd, off` | 2 | off as for `LDR [PC]` | planned |
| `10101 ddd iiiiiiii` | `ADD rd, SP, #imm8*4` | — | `addi rd, sp, imm` | 1 | | planned |
| `101100000 iiiiiii` | `ADD SP, SP, #imm7*4` | — | `addi sp, sp, imm` | 1 | | planned |
| `101100001 iiiiiii` | `SUB SP, SP, #imm7*4` | — | `addi sp, sp, -imm` | 1 | | planned |

## Miscellaneous

| Encoding | Instruction | Flags | RV32 expansion | Ops | Notes | Status |
|---|---|---|---|---|---|---|
| `1011001000 mmm ddd` | `SXTH rd, rm` | — | `slli rd, rm, 16; srai rd, rd, 16` | 2 | 1 with Zbb `sext.h` | planned |
| `1011001001 mmm ddd` | `SXTB rd, rm` | — | `slli rd, rm, 24; srai rd, rd, 24` | 2 | 1 with Zbb `sext.b` | planned |
| `1011001010 mmm ddd` | `UXTH rd, rm` | — | `slli rd, rm, 16; srli rd, rd, 16` | 2 | 1 with Zbb `zext.h` | planned |
| `1011001011 mmm ddd` | `UXTB rd, rm` | — | `andi rd, rm, 255` | 1 | | planned |
| `1011010 M rrrrrrrr` | `PUSH {list}` (M: also LR) | — | `sw` each register below SP, then `addi sp, sp, -4n` | n+1 | Lowest register at the lowest address. SP is written last | planned |
| `10110110011 1 0010` | `CPSID i` | — | `csrci mstatus, 8` | 1 | Sets PRIMASK = clears `mstatus.MIE` (Q6) | planned |
| `10110110011 0 0010` | `CPSIE i` | — | `csrsi mstatus, 8` | 1 | | planned |
| `1011101000 mmm ddd` | `REV rd, rm` | — | byte swap with shifts, masks and ORs | ~11 | 1 with Zbb `rev8` | planned |
| `1011101001 mmm ddd` | `REV16 rd, rm` | — | `((x >> 8) & 0x00FF00FF) \| ((x & 0x00FF00FF) << 8)` | ~7 | 2 with Zbb (`rev8; rori 16`) | planned |
| `1011101011 mmm ddd` | `REVSH rd, rm` | — | `slli t, rm, 24; srai t, t, 16; srli u, rm, 8; andi u, u, 255; or rd, t, u` | 5 | 2 with Zbb (`rev8; srai 16`) | planned |
| `1011110 P rrrrrrrr` | `POP {list}` (P: also PC) | — | `lw` each register, then `addi sp, sp, 4n`; with PC: load PC into `t`, then `jalr x0, 0(t)` | n+1, +1 with PC | ARM-only: PC may be an EXC_RETURN value | planned |
| `10111110 iiiiiiii` | `BKPT #imm8` | — | `ebreak` | 1 | | planned |
| `1011111100000000` | `NOP` | — | `addi x0, x0, 0` | 1 | | planned |
| `1011111100010000` | `YIELD` | — | `addi x0, x0, 0` | 1 | | planned |
| `1011111100100000` | `WFE` | — | `addi x0, x0, 0` or `wfi` | 1 | Q5 | planned |
| `1011111100110000` | `WFI` | — | `wfi` | 1 | | planned |
| `1011111101000000` | `SEV` | — | `addi x0, x0, 0` | 1 | Single core, so no other observer | planned |

The other `1011` encodings are ARMv7-M instructions (`CBZ`/`CBNZ`, `IT`) or unallocated, and are undefined on ARMv6-M. Compilers targeting Cortex-M0 never emit them.

## Load and store multiple

| Encoding | Instruction | Flags | RV32 expansion | Ops | Notes | Status |
|---|---|---|---|---|---|---|
| `11000 nnn rrrrrrrr` | `STM rn!, {list}` | — | `sw` each register, then `addi rn, rn, 4n` | n+1 | If rn is in the list it must be the lowest; the original value is stored | planned |
| `11001 nnn rrrrrrrr` | `LDM rn{!}, {list}` | — | `lw` each register, then `addi rn, rn, 4n` | n+1, or n if rn is in the list | Writeback only if rn isn't in the list; then rn is loaded last | planned |

## Branches and exception generation

| Encoding | Instruction | Flags | RV32 expansion | Ops | Notes | Status |
|---|---|---|---|---|---|---|
| `1101 cccc iiiiiiii` (cccc ≠ 111x) | `B<cond> label` | R: per condition | depends on the flag strategy | 1–3 | Target PC + 4 + imm8·2, within RISC-V's ±4 KiB branch range. See [Flag computation](#flag-computation) | planned |
| `11011110 iiiiiiii` | `UDF #imm8` | — | an illegal RV32 encoding (e.g. `0x00000000`) | 1 | Illegal-instruction trap | planned |
| `11011111 iiiiiiii` | `SVC #imm8` | — | `ecall` | 1 | The handler reads imm8 from the instruction at `mepc` and resumes at `mepc`+2 | planned |
| `11100 iiiiiiiiiii` | `B label` | — | `jal x0, off` | 1 | Target PC + 4 + imm11·2 (±2 KiB) | planned |

## 32-bit instructions

| Encoding | Instruction | Flags | RV32 expansion | Ops | Notes | Status |
|---|---|---|---|---|---|---|
| `11110 s iiiiiiiiii`, `11 j 1 k iiiiiiiiiii` | `BL label` | — | `jal ra, off` | 1–4 | ±16 MiB. 1 op if within `jal`'s ±1 MiB and LR bit 0 may stay clear (Q1). Exact LR: `auipc ra, 0; addi ra, ra, 5; jal x0, off` (3). Beyond ±1 MiB: `auipc t, hi; jalr x0, lo(t)` in place of the `jal` (4) | planned |
| `111100111000 nnnn`, `10001000 ssssssss` | `MSR spec_reg, rn` | W: NZCV (APSR) | APSR: unpack into the flag representation. PRIMASK: update `mstatus.MIE`. Others: trap to the handler | varies | Q7 | planned |
| `1111001111101111`, `1000 dddd ssssssss` | `MRS rd, spec_reg` | R: NZCV (APSR) | APSR: pack the flags into bits 31:28. PRIMASK: read `mstatus.MIE`. Others: trap to the handler | varies | Q7 | planned |
| `1111001110111111`, `100011110100 oooo` | `DSB` | — | `fence` | 1 | | planned |
| `1111001110111111`, `100011110101 oooo` | `DMB` | — | `fence` | 1 | | planned |
| `1111001110111111`, `100011110110 oooo` | `ISB` | — | `fence.i` | 1 | | planned |

All other 32-bit encodings (first halfword `11101`, `11110` or `11111` not matching the above) are undefined on ARMv6-M and raise an illegal-instruction trap. ARMv6-M has no 32-bit `UDF.W`; the assembler rejects it for Cortex-M0.

## Summary

83 encodings. Counting the result only, with plain RV32IM:

| Result cost | Encodings |
|---|---|
| 0 ops (only the flags are needed) | 5 (`CMP` ×3, `CMN`, `TST`) |
| 1 op | 46 |
| 1 op or more, depending on Q1/Q2 or the flag strategy | 3 (`BL`, `BLX`, `B<cond>`) |
| 2 or more ops | 29 (register-offset loads and stores, register shifts, `PUSH`/`POP`/`LDM`/`STM`, byte reversal, extends, `ADCS`/`SBCS`, `BICS`, `ADR`, `LDR [PC]`, `MSR`/`MRS`) |

This is a static count. What matters for performance is the dynamic mix, which Phase 0.7 measures on CoreMark and Embench.

## Flag computation

Rough costs for strategy A (eager software flags), to be pinned down in 0.3. They assume a QEMU-style representation: N and Z derived from saved result values, C as 0/1 in a register, V as the sign bit of a register.

| Flags | Cost | Sketch |
|---|---|---|
| N, Z | 1–2 | copy the result |
| C after add | 1 | `sltu C, res, a` |
| C after subtract or compare | 2 | `sltu C, a, b; xori C, C, 1` (ARM's C is NOT borrow) |
| V after add | 3 | `xor t, res, a; xor u, res, b; and V, t, u` |
| V after subtract or compare | 3 | `xor t, a, b; xor u, a, res; and V, t, u` |
| C after a shift | 2 | extract the last bit shifted out |
| C and V after `ADCS`/`SBCS` | ~6–8 | carry in makes the overflow cases harder |

If the destination is also a source (`ADDS rdn, #imm8`), the original operand needs a copy first, which costs one more op. A full `ADDS` therefore costs around 7 ops under strategy A, against 1 for the result alone. This is the main input to D1.

Conditional branches with this representation:

| Condition | Cost |
|---|---|
| EQ, NE, MI, PL, CS, CC, VS, VC | 1 (one flag register against zero) |
| GE, LT (N = V or N ≠ V) | 2 |
| HI, LS (C and Z) | 2–3 |
| GT, LE (Z and N = V) | 3 |

## UNPREDICTABLE encodings

ARMv6-M leaves some encodings UNPREDICTABLE, e.g. `ADD PC, PC`, `BLX PC`, a high-register `CMP` with two low registers, or empty register lists. Thumb-V does whatever is cheapest in the expander and documents it here once modelled. The lockstep tests don't generate them, since Unicorn's behaviour for them isn't a meaningful reference.

## Open questions

| # | Question | Notes |
|---|---|---|
| Q1 | Must `BL`/`BLX` set bit 0 of LR? | With address-based mode, bit 0 is never needed to return correctly, and leaving it clear makes `BL` a single `jal`. Code that inspects LR (rare) would see a difference, and the lockstep harness would have to mask bit 0. |
| Q2 | Can the core produce a PC+2 link value for `BLX rm`? | VexRiscv computes the link as `pc + (isRvc ? 2 : 4)`. If the expander marks 16-bit Thumb ops as RVC-like, `BLX rm` is one `jalr`. Confirm in Phase 1.3. |
| Q3 | Are register shifts common enough to need a better expansion? | 5 ops each. Options: Zbb's `minu`, or a custom shift micro-op with ARM semantics. Decide from 0.7. |
| Q4 | Add Zbb to the core? | Reduces extends, `REV*`, `RORS` and `BICS` to 1–2 ops. Check whether VexRiscv has a bit-manipulation plugin, and its LE cost. |
| Q5 | `WFE`: `nop` or `wfi`? | A `nop` is always correct for a single core with no event sources, at the cost of busy-waiting. |
| Q6 | Is `mstatus.MIE` a faithful PRIMASK? | PRIMASK masks all configurable-priority interrupts but not NMI or HardFault. Fine for mixed mode; check for ARM-only mode. |
| Q7 | Which special registers does `MRS`/`MSR` handle inline? | Proposal: APSR and PRIMASK inline, everything else (MSP, PSP, CONTROL, IPSR, EPSR, …) traps to the handler. |
