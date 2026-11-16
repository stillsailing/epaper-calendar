#!/usr/bin/env python3
"""Set the calendar's clock to China Standard Time over USB serial.

The pages follow the Chinese calendar, so the time sent is Asia/Shanghai
regardless of this Mac's TZ setting (override with --tz).

Without a DS3231 the firmware stays awake and accepts the time at any moment,
so this first sends "SET YYYY-MM-DD HH:MM:SS" without resetting. On boards
whose USB-serial chip resets the ESP32 when the port opens (the tested ESP32-L
does), that first attempt lands during boot and goes unanswered; the board is
then reset and the time is sent in the boot-time window, as for a board in
deep sleep (DS3231 mode). If the board has no auto-reset circuit, press its
reset (EN/RST) button when asked.

After the firmware confirms, this keeps the port open and echoes the log until
the display refresh finishes: reopening the port later can reset the board,
which erases the internal clock.
"""

import argparse
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    import serial
except ImportError:
    sys.exit("pyserial is required: python3 -m pip install --user -r scripts/requirements.txt")

PROMPT = b"to set the clock"
PROMPT_TIMEOUT_S = 20
REFRESH_DONE = "Powering off display driver"
REFRESH_START_S = 3
REFRESH_TIMEOUT_S = 90


def send_time(port, zone):
    now = datetime.now(zone).strftime("%Y-%m-%d %H:%M:%S")
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


def follow_refresh(port):
    """Echo the log until the page refresh finishes, without reopening the port.

    If the date did not change, no refresh starts and this returns after a few
    seconds.
    """
    start = time.monotonic()
    started = False
    while time.monotonic() - start < (REFRESH_TIMEOUT_S if started else REFRESH_START_S):
        line = port.readline().decode(errors="replace")
        if line:
            sys.stdout.write(line)
        started = started or "Showing page" in line
        if REFRESH_DONE in line or "Nothing to show" in line or "skipped" in line:
            return
    if started:
        print("note: the refresh did not finish within the wait; check the panel")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("port", help="serial port, e.g. /dev/cu.usbserial-0001")
    parser.add_argument("--tz", default="Asia/Shanghai", help="time zone to send (default: %(default)s)")
    args = parser.parse_args(argv)
    zone = ZoneInfo(args.tz)

    with serial.Serial() as port:
        port.port = args.port
        port.baudrate = 115200
        port.timeout = 0.5
        port.dtr = False
        port.rts = False
        port.open()
        port.reset_input_buffer()

        # Awake (internal-clock mode): answers immediately, no reset.
        send_time(port, zone)
        if not await_reply(port, 2):
            print("no answer; resetting the board (it may be booting or in deep sleep)")
            reset_and_wait_for_prompt(port)
            send_time(port, zone)
            if not await_reply(port, 5):
                sys.exit("error: no confirmation from the firmware")
        follow_refresh(port)


if __name__ == "__main__":
    main()
