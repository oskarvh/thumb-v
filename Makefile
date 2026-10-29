.PHONY: help setup check-tools test clean

help:
	@echo "make setup        create the Python environment (uv)"
	@echo "make check-tools  report which toolchains are installed"
	@echo "make test         run the model test suite"
	@echo "make clean        remove build outputs and caches"

setup:
	uv sync

check-tools:
	@./scripts/check-tools.sh

test:
	uv run pytest

clean:
	rm -rf build .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
