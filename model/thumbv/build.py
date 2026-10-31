"""Build recipes for test programs and benchmarks, shared by the tests and measurements.

Every recipe writes its output into a caller-supplied directory and returns
the ELF paths. Missing cross toolchains raise ToolMissing.

Memory layout of the programs (see tests/link/):
  Thumb programs        code 0x0001_0000, data 0x2000_0000 (48 KiB)
  Thumb libraries       code 0x0001_0000, data 0x2000_0000 (16 KiB)   for mixed programs
  RV32 programs         code 0x0002_0000, data 0x2000_4000 (16 KiB)
                        the import jump table for Thumb code first, at IMPORT_BASE
  Stack                 top at 0x2001_0000, shared
"""

import re
import shutil
import subprocess
from pathlib import Path

from . import elf, interwork

REPO = Path(__file__).resolve().parents[2]
C_DIR = REPO / "tests" / "c"
LINK_DIR = REPO / "tests" / "link"
BENCH_DIR = REPO / "tests" / "bench"
COREMARK = REPO / "third_party" / "coremark"
EMBENCH = REPO / "third_party" / "embench-iot"

IMPORT_BASE = 0x0002_0000  # start of RV32 ROM, see tests/link/rv32.ld

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
    """Compile and link `sources` into `out`, with a link map next to it (`out` + ".map")."""
    cc, arch_flags = TOOLCHAINS[kind]
    if shutil.which(cc) is None:
        raise ToolMissing(cc)
    subprocess.run([cc, *arch_flags, "-nostdlib", *extra, f"-Wl,-Map={out}.map", "-o", str(out),
                    *map(str, sources), *libs], check=True)
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


def mixed_program(thumb_names, rv_names, out_dir: Path, interface: str | None = None) -> tuple[Path, Path]:
    """A Thumb library from tests/c/, then a RISC-V program linked against it.

    Without an interface header, the library's global functions become
    absolute symbols in the RISC-V link, and calls must have signatures that
    both ABIs pass the same way. Reserved names (`__aeabi_idiv`, `__divsi3`,
    ...) stay private: they are the Thumb side's libgcc, and RISC-V's libgcc
    has functions of the same names.

    With an interface header (from tests/c/, see thumbv/interwork.py), only the
    declared functions cross: thunks are generated where the ABIs differ, and
    Thumb code can call the declared RISC-V functions by name through the
    import jump table. Returns (rv_elf, thumb_elf).
    """
    thumb_sources = [C_DIR / n for n in thumb_names]
    rv_sources = [C_DIR / "crt_rv32.S", *(C_DIR / n for n in rv_names)]
    gen = None
    if interface:
        gen = interwork.generate(interwork.parse((C_DIR / interface).read_text()), IMPORT_BASE)
        (out_dir / "interwork_thumb.S").write_text(gen.thumb_asm)
        (out_dir / "interwork_rv32.S").write_text(gen.rv_asm)
        thumb_sources.append(out_dir / "interwork_thumb.S")
        rv_sources.append(out_dir / "interwork_rv32.S")

    thumb = compile_and_link(
        "thumb", thumb_sources, out_dir / "lib_thumb.elf",
        [*C_FLAGS["thumb"], _linker_script("thumb_lib.ld"), "-Wl,--entry=0"], ["-lgcc"])
    functions = elf.load(thumb).functions
    if gen:
        exports = {gen.export_symbols[name]: functions[name] for name in gen.export_symbols}
    else:
        exports = {name: value for name, value in functions.items() if not name.startswith("__")}
    defsyms = [f"-Wl,--defsym={name}={value & ~1:#x}" for name, value in exports.items()]
    rv = compile_and_link(
        "rv32", rv_sources, out_dir / "main_rv32.elf",
        [*C_FLAGS["rv32"], _linker_script("rv32.ld"), *defsyms], ["-lgcc"])
    if gen:  # the Thumb side was linked against the table's slots at IMPORT_BASE
        table = elf.load(rv).symbols.get("__thumbv_imports")
        if table != IMPORT_BASE:
            raise RuntimeError(f"import table at {table}, expected {IMPORT_BASE:#x}: check rv32.ld")
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


def float_kernels(out_dir: Path) -> Path:
    """Soft-float kernels (tests/bench/float/): libgcc's float and double routines and libm.

    Embench IoT 2 is integer-only, so this is the measurements' float workload.
    main() returns a checksum of the results.
    """
    sources = [C_DIR / "crt_thumb.S", BENCH_DIR / "float" / "float_kernels.c"]
    flags = ["-O2", "-fno-builtin", _linker_script("thumb.ld")]
    return compile_and_link("thumb", sources, out_dir / "float_kernels.elf", flags, NEWLIB)


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
