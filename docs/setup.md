# Setup

Instructions for Ubuntu 24.04. Run `make check-tools` to see what is installed. The full list of dependencies, with versions and licenses, is in [dependencies.md](dependencies.md).

## Phase 0: model and test programs

```sh
sudo apt-get install gcc-arm-none-eabi gcc-riscv64-unknown-elf
curl -LsSf https://astral.sh/uv/install.sh | sh   # if uv is missing
make setup
make test
```

- `arm-none-eabi-gcc` builds the Thumb test programs (`-mcpu=cortex-m0 -mthumb`).
- `riscv64-unknown-elf-gcc` builds the RISC-V programs. Despite the name it targets RV32 too (`-march=rv32im -mabi=ilp32`).
- `uv` manages the Python environment: Unicorn (ARMv6-M and RV32 reference models), Capstone (disassembly), pyelftools and pytest.

Tests skip when a cross toolchain is missing. Set `THUMBV_REQUIRE_TOOLS=1` to make them fail instead, as CI does.

## Running

### Make targets

| Command | What it does |
|---|---|
| `make setup` | Create or update `.venv` from `uv.lock` |
| `make check-tools` | List which toolchains are installed, and which phase needs them |
| `make test` | Run the whole test suite |
| `make clean` | Remove `build/` and Python caches |

### Running tests selectively

`make test` is `uv run pytest`, so any pytest option works through `uv run`:

```sh
uv run pytest -v                      # one line per test
uv run pytest -k thumb                # only tests whose name contains "thumb"
uv run pytest tests/test_smoke.py     # one file
uv run pytest -x                      # stop at the first failure
THUMBV_REQUIRE_TOOLS=1 make test      # fail instead of skip when a toolchain is missing
```

The tests build their programs into a temporary directory. To keep the built ELF files for inspection, give pytest a directory:

```sh
mkdir -p build
uv run pytest --basetemp=build/pytest
ls build/pytest/*/                    # one directory per test
```

### The Python environment

`uv run` uses `.venv` automatically, so activation is optional. To work in it interactively, e.g. to load a program built as in the next section:

```sh
source .venv/bin/activate
python -c "from thumbv import elf; print(elf.load('build/smoke_thumb.elf'))"
```

### Building and disassembling a program by hand

The same commands the tests use:

```sh
mkdir -p build
# Thumb (Cortex-M0)
arm-none-eabi-gcc -mcpu=cortex-m0 -mthumb -nostdlib -Wl,-e,_start -Wl,-Ttext=0x1000 \
    -o build/smoke_thumb.elf tests/asm/smoke_thumb.S
arm-none-eabi-objdump -d build/smoke_thumb.elf

# RV32
riscv64-unknown-elf-gcc -march=rv32im -mabi=ilp32 -nostdlib -Wl,-e,_start -Wl,-Ttext=0x1000 \
    -o build/smoke_rv32.elf tests/asm/smoke_rv32.S
riscv64-unknown-elf-objdump -d build/smoke_rv32.elf
```

### Adding a test program

1. Put the assembly source in `tests/asm/`, with a global `_start` label. For Thumb, mark it `.thumb_func`.
2. In a test, build it with the `build_asm` fixture from `tests/conftest.py`: `build_asm("thumb", "my_test.S")` or `build_asm("rv32", "my_test.S")`. It returns the path of the linked ELF (text at `0x1000` by default).
3. Load it with `thumbv.elf.load(path)` to get its segments, entry point and symbols. See `tests/test_smoke.py` for an example that runs a program in Unicorn.

### CI

`.github/workflows/ci.yml` runs `make setup` and `make test` with `THUMBV_REQUIRE_TOOLS=1` on Ubuntu 24.04, on every push and pull request.

## Phase 1 and later

- **Verilator** (`sudo apt-get install verilator`) for RTL simulation. Ubuntu 24.04 ships 5.020.
- **Java and sbt** for SpinalHDL, which generates VexRiscv. Install sbt from [scala-sbt.org](https://www.scala-sbt.org/download).
- **Quartus Prime Lite** for the Cyclone 10 LP, from Intel's website.
- **openFPGALoader** (`sudo apt-get install openfpgaloader`) to program the CYC1000.
