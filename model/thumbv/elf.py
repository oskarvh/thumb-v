"""Minimal ELF loading shared by the model, the reference runs and the tests."""

from dataclasses import dataclass
from pathlib import Path

from elftools.elf.elffile import ELFFile


@dataclass
class Segment:
    addr: int
    data: bytes
    executable: bool = False


@dataclass
class Image:
    machine: str
    entry: int
    segments: list[Segment]
    symbols: dict[str, int]
    functions: dict[str, int]  # global function symbols (Thumb ones have bit 0 set)

    @property
    def is_thumb(self) -> bool:
        return self.machine == "EM_ARM"

    def code_ranges(self) -> list[tuple[int, int]]:
        """[base, limit) of each executable segment."""
        return [(s.addr, s.addr + len(s.data)) for s in self.segments if s.executable]


def load(path: str | Path) -> Image:
    """Read the loadable segments and symbol table of an ELF file."""
    with open(path, "rb") as f:
        elf = ELFFile(f)
        segments = []
        for seg in elf.iter_segments():
            if seg["p_type"] != "PT_LOAD" or seg["p_memsz"] == 0:
                continue
            # Zero-fill .bss-style tails (memsz > filesz).
            data = seg.data().ljust(seg["p_memsz"], b"\0")
            segments.append(Segment(seg["p_paddr"], data, executable=bool(seg["p_flags"] & 1)))

        symbols, functions = {}, {}
        symtab = elf.get_section_by_name(".symtab")
        if symtab is not None:
            for sym in symtab.iter_symbols():
                if not sym.name or sym["st_shndx"] == "SHN_UNDEF":
                    continue
                symbols[sym.name] = sym["st_value"]
                if sym["st_info"]["type"] == "STT_FUNC" and sym["st_info"]["bind"] == "STB_GLOBAL":
                    functions[sym.name] = sym["st_value"]

        return Image(elf["e_machine"], elf["e_entry"], segments, symbols, functions)
