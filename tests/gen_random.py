"""Random Thumb programs: sequences of random instructions whose state carries over.

Flags set by one instruction feed later ADCS/SBCS and conditional branches,
and loads read what earlier stores wrote. Register use: r0-r6 are random
operands, r7 points at a 256-byte buffer for memory operations, and SP has a
64-byte frame. Control flow is forward branches over a few instructions and
calls to a leaf function, so every program ends.
"""

import random

LOW = [f"r{i}" for i in range(7)]           # operands and destinations; r7 is the buffer base
HIGH = ["r8", "r9", "r10", "r11", "r12"]
CONDS = ["eq", "ne", "cs", "cc", "mi", "pl", "vs", "vc", "hi", "ls", "ge", "lt", "gt", "le"]
EDGES = [0, 1, 31, 32, 33, 255, 256, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, 0xFFFFFFE0]


def _value(rng):
    return rng.choice(EDGES) if rng.random() < 0.4 else rng.getrandbits(32)


class Generator:
    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.lines = []
        self.labels = 0

    def reg(self, regs=LOW):
        return self.rng.choice(regs)

    def label(self):
        self.labels += 1
        return f"lbl{self.labels}"

    def straight(self):
        """One random instruction that falls through."""
        rng, r = self.rng, self.reg
        kind = rng.random()
        if kind < 0.30:
            op = rng.choice(["ands", "eors", "orrs", "bics", "adcs", "sbcs", "lsls", "lsrs", "asrs",
                             "rors", "muls", "mvns", "tst", "cmp", "cmn"])
            if op == "muls":
                d = r()
                return [f"muls {d}, {r()}, {d}"]
            return [f"{op} {r()}, {r()}"]
        if kind < 0.45:
            op = rng.choice(["adds", "subs"])
            third = r() if rng.random() < 0.5 else f"#{rng.randrange(8)}"
            return [f"{op} {r()}, {r()}, {third}"]
        if kind < 0.55:
            op = rng.choice(["movs", "cmp", "adds", "subs"])
            return [f"{op} {r()}, #{rng.randrange(256)}"]
        if kind < 0.62:
            op = rng.choice(["lsls", "lsrs", "asrs"])
            k = rng.randrange(32) if op == "lsls" else rng.randrange(1, 33)
            return [f"{op} {r()}, {r()}, #{k}"]
        if kind < 0.67:
            return [f"rsbs {r()}, {r()}, #0"]
        if kind < 0.72:
            op = rng.choice(["rev", "rev16", "revsh", "sxtb", "sxth", "uxtb", "uxth"])
            return [f"{op} {r()}, {r()}"]
        if kind < 0.78:
            hi = r(HIGH)
            return rng.choice([[f"mov {hi}, {r()}"], [f"mov {r()}, {hi}"], [f"add {r()}, {hi}"],
                               [f"add {hi}, {r()}"], [f"cmp {hi}, {r()}"]])
        if kind < 0.88:
            return self.memory()
        if kind < 0.92:
            nzcv = rng.randrange(16)
            return [f"ldr r6, ={nzcv << 28:#x}", "msr apsr_nzcvq, r6"]
        if kind < 0.94:
            return [f"mrs {r()}, apsr"]
        if kind < 0.97:
            return [f"ldr {r()}, ={_value(rng):#x}"]
        return [f"str {r()}, [sp, #{4 * rng.randrange(16)}]" if rng.random() < 0.5
                else f"ldr {r()}, [sp, #{4 * rng.randrange(16)}]"]

    def memory(self):
        rng, r = self.rng, self.reg
        size, op = rng.choice([(4, "str"), (4, "ldr"), (2, "strh"), (2, "ldrh"), (1, "strb"),
                               (1, "ldrb"), (2, "ldrsh"), (1, "ldrsb")])
        offset = size * rng.randrange(256 // size)
        if op in ("ldrsh", "ldrsb") or rng.random() < 0.4:   # register offset
            index = "r6"
            return [f"ldr {index}, ={offset}", f"{op} {r(LOW[:6])}, [r7, {index}]"]
        if offset > 31 * size:
            offset = size * rng.randrange(32)
        return [f"{op} {r()}, [r7, #{offset}]"]

    def block(self, n):
        out = []
        while len(out) < n:
            kind = self.rng.random()
            if kind < 0.08:
                skip = self.label()
                body = [line for _ in range(self.rng.randrange(1, 4)) for line in self.straight()]
                out += [f"b{self.rng.choice(CONDS)} {skip}", *body, f"{skip}:"]
            elif kind < 0.11:
                regs = sorted(self.rng.sample(range(7), self.rng.randrange(1, 4)))
                dests = sorted(self.rng.sample(range(7), len(regs)))
                out += [f"push {{{', '.join(f'r{i}' for i in regs)}}}",
                        *self.straight(), f"pop {{{', '.join(f'r{i}' for i in dests)}}}"]
            elif kind < 0.13:
                regs = sorted(self.rng.sample(range(6), self.rng.randrange(1, 4)))
                lst = ", ".join(f"r{i}" for i in regs)
                op = self.rng.choice(["stmia", "ldmia"])
                out += ["mov r6, r7", f"{op} r6!, {{{lst}}}"]
            elif kind < 0.15:
                out.append(self.rng.choice(["bl leaf", "ldr r6, =leaf\nblx r6"]))
            else:
                out += self.straight()
        return out


def program(seed: int, length: int = 300) -> str:
    g = Generator(seed)
    rng = g.rng
    setup = [f"ldr {reg}, ={_value(rng):#x}" for reg in LOW]
    setup += [f"ldr r6, ={_value(rng):#x}\nmov {hi}, r6" for hi in HIGH]
    setup += [f"ldr r6, ={rng.randrange(16) << 28:#x}", "msr apsr_nzcvq, r6"]
    body = []
    for chunk in range(0, length, 40):     # literal pools between chunks
        body += g.block(40)
        skip = g.label()
        body += [f"b {skip}", ".ltorg", f"{skip}:"]
    leaf = [".thumb_func", "leaf:", *[line for _ in range(4) for line in g.straight()
                                      if "sp" not in line and "r7" not in line], "bx lr", ".ltorg"]
    return "\n".join([
        ".syntax unified", ".thumb",
        ".bss", ".balign 4", "buf: .space 256",
        ".section .text.start, \"ax\"", ".global _start", ".thumb_func", "_start:",
        "ldr r0, =__stack_top", "mov sp, r0", "sub sp, #64", "ldr r7, =buf",
        *setup, *body,
        ".global done", "done:", "b done", ".ltorg",
        *leaf, "",
    ])
