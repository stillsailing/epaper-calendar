#!/usr/bin/env python3
"""Set the calendar's clock to this Mac's local time over USB serial.

Without a DS3231 the firmware stays awake and accepts the time at any moment,
so this first sends "SET YYYY-MM-DD HH:MM:SS" without resetting (a reset would
erase the internal clock). If nothing answers, the board is in deep sleep
(DS3231 mode): it is reset and the time is sent in the boot-time window. If the
board has no auto-reset circuit, press its reset (EN/RST) button when asked.

The firmware replies with how far the clock had drifted since the last SET.
"""

import argparse
import sys
import time
from datetime import datetime

try:
    import serial
except ImportError:
    sys.exit("pyserial is required: python3 -m pip install --user -r scripts/requirements.txt")

PROMPT = b"to set the clock"
PROMPT_TIMEOUT_S = 20


def send_time(port):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    port.write(f"SET {now}\n".encode())
    print(f"sent SET {now}")


def await_reply(port, seconds):
    """Echo firmware output; return True once the clock is confirmed set."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        line = port.readline().decode(errors="replace")
        if line:
            sys.stdout.write(line)
        if "Clock set to" in line:
            # Pick up the drift report that follows.
            follow = port.readline().decode(errors="replace")
            if "Clock was" in follow:
                sys.stdout.write(follow)
            return True
        if "Invalid time" in line or "Clock write failed" in line:
            sys.exit("error: the firmware rejected the time")
    return False


def reset_and_wait_for_prompt(port):
    # Classic ESP32 auto-reset: RTS pulls EN low while DTR keeps IO0 high.
    port.rts = True
    time.sleep(0.1)
    port.rts = False
    start = time.monotonic()
    hinted = False
    buffer = b""
    while PROMPT not in buffer:
        elapsed = time.monotonic() - start
        if elapsed > PROMPT_TIMEOUT_S:
            sys.exit("error: no prompt from the calendar firmware")
        if not hinted and elapsed > 4:
            print("waiting... press the board's reset (EN/RST) button if nothing happens")
            hinted = True
        line = port.readline()
        if line:
            sys.stdout.write(line.decode(errors="replace"))
        buffer = (buffer + line)[-256:]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("port", help="serial port, e.g. /dev/cu.usbserial-0001")
    args = parser.parse_args(argv)

    with serial.Serial() as port:
        port.port = args.port
        port.baudrate = 115200
        port.timeout = 0.5
        port.dtr = False
        port.rts = False
        port.open()
        port.reset_input_buffer()

        # Awake (internal-clock mode): answers immediately, no reset.
        send_time(port)
        if await_reply(port, 2):
            return

        print("no answer; resetting the board (DS3231 mode sleeps between refreshes)")
        reset_and_wait_for_prompt(port)
        send_time(port)
        if not await_reply(port, 5):
            sys.exit("error: no confirmation from the firmware")


if __name__ == "__main__":
    main()
