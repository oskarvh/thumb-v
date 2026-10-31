"""Executor: a minimal RV32IM machine with programmable Thumb regions.

Fetches from a Thumb region go through the expander; everything else runs as
native RV32 (without the C extension). This is the software counterpart of
the hardware: one register file, one PC, the decoder chosen by address.
"""

from . import expander
from . import rv32 as r

MASK = 0xFFFFFFFF
PAGE = 4096


class Trap(Exception):
    def __init__(self, cause: str, pc: int, tval: int = 0):
        super().__init__(f"{cause} at {pc:#010x} (tval {tval:#x})")
        self.cause, self.pc, self.tval = cause, pc, tval


class Memory:
    """Sparse, page-granular memory. Accesses outside mapped pages fault."""

    def __init__(self):
        self._pages: dict[int, bytearray] = {}
        self.log: list[tuple[int, int, int]] | None = None  # (addr, size, value) per store, if set

    def map(self, base: int, size: int):
        if base % PAGE or size % PAGE:
            raise ValueError("mappings must be page-aligned")
        for page in range(base // PAGE, (base + size) // PAGE):
            self._pages.setdefault(page, bytearray(PAGE))

    def write_bytes(self, addr: int, data: bytes):
        for start, offset, length in self._chunks(addr, len(data)):
            self._page(start, "store", addr)[offset:offset + length] = data[start - addr:start - addr + length]

    def read_bytes(self, addr: int, n: int) -> bytes:
        return b"".join(bytes(self._page(start, "load", addr)[offset:offset + length])
                        for start, offset, length in self._chunks(addr, n))

    @staticmethod
    def _chunks(addr, n):
        """Split [addr, addr + n) at page boundaries: (address, offset in page, length)."""
        end = addr + n
        while addr < end:
            offset = addr % PAGE
            length = min(PAGE - offset, end - addr)
            yield addr, offset, length
            addr += length

    def read(self, addr: int, n: int) -> int:
        return int.from_bytes(self.read_bytes(addr, n), "little")

    def write(self, addr: int, n: int, value: int):
        value &= (1 << (8 * n)) - 1
        self.write_bytes(addr, value.to_bytes(n, "little"))
        if self.log is not None:
            self.log.append((addr, n, value))

    def _page(self, addr, kind, base):
        page = self._pages.get((addr & MASK) // PAGE)
        if page is None:
            raise Trap(f"{kind}_access_fault", 0, base)
        return page


def _sext(value, bits):
    sign = 1 << (bits - 1)
    return (value & (sign - 1)) - (value & sign)


class Machine:
    def __init__(self, thumb_regions=(), options: expander.Options = expander.Options()):
        self.x = [0] * 32
        self.pc = 0
        self.mstatus = 0
        self.mem = Memory()
        self.thumb_regions = list(thumb_regions)  # [(base, limit)), like the region CSRs
        self.options = options
        self.retired_thumb = 0   # Thumb instructions completed
        self.retired_ops = 0     # RV32 ops executed, native or expanded
        self._expansions = {}    # (pc, hw1, hw2) -> Expansion; expand() is a pure function

    def in_thumb(self, addr: int) -> bool:
        return any(base <= addr < limit for base, limit in self.thumb_regions)

    def step(self):
        """Execute one instruction: one Thumb instruction (all its ops) or one RV32 op."""
        pc = self.pc
        if self.in_thumb(pc):
            hw1 = self.mem.read(pc, 2)
            hw2 = self.mem.read(pc + 2, 2) if expander.isa.is_32bit(hw1) else 0
            key = (pc, hw1, hw2)
            exp = self._expansions.get(key)
            if exp is None:
                exp = self._expansions[key] = expander.expand(hw1, hw2, pc, self.options)
            for i, op in enumerate(exp.ops):
                target = self.execute(op, pc, link=pc + exp.length)
                if target is not None:
                    assert i == len(exp.ops) - 1, f"{exp.name}: control transfer before the last op"
                    self.pc = target
                    break
            else:
                self.pc = (pc + exp.length) & MASK
            self.retired_thumb += 1
        else:
            target = self.execute(self.mem.read(pc, 4), pc, link=pc + 4)
            self.pc = target if target is not None else (pc + 4) & MASK

    # --- RV32IM ------------------------------------------------------------------

    def _set(self, rd, value):
        if rd:
            self.x[rd] = value & MASK

    def execute(self, w: int, pc: int, link: int) -> int | None:
        """Execute one RV32 instruction at `pc`. Returns the target if control transfers."""
        self.retired_ops += 1
        x = self.x
        opcode, rd, f3 = w & 0x7F, (w >> 7) & 0x1F, (w >> 12) & 7
        rs1, rs2, f7 = (w >> 15) & 0x1F, (w >> 20) & 0x1F, w >> 25
        a, b = x[rs1], x[rs2]
        imm_i = _sext(w >> 20, 12)

        if opcode == 0x37:                                    # LUI
            self._set(rd, w & 0xFFFFF000)
        elif opcode == 0x17:                                  # AUIPC
            self._set(rd, pc + (w & 0xFFFFF000))
        elif opcode == 0x6F:                                  # JAL
            off = _sext((w >> 31) << 20 | ((w >> 12) & 0xFF) << 12
                        | ((w >> 20) & 1) << 11 | ((w >> 21) & 0x3FF) << 1, 21)
            self._set(rd, link)
            return (pc + off) & MASK
        elif opcode == 0x67 and f3 == 0:                      # JALR
            target = (a + imm_i) & MASK & ~1
            self._set(rd, link)
            return target
        elif opcode == 0x63:                                  # BRANCH
            off = _sext((w >> 31) << 12 | ((w >> 7) & 1) << 11
                        | ((w >> 25) & 0x3F) << 5 | ((w >> 8) & 0xF) << 1, 13)
            sa, sb = _sext(a, 32), _sext(b, 32)
            taken = {0: a == b, 1: a != b, 4: sa < sb, 5: sa >= sb, 6: a < b, 7: a >= b}.get(f3)
            if taken is None:
                raise Trap("illegal_instruction", pc, w)
            return (pc + off) & MASK if taken else None
        elif opcode == 0x03:                                  # LOAD
            addr = (a + imm_i) & MASK
            size, signed = {0: (1, True), 1: (2, True), 2: (4, False),
                            4: (1, False), 5: (2, False)}.get(f3, (None, None))
            if size is None:
                raise Trap("illegal_instruction", pc, w)
            if addr % size:
                raise Trap("load_misaligned", pc, addr)
            value = self._load(addr, size, pc)
            self._set(rd, _sext(value, 8 * size) if signed else value)
        elif opcode == 0x23:                                  # STORE
            addr = (a + _sext((w >> 25) << 5 | (w >> 7) & 0x1F, 12)) & MASK
            size = {0: 1, 1: 2, 2: 4}.get(f3)
            if size is None:
                raise Trap("illegal_instruction", pc, w)
            if addr % size:
                raise Trap("store_misaligned", pc, addr)
            self._store(addr, size, b, pc)
        elif opcode == 0x13:                                  # OP-IMM
            sh = rs2
            if f3 == 0:
                v = a + imm_i
            elif f3 == 2:
                v = int(_sext(a, 32) < imm_i)
            elif f3 == 3:
                v = int(a < (imm_i & MASK))
            elif f3 == 4:
                v = a ^ imm_i
            elif f3 == 6:
                v = a | imm_i
            elif f3 == 7:
                v = a & imm_i
            elif f3 == 1 and f7 == 0:
                v = a << sh
            elif f3 == 5 and f7 == 0:
                v = a >> sh
            elif f3 == 5 and f7 == 0x20:
                v = _sext(a, 32) >> sh
            else:
                raise Trap("illegal_instruction", pc, w)
            self._set(rd, v)
        elif opcode == 0x33:                                  # OP, M extension
            self._set(rd, self._op(f7, f3, a, b, pc, w))
        elif opcode == 0x0F:                                  # FENCE, FENCE.I
            pass
        elif opcode == 0x73:                                  # SYSTEM
            return self._system(w, f3, rd, rs1, pc)
        else:
            raise Trap("illegal_instruction", pc, w)
        return None

    def _op(self, f7, f3, a, b, pc, w):
        sa, sb = _sext(a, 32), _sext(b, 32)
        if f7 == 0x00:
            return {0: a + b, 1: a << (b & 31), 2: int(sa < sb), 3: int(a < b),
                    4: a ^ b, 5: a >> (b & 31), 6: a | b, 7: a & b}[f3]
        if f7 == 0x20 and f3 == 0:
            return a - b
        if f7 == 0x20 and f3 == 5:
            return sa >> (b & 31)
        if f7 == 0x01:
            if f3 == 0:
                return sa * sb
            if f3 == 1:
                return (sa * sb) >> 32
            if f3 == 2:
                return (sa * b) >> 32
            if f3 == 3:
                return (a * b) >> 32
            if f3 == 4:
                return -1 if b == 0 else (a if sa == -(1 << 31) and sb == -1
                                          else int(sa / sb))
            if f3 == 5:
                return MASK if b == 0 else a // b
            if f3 == 6:
                return a if b == 0 else (0 if sa == -(1 << 31) and sb == -1
                                         else sa - sb * int(sa / sb))
            if f3 == 7:
                return a if b == 0 else a % b
        raise Trap("illegal_instruction", pc, w)

    def _system(self, w, f3, rd, rs1, pc):
        if w == r.ecall():
            raise Trap("ecall", pc)
        if w == r.ebreak():
            raise Trap("breakpoint", pc)
        if w == r.wfi():
            return None
        csr = w >> 20
        if f3 in (1, 2, 3, 5, 6, 7) and csr == r.MSTATUS:
            old = self.mstatus
            src = rs1 if f3 >= 5 else self.x[rs1]   # immediate forms use the field itself
            if f3 & 3 == 1:
                new = src
            elif f3 & 3 == 2:
                new = old | src
            else:
                new = old & ~src
            # Writes are skipped when rs1/uimm is 0 for the set/clear forms.
            if f3 & 3 == 1 or rs1:
                self.mstatus = new & MASK
            self._set(rd, old)
            return None
        raise Trap("illegal_instruction", pc, w)

    def _load(self, addr, size, pc):
        try:
            return self.mem.read(addr, size)
        except Trap as t:
            raise Trap(t.cause, pc, addr) from None

    def _store(self, addr, size, value, pc):
        try:
            self.mem.write(addr, size, value)
        except Trap as t:
            raise Trap(t.cause, pc, addr) from None
