"""ARMv6-M Thumb decode table.

The patterns mirror docs/isa-coverage.md exactly; tests/test_isa.py keeps the
two in sync. In a pattern, 0/1 are fixed bits and letters are fields. A
letter that appears in several places (BL's `i`) is one field, concatenated
from the most significant bit down. Fields are case-sensitive: in
`D mmmm ddd`, `D` is the top bit of rd and the expander combines it as D:ddd.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Encoding:
    name: str
    patterns: tuple[str, ...]  # one per halfword, first halfword first
    mask: int = field(init=False)
    value: int = field(init=False)

    def __post_init__(self):
        bits = self.bits
        if len(bits) != 16 * len(self.patterns):
            raise ValueError(f"{self.name}: pattern is {len(bits)} bits")
        mask = value = 0
        for b in bits:
            mask = mask << 1 | (b in "01")
            value = value << 1 | (b == "1")
        object.__setattr__(self, "mask", mask)
        object.__setattr__(self, "value", value)

    @property
    def bits(self) -> str:
        return "".join(p.replace(" ", "") for p in self.patterns)

    @property
    def length(self) -> int:
        return 2 * len(self.patterns)

    def matches(self, word: int) -> bool:
        return word & self.mask == self.value

    def fields(self, word: int) -> dict[str, int]:
        out: dict[str, int] = {}
        bits = self.bits
        for i, b in enumerate(bits):
            if b not in "01":
                bit = word >> (len(bits) - 1 - i) & 1
                out[b] = out.get(b, 0) << 1 | bit
        return out


def _e(name, *patterns):
    return Encoding(name, patterns)


ENCODINGS = (
    # Shift (immediate), add, subtract, move, compare
    _e("LSLS_imm", "00000 iiiii mmm ddd"),
    _e("MOVS_reg", "00000 00000 mmm ddd"),
    _e("LSRS_imm", "00001 iiiii mmm ddd"),
    _e("ASRS_imm", "00010 iiiii mmm ddd"),
    _e("ADDS_reg", "0001100 mmm nnn ddd"),
    _e("SUBS_reg", "0001101 mmm nnn ddd"),
    _e("ADDS_imm3", "0001110 iii nnn ddd"),
    _e("SUBS_imm3", "0001111 iii nnn ddd"),
    _e("MOVS_imm", "00100 ddd iiiiiiii"),
    _e("CMP_imm", "00101 nnn iiiiiiii"),
    _e("ADDS_imm8", "00110 ddd iiiiiiii"),
    _e("SUBS_imm8", "00111 ddd iiiiiiii"),
    # Data processing (register)
    _e("ANDS", "0100000000 mmm ddd"),
    _e("EORS", "0100000001 mmm ddd"),
    _e("LSLS_reg", "0100000010 mmm ddd"),
    _e("LSRS_reg", "0100000011 mmm ddd"),
    _e("ASRS_reg", "0100000100 mmm ddd"),
    _e("ADCS", "0100000101 mmm ddd"),
    _e("SBCS", "0100000110 mmm ddd"),
    _e("RORS", "0100000111 mmm ddd"),
    _e("TST", "0100001000 mmm nnn"),
    _e("RSBS", "0100001001 nnn ddd"),
    _e("CMP_reg", "0100001010 mmm nnn"),
    _e("CMN", "0100001011 mmm nnn"),
    _e("ORRS", "0100001100 mmm ddd"),
    _e("MULS", "0100001101 nnn ddd"),
    _e("BICS", "0100001110 mmm ddd"),
    _e("MVNS", "0100001111 mmm ddd"),
    # Special data processing and branch exchange
    _e("ADD_hi", "01000100 D mmmm ddd"),
    _e("CMP_hi", "01000101 N mmmm nnn"),
    _e("MOV_hi", "01000110 D mmmm ddd"),
    _e("BX", "010001110 mmmm 000"),
    _e("BLX", "010001111 mmmm 000"),
    # Loads and stores
    _e("LDR_lit", "01001 ttt iiiiiiii"),
    _e("STR_reg", "0101000 mmm nnn ttt"),
    _e("STRH_reg", "0101001 mmm nnn ttt"),
    _e("STRB_reg", "0101010 mmm nnn ttt"),
    _e("LDRSB_reg", "0101011 mmm nnn ttt"),
    _e("LDR_reg", "0101100 mmm nnn ttt"),
    _e("LDRH_reg", "0101101 mmm nnn ttt"),
    _e("LDRB_reg", "0101110 mmm nnn ttt"),
    _e("LDRSH_reg", "0101111 mmm nnn ttt"),
    _e("STR_imm", "01100 iiiii nnn ttt"),
    _e("LDR_imm", "01101 iiiii nnn ttt"),
    _e("STRB_imm", "01110 iiiii nnn ttt"),
    _e("LDRB_imm", "01111 iiiii nnn ttt"),
    _e("STRH_imm", "10000 iiiii nnn ttt"),
    _e("LDRH_imm", "10001 iiiii nnn ttt"),
    _e("STR_sp", "10010 ttt iiiiiiii"),
    _e("LDR_sp", "10011 ttt iiiiiiii"),
    # Address generation and stack adjustment
    _e("ADR", "10100 ddd iiiiiiii"),
    _e("ADD_rd_sp", "10101 ddd iiiiiiii"),
    _e("ADD_sp", "101100000 iiiiiii"),
    _e("SUB_sp", "101100001 iiiiiii"),
    # Miscellaneous
    _e("SXTH", "1011001000 mmm ddd"),
    _e("SXTB", "1011001001 mmm ddd"),
    _e("UXTH", "1011001010 mmm ddd"),
    _e("UXTB", "1011001011 mmm ddd"),
    _e("PUSH", "1011010 M rrrrrrrr"),
    _e("CPSID", "10110110011 1 0010"),
    _e("CPSIE", "10110110011 0 0010"),
    _e("REV", "1011101000 mmm ddd"),
    _e("REV16", "1011101001 mmm ddd"),
    _e("REVSH", "1011101011 mmm ddd"),
    _e("POP", "1011110 P rrrrrrrr"),
    _e("BKPT", "10111110 iiiiiiii"),
    _e("NOP", "1011111100000000"),
    _e("YIELD", "1011111100010000"),
    _e("WFE", "1011111100100000"),
    _e("WFI", "1011111100110000"),
    _e("SEV", "1011111101000000"),
    # Load and store multiple
    _e("STM", "11000 nnn rrrrrrrr"),
    _e("LDM", "11001 nnn rrrrrrrr"),
    # Branches and exception generation
    _e("B_cond", "1101 cccc iiiiiiii"),
    _e("UDF", "11011110 iiiiiiii"),
    _e("SVC", "11011111 iiiiiiii"),
    _e("B", "11100 iiiiiiiiiii"),
    # 32-bit instructions
    _e("BL", "11110 s iiiiiiiiii", "11 j 1 k iiiiiiiiiii"),
    _e("MSR", "111100111000 nnnn", "10001000 ssssssss"),
    _e("MRS", "1111001111101111", "1000 dddd ssssssss"),
    _e("DSB", "1111001110111111", "100011110100 oooo"),
    _e("DMB", "1111001110111111", "100011110101 oooo"),
    _e("ISB", "1111001110111111", "100011110110 oooo"),
)

BY_NAME = {e.name: e for e in ENCODINGS}


def is_32bit(hw1: int) -> bool:
    """Thumb length rule: hw1[15:11] in {11101, 11110, 11111} starts a 32-bit instruction."""
    return hw1 >> 11 in (0b11101, 0b11110, 0b11111)


def decode(hw1: int, hw2: int = 0) -> tuple[Encoding, dict[str, int]] | None:
    """Decode one instruction. Returns None for undefined encodings.

    Where patterns overlap (MOVS_reg inside LSLS_imm, UDF/SVC inside B_cond),
    the most specific match wins.
    """
    if is_32bit(hw1):
        word, candidates = hw1 << 16 | hw2, [e for e in ENCODINGS if e.length == 4]
    else:
        word, candidates = hw1, [e for e in ENCODINGS if e.length == 2]
    matches = [e for e in candidates if e.matches(word)]
    if not matches:
        return None
    best = max(matches, key=lambda e: bin(e.mask).count("1"))
    return best, best.fields(word)
