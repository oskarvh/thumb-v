"""Build recipes for test programs and benchmarks, shared by the tests and measurements.

Every recipe writes its output into a caller-supplied directory and returns
the ELF paths. Missing cross toolchains raise ToolMissing.

Memory layout of the programs (see tests/link/):
  Thumb programs        code 0x0001_0000, data 0x2000_0000 (48 KiB)
  Thumb libraries       code 0x0001_0000, data 0x2000_0000 (16 KiB)   for mixed programs
  RV32 programs         code 0x0002_0000, data 0x2000_4000 (16 KiB)
  Stack                 top at 0x2001_0000, shared
"""

import re
import shutil
import subprocess
from pathlib import Path

from . import elf

REPO = Path(__file__).resolve().parents[2]
C_DIR = REPO / "tests" / "c"
LINK_DIR = REPO / "tests" / "link"
BENCH_DIR = REPO / "tests" / "bench"
COREMARK = REPO / "third_party" / "coremark"
EMBENCH = REPO / "third_party" / "embench-iot"

TOOLCHAINS = {
    "thumb": ("arm-none-eabi-gcc", ["-mcpu=cortex-m0", "-mthumb"]),
    "rv32": ("riscv64-unknown-elf-gcc", ["-march=rv32im", "-mabi=ilp32"]),
}

C_FLAGS = {
    "thumb": ["-O2", "-ffreestanding", "-fno-builtin"],
    "rv32": ["-O2", "-ffreestanding", "-fno-builtin", "-msmall-data-limit=0", "-Wl,--no-relax"],
}

# newlib for ARM: optimised Thumb string functions, libm, and stub syscalls.
NEWLIB = ["-Wl,--start-group", "-lc", "-lm", "-lnosys", "-lgcc", "-Wl,--end-group"]


class ToolMissing(Exception):
    pass


def compile_and_link(kind: str, sources, out: Path, extra=(), libs=()) -> Path:
    cc, arch_flags = TOOLCHAINS[kind]
    if shutil.which(cc) is None:
        raise ToolMissing(cc)
    subprocess.run([cc, *arch_flags, "-nostdlib", *extra, "-o", str(out), *map(str, sources), *libs],
                   check=True)
    return out


def _linker_script(name):
    return f"-Wl,-T,{LINK_DIR / name}"


def c_program(kind: str, names, out_dir: Path) -> Path:
    """A C program from tests/c/ with its startup file (set SP, call main, spin at `done`)."""
    sources = [C_DIR / f"crt_{kind}.S", *(C_DIR / n for n in names)]
    out = out_dir / (Path(names[0]).stem + ".elf")
    return compile_and_link(kind, sources, out, [*C_FLAGS[kind], _linker_script(f"{kind}.ld")],
                            ["-lgcc"])


def thumb_asm_program(source: Path, out: Path) -> Path:
    """A Thumb assembly program with its own `_start` and `done`, linked like a C program."""
    return compile_and_link("thumb", [source], out, [_linker_script("thumb.ld")])


def mixed_program(thumb_names, rv_names, out_dir: Path) -> tuple[Path, Path]:
    """A Thumb library from tests/c/, then a RISC-V program linked against it.

    The library's global functions become absolute symbols in the RISC-V link.
    Reserved names (`__aeabi_idiv`, `__divsi3`, ...) stay private: they are the
    Thumb side's libgcc, and RISC-V's libgcc has functions of the same names.
    Returns (rv_elf, thumb_elf).
    """
    thumb = compile_and_link(
        "thumb", [C_DIR / n for n in thumb_names], out_dir / "lib_thumb.elf",
        [*C_FLAGS["thumb"], _linker_script("thumb_lib.ld"), "-Wl,--entry=0"], ["-lgcc"])
    defsyms = [f"-Wl,--defsym={name}={value & ~1:#x}"
               for name, value in elf.load(thumb).functions.items() if not name.startswith("__")]
    rv = compile_and_link(
        "rv32", [C_DIR / "crt_rv32.S", *(C_DIR / n for n in rv_names)], out_dir / "main_rv32.elf",
        [*C_FLAGS["rv32"], _linker_script("rv32.ld"), *defsyms], ["-lgcc"])
    return rv, thumb


def coremark(out_dir: Path, iterations: int = 1) -> Path:
    """CoreMark for Cortex-M0, with the port in tests/bench/coremark/.

    The port prints into a RAM buffer, `coremark_output`. CoreMark's own
    ee_printf.c is used with its UART hook replaced by the port's.
    """
    port = BENCH_DIR / "coremark"
    printf = (COREMARK / "barebones" / "ee_printf.c").read_text()
    printf, n = re.subn(r'#error "You must implement the method uart_send_char[^\n]*\n',
                        "coremark_putc(c);\n", printf)
    assert n == 1, "CoreMark's ee_printf.c changed: update the port"
    patched = out_dir / "ee_printf.c"
    patched.write_text("void coremark_putc(char c);\n" + printf)

    sources = [C_DIR / "crt_thumb.S", port / "core_portme.c", patched,
               *(COREMARK / f for f in ("core_list_join.c", "core_main.c", "core_matrix.c",
                                        "core_state.c", "core_util.c"))]
    flags = ["-O2", f"-I{port}", f"-I{COREMARK}", f"-DITERATIONS={iterations}",
             '-DFLAGS_STR="-O2"', _linker_script("thumb.ld")]
    return compile_and_link("thumb", sources, out_dir / "coremark.elf", flags, NEWLIB)


def embench_names() -> list[str]:
    return sorted(p.name for p in (EMBENCH / "src").iterdir() if p.is_dir())


def embench(name: str, out_dir: Path) -> Path:
    """One Embench IoT benchmark for Cortex-M0, run once (LOCAL_SCALE_FACTOR = 1).

    The benchmark's sources are copied with its scale factor replaced, so the
    submodule stays untouched. main() returns 0 if the benchmark verified.
    """
    src_dir = out_dir / f"embench-{name}"
    if src_dir.exists():
        shutil.rmtree(src_dir)
    shutil.copytree(EMBENCH / "src" / name, src_dir)
    for c in src_dir.glob("*.c"):
        text = c.read_text(errors="replace")
        c.write_text(re.sub(r"#define\s+LOCAL_SCALE_FACTOR\s+\d+", "#define LOCAL_SCALE_FACTOR 1", text))
    port = BENCH_DIR / "embench"
    sources = [C_DIR / "crt_thumb.S", port / "boardsupport.c", EMBENCH / "support" / "main.c",
               EMBENCH / "support" / "beebsc.c", *sorted(src_dir.glob("*.c"))]
    flags = ["-O2", "-fno-common", f"-I{port}", f"-I{EMBENCH / 'support'}", f"-I{src_dir}",
             "-DHAVE_BOARDSUPPORT_H", "-DGLOBAL_SCALE_FACTOR=1", "-DWARMUP_HEAT=0",
             "-Wno-implicit-function-declaration", _linker_script("thumb.ld")]
    return compile_and_link("thumb", sources, out_dir / f"embench-{name}.elf", flags, NEWLIB)
