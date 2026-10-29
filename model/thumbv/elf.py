"""Minimal ELF loading shared by the model, the reference runs and the tests."""

from dataclasses import dataclass
from pathlib import Path

from elftools.elf.elffile import ELFFile


@dataclass
class Segment:
    addr: int
    data: bytes


@dataclass
class Image:
    machine: str
    entry: int
    segments: list[Segment]
    symbols: dict[str, int]


def load(path: str | Path) -> Image:
    """Read the loadable segments and symbol table of an ELF file."""
    with open(path, "rb") as f:
        elf = ELFFile(f)
        segments = []
        for seg in elf.iter_segments():
            if seg["p_type"] != "PT_LOAD":
                continue
            # Zero-fill .bss-style tails (memsz > filesz).
            data = seg.data().ljust(seg["p_memsz"], b"\0")
            segments.append(Segment(seg["p_paddr"], data))

        symbols = {}
        symtab = elf.get_section_by_name(".symtab")
        if symtab is not None:
            for sym in symtab.iter_symbols():
                if sym.name and sym["st_shndx"] != "SHN_UNDEF":
                    symbols[sym.name] = sym["st_value"]

        return Image(elf["e_machine"], elf["e_entry"], segments, symbols)
