"""The SoC in Verilator (Phase 1.2): RISC-V programs run on the RTL in lockstep with the model.

Needs Verilator, and sbt to generate the core (`make core`); the tests skip
without them unless THUMBV_REQUIRE_RTL=1.
"""

import dataclasses
import math
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from thumbv import build, elf, expander, lockstep, rtlsim
from thumbv import rv32


def run(images, tmp_path, **kwargs):
    result = rtlsim.run(images, tmp_path, **kwargs)
    assert result.status == rtlsim.EXIT, result.uart
    return result


def test_hello(rtl_simulator, build_c, tmp_path):
    image = elf.load(build_c("rv32", "hello.c"))
    result = run([image], tmp_path)
    assert result.uart == "Hello from Thumb-V\n"
    assert result.a0 == 0xA5                      # the LED register reads back
    assert rtlsim.lockstep([image], result) is None


@pytest.mark.parametrize("names", [
    ("abi_main.c", "abi_lib.c", "string_min.c"),
    ("interwork_main.c", "interwork_lib.c"),
    ("mixed_main.c", "mixed_lib.c"),
])
def test_programs_match_model(rtl_simulator, build_c, tmp_path, names):
    """The all-RISC-V builds of the interworking test programs."""
    image = elf.load(build_c("rv32", *names))
    result = run([image], tmp_path)
    model = lockstep.simulate([image], stop=image.symbols["done"])
    assert result.a0 == model.final_regs[0]
    divergence = rtlsim.lockstep([image], result)
    assert divergence is None, str(divergence)


def test_lockstep_catches_a_wrong_write(rtl_simulator, build_c, tmp_path):
    image = elf.load(build_c("rv32", "hello.c"))
    result = run([image], tmp_path)
    i = next(i for i, r in enumerate(result.trace) if r.rd)
    result.trace[i] = dataclasses.replace(result.trace[i], rd_wdata=result.trace[i].rd_wdata ^ 1)
    divergence = rtlsim.lockstep([image], result)
    assert divergence is not None and divergence.step == i
    assert f"x{result.trace[i].rd}: model" in divergence.problems[0]


def test_wave(rtl_simulator, build_c, tmp_path):
    image = elf.load(build_c("rv32", "hello.c"))
    wave = tmp_path / "hello.fst"
    run([image], tmp_path, wave=wave)
    assert wave.stat().st_size > 1000


def build_rv_asm(name, tmp_path):
    """An RV32 program from tests/asm/ with its own _start, linked like the C programs."""
    source = Path(__file__).parent / "asm" / name
    return elf.load(build.compile_and_link("rv32", [source], tmp_path / (source.stem + ".elf"),
                                           [*build.C_FLAGS["rv32"], build._linker_script("rv32.ld"),
                                            "-Wl,--entry=_start"]))   # no crt_rv32.S, so no _reset


def test_thumb_mode_switch(rtl_simulator, tmp_path):
    """Phase 2.1: a call into a Thumb region and back. The region comes from the
    program's own CSR writes, in the RTL and in the model."""
    image = build_rv_asm("rtl_thumb_mode.S", tmp_path)
    result = run([image], tmp_path)
    assert result.a0 == 2
    thumb = [r.pc for r in result.trace if r.pc >= image.symbols["thumb_start"] and r.pc < image.symbols["thumb_end"]]
    start = image.symbols["thumb_start"]
    assert [pc - start for pc in thumb] == [0, 2, 6, 8, 12, 16, 18, 20, 18, 20]
    assert rtlsim.lockstep([image], result) is None


def test_thumb_illegal_traps_at_its_address(rtl_simulator, tmp_path):
    image = build_rv_asm("rtl_thumb_illegal.S", tmp_path)
    result = run([image], tmp_path)
    assert result.a0 == image.symbols["thumb_udf"]


def test_thumb_single_ops(rtl_simulator, build_mixed, tmp_path):
    """Phase 2.2: an assembled Thumb function of single-op instructions, called
    from RISC-V, in lockstep with the model (results only, no flags)."""
    rv_elf, thumb_elf = build_mixed(["rtl_thumb_ops.S"], ["rtl_thumb_ops_main.c"])
    images = [elf.load(rv_elf), elf.load(thumb_elf)]
    result = run(images, tmp_path)
    model = lockstep.simulate(images, stop=images[0].symbols["done"], options=rtlsim.HARDWARE)
    assert result.a0 == model.final_regs[0]
    in_thumb = sum(1 for r in result.trace if 0x1_4000 <= r.pc < 0x2_0000)
    assert in_thumb > 80                    # both calls ran in Thumb mode
    divergence = rtlsim.lockstep(images, result)
    assert divergence is None, str(divergence)


def thumb_instructions_run(images, result):
    """The Thumb instructions in an RTL trace: {(pc, name): ops per execution}.

    The ops of one execution are consecutive records with the same PC.
    """
    thumb = images[1]
    ops, previous, run = {}, None, 0
    for r in result.trace:
        if not any(lo <= r.pc < hi for lo, hi in thumb.code_ranges()):
            previous = None
            continue
        name = expander.expand(r.insn & 0xFFFF, r.insn >> 16, r.pc, rtlsim.HARDWARE).name
        run = run + 1 if r.pc == previous else 1
        ops[r.pc, name] = max(ops.get((r.pc, name), 0), run)
        previous = r.pc
    return ops


def test_thumb_sequences(rtl_simulator, build_mixed, tmp_path):
    """Phase 3.1: an assembled Thumb function of two- to five-op instructions,
    run by the sequencer, in lockstep with the model op by op."""
    rv_elf, thumb_elf = build_mixed(["rtl_thumb_seq.S"], ["rtl_thumb_seq_main.c"])
    images = [elf.load(rv_elf), elf.load(thumb_elf)]
    result = run(images, tmp_path)
    divergence = rtlsim.lockstep(images, result)
    assert divergence is None, str(divergence)
    run_ops = thumb_instructions_run(images, result)
    multi = {name for (pc, name), n in run_ops.items() if n > 1}
    assert multi >= {"LDR_lit", "ADR", "STR_reg", "STRH_reg", "STRB_reg", "LDR_reg", "LDRH_reg",
                     "LDRSH_reg", "LDRB_reg", "LDRSB_reg", "BICS", "SXTH", "SXTB", "UXTH",
                     "MOV_hi", "ADD_hi"}
    # LDR (literal) ran at both alignments.
    assert {pc % 4 for pc, name in run_ops if name == "LDR_lit"} == {0, 2}


def test_thumb_register_lists(rtl_simulator, build_mixed, tmp_path):
    """Phase 3.2: PUSH/POP with LR and PC, LDM/STM, a nested call."""
    rv_elf, thumb_elf = build_mixed(["rtl_thumb_lists.S"], ["rtl_thumb_lists_main.c"])
    images = [elf.load(rv_elf), elf.load(thumb_elf)]
    result = run(images, tmp_path)
    divergence = rtlsim.lockstep(images, result)
    assert divergence is None, str(divergence)
    run_ops = thumb_instructions_run(images, result)
    longest = {}
    for (pc, name), n in run_ops.items():
        longest[name] = max(longest.get(name, 0), n)
    assert longest["PUSH"] == 6 and longest["POP"] == 7     # {r4-r7, lr}: 5 + SP; {r4-r7, pc}: 4 + T1, SP, jump
    assert longest["STM"] == 5 and longest["LDM"] == 4


def test_thumb_shifts_reversals_primask(rtl_simulator, build_mixed, tmp_path):
    """Phase 3.3: shifts by a register, REV*, MSR/MRS of PRIMASK."""
    rv_elf, thumb_elf = build_mixed(["rtl_thumb_misc.S"], ["rtl_thumb_misc_main.c"])
    images = [elf.load(rv_elf), elf.load(thumb_elf)]
    result = run(images, tmp_path)
    divergence = rtlsim.lockstep(images, result)
    assert divergence is None, str(divergence)
    names = {name for (pc, name), n in thumb_instructions_run(images, result).items()}
    assert names >= {"LSLS_reg", "LSRS_reg", "ASRS_reg", "RORS", "REV", "REV16", "REVSH",
                     "MSR", "MRS", "CPSID", "CPSIE"}


FLAG_WRITERS = {"ADDS_reg", "SUBS_reg", "ADDS_imm3", "SUBS_imm3", "ADDS_imm8", "SUBS_imm8",
                "CMP_imm", "CMP_reg", "CMN", "RSBS", "TST", "ANDS", "EORS", "ORRS", "BICS",
                "MVNS", "MOVS_imm", "MOVS_reg", "MULS", "LSLS_imm", "LSRS_imm", "ASRS_imm",
                "LSLS_reg", "LSRS_reg", "ASRS_reg", "RORS", "CMP_hi"}


def test_thumb_flag_writers(rtl_simulator, build_mixed, tmp_path):
    """Phase 4.2: every instruction that writes the flags, on edge-case
    operands, in lockstep with the model; NZCV is compared after every op."""
    rv_elf, thumb_elf = build_mixed(["rtl_thumb_flags.S"], ["rtl_thumb_flags_main.c"])
    images = [elf.load(rv_elf), elf.load(thumb_elf)]
    result = run(images, tmp_path)
    divergence = rtlsim.lockstep(images, result)
    assert divergence is None, str(divergence)
    names = {name for (pc, name), n in thumb_instructions_run(images, result).items()}
    assert names >= FLAG_WRITERS
    # The flags take every value they can here: N and Z exclusive, C and V free.
    assert len({r.nzcv for r in result.trace}) >= 10


VALUES = [(0, 0, 0, 0), (0xFFFFFFFF,) * 4, (1, 0, 0, 0), (0xFFFFFFFF, 0, 0x7FFFFFFF, 0x80000000),
          (0x12345678, 0x9ABCDEF0, 0x0FEDCBA9, 0x87654321)]


def readers_oracle():
    """What rtl_thumb_readers_main.c returns, from ARM's definitions alone."""
    conds = [
        lambda n, z, c, v: z, lambda n, z, c, v: not z, lambda n, z, c, v: c, lambda n, z, c, v: not c,
        lambda n, z, c, v: n, lambda n, z, c, v: not n, lambda n, z, c, v: v, lambda n, z, c, v: not v,
        lambda n, z, c, v: c and not z, lambda n, z, c, v: not c or z,
        lambda n, z, c, v: n == v, lambda n, z, c, v: n != v,
        lambda n, z, c, v: not z and n == v, lambda n, z, c, v: z or n != v,
    ]
    h = 0

    def mix(x):
        nonlocal h
        h = (h * 31 + x) & 0xFFFF_FFFF

    for cond in conds:
        mix(sum(1 << k for k in range(16) if cond(k >> 3 & 1, k >> 2 & 1, k >> 1 & 1, k & 1)))
    words = lambda t: sum(w << 32 * i for i, w in enumerate(t))
    for a in VALUES:
        for b in VALUES:
            x, y = words(a), words(b)
            for sub in (False, True):
                r = (x - y if sub else x + y) % (1 << 128)
                carry = x >= y if sub else x + y >= 1 << 128     # C: NOT borrow for subtraction
                sa, sb, sr = a[3] >> 31, b[3] >> 31, r >> 127
                v = (sa != sb if sub else sa == sb) and sr != sa
                z = r >> 96 == 0                                  # Z: of the last word only
                mix(sr << 31 | int(z) << 30 | int(carry) << 29 | int(v) << 28)
                for i in range(4):
                    mix(r >> 32 * i & 0xFFFF_FFFF)
    for k in range(16):
        mix(k << 28)
    return h


def test_thumb_flag_readers(rtl_simulator, build_mixed, tmp_path):
    """Phase 4.3: B<cond> under every condition and NZCV, ADCS/SBCS carry
    chains (128-bit add and subtract), MSR/MRS of the APSR. In lockstep with
    the model, and the result against ARM's definitions computed in Python."""
    rv_elf, thumb_elf = build_mixed(["rtl_thumb_readers.S"], ["rtl_thumb_readers_main.c"])
    images = [elf.load(rv_elf), elf.load(thumb_elf)]
    result = run(images, tmp_path)
    divergence = rtlsim.lockstep(images, result)
    assert divergence is None, str(divergence)
    names = {name for (pc, name), n in thumb_instructions_run(images, result).items()}
    assert names >= {"B_cond", "ADCS", "SBCS", "MSR", "MRS"}
    assert result.a0 == readers_oracle()


def check_interrupts(images, tmp_path, seed):
    """Run `images` (an irq_*main.c program) without and with interrupts
    (sim/tb.sv +irq): the same result, both in lockstep with the model (which
    takes each interrupt where the core did), and every interrupt between two
    instructions, none of whose ops ran before it. Returns the interrupts
    taken: [(mepc, ops the interrupted instruction then ran)], Thumb ones only."""
    (tmp_path / "quiet").mkdir()
    (tmp_path / "irq").mkdir()
    quiet = run(images, tmp_path / "quiet")
    assert quiet.status == "EXIT"
    assert rtlsim.lockstep(images, quiet) is None
    noisy = run(images, tmp_path / "irq", irq=seed)
    assert noisy.status == "EXIT" and noisy.a0 == quiet.a0
    # Phase 5.1: the run with interrupts, in lockstep too, handler included.
    divergence = rtlsim.lockstep(images, noisy)
    assert divergence is None, str(divergence)

    entry, read_mepc, mret = (images[0].symbols[s] for s in ("irq_handler", "irq_mepc", "irq_mret"))
    trace = noisy.trace
    entries = [i for i, r in enumerate(trace) if r.pc == entry]
    thumb = []
    for i in entries:
        before = trace[i - 1]
        mepc = next(r.rd_wdata for r in trace[i:] if r.pc == read_mepc)
        back = next(k for k in range(i, len(trace)) if trace[k].pc == mret) + 1
        assert before.pc != mepc, f"interrupt inside the instruction at {mepc:#x}"
        # Back to mepc, or straight into the next interrupt (taken before the
        # instruction at mepc ran; its mepc is the same).
        assert trace[back].pc in (mepc, entry), f"returned to {trace[back].pc:#x}, not {mepc:#x}"
        if trace[back].pc == entry:
            continue
        if 0x1_4000 <= mepc < 0x2_0000:
            # The interrupted instruction, once resumed: how many ops?
            k = back
            while k + 1 < len(trace) and trace[k + 1].pc == mepc:
                k += 1
            thumb.append((mepc, k - back + 1))
    assert len(entries) > 300, len(entries)
    return thumb


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_interrupts_land_between_thumb_instructions(rtl_simulator, build_mixed, tmp_path, seed):
    """Phase 3.4 (D3): with the timer interrupt raised every few cycles, Thumb
    code gives the same result, and every interrupt lands between two
    instructions: none of the interrupted instruction's ops ran before it.
    Without the sequencer's interrupt gating, the program doesn't finish
    (checked by hand: an interrupt part-way through a PUSH or POP {pc})."""
    rv_elf, thumb_elf = build_mixed(["rtl_thumb_lists.S", "rtl_thumb_seq.S", "rtl_thumb_misc.S"],
                                    ["irq_main.c", "irq_handler.S"])
    images = [elf.load(rv_elf), elf.load(thumb_elf)]
    thumb = check_interrupts(images, tmp_path, seed)
    # Enough of them in Thumb code, in front of multi-op instructions.
    multi_op = sum(ops > 1 for mepc, ops in thumb)
    assert len(thumb) > 150 and multi_op > 30, (len(thumb), multi_op)


def halfword(images, addr):
    seg = next(s for img in images for s in img.segments if s.addr <= addr < s.addr + len(s.data))
    return int.from_bytes(seg.data[addr - seg.addr:addr - seg.addr + 2], "little")


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_interrupts_in_gcc_loops(rtl_simulator, build_mixed, tmp_path, seed):
    """Phase 4.4: gcc-compiled loops (loops.c) under interrupts every few
    cycles: the same result, every interrupt between two instructions, and
    some between a flag-setting instruction and the B<cond> that reads its
    flags, so NZCV must survive the RISC-V handler."""
    rv_elf, thumb_elf = build_mixed(["loops.c"], ["irq_loops_main.c", "loops_run.c", "irq_handler.S"])
    images = [elf.load(rv_elf), elf.load(thumb_elf)]
    thumb = check_interrupts(images, tmp_path, seed)
    before_branch = sum(expander.expand(halfword(images, mepc), 0, mepc, rtlsim.HARDWARE).name == "B_cond"
                        for mepc, ops in thumb)
    # About 1,900 and 170 per seed.
    assert len(thumb) > 1000 and before_branch > 100, (len(thumb), before_branch)


def test_gcc_loops(rtl_simulator, build_mixed, build_c, tmp_path):
    """Phase 4.4: gcc-compiled Thumb code with loops and conditions (loops.c),
    called from RISC-V, in lockstep with the model. Its checksum must match
    the same sources built all-RISC-V, run in the model."""
    rv_elf, thumb_elf = build_mixed(["loops.c"], ["loops_main.c", "loops_run.c"])
    images = [elf.load(rv_elf), elf.load(thumb_elf)]
    result = run(images, tmp_path)
    assert result.status == "EXIT"
    divergence = rtlsim.lockstep(images, result)
    assert divergence is None, str(divergence)
    names = {name for (pc, name), n in thumb_instructions_run(images, result).items()}
    assert names >= {"B_cond", "CMP_imm", "CMP_reg", "ADCS", "TST", "MULS"}, names
    assert f"checksum           = {result.a0:08x}" in result.uart
    native = elf.load(build_c("rv32", "loops_check_main.c", "loops_run.c", "loops.c"))
    reference = lockstep.simulate([native], stop=native.symbols["done"])
    assert reference.stopped == "stop address"
    assert reference.final_regs[0] == 2 * result.a0 & 0xFFFF_FFFF    # it runs them twice


@pytest.mark.parametrize("libs, mains, interface", [
    (["mixed_lib.c"], ["mixed_main.c"], None),
    (["interwork_lib.c"], ["interwork_main.c"], None),
    (["abi_lib.c", "string_min.c"], ["abi_main.c", "string_min.c"], "abi.h"),   # with thunks
], ids=["mixed", "interwork", "abi"])
def test_mixed_corpus(rtl_simulator, build_mixed, tmp_path, libs, mains, interface):
    """Phase 4.4: the Phase 0 mixed programs (RISC-V and gcc-compiled Thumb
    calling each other, with loops) on the RTL, in lockstep with the model."""
    rv_elf, thumb_elf = build_mixed(libs, mains, interface)
    images = [elf.load(rv_elf), elf.load(thumb_elf)]
    result = run(images, tmp_path)
    assert result.status == "EXIT"
    divergence = rtlsim.lockstep(images, result)
    assert divergence is None, str(divergence)
    model = lockstep.simulate(images, stop=images[0].symbols["done"], options=rtlsim.HARDWARE)
    assert model.final_regs[0] == result.a0
    names = {name for (pc, name), n in thumb_instructions_run(images, result).items()}
    assert "B_cond" in names


def run_thumb_program(path, tmp_path, max_cycles=10_000_000):
    """A Thumb-only program on the RTL behind a RISC-V boot stub, in lockstep:
    the model, whose state is then the RTL's."""
    image = elf.load(path)
    images = [rtlsim.thumb_boot(image), image]
    result = run(images, tmp_path, max_cycles=max_cycles)
    assert result.status == "EXIT", result.status
    divergence, model = rtlsim.replay(images, result)
    assert divergence is None, str(divergence)
    return image, result, model


def test_thumb_selftest(rtl_simulator, build_c, tmp_path):
    """Phase 4.4: the Phase 0 Thumb self-test, Thumb-only, on the RTL."""
    image, result, model = run_thumb_program(build_c("thumb", "thumb_selftest.c"), tmp_path)
    reference = lockstep.simulate([image], stop=image.symbols["done"])
    assert result.a0 == reference.final_regs[0]


def test_coremark(rtl_simulator, build_bench, tmp_path):
    """Phase 4.4: CoreMark (one iteration), Thumb-only, on the RTL, in
    lockstep; CoreMark validates its own results."""
    image, result, model = run_thumb_program(build_bench.coremark(), tmp_path)
    n = int.from_bytes(model.mem.read_bytes(image.symbols["coremark_output_len"], 4), "little")
    out = model.mem.read_bytes(image.symbols["coremark_output"], n).decode()
    assert "Correct operation validated" in out and "ERROR" not in out, out


EMBENCH_LARGE = ["picojpeg", "qrduino", "wikisort", "xgboost"]     # about 1 million ops or more


@pytest.mark.parametrize("name", [n for n in build.embench_names() if n not in EMBENCH_LARGE])
def test_embench(rtl_simulator, build_bench, tmp_path, name):
    """Phase 4.4: Embench IoT, Thumb-only, on the RTL, in lockstep; main()
    returns 0 if the benchmark verified its result."""
    image, result, model = run_thumb_program(build_bench.embench(name), tmp_path)
    assert result.a0 == 0


@pytest.mark.slow
@pytest.mark.parametrize("name", EMBENCH_LARGE)
def test_embench_large(rtl_simulator, build_bench, tmp_path, name):
    image, result, model = run_thumb_program(build_bench.embench(name), tmp_path, max_cycles=100_000_000)
    assert result.a0 == 0


@pytest.mark.slow
def test_float_kernels(rtl_simulator, build_bench, tmp_path):
    """Soft-float: libgcc's float and double routines and libm; main() returns
    a checksum, which must be the model's."""
    image, result, model = run_thumb_program(build_bench.float_kernels(), tmp_path, max_cycles=100_000_000)
    reference = lockstep.simulate([image], stop=image.symbols["done"])
    assert result.a0 == reference.final_regs[0]


def test_synchronous_traps(rtl_simulator, build_mixed, tmp_path):
    """Phase 5.1: traps from Thumb code (SVC, BKPT, UDF, a trapping MRS,
    misaligned and faulting loads and stores, one at op 1 of its expansion)
    and from RISC-V (ecall, ebreak), handled and resumed, in lockstep with
    the model, which takes the same traps. The records the handler keeps are
    checked against what the architecture says."""
    rv_elf, thumb_elf = build_mixed(["trap_lib.S"], ["trap_main.c", "trap_handler.S"])
    images = [elf.load(rv_elf), elf.load(thumb_elf)]
    result = run(images, tmp_path)
    assert result.status == "EXIT"
    divergence, model = rtlsim.replay(images, result)
    assert divergence is None, str(divergence)
    alone = lockstep.simulate(images, stop=images[0].symbols["done"], options=rtlsim.HARDWARE, traps=True)
    assert alone.stopped == "stop address" and alone.final_regs[0] == result.a0

    rv, thumb = images
    words = lambda name, n: [int.from_bytes(model.mem.read_bytes(rv.symbols[name] + 4 * k, 4), "little")
                             for k in range(n)]
    n = words("nrecords", 1)[0]
    records = [tuple(words("records", 4 * n)[4 * k:4 * k + 4]) for k in range(n)]
    fn = lambda name: thumb.functions[name] & ~1
    expected = [
        (11, fn("t_svc"), rv32.ecall(), 42),           # ecall: mtval is the instruction
        (3, fn("t_bkpt"), rv32.ebreak(), 7),
        (2, fn("t_udf"), 0, 0),                     # the illegal instruction: 0
        (2, fn("t_mrs_msp") + 2, 0, 0),             # after its MOVS
    ]
    assert records[:4] == expected, records
    causes = [rec[0] for rec in records]
    assert causes == [11, 3, 2, 2, 4, 4, 5, 6, 11, 3], causes
    assert records[4][1] == fn("t_load") and records[4][2] & 3 == 1        # misaligned address
    assert records[5][1] == fn("t_load_reg") and records[5][2] & 3 == 2    # at op 1: base + offset
    assert records[6][1:3] == (fn("t_load"), 0x3000_0000)                   # access fault
    assert records[7][1] == fn("t_store") and records[7][2] & 3 == 2
    assert not thumb_region(images, records[8][1]) and records[8][2] == rv32.ecall()
    assert words("results", 4) == [0, records[4][2], records[5][2] - 2, 0x3000_0000]


def test_interrupt_controller(rtl_simulator, build_c, tmp_path):
    """Phase 5.2: the controller from software on the SoC: a pended
    interrupt (priority 1), PendSV (3) and SysTick (0), claimed in priority
    order, in lockstep with the model (which takes the controller's values
    from the trace)."""
    path = build_c("rv32", "nvic_main.c", "trap_handler.S")
    images = [elf.load(path)]
    result = run(images, tmp_path)
    assert result.status == "EXIT"
    divergence, model = rtlsim.replay(images, result)
    assert divergence is None, str(divergence)
    words = lambda name, n: [int.from_bytes(model.mem.read_bytes(images[0].symbols[name] + 4 * k, 4), "little")
                             for k in range(n)]
    n = words("nclaimed", 1)[0]
    # Interrupt 3 (exception 19) first, then PendSV (14), by priority; then
    # five SysTicks (15), the first some 300 cycles after SysTick starts.
    assert words("claimed", n) == [19, 14, 15, 15, 15, 15, 15]
    assert words("active_seen", n) == words("claimed", n)       # VECTACTIVE while active


def uart_values(uart):
    """{label: value} from lines "label: hex"."""
    out = {}
    for line in uart.splitlines():
        label, _, value = line.rpartition(":")
        if label:
            out[label.strip()] = int(value, 16)
    return out


def test_firmware_interrupts(rtl_simulator, build_mixed, tmp_path):
    """Phase 5.3: the firmware's entry routine (firmware/), in lockstep:
    a Thumb SysTick handler (compiled for Cortex-M0) interrupting RISC-V
    code, a RISC-V one interrupting Thumb code, and a Thumb one that changes
    the flags interrupting Thumb code (NZCV saved: without it, checked by
    hand, the third result is wrong); preemption by priority and PendSV;
    SVC from Thumb and ecall from RISC-V; the interrupt latency."""
    rv_elf, thumb_elf = build_mixed(["irq_mixed_thumb.c"], ["irq_mixed_main.c"], firmware=True)
    images = [elf.load(rv_elf), elf.load(thumb_elf)]
    result = run(images, tmp_path)
    assert result.status == "EXIT"
    divergence = rtlsim.lockstep(images, result)
    assert divergence is None, str(divergence)
    v = uart_values(result.uart)
    assert v["thumb handler, riscv code"] == v["riscv handler, thumb code"] == v["thumb handler, thumb code"] == 1
    # Enough interrupts in each case (the labels repeat, so read them all).
    ticks = [int(line.rpartition(":")[2], 16) for line in result.uart.splitlines() if "ticks" in line]
    assert len(ticks) == 3 and min(ticks) > 100, ticks
    # Interrupt 1 enters, 2 preempts it, 1 leaves; then 3 (same priority as 1) and PendSV.
    assert v["order (12345)"] == 0x12345
    assert v["svc #1 (20, 22)"] == 42 and v["svc #2 (6, 7)"] == 42 and v["ecall 1 (100, 23)"] == 123
    # From SysTick pending to the C handler's first load: 80 cycles in 5.3.
    assert v["latency (cycles)"] <= 90, v["latency (cycles)"]


def test_firmware_faults(rtl_simulator, build_mixed, tmp_path):
    """Phase 5.3: the firmware's default reports: BKPT (Thumb) and ebreak
    (RISC-V) reported and resumed, then a Thumb load fault reported and the
    program stopped."""
    rv_elf, thumb_elf = build_mixed(["trap_lib.S"], ["fault_main.c"], firmware=True)
    images = [elf.load(rv_elf), elf.load(thumb_elf)]
    result = run(images, tmp_path)
    assert result.status == "EXIT"
    divergence = rtlsim.lockstep(images, result)
    assert divergence is None, str(divergence)
    fn = lambda name: images[1].functions[name] & ~1
    lines = result.uart.splitlines()
    assert lines[0] == f"thumbv: breakpoint at {fn('t_bkpt'):08x} (Thumb), mtval 00100073"
    assert lines[1].startswith("thumbv: breakpoint at ") and lines[1].endswith("(RISC-V), mtval 00100073")
    assert lines[2] == f"thumbv: load access fault at {fn('t_load'):08x} (Thumb), mtval 30000000"
    assert len(lines) == 3


def test_firmware_systick_tick(rtl_simulator, build_mixed, tmp_path):
    """Phase 5.3: the board's SysTick program, simulated for its first two
    ticks (10 Hz on the board's 12 MHz clock: 1.2 million cycles each)."""
    rv_elf, thumb_elf = build_mixed(["tick_thumb.c"], ["tick_main.c"], firmware=True)
    images = [elf.load(rv_elf), elf.load(thumb_elf)]
    result = rtlsim.run(images, tmp_path, max_cycles=2_500_000, trace=False)
    assert result.status == "TIMEOUT"                 # it runs forever
    assert result.uart.splitlines()[:3] == ["SysTick at 10 Hz, Thumb handler", "tick 00000001",
                                            "tick 00000002"]


def test_cmsis_dsp(rtl_simulator, build_mixed, build_c, cmsis_dsp, tmp_path):
    """Phase 5.4: RISC-V code calling CMSIS-DSP's Cortex-M0 build, linked as
    a binary through the interface cmsis_dsp.h (three calls need thunks: a
    fifth argument goes on the stack under AAPCS), in lockstep with the
    model. It must print what the same program prints with CMSIS-DSP built
    for RISC-V, and a few results are checked against their definitions."""
    flags = build.cmsis_dsp_flags
    rv_elf, thumb_elf = build_mixed([], ["dsp_main.c"], "cmsis_dsp.h", thumb_libs=[cmsis_dsp["thumb"]],
                                    thumb_flags=flags("thumb"), rv_flags=flags("rv32"),
                                    rv_libs=build.rv_libc())
    images = [elf.load(rv_elf), elf.load(thumb_elf)]
    (tmp_path / "mixed").mkdir()
    result = run(images, tmp_path / "mixed")
    divergence = rtlsim.lockstep(images, result)
    assert divergence is None, str(divergence)
    native = elf.load(build_c("rv32", "dsp_main.c", libs=[cmsis_dsp["rv32"], *build.rv_libc()],
                              flags=flags("rv32")))
    (tmp_path / "native").mkdir()
    reference = run([native], tmp_path / "native")
    assert result.uart == reference.uart
    v = {line[:18].strip(): int(line[18:], 16) for line in result.uart.splitlines()[1:]}
    assert v["arm_sqrt_q31"] == 0x4000_0000 and v["status"] == 0       # sqrt(0.25) = 0.5
    assert v["negative"] == 0xFFFF_FFFF            # ARM_MATH_ARGUMENT_ERROR: a 1-byte enum, sign-extended
    assert v["size mismatch"] == 0xFFFF_FFFD       # ARM_MATH_SIZE_MISMATCH
    assert v["arm_fir_init_q15"] == 0 and v["arm_mat_mult_f32"] == 0
    sin = lambda name: struct.unpack("<f", struct.pack("<I", v[name]))[0]
    assert abs(sin("arm_sin_f32(0.5)") - math.sin(0.5)) < 1e-5
    assert abs(sin("arm_sin_f32(-2)") - math.sin(-2)) < 1e-5


def thumb_region(images, addr):
    return any(lo <= addr < hi for img in images if img.is_thumb for lo, hi in img.code_ranges())


def test_thumb_calls_back_into_riscv(rtl_simulator, build_mixed, tmp_path):
    """Phase 3.5: gcc-compiled Thumb code calls RISC-V functions (PUSH/POP
    around a BL through the import table) and reads a table through a
    literal pool; RISC-V prints the results. In lockstep with the model."""
    rv_elf, thumb_elf = build_mixed(["callback.c"], ["callback_main.c"], interface="callback.h")
    images = [elf.load(rv_elf), elf.load(thumb_elf)]
    result = run(images, tmp_path)
    divergence = rtlsim.lockstep(images, result)
    assert divergence is None, str(divergence)
    digits = [3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5, 8, 9, 7, 9, 3]
    lookup5, callback11, report7 = digits[5], 12 * 12 + 11, digits[7] * 1000 + 8 * 8 + 7
    assert result.uart == ("RISC-V and Thumb call each other\n"
                           f"t_lookup(5)        = {lookup5:08x}\n"
                           f"t_callback(11)     = {callback11:08x}\n"
                           f"Thumb reports      = {report7:08x}\n")
    assert result.a0 == lookup5 + callback11 + report7
    # Thumb really called RISC-V: a BL from the Thumb window into the import table.
    in_thumb = lambda pc: 0x1_4000 <= pc < 0x2_0000
    calls = sum(1 for a, b in zip(result.trace, result.trace[1:])
                if in_thumb(a.pc) and b.pc in (rtlsim_import(0), rtlsim_import(1)))
    assert calls >= 4
    rtlsim.memory_images(images, tmp_path, rtlsim.BOARD)     # it fits the board


def rtlsim_import(i):
    """Address of the i-th slot of the import jump table (thumbv.build.IMPORT_BASE)."""
    return build.IMPORT_BASE + 4 * i


def single_op_violations(thumb_image):
    """Instructions in a Thumb image's code that the 2.2 expander can't run yet."""
    out = []
    for lo, hi in thumb_image.code_ranges():
        data = b"".join(s.data for s in thumb_image.segments if s.addr <= lo < s.addr + len(s.data))
        base = next(s.addr for s in thumb_image.segments if s.addr <= lo < s.addr + len(s.data))
        pc = lo
        while pc < hi:
            hw1 = int.from_bytes(data[pc - base:pc - base + 2], "little")
            hw2 = int.from_bytes(data[pc - base + 2:pc - base + 4], "little")
            e = expander.expand(hw1, hw2, pc, rtlsim.HARDWARE)
            if len(e.ops) != 1 or e.ops[0] == rv32.ILLEGAL:
                out.append(f"{pc:#x} {e.name}")
            pc += e.length
    return out


def test_mixed_leaf_program(rtl_simulator, build_mixed, tmp_path):
    """Phase 2.4: RISC-V calls gcc-compiled leaf Thumb functions and prints the
    results over the UART, in lockstep with the model."""
    rv_elf, thumb_elf = build_mixed(["thumb_leaf.c"], ["thumb_leaf_main.c"])
    images = [elf.load(rv_elf), elf.load(thumb_elf)]
    assert not single_op_violations(images[1]), "gcc emitted instructions the expander can't run yet"
    result = run(images, tmp_path)
    # The functions in Python, as a second opinion on the printed values.
    m32 = 0xFFFF_FFFF
    def mix(a, b):
        return (((a << 3) ^ b) * 7 + (a >> 2) - (b & 0xFF)) & m32
    def xorshift(x, y):
        x ^= (x << 13) & m32
        x ^= x >> 17
        x ^= (x << 5) & m32
        return (x + y * 33) & m32
    x = 1
    for i in range(4):
        x = xorshift(x, i)
    values = [mix(1234, 567), mix(-5, 99), x]
    assert result.uart == ("RISC-V calls Thumb\n"
                           f"mix(1234, 567)     = {values[0]:08x}\n"
                           f"mix(-5, 99)        = {values[1]:08x}\n"
                           f"xorshift, 4 rounds = {values[2]:08x}\n")
    assert result.a0 == sum(values) & m32
    assert any(0x1_4000 <= r.pc < 0x2_0000 for r in result.trace)
    divergence = rtlsim.lockstep(images, result)
    assert divergence is None, str(divergence)
    # It fits the board's RAMs: Thumb code in the upper half of the code RAM.
    rtlsim.memory_images(images, tmp_path, rtlsim.BOARD)


def test_board_memories(rtl_simulator, build_c, tmp_path):
    """The board's smaller RAMs run the same binary: the stack at the top of the
    data region aliases into the 16 KiB data RAM."""
    image = elf.load(build_c("rv32", "hello.c"))
    result = run([image], tmp_path, memories=rtlsim.BOARD)
    assert result.uart == "Hello from Thumb-V\n"
    assert rtlsim.lockstep([image], result) is None


def test_board_memories_collide(tmp_path):
    """Addresses 32 KiB apart share a byte of the board's code RAM (as Thumb-only
    programs at 0x1_0000 and RISC-V code at 0x2_0000 would)."""
    image = SimpleNamespace(segments=[SimpleNamespace(addr=0x1_0000, data=b"\x01"),
                                      SimpleNamespace(addr=0x2_0000, data=b"\x02")])
    rtlsim.memory_images([image], tmp_path)   # fine with the simulation's RAMs
    with pytest.raises(ValueError, match="share a byte"):
        rtlsim.memory_images([image], tmp_path, rtlsim.BOARD)


def test_timeout(rtl_simulator, build_c, tmp_path):
    image = elf.load(build_c("rv32", "hello.c"))
    result = rtlsim.run([image], tmp_path, max_cycles=100)
    assert result.status == rtlsim.TIMEOUT
