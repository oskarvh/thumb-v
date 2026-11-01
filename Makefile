.PHONY: help setup check-tools test test-slow measure core test-rtl board clean

help:
	@echo "make setup        create the Python environment (uv)"
	@echo "make check-tools  report which toolchains are installed"
	@echo "make test         run the model test suite"
	@echo "make test-slow    also run the slow tests (benchmarks, many random programs)"
	@echo "make measure      cost the flags strategies over all benchmarks (Phase 0.7)"
	@echo "make core         generate the VexRiscv core into build/rtl/ and lint it (Phase 1.1)"
	@echo "make test-rtl     the RTL tests in Verilator: programs in lockstep with the model, the exhaustive expander check"
	@echo "make board        run hello world (or ELF=program.elf) on the CYC1000 (Phase 1.4)"
	@echo "make clean        remove build outputs and caches"

setup:
	git submodule update --init
	uv sync

check-tools:
	@./scripts/check-tools.sh

test:
	uv run pytest

test-slow:
	uv run pytest --slow

measure:
	uv run python -m thumbv.measure

core:
	cd rtl/core && sbt -batch "runMain thumbv.GenCore $(CURDIR)/build/rtl"
	verilator --lint-only --top-module VexRiscv build/rtl/VexRiscv.v
	verilator --lint-only --top-module ThumbExpander build/rtl/ThumbExpander.v
	verilator --lint-only --top-module thumbv_soc build/rtl/VexRiscv.v rtl/soc/*.v

test-rtl: core
	THUMBV_REQUIRE_RTL=1 uv run pytest tests/test_rtl.py tests/test_expander_rtl.py

board: core
	uv run python -m thumbv.board $(ELF)

clean:
	rm -rf build .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
