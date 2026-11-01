# The CYC1000 board

Thumb-V runs on the Trenz CYC1000 (Cyclone 10 LP `10CL025YU256C8G`, 12 MHz oscillator, on-board Arrow USB Blaster). The board design is in `rtl/board/`; resource use and timing are in [resources.md](resources.md).

```sh
make board                      # hello world
make board PROGRAM=leaf         # RISC-V calls gcc-compiled Thumb functions (Phase 2.4)
make board PROGRAM=blinky       # counts on the LEDs, forever
make board ELF="a.elf b.elf"    # any program built with tests/link/rv32.ld (and thumb_lib.ld)
```

`make board` runs `python -m thumbv.board`, which:
1. writes the program into the RAMs' initial contents (`build/board/code.mem` and `data.mem`);
2. compiles the FPGA image with Quartus if the program or the RTL changed (about 30–70 s);
3. loads it into the FPGA over JTAG;
4. prints what the program sends over the UART for 2 s (`--seconds` to change).

The FPGA's configuration is SRAM, so the board forgets the program at power-off. It also has a factory image in its flash, which runs at power-up.

## The design

| File | What |
|---|---|
| `rtl/board/cyc1000_top.v` | Top level: the SoC ([soc.md](soc.md)) at 12 MHz, the reset, the pins |
| `rtl/board/pins.tcl` | Pin assignments, from the Trenz TEI0003 rev 03 schematic |
| `rtl/board/cyc1000.sdc` | Timing constraints: the 12 MHz clock; board I/O is asynchronous |
| `rtl/board/build.tcl` | Creates the Quartus project in `build/board/`, compiles it, writes `thumbv.svf` |

**Memories.** The board has 66 M9K blocks (66 KB), so its RAMs are smaller than in simulation: 32 KiB of code RAM and 16 KiB of data RAM.
- **Aliasing:** each RAM repeats through its 256 KiB or 64 KiB region, so programs linked for the simulation run unchanged. A RISC-V program's code at `0x2_0000` lands at the start of the code RAM, and its stack at the top of the data region lands at the top of the data RAM.
- **Collisions:** `thumbv.rtlsim.memory_images` refuses a program whose loaded parts would land on the same RAM byte.
- **Mixed programs:** the Thumb library's window starts at `0x1_4000` (`tests/link/thumb_lib.ld`), so its code lands in the code RAM's upper 16 KiB and the RISC-V side's (`0x2_0000`) in the lower 16 KiB. Each side must stay under 16 KiB.
- **Data:** the Thumb library's data (`0x2000_0000`) and the RISC-V side's (`0x2000_4000`) both land at the start of the 16 KiB data RAM, below the shared stack. So on the board, only one side may have data. Initialised data is caught by the collision check, but zeroed data (`.bss`) and the stack aren't loaded, so they aren't checked.
- **Thumb-only programs** (`0x1_0000`, `tests/link/thumb.ld`) would collide with nothing, but they need RISC-V startup code to reach them: the reset vector is RISC-V code at `0x2_0000`.
- **The same configuration in simulation:** `python -m thumbv.rtlsim --board` runs the board's RAM sizes in Verilator, and `tests/test_rtl.py` checks hello world with them.

**Reset.** The SoC is held in reset for 1.4 s after configuration, and while the user button is held. The delay is for the host: loading the FPGA resets the FT2232H, its serial port disappears and comes back (often as a different `/dev/ttyUSB*`), and the program's first output would otherwise be lost. The button switches to ground with no pull-up on the board, so the pin's weak pull-up is on.

**Pins.**

| Signal | Pin | Notes |
|---|---|---|
| `CLK12M` | M2 | 12 MHz oscillator |
| `USER_BTN` | N6 | Active low, internal pull-up |
| `UART_TX` | T7 | To the FT2232H's channel B RXD (`BDBUS1`) |
| `UART_RX` | R7 | From the FT2232H's channel B TXD (`BDBUS0`), unused so far |
| `LED[7:0]` | M6, T4, T3, R3, T2, R4, N5, N3 | LED1–LED8, active high |

**UART.** 115200 baud, 8N1, through the FT2232H's channel B. The divider is 104 clocks per bit, about 115385 baud (0.2% fast). Linux gives it a stable name, `/dev/serial/by-id/usb-Arrow_Arrow_USB_Blaster_<serial>-if01-port0`, which `thumbv.board` uses. To watch it by hand: `picocom -b 115200 /dev/serial/by-id/usb-Arrow_*-if01-port0`.

## Loading: lessons from bring-up

- **Load the SVF, not the RBF.** openFPGALoader 0.12 reports `Load SRAM: 100% Done` for `thumbv.rbf`, but the FPGA doesn't start. The SVF from `quartus_cpf` works. `build.tcl` writes it after every compile.
- **Don't trust openFPGALoader's exit status.** After a USB error partway through a load it can still exit 0, so `thumbv.board` checks the output for errors and retries.
- **Let the FT2232H settle between loads.** Every openFPGALoader run resets the FT2232H. A run started in the second or two while it re-enumerates fails with `usb bulk read failed` or `unable to configure bitbang mode`. `thumbv.board` retries after 3 s.
- **Replug after installing openFPGALoader.** Its udev rule (`plugdev` access to the FT2232H) only applies to devices plugged in after it was installed. Before that, openFPGALoader fails with `usb_open() failed`.
- **What an unconfigured board looks like.** The 8 LEDs are dimly lit, from the FPGA's weak pull-ups, with one red LED fully on. If the LEDs look like that after a load, the load didn't work.

## Test programs

- `tests/c/hello.c` prints "Hello from Thumb-V" and sets the LEDs to `0xA5`.
- `tests/c/blinky.c` counts on the LEDs and prints the count about 3 times a second, forever (`PROGRAM=blinky`).
- `tests/c/thumb_leaf_main.c` calls the gcc-compiled leaf Thumb functions in `tests/c/thumb_leaf.c` and prints their results (`PROGRAM=leaf`). The LEDs show the low byte of the results' sum, `0x9d`.
