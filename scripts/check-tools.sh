#!/usr/bin/env bash
# Report which tools Thumb-V needs are installed. Exits non-zero if a
# required tool is missing. See docs/setup.md for how to install them.
set -u

missing=0

check() {
    local level=$1 tool=$2 purpose=$3
    if path=$(command -v "$tool"); then
        printf '  ok        %-26s %s\n' "$tool" "$path"
    else
        printf '  %-9s %-26s %s\n' "$level" "$tool" "($purpose)"
        [ "$level" = missing ] && missing=1
    fi
}

echo "Phase 0 (required):"
check missing uv                      "Python environment"
check missing arm-none-eabi-gcc       "Thumb test programs"
check missing riscv64-unknown-elf-gcc "RISC-V test programs"

echo "Phase 1 (make core):"
check later   java                    "SpinalHDL / VexRiscv"
check later   sbt                     "SpinalHDL / VexRiscv"
check later   verilator               "linting and RTL simulation"
check optional gtkwave                "viewing waveforms (or Surfer)"

echo "Board (optional for now):"
check later   openFPGALoader          "programming the CYC1000"
check later   quartus_sh              "Quartus Prime Lite synthesis"

exit $missing
