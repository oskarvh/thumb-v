"""The CYC1000 board: build a program into the FPGA image, load it, read the UART.

The program goes into the RAMs' initial contents, so each new program means a
Quartus compile (about 70 s); nothing is recompiled when neither the program
nor the RTL changed. Loading writes the FPGA's SRAM over JTAG (openFPGALoader),
so the board forgets it at power-off.

Loading also resets the FT2232H, so its serial port (channel B) disappears and
comes back, possibly as a different /dev/ttyUSB*. The board holds the SoC in
reset for 1.4 s after configuration (rtl/board/cyc1000_top.v), long enough to
find the port again by its stable /dev/serial/by-id name and start reading.

    python -m thumbv.board [program.elf] [--port PORT] [--seconds 2]

Without an ELF file it runs hello world (tests/c/hello.c).
"""

import argparse
import glob
import os
import select
import shutil
import subprocess
import sys
import termios
import time
import tty
from pathlib import Path

from . import build as recipes, elf, rtlsim
from .build import REPO, ToolMissing

BOARD_DIR = REPO / "build" / "board"
BOARD_RTL = REPO / "rtl" / "board"
BITSTREAM = BOARD_DIR / "thumbv.svf"
PORT_GLOB = "/dev/serial/by-id/usb-Arrow_Arrow_USB_Blaster_*-if01-port0"   # FT2232H channel B
BAUD = termios.B115200


def quartus_sh() -> Path:
    """quartus_sh from PATH or a default Quartus Prime Lite install in the home directory."""
    found = shutil.which("quartus_sh")
    if found:
        return Path(found)
    home = Path.home()
    for pattern in ("altera_lite/*/quartus/bin/quartus_sh", "intelFPGA_lite/*/quartus/bin/quartus_sh"):
        matches = sorted(glob.glob(str(home / pattern)))
        if matches:
            return Path(matches[-1])
    raise ToolMissing("quartus_sh")


def build(images) -> Path:
    """The FPGA image with `images` in its RAMs, compiled if out of date."""
    if not rtlsim.CORE.exists():
        subprocess.run(["make", "-C", str(REPO), "core"], check=True, capture_output=True)
    BOARD_DIR.mkdir(parents=True, exist_ok=True)
    code, data = rtlsim.memory_images(images, BOARD_DIR, rtlsim.BOARD, suffix=".mem")
    sources = [code, data, rtlsim.CORE, *(REPO / "rtl" / "soc").glob("*.v"), *BOARD_RTL.iterdir()]
    if not BITSTREAM.exists() or BITSTREAM.stat().st_mtime < max(s.stat().st_mtime for s in sources):
        log = BOARD_DIR / "quartus.log"
        with log.open("w") as out:
            done = subprocess.run([str(quartus_sh()), "-t", str(BOARD_RTL / "build.tcl")],
                                  cwd=BOARD_DIR, stdout=out, stderr=subprocess.STDOUT)
        if done.returncode != 0:
            raise RuntimeError(f"Quartus failed, see {log}")
    return BITSTREAM


def load(bitstream: Path = BITSTREAM, attempts: int = 3):
    """Write the bitstream into the FPGA's SRAM.

    openFPGALoader can exit with status 0 after a USB error part-way through,
    so its output is checked too. Each run resets the FT2232H, and a run
    started while it re-enumerates fails: retry after a pause.
    """
    if shutil.which("openFPGALoader") is None:
        raise ToolMissing("openFPGALoader")
    for attempt in range(attempts):
        done = subprocess.run(["openFPGALoader", "-b", "cyc1000", str(bitstream)],
                              capture_output=True, text=True)
        output = done.stdout + done.stderr
        failed = done.returncode != 0 or any(w in output for w in ("fail", "error", "isn't the one expected"))
        if not failed:
            return
        time.sleep(3)
    raise RuntimeError(f"openFPGALoader failed {attempts} times; last output:\n{output}")


def find_port(timeout: float = 1.0) -> str:
    """The board's serial port, waiting up to `timeout` seconds for it to appear."""
    end = time.monotonic() + timeout
    while True:
        for path in glob.glob(PORT_GLOB):
            if os.access(path, os.R_OK):
                return path
        if time.monotonic() > end:
            raise FileNotFoundError(f"no serial port matching {PORT_GLOB}: is the board connected?")
        time.sleep(0.05)


class Uart:
    """The board's UART at 115200 baud, 8N1, read without blocking."""

    def __init__(self, port: str):
        self.fd = os.open(port, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
        tty.setraw(self.fd)
        attrs = termios.tcgetattr(self.fd)
        attrs[4] = attrs[5] = BAUD
        termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
        termios.tcflush(self.fd, termios.TCIFLUSH)

    def read(self, seconds: float) -> bytes:
        """Everything received in the next `seconds`."""
        out, end = b"", time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0:
            if select.select([self.fd], [], [], left)[0]:
                out += os.read(self.fd, 4096)
        return out

    def close(self):
        os.close(self.fd)


def run(images, port: str | None = None, seconds: float = 2.0) -> bytes:
    """Build, load and run a program; what it printed over the UART in `seconds`
    after the SoC came out of reset."""
    load(build(images))
    time.sleep(0.2)                 # let the old port disappear first
    uart = Uart(port or find_port())
    try:
        return uart.read(seconds + 1.4)
    finally:
        uart.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run an RV32 program on the CYC1000.")
    parser.add_argument("elf", nargs="*", type=Path, help="default: hello world")
    parser.add_argument("--port", help="serial port (default: found by its /dev/serial/by-id name)")
    parser.add_argument("--seconds", type=float, default=2.0, help="how long to read the UART")
    args = parser.parse_args(argv)
    BOARD_DIR.mkdir(parents=True, exist_ok=True)
    paths = args.elf or [recipes.c_program("rv32", ["hello.c"], BOARD_DIR)]
    output = run([elf.load(p) for p in paths], args.port, args.seconds)
    sys.stdout.write(output.decode(errors="replace"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
