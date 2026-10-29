"""Check the decode table against the coverage doc and the GNU ARM assembler."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import REQUIRE_TOOLS
from thumbv import isa

DOC = Path(__file__).parents[1] / "docs" / "isa-coverage.md"

# One example per encoding, assembled to check that it decodes as that encoding.
EXAMPLES = {
    "LSLS_imm": "lsls r1, r2, #3",
    "MOVS_reg": "movs r1, r2",
    "LSRS_imm": "lsrs r1, r2, #3",
    "ASRS_imm": "asrs r1, r2, #3",
    "ADDS_reg": "adds r1, r2, r3",
    "SUBS_reg": "subs r1, r2, r3",
    "ADDS_imm3": "adds r1, r2, #3",
    "SUBS_imm3": "subs r1, r2, #3",
    "MOVS_imm": "movs r1, #200",
    "CMP_imm": "cmp r1, #200",
    "ADDS_imm8": "adds r1, #200",
    "SUBS_imm8": "subs r1, #200",
    "ANDS": "ands r1, r2",
    "EORS": "eors r1, r2",
    "LSLS_reg": "lsls r1, r2",
    "LSRS_reg": "lsrs r1, r2",
    "ASRS_reg": "asrs r1, r2",
    "ADCS": "adcs r1, r2",
    "SBCS": "sbcs r1, r2",
    "RORS": "rors r1, r2",
    "TST": "tst r1, r2",
    "RSBS": "rsbs r1, r2, #0",
    "CMP_reg": "cmp r1, r2",
    "CMN": "cmn r1, r2",
    "ORRS": "orrs r1, r2",
    "MULS": "muls r1, r2, r1",
    "BICS": "bics r1, r2",
    "MVNS": "mvns r1, r2",
    "ADD_hi": "add r1, r9",
    "CMP_hi": "cmp r9, r1",
    "MOV_hi": "mov r9, r1",
    "BX": "bx lr",
    "BLX": "blx r3",
    "LDR_lit": "ldr r1, [pc, #400]",
    "STR_reg": "str r1, [r2, r3]",
    "STRH_reg": "strh r1, [r2, r3]",
    "STRB_reg": "strb r1, [r2, r3]",
    "LDRSB_reg": "ldrsb r1, [r2, r3]",
    "LDR_reg": "ldr r1, [r2, r3]",
    "LDRH_reg": "ldrh r1, [r2, r3]",
    "LDRB_reg": "ldrb r1, [r2, r3]",
    "LDRSH_reg": "ldrsh r1, [r2, r3]",
    "STR_imm": "str r1, [r2, #20]",
    "LDR_imm": "ldr r1, [r2, #20]",
    "STRB_imm": "strb r1, [r2, #20]",
    "LDRB_imm": "ldrb r1, [r2, #20]",
    "STRH_imm": "strh r1, [r2, #20]",
    "LDRH_imm": "ldrh r1, [r2, #20]",
    "STR_sp": "str r1, [sp, #400]",
    "LDR_sp": "ldr r1, [sp, #400]",
    "ADR": "adr r1, fwd",
    "ADD_rd_sp": "add r1, sp, #400",
    "ADD_sp": "add sp, #400",
    "SUB_sp": "sub sp, #400",
    "SXTH": "sxth r1, r2",
    "SXTB": "sxtb r1, r2",
    "UXTH": "uxth r1, r2",
    "UXTB": "uxtb r1, r2",
    "PUSH": "push {r1, r4, lr}",
    "CPSID": "cpsid i",
    "CPSIE": "cpsie i",
    "REV": "rev r1, r2",
    "REV16": "rev16 r1, r2",
    "REVSH": "revsh r1, r2",
    "POP": "pop {r1, r4, pc}",
    "BKPT": "bkpt #42",
    "NOP": ".inst.n 0xbf00",  # GAS emits mov r8, r8 for `nop` on Cortex-M0
    "YIELD": "yield",
    "WFE": "wfe",
    "WFI": "wfi",
    "SEV": "sev",
    "STM": "stmia r1!, {r2, r3}",
    "LDM": "ldmia r1!, {r2, r3}",
    "B_cond": "bne lbl",
    "UDF": "udf #42",
    "SVC": "svc #42",
    "B": "b lbl",
    "BL": "bl lbl",
    "MSR": "msr primask, r1",
    "MRS": "mrs r1, primask",
    "DSB": "dsb sy",
    "DMB": "dmb sy",
    "ISB": "isb sy",
}


def _doc_patterns() -> list[str]:
    """Encoding patterns from the first column of the coverage doc's tables."""
    patterns = []
    for line in DOC.read_text().splitlines():
        if not line.startswith("| `"):
            continue
        first_cell = line.split(" | ")[0]
        spans = re.findall(r"`([^`]*)`", first_cell)
        bits = "".join(s.replace(" ", "") for s in spans)
        # Encoding patterns have fixed bits and are 16 or 32 bits long; other
        # tables (e.g. instruction names in code spans) don't.
        if all(re.fullmatch(r"[01a-zA-Z ]*[01][01a-zA-Z ]*", s) for s in spans) and len(bits) in (16, 32):
            patterns.append(bits)
    return patterns


def test_table_matches_doc():
    ours = sorted(e.bits for e in isa.ENCODINGS)
    assert sorted(_doc_patterns()) == ours


def test_names_unique():
    assert len(isa.BY_NAME) == len(isa.ENCODINGS) == 83


def test_examples_cover_table():
    assert set(EXAMPLES) == set(isa.BY_NAME)


def test_examples_decode_as_expected(tmp_path):
    cc = "arm-none-eabi-as"
    if shutil.which(cc) is None:
        if REQUIRE_TOOLS:
            pytest.fail(f"{cc} not found")
        pytest.skip(f"{cc} not found")
    names = list(EXAMPLES)
    src = tmp_path / "ex.S"
    # A label after each example lets us find where each one starts.
    body = "".join(f"{EXAMPLES[n]}\n.L{i}:\n" for i, n in enumerate(names))
    src.write_text(".syntax unified\n.thumb\n.text\n.balign 4\nlbl:\n" + body
                   + ".balign 4\nfwd: .word 0\n")
    obj = tmp_path / "ex.o"
    subprocess.run([cc, "-mcpu=cortex-m0", "-o", str(obj), str(src)], check=True)
    text = subprocess.run(["arm-none-eabi-objcopy", "-O", "binary", "-j", ".text", str(obj),
                           "/dev/stdout"], capture_output=True, check=True).stdout

    pos = 0
    for name in names:
        hw1 = int.from_bytes(text[pos:pos + 2], "little")
        hw2 = int.from_bytes(text[pos + 2:pos + 4], "little")
        result = isa.decode(hw1, hw2)
        assert result is not None, f"{name}: {hw1:#06x} did not decode"
        assert result[0].name == name, f"{name}: decoded as {result[0].name}"
        pos += result[0].length


def test_field_extraction():
    enc, f = isa.decode(0x4449)  # add r1, r9
    assert enc.name == "ADD_hi" and f == {"D": 0, "m": 9, "d": 1}
    enc, f = isa.decode(0x44C9)  # add r9, r9
    assert enc.name == "ADD_hi" and f == {"D": 1, "m": 9, "d": 1}
    # BL's imm10 and imm11 are one field `i`, split around j/1/k.
    enc, f = isa.decode(0xF7FF, 0xFFFE)  # bl .-0
    assert enc.name == "BL" and f == {"s": 1, "i": (1 << 21) - 2, "j": 1, "k": 1}


def test_every_halfword_decodes_consistently():
    """All 65536 first halfwords: 32-bit prefixes defer to hw2, the rest decode or are undefined."""
    for hw in range(1 << 16):
        if isa.is_32bit(hw):
            continue
        result = isa.decode(hw)
        if result is not None:
            assert result[0].length == 2
