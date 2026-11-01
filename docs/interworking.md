# Interworking: calls between RISC-V and Thumb code

How a RISC-V program and Thumb code call each other on Thumb-V: what crosses the boundary for free, where the two calling conventions differ, the build flow, and the generated thunks. This settles decision D8 in [plan.md](plan.md).

The code is `model/thumbv/interwork.py` (layouts and thunk generator) and `thumbv.build.mixed_program` (build flow). Tests are in `tests/test_interwork.py`, with the test program in `tests/c/abi*.c`.

## What crosses for free

The register mapping (D2) puts each ARM register in the RISC-V register with the same role in both calling conventions:

| ARM (AAPCS) | RISC-V (ilp32) | Role in both |
|---|---|---|
| r0–r3 | a0–a3 | first arguments, results, caller-saved |
| r4–r11 | s0–s7 | callee-saved |
| r12 | t0 | scratch, may be clobbered by veneers and thunks |
| SP | sp | one shared stack |
| LR | ra | return address |

The decoder is chosen by address (D7), so a call is just a jump. A RISC-V `jal` into a Thumb region starts decoding Thumb, and a Thumb `BX LR` back to a RISC-V address switches back. LR bit 0 doesn't matter (Q1).

Flags are UNKNOWN after a call under AAPCS, and Thumb code never relies on them across one. RISC-V code may freely use t3–t6, which hold the flags while Thumb code runs.

## Where the conventions differ

Both are soft-float integer conventions with the same type sizes and struct layouts (natural alignment, little-endian), so memory is shared as-is. Only argument passing differs. Every case below was checked against GCC's code for both targets:

| Case | RISC-V ilp32 | AAPCS |
|---|---|---|
| Arguments 5–8 | a4–a7 | stack |
| 64-bit argument after an odd number of words, e.g. `f(int, long long)` | a1:a2 (any pair) | r2:r3 (even pair), skipping r1 |
| 8-byte-aligned struct by value | any register pair | even register pair |
| Struct > 8 bytes by value | pointer to a caller-made copy | the struct's words in r0–r3, then the stack |
| 64-bit or struct argument with one register left | split: low word in a7, rest on the stack | 64-bit: all on the stack, 8-byte aligned. Struct: split between r3 and the stack if nothing is on the stack yet |
| Struct result of 5–8 bytes | a0:a1 | memory, via a hidden pointer in r0 |
| Struct result > 8 bytes | hidden pointer in a0 | hidden pointer in r0 (the same) |
| Stack alignment at a call | 16 bytes | 8 bytes |

Everything else is identical: up to 4 word-sized arguments, 64-bit values in r0:r1/a0:a1, structs of up to 4 bytes, narrow types (the caller extends arguments, the callee extends results), and pointers.

## Interface headers

Functions that cross the boundary are declared in an interface header, which is ordinary C. The tags come from `tests/c/thumbv_interface.h` and expand to nothing:

```c
#include <stdint.h>
#include "thumbv_interface.h"

struct pair { int32_t a, b; };

THUMBV_THUMB struct pair t_make_pair(int a, int b);   /* implemented in Thumb, called from RISC-V */
THUMBV_RISCV int rv_sum(const int32_t *p, int n);     /* implemented in RISC-V, called from Thumb */
```

Both sides include the same header, so their prototypes agree. Supported:
- Integer and pointer types: `char` to `long long`, the `<stdint.h>` types, `size_t`, `float` and `double` (soft-float, passed like integers of the same size).
- Pointers of any kind, including function pointers and array parameters.
- Structs of these (nested, arrays), by value and as results.

Rejected with an error: variadic functions, unions, bit-fields, unknown types.

To see how each function crosses and whether it needs a thunk:

```sh
uv run python -m thumbv.interwork tests/c/abi.h
```

## Build flow

```
                       interface header
                              │ thumbv.interwork.generate()
              ┌───────────────┴────────────────┐
     interwork_thumb.S                  interwork_rv32.S
  (import symbols at their      (jump table at IMPORT_BASE, thunks)
   jump-table slots)                           │
              │                                │
 1. Thumb library ── arm-none-eabi-ld          │
              │ export addresses (--defsym)    │
              └──────────────► 2. RISC-V program ── riscv64-unknown-elf-ld
                                               │
                     3. both images loaded side by side
```

1. **Link the Thumb library first** (code at `0x1_4000`, data at `0x2000_0000`). Its code window, `0x1_4000`–`0x2_0000`, is what the RISC-V startup code (`tests/c/crt_rv32.S`) marks as Thumb region 0. Its calls to RISC-V functions resolve to slots in the import jump table, whose address is fixed in advance: `IMPORT_BASE` = `0x2_0000`, the start of the RISC-V ROM. Each import is defined with `.thumb_set name, IMPORT_BASE + 4*i`, which marks it as a Thumb branch target, so a plain `BL name` works.
2. **Link the RISC-V program** (code at `0x2_0000`, data at `0x2000_4000`) together with `interwork_rv32.S`:
   - The jump table, in section `.thumbv.imports`, which `tests/link/rv32.ld` places first in ROM: one `j` per import, to the RISC-V function or to its thunk.
   - The thunks.
   - Each Thumb export is defined as an absolute symbol (`--defsym`) with its address in the Thumb library: under its own name if no thunk is needed, or as `__thumbv_thumb_<name>` for the thunk to call. Only declared functions are exported, so the Thumb side's libgcc (`__aeabi_idiv`, `__divsi3`, …) never collides with RISC-V's.
   - The build checks that the table landed at `IMPORT_BASE`.
3. **Load both images.** The Thumb library's code range becomes a Thumb region; everything else decodes as RISC-V.

Neither link needs anything from the other except: the Thumb link needs `IMPORT_BASE` and the order of the imports (both come from the header), and the RISC-V link needs the Thumb export addresses (from step 1). So there is no circular dependency.

Without an interface header, `mixed_program` falls back to the simple flow of Phase 0.4: every global Thumb function is exported, there are no imports and no thunks, and all signatures must be compatible.

## Thunks

A thunk is generated RISC-V code between a caller in one convention and a callee in the other:
- **Export thunk** (RISC-V calls Thumb): named like the function, so RISC-V code calls it unchanged; it calls `__thumbv_thumb_<name>`.
- **Import thunk** (Thumb calls RISC-V): `__thumbv_thunk_<name>`, reached through the jump table; it calls the RISC-V function.

Every thunk follows the same recipe:
1. Save the caller's SP in t3, then allocate a frame and align SP to 16 bytes.
2. Save `ra`, and spill the argument registers the caller's layout uses. Only those: for a Thumb caller, a4–a7 hold the expander's temporaries.
3. Move each argument word from its place in the caller's layout to its place in the callee's: a staging area for registers, or the outgoing stack area at the bottom of the frame.
   - **By reference (RISC-V side):** for an aggregate passed by reference, the thunk either reads through the pointer, or makes the copy in its frame and passes its address. A partial last word is read byte by byte, so nothing past the end of the object is read.
   - **Hidden result pointer:** if both sides use one, it's passed through. If only the callee does (a 5–8-byte struct result, called from RISC-V), the thunk passes a buffer in its frame and loads `a0:a1` from it afterwards. If only the caller does (called from Thumb), the thunk stores `a0:a1` to the caller's pointer afterwards, writing exactly the struct's size.
4. Load the callee's argument registers and call the target.
5. Restore `ra` and SP, and return.

The thunk only uses caller-saved registers (t0–t3, a0–a7), so it preserves everything the callee-saved rules require. Example, for `int64_t t_mixed(int a, int64_t b, int c)` called from RISC-V:

```
t_mixed:
    # t_mixed: caller args: r0/a0; r1/a1, r2/a2; r3/a3  result: regs
    #   callee args: r0/a0; r2/a2, r3/a3; [sp+0]  result: regs
    mv t3, sp                    # caller's SP: its stack arguments are above it
    addi sp, sp, -96
    andi sp, sp, -16
    sw ra, 80(sp)
    sw t3, 84(sp)
    sw a0, 48(sp)
    sw a1, 52(sp)
    sw a2, 56(sp)
    sw a3, 60(sp)
    # argument 0: int
    lw t0, 48(sp)
    sw t0, 16(sp)
    # argument 1: int64_t
    lw t0, 52(sp)
    sw t0, 24(sp)
    lw t0, 56(sp)
    sw t0, 28(sp)
    # argument 2: int
    lw t0, 60(sp)
    sw t0, 0(sp)
    lw a0, 16(sp)
    lw a2, 24(sp)
    lw a3, 28(sp)
    call __thumbv_thumb_t_mixed
    lw ra, 80(sp)
    lw sp, 84(sp)
    ret
```

That is 27 ops of overhead per call. Thunks favour being obviously correct over being fast: every word goes through memory. If thunked calls turn out to be hot, direct register-to-register moves (when sources and destinations don't overlap) would roughly halve this. Compatible signatures need no thunk; an import still costs one `j` in the jump table.

## Function pointers

A function pointer passed across the boundary (a callback) is called directly, with no thunk, because the generator can't see indirect calls. Its signature must be one the conventions pass the same way. Check it with the report tool by declaring a function of the same signature. A callback with an incompatible signature needs a hand-written wrapper on the caller's side.

## Verification

- **Layouts** (`test_layouts`): the cases from the table above are asserted explicitly. Each was checked against GCC's output for both targets.
- **Three-way check** (`test_abi_program_three_ways`): the ABI test program has 14 Thumb functions called from RISC-V and 7 RISC-V functions called from Thumb, 16 of which need thunks. It is built mixed (with thunks), all-RISC-V and all-Thumb, and all three must return the same result. The all-RISC-V and all-Thumb builds each use only one convention, so this checks both layout algorithms and every thunk against the compilers.
- **Lockstep** (`test_abi_program_lockstep`): the mixed build also runs in program lockstep, with Thumb code checked against Unicorn instruction by instruction.
- **Mutant** (`test_wrong_layout_is_caught`): dropping AAPCS's even-register rule for 8-byte-aligned arguments makes the mixed result differ, showing the three-way check catches a wrong layout.

## Limitations

- Variadic functions, unions and bit-fields aren't supported.
- Only the soft-float conventions: no `-mfloat-abi=hard` Thumb code (Cortex-M0 has no FPU anyway) and no RISC-V F/D extensions.
- Thumb code imports RISC-V functions only through the interface header. Undeclared calls fail to link, which is the safe outcome.
- C++ (name mangling, `this`, exceptions across the boundary) isn't considered.
