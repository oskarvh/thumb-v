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

## Phase 1 and later

- **Verilator** (`sudo apt-get install verilator`) for RTL simulation. Ubuntu 24.04 ships 5.020.
- **Java and sbt** for SpinalHDL, which generates VexRiscv. Install sbt from [scala-sbt.org](https://www.scala-sbt.org/download).
- **Quartus Prime Lite** for the Cyclone 10 LP, from Intel's website.
- **openFPGALoader** (`sudo apt-get install openfpgaloader`) to program the CYC1000.
