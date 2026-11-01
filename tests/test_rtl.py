"""The SoC in Verilator (Phase 1.2): RISC-V programs run on the RTL in lockstep with the model.

Needs Verilator, and sbt to generate the core (`make core`); the tests skip
without them unless THUMBV_REQUIRE_RTL=1.
"""

import dataclasses
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
                                           [*build.C_FLAGS["rv32"], build._linker_script("rv32.ld")]))


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
    (tmp_path / "quiet").mkdir()
    (tmp_path / "irq").mkdir()
    quiet = run(images, tmp_path / "quiet")
    assert rtlsim.lockstep(images, quiet) is None
    noisy = run(images, tmp_path / "irq", irq=seed)
    assert noisy.a0 == quiet.a0

    entry, read_mepc, mret = (images[0].symbols[s] for s in ("irq_handler", "irq_mepc", "irq_mret"))
    trace = noisy.trace
    entries = [i for i, r in enumerate(trace) if r.pc == entry]
    thumb, multi_op = 0, 0
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
            thumb += 1
            # The interrupted instruction, once resumed: several ops?
            k = back
            while k + 1 < len(trace) and trace[k + 1].pc == mepc:
                k += 1
            multi_op += k > back
    # Enough of them, in Thumb code, in front of multi-op instructions.
    assert len(entries) > 300 and thumb > 150 and multi_op > 30, (len(entries), thumb, multi_op)


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
