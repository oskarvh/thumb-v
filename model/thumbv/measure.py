"""Phase 0.7 measurements: the cost of each flags strategy on real programs.

A program runs once in the model under strategy A (the expander as it is).
Every Thumb instruction it executes is recorded with the flags it reads and
writes, and every flag write is followed until it is overwritten, so each
write is known to be live (read before being overwritten) or dead. The other
strategies are then costed from this trace:

  A          eager flags, as modelled: every flag computed after every write.
  A peek-k   A, skipping flags the next k instructions (straight-line, in the
             fetch stream) are seen to overwrite. Realisable in hardware.
  A oracle   A computing only flags that are actually read: a lower bound for
             any dead-flag elimination, including a compiler-like static one.
  A fused    A oracle, plus CMP + B<cond> as one RV32 branch when the compare's
             flags die at the branch.
  B          lazy flags: save the operands, compute a flag when it is read.
             Optimistic: the read knows the producer's kind for free, where real
             hardware would need branch-free code for every kind.
  C          hardware NZCV: ALU ops latch the flags, B<cond> is one custom op.
  C fused    C, plus CMP + B<cond> as one compare-and-branch that also latches
             the flags (no liveness needed).
  C shift    C fused, plus an ARM-shift micro-op for register shifts (Q3).

Costs are RV32 ops per Thumb instruction. The A cost of every instruction is
broken down into its result, the ops for each flag and a final move, and the
breakdown is checked to add up to what the expander emits.

    python -m thumbv.measure [names...] [--json out.json]

Names are `coremark`, `float` (tests/bench/float/) and Embench benchmarks;
the default is all of them.
"""

import argparse
import json
import multiprocessing
import re
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from elftools.elf.elffile import ELFFile

from . import build, elf, isa
from . import rv32 as r
from .expander import Options, expand
from .lockstep import Layout, _load_model
from .regmap import T1, T3, rv

N, Z, C, V = 1, 2, 4, 8
ALL = N | Z | C | V
FLAG_NAMES = ((N, "N"), (Z, "Z"), (C, "C"), (V, "V"))

COND_READS = {0: Z, 1: Z, 2: C, 3: C, 4: N, 5: N, 6: V, 7: V,
              8: C | Z, 9: C | Z, 10: N | V, 11: N | V, 12: N | Z | V, 13: N | Z | V}
# Conditions a single RV32 branch can test on the compare's operands
# (beq/bne/blt/bge/bltu/bgeu, swapping operands for GT/LE/HI/LS).
# MI/PL/VS/VC test the subtraction's result instead.
FUSABLE_CONDS = {0, 1, 2, 3, 8, 9, 10, 11, 12, 13}

NZ_ONLY = {"MOVS_imm", "MOVS_reg", "ANDS", "EORS", "ORRS", "BICS", "MVNS", "MULS", "TST"}
SHIFT_IMM = {"LSLS_imm", "LSRS_imm", "ASRS_imm"}
ADD_LIKE = {"ADDS_reg", "ADDS_imm3", "ADDS_imm8", "CMN"}
SUB_LIKE = {"SUBS_reg", "SUBS_imm3", "SUBS_imm8", "CMP_imm", "CMP_reg", "CMP_hi", "RSBS"}
CARRY_IN = {"ADCS", "SBCS"}
SHIFT_REG = {"LSLS_reg", "LSRS_reg", "ASRS_reg", "RORS"}
COMPARES = {"CMP_imm", "CMP_reg", "CMP_hi", "CMN", "TST"}

# Ops strategy A spends on each flag, per class (see the expander's helpers).
FLAG_OPS = {
    **{n: {N: 1, Z: 1} for n in NZ_ONLY},
    **{n: {N: 1, Z: 1, C: 2} for n in SHIFT_IMM},
    **{n: {N: 1, Z: 1, C: 1, V: 4} for n in ADD_LIKE},
    **{n: {N: 1, Z: 1, C: 2, V: 4} for n in SUB_LIKE},
    **{n: {N: 1, Z: 1, C: 3, V: 4} for n in CARRY_IN},
}
SHIFT_REG_RESULT = 5    # register shift without flags: docs/isa-coverage.md, Register shifts
RESULT_OPS = {"BICS": 2, "ADCS": 2, "SBCS": 3}  # ops for the result alone; 1 for the rest
SAVED = {**{n: 0 for n in NZ_ONLY}, **{n: 1 for n in SHIFT_IMM},  # strategy B: operands to save
         **{n: 2 for n in ADD_LIKE | SUB_LIKE}, **{n: 3 for n in CARRY_IN}}
CMPS = {"CMP_imm", "CMP_reg", "CMP_hi"}  # compares a single RV32 branch can replace
# Stop looking ahead at these (and at writes to the PC): the jump target or
# the exception handler may read the flags.
PEEK_STOP = {"B_cond", "B", "SVC", "BKPT", "UDF", "UNDEFINED", "MRS", "MSR"}
APSR = 0                # SYSm of MRS/MSR APSR


@dataclass
class Static:
    """What is known about one instruction from its encoding alone."""
    pc: int
    name: str
    fields: dict
    length: int
    a_ops: int
    writes: int = 0         # flags it writes (register shifts: C only if the amount isn't 0)
    reads: int = 0          # flags it reads
    flag_ops: dict = field(default_factory=dict)
    result: int = 0         # ops for the result alone
    move: int = 0           # final move from a temporary, needed only if C or V is computed
    c_ops: int = 0          # cost under strategy C
    record: int = 0         # strategy B: ops to save operands and kind
    call_or_return: bool = False
    writes_pc: bool = False     # ADD/MOV pc: a computed jump

    def a_cost(self, live: int) -> int:
        """Strategy A ops when only the flags in `live` are computed."""
        if not self.writes:
            return self.a_ops
        return (self.result + (self.move if live & (C | V) else 0)
                + sum(ops for f, ops in self.flag_ops.items() if live & f))


def analyse(pc, hw1, hw2) -> Static:
    exp = expand(hw1, hw2, pc)
    name = exp.name
    fields = isa.decode(hw1, hw2)[1] if name != "UNDEFINED" else {}
    s = Static(pc, name, fields, exp.length, len(exp.ops))
    s.c_ops = s.a_ops
    if name in FLAG_OPS or name in SHIFT_REG:
        s.writes = N | Z | C | V if name in ADD_LIKE | SUB_LIKE | CARRY_IN else (
            N | Z | C if name in SHIFT_IMM | SHIFT_REG else N | Z)
        last = exp.ops[-1]
        s.move = int(any(last == r.mv(d, t) for t in (T1, T3) for d in range(1, 32) if d != t))
        if name in SHIFT_REG:
            # Everything but the result and N, Z (the last two ops) is for C,
            # including the move of the result out of its temporary.
            s.result = SHIFT_REG_RESULT
            s.flag_ops = {N: 1, Z: 1, C: s.a_ops - SHIFT_REG_RESULT - 2}
            s.c_ops = s.a_ops - 2          # NZ from the unit, C still in software
            s.record = 4                   # result, value, amount, kind
        else:
            s.flag_ops = FLAG_OPS[name]
            s.result = s.a_ops - sum(s.flag_ops.values()) - s.move
            # The breakdown must account for exactly the ops the expander emits.
            pc_reads = 2 * sum(reg == 15 for reg in _hi_operands(name, fields))
            assert s.result == RESULT_OPS.get(name, 1) + pc_reads, (name, exp.ops)
            s.c_ops = 1 if name in CARRY_IN else s.result
            # Save the operands and the kind; the result too unless it goes there directly.
            s.record = SAVED[name] + (0 if name in COMPARES else 1) + 1
    if name in CARRY_IN:
        s.reads = C
    elif name == "B_cond":
        s.reads = COND_READS[fields["c"]]
        s.c_ops = 1
    elif name == "MRS" and fields["s"] == APSR:
        s.reads, s.c_ops = ALL, 1
    elif name == "MSR" and fields["s"] == APSR:
        s.writes, s.c_ops = ALL, 1
        s.flag_ops, s.result, s.record = {N: 1, Z: 2, C: 2, V: 2}, 0, 1
    s.call_or_return = name in ("BL", "BLX", "BX") or (name == "POP" and fields["P"])
    s.writes_pc = name in ("ADD_hi", "MOV_hi") and (fields["D"] << 3 | fields["d"]) == 15
    return s


def _hi_operands(name, fields):
    return (fields["N"] << 3 | fields["n"], fields["m"]) if name == "CMP_hi" else ()


def peek_dead(code: dict, s: Static, k: int) -> int:
    """Flags of `s` that the next k instructions in the fetch stream overwrite.

    Stops at branches (the target isn't in the window). Calls and returns end
    the flags' lifetime: AAPCS leaves them UNKNOWN across a call, and the
    measurement checks that no program reads them across one.
    """
    remaining, dead, pc = s.writes, 0, s.pc + s.length
    for _ in range(k):
        n = code.get(pc)
        if n is None or n.name in PEEK_STOP or n.writes_pc:
            break
        if n.call_or_return:
            return dead | remaining
        remaining &= ~n.reads
        # A register shift by 0 leaves C alone, so it can't be relied on to overwrite it.
        overwrites = n.writes & ~(C if n.name in SHIFT_REG else 0)
        dead |= remaining & overwrites
        remaining &= ~overwrites
        if not remaining:
            break
        pc += n.length
    return dead


class _Write:
    """One dynamic flag write, followed until all its flags are overwritten."""
    __slots__ = ("s", "pending", "live", "fused", "branch", "materialized", "epoch")

    def __init__(self, s, flags, epoch):
        self.s, self.pending, self.live = s, flags, 0
        self.fused, self.branch = 0, None   # flags read by the B<cond> right after it, and its pc
        self.materialized = ALL if s.name == "MSR" else 0   # strategy B: flags computed
        self.epoch = epoch

    def key(self):
        return self.s.pc, self.live, self.fused, self.branch


@dataclass
class Trace:
    """Per-instruction counts and flag liveness from one run."""
    thumb: int = 0
    rv_ops: int = 0
    executions: Counter = field(default_factory=Counter)        # pc -> count
    writes: Counter = field(default_factory=Counter)            # _Write.key() -> count
    shift_amounts: Counter = field(default_factory=Counter)     # (pc, bucket) -> count
    lazy_reads: int = 0                                         # strategy B read-side ops
    cross_call_reads: int = 0
    statics: dict = field(default_factory=dict)


def _amount_bucket(a):
    return "0" if a == 0 else "1-31" if a < 32 else "32" if a == 32 else ">32"


def trace(images, stop: int, max_steps: int = 50_000_000) -> Trace:
    layout = Layout.for_images(images)
    m = _load_model(images, layout, Options())
    m.pc = images[0].entry & ~1
    stop &= ~1
    t = Trace()
    statics = t.statics
    current = [None] * 16          # flag bit -> its _Write
    epoch = 0                      # counts calls and returns
    prev = None
    steps = 0
    while m.pc != stop and steps < max_steps:
        pc = m.pc
        steps += 1
        if not m.in_thumb(pc):
            m.step()
            prev = None
            continue
        s = statics.get(pc)
        if s is None:
            hw1 = m.mem.read(pc, 2)
            hw2 = m.mem.read(pc + 2, 2) if isa.is_32bit(hw1) else 0
            s = statics[pc] = analyse(pc, hw1, hw2)
        t.executions[pc] += 1
        reads, writes = s.reads, s.writes
        if s.name in SHIFT_REG:
            amount = m.x[rv(s.fields["m"])] & 255
            t.shift_amounts[pc, _amount_bucket(amount)] += 1
            if amount == 0:
                writes = N | Z   # C passes through untouched
        if reads:
            producers = {current[f] for f in (N, Z, C, V) if reads & f}
            fused = (s.name == "B_cond" and prev is not None and prev.s.pc + prev.s.length == pc
                     and producers == {prev})
            if fused:
                prev.branch = pc
            t.lazy_reads += _lazy_read(s, reads, current)
            for f in (N, Z, C, V):
                w = current[f]
                if reads & f and w is not None:
                    if fused:
                        w.fused |= f
                    else:
                        w.live |= f
                    if w.epoch != epoch:
                        t.cross_call_reads += 1
        new = None
        if writes:
            new = _Write(s, writes, epoch)
            for f in (N, Z, C, V):
                if writes & f:
                    old = current[f]
                    if old is not None:
                        old.pending &= ~f
                        if not old.pending:
                            t.writes[old.key()] += 1
                    current[f] = new
        if s.call_or_return:
            epoch += 1
        prev = new
        m.step()
    if m.pc != stop:
        raise RuntimeError(f"stopped after {steps} steps at {m.pc:#x}")
    for w in {w for w in current if w is not None}:
        t.writes[w.key()] += 1
    t.thumb, t.rv_ops = m.retired_thumb, m.retired_ops
    return t


def _lazy_read(s, reads, current) -> int:
    """Strategy B: ops a flag read costs, given which writes produced the flags."""
    producers = {current[f] for f in (N, Z, C, V) if reads & f} - {None}
    if s.name == "B_cond":
        # Lazy flags' best case: branch on the saved operands or result.
        cond = s.fields["c"]
        if len(producers) == 1:
            p = producers.pop()
            # Branch directly on the saved operands, or on the saved result.
            if p.s.name in SUB_LIKE and cond in FUSABLE_CONDS:
                return 1
            if cond in (0, 1, 4, 5):
                return 1
    cost = 0
    for f in (N, Z, C, V):
        w = current[f]
        if reads & f and w is not None and not w.materialized & f:
            cost += w.s.flag_ops.get(f, 1)
            w.materialized |= f
    return cost + (s.a_ops if s.name in ("B_cond", "MRS") else 0)


# --- Costing ---------------------------------------------------------------------

PEEKS = (1, 2, 4)


def costs(t: Trace) -> dict:
    st, ex = t.statics, t.executions
    a = sum(st[pc].a_ops * n for pc, n in ex.items())
    flag_ops = sum((st[pc].a_ops - st[pc].a_cost(0)) * n for pc, n in ex.items() if st[pc].writes)
    flag_ops += sum((st[pc].a_ops - 1) * n for pc, n in ex.items() if st[pc].name == "B_cond")
    out = {"thumb": t.thumb, "A": a, "A flag ops": flag_ops}

    # Oracle: only flags that are read. Peek: hardware lookahead, checked to be safe.
    oracle = fused_a = a
    unsafe = 0
    peek = {k: a for k in PEEKS}
    dead = {k: {pc: peek_dead(st, s, k) for pc, s in st.items() if s.writes} for k in PEEKS}
    for (pc, live, fused, branch), n in t.writes.items():
        s = st[pc]
        used = live | fused
        saving = s.a_ops - s.a_cost(used)
        oracle -= saving * n
        for k in PEEKS:
            if dead[k][pc] & used:
                unsafe += n
            peek[k] -= (s.a_ops - s.a_cost(s.writes & ~dead[k][pc])) * n
        if _fusable(s, branch and st[branch]) and not live:
            # Flags dead after the branch: compare and branch become one RV32
            # branch (two if the immediate needs a register).
            saving = s.a_ops + st[branch].a_ops - _fused_ops(s)
        fused_a -= saving * n
    out.update({f"A peek-{k}": peek[k] for k in PEEKS})
    out.update({"A oracle": oracle, "A fused": fused_a, "peek unsafe": unsafe,
                "cross-call reads": t.cross_call_reads})

    lazy = t.lazy_reads
    for pc, n in ex.items():
        s = st[pc]
        if s.writes:
            lazy += (s.result + s.record) * n
        elif s.name not in ("B_cond", "MRS"):
            lazy += s.a_ops * n
    out["B"] = lazy

    # Strategy C fuses regardless of liveness: the fused op latches the flags too.
    c = sum(st[pc].c_ops * n for pc, n in ex.items())
    fusable = fusable_imm = 0
    for (pc, live, fused, branch), n in t.writes.items():
        if _fusable(st[pc], branch and st[branch]):
            fusable_imm += n
            fusable += n * (_fused_ops(st[pc]) == 1 and st[pc].c_ops == 1)
    shifts = sum((st[pc].c_ops - 1) * n for pc, n in ex.items() if st[pc].name in SHIFT_REG)
    out.update({"C": c, "C fused": c - fusable, "C fused imm": c - fusable_imm,
                "C shift": c - fusable_imm - shifts})
    return out


def _fusable(s, branch):
    return bool(branch) and s.name in CMPS and branch.fields["c"] in FUSABLE_CONDS


def _fused_ops(s):
    return 2 if s.name == "CMP_imm" and s.fields["i"] else 1


def flag_stats(t: Trace) -> dict:
    """Dead-flag rates, fusable pairs, BL range and register shifts."""
    st = t.statics
    written = Counter()
    read = Counter()
    all_dead = total = 0
    peek1 = 0
    dead1 = {pc: peek_dead(st, s, 1) for pc, s in st.items() if s.writes}
    pairs = 0
    for (pc, live, fused, branch), n in t.writes.items():
        used = live | fused
        pairs += n * _fusable(st[pc], branch and st[branch])
        total += n
        all_dead += n * (not used)
        peek1 += n * bool(dead1[pc] == st[pc].writes)
        for f, name in FLAG_NAMES:
            if st[pc].writes & f:
                written[name] += n
                read[name] += n * bool(used & f)
    bconds = sum(n for pc, n in t.executions.items() if st[pc].name == "B_cond")
    bl = [pc for pc, s in st.items() if s.name == "BL"]
    bl_far = [pc for pc in bl if st[pc].a_ops > 1]
    shifts = Counter()
    for (pc, bucket), n in t.shift_amounts.items():
        shifts[bucket] += n
    return {
        "flag writes": total,
        "all flags dead": all_dead / max(1, total),
        "dead per flag": {f: 1 - read[f] / max(1, written[f]) for f in written},
        "peek-1 kills all": peek1 / max(1, total),
        "B<cond>": bconds,
        "fusable CMP+B<cond>": pairs / max(1, bconds),
        "BL executed": sum(t.executions[pc] for pc in bl),
        "BL beyond 1 MiB": sum(t.executions[pc] for pc in bl_far),
        "BL static": len(bl), "BL static far": len(bl_far),
        "register shifts": sum(shifts.values()),
        "register shift amounts": dict(shifts),
    }


# --- Where register shifts come from ----------------------------------------------

def _origins(elf_path: Path):
    """[(start, end, origin)] from the link map: program, libc, libm, libgcc or soft-float."""
    spans = []
    text = Path(f"{elf_path}.map").read_text()
    pending = None
    for line in text.splitlines():
        m = re.match(r"^ (\.text\S*)?\s+(0x[0-9a-f]+)\s+(0x[0-9a-f]+)\s+(\S+)$", line)
        if m is None:
            pending = line.strip() if re.match(r"^ \.text\S*$", line) else None
            continue
        if not (m.group(1) or pending):
            continue
        pending = None
        start, size, path = int(m.group(2), 16), int(m.group(3), 16), m.group(4)
        if size:
            spans.append((start, start + size, _origin(path)))
    return spans


def _origin(path):
    lib = re.search(r"lib(\w+)\.a\((.*)\)$", path)
    if lib is None:
        return "program"
    archive, obj = lib.groups()
    if archive == "gcc":
        return "soft-float" if re.search(r"[sd]f\d?\.o$|[sd]f[sd]f2\.o|_[sd]f", obj, re.I) else "libgcc"
    return {"m": "libm", "c": "libc"}.get(archive, archive)


def _functions(elf_path: Path):
    with open(elf_path, "rb") as f:
        symtab = ELFFile(f).get_section_by_name(".symtab")
        return sorted((s["st_value"] & ~1, s["st_value"] + s["st_size"], s.name)
                      for s in symtab.iter_symbols()
                      if s["st_info"]["type"] == "STT_FUNC" and s["st_size"])


def shift_origins(t: Trace, elf_path: Path) -> dict:
    spans = _origins(elf_path)
    funcs = _functions(elf_path)
    by_origin, by_function = Counter(), Counter()
    for (pc, _), n in t.shift_amounts.items():
        origin = next((o for lo, hi, o in spans if lo <= pc < hi), "program")
        by_origin[origin] += n
        name = next((f for lo, hi, f in funcs if lo <= pc < hi), "?")
        by_function[name] += n
    return {"by origin": dict(by_origin), "top functions": by_function.most_common(5)}


# --- Running -----------------------------------------------------------------------

def _build(name, out_dir):
    if name == "coremark":
        return build.coremark(out_dir)
    if name == "float":
        return build.float_kernels(out_dir)
    return build.embench(name, out_dir)


def measure(name: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        path = _build(name, Path(tmp))
        image = elf.load(path)
        t = trace([image], stop=image.symbols["done"])
        return {"name": name, "costs": costs(t), "flags": flag_stats(t),
                "shifts": shift_origins(t, path)}


def all_names():
    return ["coremark", "float", *build.embench_names()]


def table(results) -> str:
    keys = ["A", "A peek-1", "A peek-4", "A oracle", "A fused", "B", "C", "C fused", "C shift"]
    lines = ["| Benchmark | Thumb instr. | " + " | ".join(keys) + " |",
             "|---|---:|" + "---:|" * len(keys)]
    total = Counter()
    for res in results:
        c = res["costs"]
        total.update({k: c[k] for k in ["thumb", *keys]})
        lines.append(f"| {res['name']} | {c['thumb']:,} | "
                     + " | ".join(f"{c[k] / c['thumb']:.2f}" for k in keys) + " |")
    # Unweighted mean of the ratios, so the longest benchmark doesn't dominate.
    mean = {k: sum(res["costs"][k] / res["costs"]["thumb"] for res in results) / len(results)
            for k in keys}
    lines.append("| **mean** | | " + " | ".join(f"**{mean[k]:.2f}**" for k in keys) + " |")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("names", nargs="*", help="benchmarks (default: all)")
    parser.add_argument("--json", type=Path, help="write the full results here")
    args = parser.parse_args(argv)
    names = args.names or all_names()
    with multiprocessing.Pool() as pool:
        results = pool.map(measure, names)
    print(table(results))
    if args.json:
        args.json.write_text(json.dumps(results, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
