"""Interworking: interface parsing, ABI layouts, and generated thunks in real programs."""

import pytest

from thumbv import build, elf, interwork, lockstep
from thumbv.interwork import Arg, Loc

R = lambda n: Loc("reg", n)
S = lambda n: Loc("stack", n)

HEADER = """
#include <stdint.h>
struct pair { int32_t a, b; };
struct p64 { int64_t v; };
struct big { int32_t w[4]; };
struct six { uint8_t c[6]; };
struct nest { char tag; struct pair p; short s; };
THUMBV_THUMB int64_t mixed(int a, int64_t b, int c);
THUMBV_THUMB int sum_p64(int x, struct p64 p);
THUMBV_THUMB int sum_big(struct big b);
THUMBV_THUMB struct pair make_pair(int a, int b);
THUMBV_THUMB int tail(int a, int b, int c, int d, int e, int f, int g, int64_t h);
THUMBV_THUMB int tail_pair(int a, int b, int c, int d, int e, int f, int g, struct pair p);
THUMBV_RISCV int add(int a, int b);
THUMBV_RISCV void callback(int (*f)(int), const char *name, unsigned long long x);
"""


@pytest.fixture(scope="module")
def iface():
    return interwork.parse(HEADER)


def fn(iface, name):
    return next(f for f in iface.functions if f.name == name)


def test_struct_layouts(iface):
    s = iface.structs
    assert (s["pair"].size, s["pair"].align) == (8, 4)
    assert (s["p64"].size, s["p64"].align) == (8, 8)
    assert (s["big"].size, s["big"].align) == (16, 4)
    assert (s["six"].size, s["six"].align) == (6, 1)
    assert (s["nest"].size, s["nest"].align) == (16, 4)   # char, pad, pair, short, pad


def test_sides_and_types(iface):
    assert [f.name for f in iface.exports][:2] == ["mixed", "sum_p64"]
    assert [f.name for f in iface.imports] == ["add", "callback"]
    cb = fn(iface, "callback")
    assert [p.size for p in cb.params] == [4, 4, 8]   # function pointer, pointer, 64-bit


# Each expectation below was checked against GCC's code for both targets.
@pytest.mark.parametrize("name, aapcs_args, riscv_args", [
    ("mixed", [(R(0),), (R(2), R(3)), (S(0),)], [(R(0),), (R(1), R(2)), (R(3),)]),
    ("sum_p64", [(R(0),), (R(2), R(3))], [(R(0),), (R(1), R(2))]),
    ("tail", [*[(R(i),) for i in range(4)], (S(0),), (S(4),), (S(8),), (S(16), S(20))],
             [*[(R(i),) for i in range(7)], (R(7), S(0))]),
    ("tail_pair", [*[(R(i),) for i in range(4)], (S(0),), (S(4),), (S(8),), (S(12), S(16))],
                  [*[(R(i),) for i in range(7)], (R(7), S(0))]),
])
def test_layouts(iface, name, aapcs_args, riscv_args):
    f = fn(iface, name)
    assert [a.words for a in interwork.aapcs(f).args] == aapcs_args
    assert [a.words for a in interwork.riscv(f).args] == riscv_args


def test_struct_passing_and_results(iface):
    big = fn(iface, "sum_big")
    assert interwork.aapcs(big).args == (Arg((R(0), R(1), R(2), R(3))),)
    assert interwork.riscv(big).args == (Arg((R(0),), by_ref=True),)
    pair = fn(iface, "make_pair")
    assert (interwork.aapcs(pair).ret, interwork.riscv(pair).ret) == ("hidden", "regs")
    assert interwork.aapcs(pair).args[0].words == (R(1),)   # the hidden pointer takes r0


def test_compatible(iface):
    assert interwork.compatible(fn(iface, "add"))
    assert not interwork.compatible(fn(iface, "mixed"))


@pytest.mark.parametrize("text, message", [
    ("THUMBV_THUMB int f(int a, ...);", "variadic"),
    ("union u { int a; float b; };", "unions"),
    ("struct s { int a : 3; };", "bit-fields"),
    ("THUMBV_THUMB int f(wchar_t c);", "unsupported type"),
    ("THUMBV_THUMB int f(struct nope n);", "unknown struct"),
])
def test_rejects(text, message):
    with pytest.raises(interwork.InterfaceError, match=message):
        interwork.parse(text)


def test_report_cli(capsys, tmp_path):
    header = tmp_path / "i.h"
    header.write_text(HEADER)
    assert interwork.main([str(header)]) == 0
    out = capsys.readouterr().out
    assert "mixed (RISC-V -> Thumb): thunk" in out and "add (Thumb -> RISC-V): direct" in out


ABI_THUMB = ["abi_lib.c", "string_min.c"]
ABI_RV = ["abi_main.c", "string_min.c"]
ABI_ALL = ["abi_main.c", "abi_lib.c", "string_min.c"]


def three_way(tmp_path):
    """Results of the ABI program built mixed (with thunks), all-RISC-V and all-Thumb."""
    try:
        rv, thumb = build.mixed_program(ABI_THUMB, ABI_RV, tmp_path, interface="abi.h")
        results = {}
        images = [elf.load(rv), elf.load(thumb)]
        results["mixed"] = lockstep.simulate(images, stop=images[0].symbols["done"])
        for kind in ("rv32", "thumb"):
            img = elf.load(build.c_program(kind, ABI_ALL, tmp_path))
            results[kind] = lockstep.simulate([img], stop=img.symbols["done"])
    except build.ToolMissing as missing:
        pytest.skip(f"{missing} not found")
    assert all(r.ok for r in results.values())
    return {k: r.final_regs[0] for k, r in results.items()}, images


def test_abi_program_three_ways(tmp_path):
    """Thunks in both directions give the same results as either ABI on its own."""
    values, _ = three_way(tmp_path)
    assert values["mixed"] == values["rv32"] == values["thumb"]


def test_abi_program_lockstep(tmp_path):
    _, images = three_way(tmp_path)
    result = lockstep.run(images, stop=images[0].symbols["done"])
    assert result.ok, f"{result.stopped}\n{result.divergence}"


def test_wrong_layout_is_caught(tmp_path, monkeypatch):
    """Dropping AAPCS's even-register rule for 8-byte-aligned arguments must show."""
    real = interwork.aapcs

    def no_even_pairs(f):
        params = [interwork.CType(p.name, p.size, min(p.align, 4), p.composite) for p in f.params]
        return real(interwork.Function(f.name, f.side, f.ret, params))

    monkeypatch.setattr(interwork, "aapcs", no_even_pairs)
    values, _ = three_way(tmp_path)
    assert values["mixed"] != values["rv32"] == values["thumb"]
