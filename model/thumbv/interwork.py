"""Interworking between RISC-V (ilp32) and Thumb (AAPCS) code: layouts and thunks.

Input is an interface header: plain C, restricted to struct definitions and
function prototypes tagged with the side that implements them:

    struct pair { int a, b; };
    THUMBV_THUMB struct pair make_pair(int a, int b);   /* Thumb code, called from RISC-V */
    THUMBV_RISCV int rv_sum(const int *p, int n);       /* RISC-V code, called from Thumb */

Both tags expand to nothing in C (see tests/c/thumbv_interface.h), so the
same header serves both compilers. For each function this module computes the
argument and result layout under both ABIs. Where they agree, calls go
straight through; where they differ, it generates a RISC-V thunk that moves
every argument word from the caller's layout to the callee's. All generated
code is RISC-V; the Thumb side is never modified.

Thumb code calls RISC-V functions through a jump table at a fixed address
(`import_base`): one `j` per imported function. The Thumb library is linked
first against the table's known addresses, so neither link needs the other's
addresses in advance. See docs/interworking.md.
"""

import argparse
import re
import sys
from dataclasses import dataclass, field

# --- C types ---------------------------------------------------------------------

@dataclass(frozen=True)
class CType:
    name: str
    size: int
    align: int
    composite: bool = False

    @property
    def words(self):
        return (self.size + 3) // 4


_SCALARS = {
    ("char",): 1, ("signed", "char"): 1, ("unsigned", "char"): 1, ("_Bool",): 1, ("bool",): 1,
    ("short",): 2, ("short", "int"): 2, ("signed", "short"): 2, ("unsigned", "short"): 2,
    ("unsigned", "short", "int"): 2,
    ("int",): 4, ("signed",): 4, ("signed", "int"): 4, ("unsigned",): 4, ("unsigned", "int"): 4,
    ("long",): 4, ("long", "int"): 4, ("unsigned", "long"): 4, ("unsigned", "long", "int"): 4,
    ("float",): 4,
    ("long", "long"): 8, ("long", "long", "int"): 8, ("unsigned", "long", "long"): 8,
    ("unsigned", "long", "long", "int"): 8, ("double",): 8,
    ("int8_t",): 1, ("uint8_t",): 1, ("int16_t",): 2, ("uint16_t",): 2, ("int32_t",): 4,
    ("uint32_t",): 4, ("int64_t",): 8, ("uint64_t",): 8, ("size_t",): 4, ("uintptr_t",): 4,
    ("intptr_t",): 4, ("ptrdiff_t",): 4,
}
POINTER = CType("pointer", 4, 4)
_QUALIFIERS = {"const", "volatile", "restrict", "register", "static", "extern", "inline"}


class InterfaceError(Exception):
    pass


@dataclass
class Function:
    name: str
    side: str                    # "thumb" (Thumb implements it) or "riscv"
    ret: CType | None            # None for void
    params: list[CType]


@dataclass
class Interface:
    structs: dict[str, CType] = field(default_factory=dict)
    functions: list[Function] = field(default_factory=list)

    @property
    def exports(self):
        """Implemented in Thumb, called from RISC-V."""
        return [f for f in self.functions if f.side == "thumb"]

    @property
    def imports(self):
        """Implemented in RISC-V, called from Thumb."""
        return [f for f in self.functions if f.side == "riscv"]


def _strip(text):
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    return re.sub(r"^\s*#[^\n]*", " ", text, flags=re.M)


def _split_top(text, sep=","):
    parts, depth, cur = [], 0, ""
    for ch in text:
        depth += ch in "([{"
        depth -= ch in ")]}"
        if ch == sep and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    return parts + [cur] if cur.strip() else parts


def _type(decl, structs, named):
    """The type of a declaration; `named` if it ends in a name to drop."""
    if "(" in decl or "[" in decl:  # function pointer or array parameter
        return POINTER
    pointer = "*" in decl
    words = [w for w in decl.replace("*", " ").split() if w not in _QUALIFIERS]
    if words[:1] == ["struct"]:
        if len(words) < 2 or words[1] not in structs:
            raise InterfaceError(f"unknown struct in '{decl.strip()}'")
        return POINTER if pointer else structs[words[1]]
    if named and len(words) > 1 and tuple(words) not in _SCALARS:
        words = words[:-1]
    if words == ["void"]:
        return POINTER if pointer else None
    if pointer:
        return POINTER
    size = _SCALARS.get(tuple(words))
    if size is None:
        raise InterfaceError(f"unsupported type in '{decl.strip()}'")
    return CType(" ".join(words), size, size)


def _struct(name, body, structs):
    offset, align = 0, 1
    for member in body.split(";"):
        if not member.strip():
            continue
        if ":" in member:
            raise InterfaceError(f"struct {name}: bit-fields are not supported")
        base, *names = _split_top(member)
        first = base.split()[-1]
        decls = [base] + [base[:base.rfind(first)] + n for n in names]
        for d in decls:
            count = 1
            if m := re.search(r"\[(\d+)\]", d):
                count, d = int(m.group(1)), d[:m.start()]
            t = _type(d, structs, named=True)
            if t is None:
                raise InterfaceError(f"struct {name}: void member")
            offset = (offset + t.align - 1) // t.align * t.align + t.size * count
            align = max(align, t.align)
    size = (offset + align - 1) // align * align
    return CType(f"struct {name}", size, align, composite=True)


def parse(text: str) -> Interface:
    text = _strip(text)
    iface = Interface()
    if re.search(r"\bunion\b", text):
        raise InterfaceError("unions are not supported")
    for m in re.finditer(r"struct\s+(\w+)\s*\{([^{}]*)\}\s*;", text):
        iface.structs[m.group(1)] = _struct(m.group(1), m.group(2), iface.structs)
    text = re.sub(r"struct\s+\w+\s*\{[^{}]*\}\s*;", " ", text)
    for decl in text.split(";"):
        m = re.fullmatch(r"\s*(THUMBV_THUMB|THUMBV_RISCV)\s+(.+?)\b(\w+)\s*\((.*)\)\s*", decl, re.S)
        if not m:
            if "THUMBV_" in decl:
                raise InterfaceError(f"can't parse declaration: {decl.strip()}")
            continue
        tag, ret, name, params = m.groups()
        if "..." in params:
            raise InterfaceError(f"{name}: variadic functions are not supported")
        param_types = [] if params.strip() in ("", "void") else [
            _type(p, iface.structs, named=True) for p in _split_top(params)]
        if None in param_types:
            raise InterfaceError(f"{name}: void parameter")
        side = "thumb" if tag == "THUMBV_THUMB" else "riscv"
        iface.functions.append(Function(name, side, _type(ret, iface.structs, named=False), param_types))
    return iface


# --- ABI layouts ---------------------------------------------------------------------

@dataclass(frozen=True)
class Loc:
    kind: str    # "reg" (argument register 0-7: r0-r3 / a0-a7) or "stack" (offset from SP at the call)
    n: int

    def __str__(self):
        return f"r{self.n}/a{self.n}" if self.kind == "reg" else f"[sp+{self.n}]"


@dataclass(frozen=True)
class Arg:
    words: tuple[Loc, ...]   # where each 32-bit word goes; for by-reference, the pointer's place
    by_ref: bool = False     # RISC-V: an aggregate > 8 bytes is passed as a pointer to a copy


@dataclass(frozen=True)
class Layout:
    args: tuple[Arg, ...]
    ret: str                 # "none", "regs" (r0/a0, or r0:r1/a0:a1), or "hidden" (pointer in r0/a0)
    stack_size: int

    def describe(self):
        parts = []
        for a in self.args:
            where = ", ".join(map(str, a.words))
            parts.append(f"&copy in {where}" if a.by_ref else where)
        return f"args: {'; '.join(parts) or '-'}  result: {self.ret}"


def _ret_kind(t, abi):
    if t is None:
        return "none"
    if abi == "aapcs":
        return "hidden" if t.composite and t.size > 4 else "regs"
    return "hidden" if t.size > 8 else "regs"


def aapcs(fn: Function) -> Layout:
    """AAPCS base standard (soft-float): r0-r3, then the stack."""
    ret = _ret_kind(fn.ret, "aapcs")
    ncrn, nsaa, args = (1 if ret == "hidden" else 0), 0, []
    for t in fn.params:
        words, align8 = t.words, t.align == 8
        if align8:
            ncrn = (ncrn + 1) & ~1                      # C.3: even register for 8-byte alignment
        if ncrn + words <= 4:                           # C.4: fits in registers
            locs = [Loc("reg", ncrn + i) for i in range(words)]
            ncrn += words
        elif t.composite and ncrn < 4 and nsaa == 0:    # C.5: split between registers and stack
            n_regs = 4 - ncrn
            locs = [Loc("reg", ncrn + i) for i in range(n_regs)]
            locs += [Loc("stack", 4 * i) for i in range(words - n_regs)]
            ncrn, nsaa = 4, 4 * (words - n_regs)
        else:                                           # C.6-C.8: on the stack
            ncrn = 4
            if align8:
                nsaa = (nsaa + 7) & ~7
            locs = [Loc("stack", nsaa + 4 * i) for i in range(words)]
            nsaa += 4 * words
        args.append(Arg(tuple(locs)))
    return Layout(tuple(args), ret, nsaa)


def riscv(fn: Function) -> Layout:
    """RISC-V ilp32 integer calling convention (non-variadic): a0-a7, then the stack."""
    ret = _ret_kind(fn.ret, "riscv")
    nxt, stack, args = (1 if ret == "hidden" else 0), 0, []
    for t in fn.params:
        by_ref = t.composite and t.size > 8
        words = 1 if by_ref else t.words
        if words == 1:
            if nxt < 8:
                locs = [Loc("reg", nxt)]
                nxt += 1
            else:
                locs = [Loc("stack", stack)]
                stack += 4
        elif nxt <= 6:                                  # a register pair, not aligned
            locs = [Loc("reg", nxt), Loc("reg", nxt + 1)]
            nxt += 2
        elif nxt == 7:                                  # split: low word in a7, high word on the stack
            locs = [Loc("reg", 7), Loc("stack", stack)]
            nxt, stack = 8, stack + 4
        else:
            stack = (stack + max(t.align, 4) - 1) // max(t.align, 4) * max(t.align, 4)
            locs = [Loc("stack", stack), Loc("stack", stack + 4)]
            stack += 8
        args.append(Arg(tuple(locs), by_ref))
    return Layout(tuple(args), ret, stack)


def compatible(fn: Function) -> bool:
    return aapcs(fn) == riscv(fn)


# --- Thunks --------------------------------------------------------------------------

def _align(n, a):
    return (n + a - 1) // a * a


def _arg_regs(layout: Layout) -> list[int]:
    """Argument registers a layout uses, including the hidden result pointer."""
    regs = {loc.n for arg in layout.args for loc in arg.words if loc.kind == "reg"}
    if layout.ret == "hidden":
        regs.add(0)
    return sorted(regs)


def thunk(fn: Function, name: str, target: str) -> str:
    """RISC-V assembly for a thunk `name` that calls `target` across the ABI boundary.

    For an export (Thumb implements fn) the caller is RISC-V and the callee
    AAPCS; for an import it is the other way round.
    """
    if fn.side == "thumb":
        caller, callee = riscv(fn), aapcs(fn)
    else:
        caller, callee = aapcs(fn), riscv(fn)

    # Frame, from the (16-byte aligned) SP upwards.
    out = 0
    copies, copy_size = {}, _align(callee.stack_size, 8)
    for i, (src, dst) in enumerate(zip(caller.args, callee.args)):
        if dst.by_ref:
            copies[i] = copy_size
            copy_size += _align(fn.params[i].size, 8)
    retbuf = copy_size
    regs = retbuf + 8
    spill = regs + 32
    save = spill + 32
    frame = _align(save + 8, 16)
    if frame > 2040:
        raise InterfaceError(f"{fn.name}: thunk frame of {frame} bytes is too large")

    lines = [f".global {name}", f".type {name}, @function", f"{name}:",
             f"    # {fn.name}: caller {caller.describe()}",
             f"    #   callee {callee.describe()}",
             "    mv t3, sp                    # caller's SP: its stack arguments are above it",
             f"    addi sp, sp, -{frame}",
             "    andi sp, sp, -16",
             f"    sw ra, {save}(sp)",
             f"    sw t3, {save + 4}(sp)"]
    # Only the argument registers each side uses: the others hold leftovers (for
    # a Thumb caller, a4-a7 are the expander's temporaries).
    lines += [f"    sw a{i}, {spill + 4 * i}(sp)" for i in _arg_regs(caller)]

    def load_word(src, k, size):
        """Load word k of an argument from the caller's layout into t0."""
        if src.by_ref:
            ptr = src.words[0]
            ops = [f"    lw t1, {spill + 4 * ptr.n}(sp)" if ptr.kind == "reg" else f"    lw t1, {ptr.n}(t3)"]
            tail = size - 4 * k
            if tail >= 4:
                return ops + [f"    lw t0, {4 * k}(t1)"]
            ops.append(f"    lbu t0, {4 * k}(t1)")    # don't read past the end of the object
            for b in range(1, tail):
                ops += [f"    lbu t2, {4 * k + b}(t1)", f"    slli t2, t2, {8 * b}", "    or t0, t0, t2"]
            return ops
        loc = src.words[k]
        return [f"    lw t0, {spill + 4 * loc.n}(sp)" if loc.kind == "reg" else f"    lw t0, {loc.n}(t3)"]

    def store_word(loc):
        return [f"    sw t0, {regs + 4 * loc.n}(sp)" if loc.kind == "reg" else f"    sw t0, {out + loc.n}(sp)"]

    # The hidden result pointer, where the conventions use one.
    if caller.ret == "hidden" and callee.ret == "hidden":
        lines += [f"    lw t0, {spill}(sp)", f"    sw t0, {regs}(sp)"]
    elif callee.ret == "hidden":
        lines += [f"    addi t0, sp, {retbuf}", f"    sw t0, {regs}(sp)"]

    for i, (src, dst) in enumerate(zip(caller.args, callee.args)):
        size = fn.params[i].size
        lines.append(f"    # argument {i}: {fn.params[i].name}")
        for k in range(fn.params[i].words):
            lines += load_word(src, k, size)
            if dst.by_ref:
                lines.append(f"    sw t0, {copies[i] + 4 * k}(sp)")
            else:
                lines += store_word(dst.words[k])
        if dst.by_ref:
            lines.append(f"    addi t0, sp, {copies[i]}")
            lines += store_word(dst.words[0])

    lines += [f"    lw a{i}, {regs + 4 * i}(sp)" for i in _arg_regs(callee)]
    lines.append(f"    call {target}")

    if callee.ret == "hidden" and caller.ret == "regs":       # result came back in memory
        lines += [f"    lw a0, {retbuf}(sp)", f"    lw a1, {retbuf + 4}(sp)"]
    elif caller.ret == "hidden" and callee.ret == "regs":     # result goes out to memory
        size = fn.ret.size
        lines.append(f"    lw t1, {spill}(sp)")
        lines.append("    sw a0, 0(t1)")
        if size == 8:
            lines.append("    sw a1, 4(t1)")
        else:
            for b in range(size - 4):
                lines += [f"    srli t2, a1, {8 * b}", f"    sb t2, {4 + b}(t1)"]
    lines += [f"    lw ra, {save}(sp)", f"    lw sp, {save + 4}(sp)", "    ret", f".size {name}, .-{name}"]
    return "\n".join(lines)


@dataclass
class Generated:
    rv_asm: str                    # jump table and thunks, linked into the RISC-V program
    thumb_asm: str                 # import symbols at their jump-table slots, linked into the Thumb library
    export_symbols: dict[str, str] # Thumb symbol -> the RISC-V-side name its address is defined as


def generate(iface: Interface, import_base: int) -> Generated:
    rv = [".section .thumbv.imports, \"ax\"", ".global __thumbv_imports", "__thumbv_imports:"]
    thumb = [".syntax unified", ".thumb"]
    thunks = []
    for i, fn in enumerate(iface.imports):
        target = fn.name
        if not compatible(fn):
            target = f"__thumbv_thunk_{fn.name}"
            thunks.append(thunk(fn, target, fn.name))
        rv.append(f"    j {target}                    # slot {i}: {fn.name}")
        thumb += [f".global {fn.name}", f".thumb_set {fn.name}, {import_base + 4 * i:#x}"]

    exports = {}
    for fn in iface.exports:
        if compatible(fn):
            exports[fn.name] = fn.name
        else:
            exports[fn.name] = f"__thumbv_thumb_{fn.name}"
            thunks.append(thunk(fn, fn.name, exports[fn.name]))
    rv += [".text"] + thunks + [""]
    return Generated("\n".join(rv), "\n".join(thumb) + "\n", exports)


def report(iface: Interface) -> str:
    lines = []
    for fn in iface.functions:
        direction = "RISC-V -> Thumb" if fn.side == "thumb" else "Thumb -> RISC-V"
        verdict = "direct" if compatible(fn) else "thunk"
        lines.append(f"{fn.name} ({direction}): {verdict}")
        lines.append(f"    AAPCS   {aapcs(fn).describe()}")
        lines.append(f"    RISC-V  {riscv(fn).describe()}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Show how an interface header's functions cross the ABI boundary.")
    parser.add_argument("header")
    args = parser.parse_args(argv)
    with open(args.header) as f:
        print(report(parse(f.read())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
