# Resources and timing

FPGA resource use and timing of the board design ([board.md](board.md)), one row per milestone. Numbers are from Quartus Prime Lite 25.1std, for the `10CL025YU256C8G` (24,624 LEs, 66 M9K blocks, 132 9-bit multipliers). Fmax is the slow 1200 mV 85 °C model.

| Milestone | Date | LEs | Registers | M9K | Multipliers (9-bit) | Fmax | Notes |
|---|---|---|---|---|---|---|---|
| 1.4 stock core | 2026-10-31 | 2,966 (12%) | 1,224 | 50 (76%) | 8 | 50.5 MHz | RV32IMC VexRiscv ([core.md](core.md)), 32 KiB code + 16 KiB data RAM, UART, LEDs; no PLL, runs at 12 MHz |
| 2.1 mode switch | 2026-11-01 | 3,351 (14%) | 1,364 | 50 (76%) | 8 | 48.8 MHz | + 2 Thumb regions (four 30-bit CSRs and comparators in fetch), the Thumb length rule, the stub expander |

## 1.4 baseline

- **Memory:** 50 M9K blocks: 32 for the code RAM, 16 for the data RAM and 2 for the register file. That leaves 16 blocks for the Thumb-V additions, caches and FIFOs. Larger programs need the SDRAM (Phase 7).
- **Critical path:** 20 ns, from `decode_to_execute_RS1` through the load/store address adder and the SoC's address decode into the RAMs' write and byte enables. The DBusSimple command leaves the core combinationally from execute, so the SoC's decode adds to the core's path. Registering the data bus command, or a simpler decode, would raise Fmax if it ever matters. The core itself is not yet the limit.
- **Headroom:** 88% of the logic is free. The plan's concern was the expander lengthening fetch→decode; Phase 2 adds a row here to measure that.

To reproduce: `make board`, then the reports are `build/board/thumbv.fit.summary` and `build/board/thumbv.sta.rpt` ("Fmax Summary").
