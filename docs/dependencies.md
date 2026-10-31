# Dependencies

Everything Thumb-V depends on, including what later phases will need. Install instructions are in [setup.md](setup.md). "Verified" versions are the ones the tests have run with; update them when they change.

## Host tools

| Dependency | Used for | Needed from | Verified version | Install (Ubuntu 24.04) | License |
|---|---|---|---|---|---|
| Python | model, harness, tools | Phase 0 | 3.12.3 | system | PSF |
| uv | Python environment and lock file | Phase 0 | 0.11.8 | [astral.sh/uv](https://docs.astral.sh/uv/) | MIT / Apache-2.0 |
| GNU Make | build entry points | Phase 0 | system | `build-essential` | GPL-3.0 |
| arm-none-eabi-gcc + binutils | Thumb test programs, Cortex-M0 libraries and benchmarks | Phase 0 | 13.2.1 (13.2.rel1) | `gcc-arm-none-eabi` | GPL-3.0 with runtime exception |
| newlib for ARM | C library (string functions, libm, stub syscalls) for the Cortex-M0 benchmarks | Phase 0.5 | 4.4.0 | `libnewlib-arm-none-eabi` (install explicitly with `--no-install-recommends`) | BSD-style |
| riscv64-unknown-elf-gcc + binutils | RV32 programs, firmware (`-march=rv32im -mabi=ilp32`; rv32e multilibs included) | Phase 0 | 13.2.0 | `gcc-riscv64-unknown-elf` | GPL-3.0 with runtime exception |
| picolibc for RISC-V | C library for RV32 programs that need one (not needed so far: the RISC-V test programs are freestanding) | when needed | — | `picolibc-riscv64-unknown-elf` | BSD-style |
| Verilator | linting the generated core, RTL simulation | Phase 1 | 5.020 | `verilator` | LGPL-3.0 / Artistic-2.0 |
| GTKWave or Surfer (optional) | viewing waveforms from `rtlsim --wave` | Phase 1 | — | `gtkwave`; Surfer from [surfer-project.org](https://surfer-project.org/) | GPL-2.0; EUPL-1.2 |
| Java (JDK) | SpinalHDL / VexRiscv generation | Phase 1 | OpenJDK 21 | `openjdk-21-jdk` | GPL-2.0 with classpath exception |
| sbt | SpinalHDL / VexRiscv build. `rtl/core` pins sbt 1.10.7 (downloaded by the launcher) and Scala 2.12.18, VexRiscv's | Phase 1 | launcher 2.0.12 | sbt's apt repository, see setup.md | Apache-2.0 |
| Quartus Prime Lite | synthesis for the Cyclone 10 LP | Phase 1.4 | — | Intel download | proprietary, free |
| openFPGALoader | programming the CYC1000 | Phase 1.4 | — | `openfpgaloader` | Apache-2.0 |

## Python packages

Pinned in `uv.lock`, declared in `pyproject.toml`.

| Package | Used for | Needed from | Verified version | License |
|---|---|---|---|---|
| unicorn | ARMv6-M (and RV32) reference model for lockstep | Phase 0 | 2.1.4 | GPL-2.0 |
| capstone | disassembly in reports and tests | Phase 0 | 5.0.7 | BSD-3-Clause |
| pyelftools | ELF loading | Phase 0 | 0.33 | Public domain (Unlicense) |
| pytest | test runner | Phase 0 | 9.2.0 | MIT |
| cocotb | RTL testbenches driven from the Python model | Phase 2 | — | BSD-3-Clause |

Unicorn is GPL-2.0 while the project is Apache-2.0. That's fine for a development and test dependency. Keep it out of anything we would distribute as part of Thumb-V itself.

## Hardware IP

| Dependency | Used for | Needed from | Pinned at | License |
|---|---|---|---|---|
| SpinalHDL | HDL that VexRiscv is written in; fetched by sbt at the version VexRiscv's `build.sbt` names | Phase 1 | 1.13.0 | LGPL-3.0 (core), MIT (lib) |
| VexRiscv | base RISC-V core, submodule `third_party/VexRiscv` | Phase 1 | `baf7dc82` (2026-09-24) | MIT |
| SDRAM controller | 8 MB SDRAM on the CYC1000 | Phase 7 | not chosen | — |

## Test programs and benchmarks

| Dependency | Used for | Needed from | License |
|---|---|---|---|
| CoreMark | correctness and expansion-ratio measurements, later board performance. Submodule `third_party/coremark`, pinned at `1f483d5` | Phase 0.5 | Apache-2.0 (with EEMBC reporting terms) |
| Embench IoT | additional benchmark programs. Submodule `third_party/embench-iot`, pinned at `09c2ed8`; only built and run, never modified or copied into the repo | Phase 0.5 | GPL-3.0 |
| A prebuilt Cortex-M0 library (DSP or crypto) | real-world mixed-execution test | Phase 5 | not chosen |
| FreeRTOS or Zephyr | RTOS with Thumb tasks | Phase 5 | MIT / Apache-2.0 |

## Hardware

| Item | Notes |
|---|---|
| Trenz CYC1000 | Intel Cyclone 10 LP 10CL025 (~25K LEs, ~66 KB M9K RAM), 8 MB SDRAM, on-board Arrow USB Blaster, 8 LEDs, UART over USB |

## Reference documents

| Document | Used for |
|---|---|
| ARMv6-M Architecture Reference Manual (ARM DDI 0419) | instruction encodings and semantics, exception model |
| Cortex-M0 Devices Generic User Guide (ARM DUI 0497) | NVIC, SysTick, SCB register maps |
| Procedure Call Standard for the Arm Architecture (AAPCS, ARM IHI 0042) | interworking calling convention |
| RISC-V Unprivileged ISA specification | RV32IM, Zbb |
| RISC-V Privileged ISA specification | traps, CSRs, `mret`, interrupts |
| RISC-V ELF psABI | ilp32 calling convention |
| RISC-V CLIC specification (draft) | reference for the interrupt controller design |
| CYC1000 user guide (Trenz TEI0003) | board pinout and clocks |
