"""Build recipes for test programs and benchmarks, shared by the tests and measurements.

Every recipe writes its output into a caller-supplied directory and returns
the ELF paths. Missing cross toolchains raise ToolMissing.

Memory layout of the programs (see tests/link/):
  Thumb programs        code 0x0001_0000, data 0x2000_0000 (48 KiB)
  Thumb libraries       code 0x0001_4000, data 0x2000_0000 (8 KiB)    for mixed programs:
                        the Thumb window, Thumb region 0 (set by crt_rv32.S)
  RV32 programs         code 0x0002_0000, data 0x2000_2000 (24 KiB; on the board's 16 KiB
                        RAM, the second 8 KiB, under the stack)
                        a jump to _start at 0x0002_0000 (the core's reset vector), then
                        the import jump table for Thumb code, at IMPORT_BASE
  Stack                 top at 0x2001_0000, shared
"""

import re
import shutil
import subprocess
from pathlib import Path

from . import elf, interwork

REPO = Path(__file__).resolve().parents[2]
C_DIR = REPO / "tests" / "c"
FIRMWARE_DIR = REPO / "firmware"
# The shared trap entry routine and its C side (Phase 5.3), for RISC-V programs.
FIRMWARE = [FIRMWARE_DIR / "thumbv_entry.S", FIRMWARE_DIR / "thumbv.c"]
LINK_DIR = REPO / "tests" / "link"
BENCH_DIR = REPO / "tests" / "bench"
COREMARK = REPO / "third_party" / "coremark"
EMBENCH = REPO / "third_party" / "embench-iot"
CMSIS_DSP = REPO / "third_party" / "CMSIS-DSP"
CMSIS_CORE = REPO / "third_party" / "CMSIS_6" / "CMSIS" / "Core" / "Include"
FREERTOS = REPO / "third_party" / "FreeRTOS-Kernel"
FREERTOS_PORT = FREERTOS / "portable" / "GCC" / "RISC-V"
# picolibc, the C library for the RISC-V side where one is needed (Phase 5.4):
# Debian's picolibc-riscv64-unknown-elf package.
PICOLIBC = Path("/usr/lib/picolibc/riscv64-unknown-elf")

IMPORT_BASE = 0x0002_0004  # after the reset jump at the start of RV32 ROM, see tests/link/rv32.ld

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


def c_program(kind: str, names, out_dir: Path, firmware: bool = False, libs=(), flags=()) -> Path:
    """A C program from tests/c/ with its startup file (set SP, call main, spin at `done`).
    `firmware` (RISC-V only): link the trap entry routine from firmware/.
    `libs`, `flags`: extra static libraries and compiler flags."""
    sources = [C_DIR / f"crt_{kind}.S", *(C_DIR / n for n in names), *(FIRMWARE if firmware else [])]
    out = out_dir / (Path(names[0]).stem + ".elf")
    gc = ["-Wl,--gc-sections"] if libs else []
    return compile_and_link(kind, sources, out, [*C_FLAGS[kind], f"-I{FIRMWARE_DIR}", *flags,
                                                 _linker_script(f"{kind}.ld"), *gc],
                            [*map(str, libs), "-lgcc"])


def thumb_asm_program(source: Path, out: Path) -> Path:
    """A Thumb assembly program with its own `_start` and `done`, linked like a C program."""
    return compile_and_link("thumb", [source], out, [_linker_script("thumb.ld")])


def mixed_program(thumb_names, rv_names, out_dir: Path, interface: str | None = None,
                  firmware: bool = False, thumb_libs=(), thumb_flags=(), rv_libs=(),
                  rv_flags=()) -> tuple[Path, Path]:
    """A Thumb library from tests/c/, then a RISC-V program linked against it.

    Without an interface header, the library's global functions become
    absolute symbols in the RISC-V link, and calls must have signatures that
    both ABIs pass the same way. Reserved names (`__aeabi_idiv`, `__divsi3`,
    ...) stay private: they are the Thumb side's libgcc, and RISC-V's libgcc
    has functions of the same names.

    With an interface header (from tests/c/, see thumbv/interwork.py), only the
    declared functions cross: thunks are generated where the ABIs differ, and
    Thumb code can call the declared RISC-V functions by name through the
    import jump table. `firmware` links the trap entry routine from firmware/
    into the RISC-V side (Phase 5.3); both sides can include its headers.

    `thumb_libs`: static libraries for the Thumb side, linked as binaries
    (Phase 5.4: a prebuilt Cortex-M0 library). The interface's exports are
    kept (--undefined) and everything unused is dropped (--gc-sections), and
    the Thumb side gets newlib. `thumb_flags`/`rv_flags`, `rv_libs`: extra
    compiler flags and libraries for each side.

    Returns (rv_elf, thumb_elf).
    """
    thumb_sources = [C_DIR / n for n in thumb_names]
    rv_sources = [C_DIR / "crt_rv32.S", *(C_DIR / n for n in rv_names), *(FIRMWARE if firmware else [])]
    gen = None
    if interface:
        gen = interwork.generate(interwork.parse((C_DIR / interface).read_text()), IMPORT_BASE)
        (out_dir / "interwork_thumb.S").write_text(gen.thumb_asm)
        (out_dir / "interwork_rv32.S").write_text(gen.rv_asm)
        thumb_sources.append(out_dir / "interwork_thumb.S")
        rv_sources.append(out_dir / "interwork_rv32.S")

    keep = [f"-Wl,--undefined={name}" for name in (gen.export_symbols if gen else [])]
    gc = ["-Wl,--gc-sections"] if thumb_libs else []
    thumb = compile_and_link(
        "thumb", thumb_sources, out_dir / "lib_thumb.elf",
        [*C_FLAGS["thumb"], f"-I{FIRMWARE_DIR}", *thumb_flags, _linker_script("thumb_lib.ld"),
         "-Wl,--entry=0", *keep, *gc],
        [*map(str, thumb_libs), *(NEWLIB if thumb_libs else ["-lgcc"])])
    functions = elf.load(thumb).functions
    if gen:
        exports = {gen.export_symbols[name]: functions[name] for name in gen.export_symbols}
    else:
        exports = {name: value for name, value in functions.items() if not name.startswith("__")}
    defsyms = [f"-Wl,--defsym={name}={value & ~1:#x}" for name, value in exports.items()]
    rv = compile_and_link(
        "rv32", rv_sources, out_dir / "main_rv32.elf",
        [*C_FLAGS["rv32"], f"-I{FIRMWARE_DIR}", *rv_flags, _linker_script("rv32.ld"), *defsyms],
        [*map(str, rv_libs), "-lgcc"])
    if gen:  # the Thumb side was linked against the table's slots at IMPORT_BASE
        table = elf.load(rv).symbols.get("__thumbv_imports")
        if table != IMPORT_BASE:
            raise RuntimeError(f"import table at {table}, expected {IMPORT_BASE:#x}: check rv32.ld")
    return rv, thumb


# --- CMSIS-DSP (Phase 5.4) ---------------------------------------------------------

# The modules the library is built from: everything but the transforms (FFT,
# whose tables are large) and the classifiers. Every function and table gets
# its own section, so a link with --gc-sections keeps only what is used
# (CMSIS-DSP's own way since v1.18).
CMSIS_DSP_MODULES = ["BasicMathFunctions", "StatisticsFunctions", "FilteringFunctions",
                     "MatrixFunctions", "FastMathFunctions", "ComplexMathFunctions",
                     "SupportFunctions", "ControllerFunctions"]


def rv_libc() -> list[Path]:
    """picolibc's C library (with its maths) for rv32im/ilp32."""
    lib = PICOLIBC / "lib" / "release" / "rv32im" / "ilp32" / "libc.a"
    if not lib.exists():
        raise ToolMissing("picolibc-riscv64-unknown-elf")
    return [lib]


def cmsis_dsp_flags(kind: str) -> list[str]:
    """Compiler flags for code that includes arm_math.h. Thumb: CMSIS-DSP's
    Cortex-M0 configuration, with CMSIS-Core. RISC-V: its generic C build
    (__GNUC_PYTHON__, CMSIS-DSP's switch for builds without CMSIS-Core)."""
    # ARM_MATH_MATRIX_CHECK: the matrix functions check sizes (a standard option).
    flags = [f"-I{CMSIS_DSP / 'Include'}", f"-I{CMSIS_DSP / 'PrivateInclude'}", "-DARM_MATH_MATRIX_CHECK"]
    if kind == "thumb":
        return flags + [f"-I{CMSIS_CORE}"]
    rv_libc()                           # its headers: string.h, math.h
    return flags + ["-D__GNUC_PYTHON__", "-isystem", str(PICOLIBC / "include")]


def cmsis_dsp_library(kind: str, out_dir: Path = REPO / "build" / "cmsis-dsp") -> Path:
    """CMSIS-DSP as a static library, one object per function: `thumb` is
    the Cortex-M0 build that mixed programs link as a binary, `rv32` the
    same sources for RISC-V, the reference. Built once, into out_dir/kind."""
    cc, arch = TOOLCHAINS[kind]
    if shutil.which(cc) is None:
        raise ToolMissing(cc)
    out = out_dir / kind
    archive = out / f"libcmsisdsp_{kind}.a"
    stamp = out / "flags"
    flags = [*arch, "-O2", "-ffreestanding", "-fno-builtin", "-ffunction-sections", "-fdata-sections",
             *cmsis_dsp_flags(kind), "-c"]
    if archive.exists() and stamp.exists() and stamp.read_text() == " ".join(flags):
        return archive
    out.mkdir(parents=True, exist_ok=True)
    archive.unlink(missing_ok=True)
    sources = [f for m in CMSIS_DSP_MODULES for f in sorted((CMSIS_DSP / "Source" / m).glob("arm_*.c"))
               if not re.search(r"_(f16|f64)\b|_f16_|_f64_", f.stem)]
    sources.append(CMSIS_DSP / "Source" / "CommonTables" / "arm_common_tables.c")
    objects = []
    procs = []
    for src in sources:
        obj = out / (src.stem + ".o")
        objects.append(obj)
        procs.append(subprocess.Popen([cc, *flags, str(src), "-o", str(obj)]))
        if len(procs) >= 16:
            for proc in procs:
                if proc.wait():
                    raise subprocess.CalledProcessError(proc.returncode, proc.args)
            procs = []
    for proc in procs:
        if proc.wait():
            raise subprocess.CalledProcessError(proc.returncode, proc.args)
    ar = cc.replace("gcc", "ar")
    subprocess.run([ar, "rcs", str(archive) + ".tmp", *map(str, objects)], check=True)
    Path(str(archive) + ".tmp").rename(archive)
    stamp.write_text(" ".join(flags))
    return archive


# --- FreeRTOS (Phase 5.5) ----------------------------------------------------------

def freertos_sources() -> list[Path]:
    """The kernel, its RISC-V port with heap_4, and Thumb-V's glue
    (firmware/freertos/: the SysTick tick, NZCV in the context). For the
    RISC-V side of a program that also links the firmware."""
    return [*(FREERTOS / f for f in ("tasks.c", "queue.c", "list.c")),
            FREERTOS / "portable" / "MemMang" / "heap_4.c",
            FREERTOS_PORT / "port.c", FREERTOS_PORT / "portASM.S",
            FIRMWARE_DIR / "freertos" / "thumbv_freertos.c"]


def freertos_flags() -> list[str]:
    """RISC-V compiler flags for the kernel and code that includes its headers:
    FreeRTOSConfig.h and the chip extension from firmware/freertos/, and
    picolibc's headers (the kernel uses string.h). Zicsr for the port's
    inline CSR instructions; the interrupt stack is main's stack, whose top
    the linker script gives. Unused kernel functions are dropped, so that the
    board's 16 KiB for RISC-V code holds the kernel and a program."""
    rv_libc()
    return ["-march=rv32im_zicsr", "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections", f"-I{FIRMWARE_DIR / 'freertos'}", f"-I{FREERTOS / 'include'}",
            f"-I{FREERTOS_PORT}", "-isystem", str(PICOLIBC / "include"),
            "-Wl,--defsym=__freertos_irq_stack_top=__stack_top"]


def rtos_program(out_dir: Path, defines=()) -> tuple[Path, Path]:
    """The FreeRTOS program (tests/c/rtos_main.c): two Thumb tasks from
    rtos_thumb.c beside RISC-V tasks. `defines` (-D...) set RTOS_ROUNDS,
    RTOS_PAUSE, configTICK_RATE_HZ, or THUMBV_FREERTOS_NO_NZCV."""
    return mixed_program(["rtos_thumb.c"], ["rtos_main.c", *freertos_sources()], out_dir, "rtos.h",
                         firmware=True, rv_flags=[*freertos_flags(), *defines], rv_libs=rv_libc())


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
