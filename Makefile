.PHONY: help setup check-tools test test-slow clean

help:
	@echo "make setup        create the Python environment (uv)"
	@echo "make check-tools  report which toolchains are installed"
	@echo "make test         run the model test suite"
	@echo "make test-slow    also run the slow tests (benchmarks, many random programs)"
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

clean:
	rm -rf build .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
