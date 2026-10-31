"""Directed Thumb test programs: edge-case operands for every instruction class.

Each group returns the assembly text of a complete program. The programs
don't check their own results: the program lockstep compares every
instruction against the reference, flags included.

Register use: r0-r5 operands and results, r6 scratch, r7 points at `buf`.
"""

EDGES = [0, 1, 2, 0x7F, 0x80, 0xFF, 0x7FFF, 0x8000, 0x7FFFFFFF, 0x80000000, 0x80000001,
         0xFFFFFFFE, 0xFFFFFFFF, 0x55555555, 0xAAAAAAAA]
FEW = [0, 1, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF]
SHIFT_AMOUNTS = [0, 1, 7, 31, 32, 33, 63, 64, 127, 128, 255, 256, 257, 0xFFFFFFE0, 0xFFFFFF01]
CONDS = ["eq", "ne", "cs", "cc", "mi", "pl", "vs", "vc", "hi", "ls", "ge", "lt", "gt", "le"]


class Program:
    def __init__(self):
        self.lines = []
        self._since_pool = 0
        self._labels = 0

    def label(self):
        self._labels += 1
        return f"lbl{self._labels}"

    def emit(self, *lines):
        self.lines.extend(lines)
        self._since_pool += len(lines)
        if self._since_pool > 150:  # keep literals within LDR's 1 KiB reach
            skip = self.label()
            self.lines += [f"b {skip}", ".ltorg", f"{skip}:"]
            self._since_pool = 0

    def li(self, reg, value):
        self.emit(f"ldr {reg}, ={value:#x}")

    def flags(self, nzcv):
        self.emit(f"ldr r6, ={nzcv << 28:#x}", "msr apsr_nzcvq, r6")

    def text(self, functions=""):
        return "\n".join([
            ".syntax unified", ".thumb",
            ".bss", ".balign 4", "buf: .space 256",
            ".section .text.start, \"ax\"", ".global _start", ".thumb_func", "_start:",
            "ldr r0, =__stack_top", "mov sp, r0", "ldr r7, =buf",
            *self.lines,
            ".global done", "done:", "b done", ".ltorg",
            functions, "",
        ])


def alu():
    p = Program()
    binary = ["adds r2, r0, r1", "subs r2, r0, r1", "adcs r0, r1", "sbcs r0, r1",
              "ands r0, r1", "eors r0, r1", "orrs r0, r1", "bics r0, r1", "muls r0, r1, r0",
              "cmp r0, r1", "cmn r0, r1", "tst r0, r1"]
    for i, (a, b) in enumerate((a, b) for a in EDGES for b in EDGES):
        for j, op in enumerate(binary):
            p.li("r0", a)
            p.li("r1", b)
            p.flags((i + j) % 16)   # vary the carry-in for ADCS/SBCS
            p.emit(op)
    unary_and_imm = ["rsbs r2, r0, #0", "mvns r2, r0", "adds r2, r0, #7", "subs r2, r0, #7",
                     "adds r0, #255", "subs r0, #255", "cmp r0, #255", "cmp r0, #0",
                     "movs r2, #0", "movs r2, #255", "movs r2, r0"]
    for i, a in enumerate(EDGES):
        for j, op in enumerate(unary_and_imm):
            p.li("r0", a)
            p.flags((i * 5 + j) % 16)
            p.emit(op)
    return p.text()


def shifts():
    p = Program()
    imm = ["lsls r2, r0, #1", "lsls r2, r0, #15", "lsls r2, r0, #31",
           "lsrs r2, r0, #1", "lsrs r2, r0, #16", "lsrs r2, r0, #31", "lsrs r2, r0, #32",
           "asrs r2, r0, #1", "asrs r2, r0, #16", "asrs r2, r0, #31", "asrs r2, r0, #32"]
    for i, a in enumerate(EDGES):
        for op in imm:
            p.li("r0", a)
            p.flags(0b0010 if i % 2 else 0b1101)
            p.emit(op)
    for value in [0x80000001, 0xFFFFFFFF, 0x12345678, 0x7FFFFFFF, 1, 0x80000000]:
        for amount in SHIFT_AMOUNTS:
            for k, op in enumerate(["lsls", "lsrs", "asrs", "rors"]):
                p.li("r0", value)
                p.li("r1", amount)
                p.flags(0b0010 if k % 2 else 0b1101)   # C set and clear: amount 0 keeps it
                p.emit(f"{op} r0, r1")
    return p.text()


def branches():
    p = Program()
    p.emit("movs r2, #0")
    for a in FEW:
        for b in FEW:
            for cond in CONDS:
                skip = p.label()
                p.li("r0", a)
                p.li("r1", b)
                p.emit("cmp r0, r1", f"b{cond} {skip}", "adds r2, #1", f"{skip}:")
    for nzcv in range(16):          # every condition against every flag state
        for cond in CONDS:
            skip = p.label()
            p.flags(nzcv)
            p.emit(f"b{cond} {skip}", "adds r2, #1", f"{skip}:")
    back, fwd = p.label(), p.label()   # a taken backward branch, then B over a gap
    p.emit("movs r3, #3", f"{back}:", "subs r3, #1", f"bne {back}", f"b {fwd}", "movs r2, #99", f"{fwd}:")
    return p.text()


def memory():
    p = Program()
    for word in [0x80FF7F01, 0x7F80FF00, 0xFFFFFFFF, 0x01234567]:
        p.li("r0", word)
        p.emit("str r0, [r7, #0]", "str r0, [r7, #4]")
        for k in range(4):
            p.emit(f"ldrb r1, [r7, #{k}]", f"movs r3, #{k}", "ldrsb r2, [r7, r3]", "ldrb r4, [r7, r3]")
        for k in (0, 2):
            p.emit(f"ldrh r1, [r7, #{k}]", f"movs r3, #{k}", "ldrsh r2, [r7, r3]", "ldrh r4, [r7, r3]")
        p.emit("movs r3, #4", "ldr r1, [r7, r3]", "ldr r2, [r7, #4]")
        p.li("r5", 0xA5C3)
        p.emit("strb r5, [r7, #1]", "strh r5, [r7, #6]", "movs r3, #3", "strb r5, [r7, r3]",
               "movs r3, #2", "strh r5, [r7, r3]", "movs r3, #8", "str r5, [r7, r3]", "ldr r1, [r7, #0]", "ldr r2, [r7, #4]", "ldr r4, [r7, #8]")
        p.emit("ldr r1, [r7, #124]", "str r0, [r7, #124]", "ldrb r1, [r7, #31]", "strb r0, [r7, #31]",
               "ldrh r1, [r7, #62]", "strh r0, [r7, #62]")
    p.emit("sub sp, #16", "str r0, [sp, #0]", "str r1, [sp, #12]", "ldr r2, [sp, #12]",
           "ldr r3, [sp, #0]", "add r4, sp, #8", "add sp, #16")
    return p.text()


def stack():
    p = Program()
    for i, a in enumerate(EDGES[:6]):
        p.li("r0", a)
        p.li("r1", ~a & 0xFFFFFFFF)
        p.li("r2", i)
        p.li("r3", a ^ 0x5A5A5A5A)
    p.emit("push {r0}", "pop {r4}", "push {r0, r2}", "pop {r4, r5}",
           "push {r0, r1, r2, r3}", "pop {r2, r3, r4, r5}",
           "push {r0, r1, r2, r3, r4, r5, r6, r7}", "pop {r0, r1, r2, r3, r4, r5, r6, r7}",
           "bl func_push_lr", "bl func_lowregs")
    p.emit("mov r6, r7", "stmia r6!, {r0, r1, r2, r3}", "mov r6, r7", "ldmia r6!, {r2, r3, r4, r5}",
           "mov r6, r7", "ldmia r6, {r2, r6}",                 # base in list: no writeback
           "mov r1, r7", "stmia r1!, {r1, r2}",                # base lowest in list: stores old base
           "mov r6, r7", "stmia r6!, {r5}", "mov r6, r7", "ldmia r6!, {r0}")
    functions = "\n".join([
        ".thumb_func", "func_push_lr:", "push {r4, r5, lr}", "movs r4, #1", "adds r5, r4, r4",
        "pop {r4, r5, pc}",
        ".thumb_func", "func_lowregs:", "push {lr}", "bl func_push_lr", "pop {r0}", "bx r0",
    ])
    return p.text(functions)


def hireg():
    p = Program()
    for a in FEW:
        for b in FEW:
            p.li("r0", a)
            p.li("r1", b)
            p.emit("mov r8, r0", "mov r9, r1", "mov r12, r1", "add r8, r9", "mov r2, r8",
                   "add r2, r12", "cmp r8, r9", "cmp r9, r0", "cmp r0, r12", "mov r10, r8",
                   "mov r11, r10", "add r3, r11")
    for pad in (False, True):   # PC reads at both word alignments
        lit, skip = p.label(), p.label()
        if pad:
            p.emit("nop")
        # ADR and LDR (literal) only reach forward, so the literal follows.
        p.emit("add r0, pc", "mov r1, pc", f"adr r2, {lit}", f"ldr r3, {lit}", "mov r4, pc", "nop",
               "add r5, pc", f"b {skip}", ".balign 4", f"{lit}: .word 0xCAFEF00D", f"{skip}:")
    p.emit("mov r6, sp", "add r6, sp", "mov r6, sp", "subs r6, #8", "mov sp, r6", "add sp, #8",
           "add r4, sp, #4")
    target_add, here, target_mov, target_bx = p.label(), p.label(), p.label(), p.label()
    # GAS rejects a label difference in `ldr =`, but accepts a symbol set to one.
    p.emit(f"ldr r6, =add_pc_offset", f"{here}:", "add pc, r6", "movs r2, #77",
           f"{target_add}:", f".set add_pc_offset, {target_add} - {here} - 4",
           f"ldr r6, ={target_mov} + 1", "mov pc, r6", "movs r2, #88",
           f"{target_mov}:", "ldr r3, =func_ret", "blx r3", "bl func_ret",
           f"ldr r3, ={target_bx} + 1", "bx r3", "movs r2, #66", f"{target_bx}:")
    return p.text("\n".join([".thumb_func", "func_ret:", "movs r0, #5", "bx lr"]))


def misc():
    p = Program()
    for a in EDGES:
        p.li("r0", a)
        p.emit("rev r1, r0", "rev16 r2, r0", "revsh r3, r0", "sxtb r4, r0", "sxth r5, r0",
               "uxtb r1, r0", "uxth r2, r0")
    for nzcv in range(16):
        p.flags(nzcv)
        p.emit("mrs r2, apsr")
    p.emit("movs r0, #1", "msr primask, r0", "mrs r1, primask", "cpsie i", "mrs r1, primask",
           "cpsid i", "mrs r1, primask", "movs r0, #0", "msr primask, r0", "mrs r1, primask",
           "nop", "sev", "dsb", "dmb", "isb", "mov r8, r8")
    return p.text()


GROUPS = {"alu": alu, "shifts": shifts, "branches": branches, "memory": memory,
          "stack": stack, "hireg": hireg, "misc": misc}
