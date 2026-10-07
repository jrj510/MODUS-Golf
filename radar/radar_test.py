#!/usr/bin/env python3
"""
OPS243-A radar test: read speeds and report the peak of each burst.

Sets the radar to report in mph at a sample rate high enough for golf ball
speeds, then prints every reading with a time stamp. When readings stop for a
moment, it prints the fastest speed seen in that burst, which is what a shot
would produce.

No extra libraries needed. Run:
    python3 radar_test.py
    python3 radar_test.py --port /dev/ttyACM0 --min-speed 5

Stop with Ctrl+C.
"""

import argparse
import os
import re
import select
import termios
import time
import tty

NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def send(fd, command):
    os.write(fd, command.encode())
    time.sleep(0.15)


def main():
    p = argparse.ArgumentParser(description="OPS243-A speed test")
    p.add_argument("--port", default="/dev/ttyACM0")
    p.add_argument("--min-speed", type=float, default=3.0,
                   help="ignore readings slower than this (mph)")
    p.add_argument("--gap", type=float, default=0.5,
                   help="seconds of silence that end a burst")
    p.add_argument("--no-setup", action="store_true",
                   help="do not change the radar's settings, just listen")
    args = p.parse_args()

    fd = os.open(args.port, os.O_RDWR | os.O_NOCTTY)
    tty.setraw(fd)
    termios.tcflush(fd, termios.TCIOFLUSH)

    if not args.no_setup:
        send(fd, "US")   # report speed in miles per hour
        send(fd, "SL")   # 50,000 samples per second: reads up to about 340 mph
        print("Radar set to mph at the 50 kHz sample rate.")
    print(f"Listening on {args.port}. Positive and negative are the two directions.")
    print("Ctrl+C to stop.\n")

    start = time.monotonic()
    buffer = b""
    peak, peak_time, last_reading = 0.0, 0.0, None

    try:
        while True:
            ready, _, _ = select.select([fd], [], [], 0.1)
            now = time.monotonic()
            if ready:
                buffer += os.read(fd, 4096)
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    text = line.decode(errors="replace").strip()
                    if not text:
                        continue
                    numbers = NUMBER.findall(text)
                    if not numbers or text.startswith("{"):
                        print(f"           radar says: {text}")
                        continue
                    speed = float(numbers[-1])
                    if abs(speed) < args.min_speed:
                        continue
                    t = now - start
                    print(f"{t:9.3f} s   {speed:8.1f} mph")
                    if abs(speed) > abs(peak):
                        peak, peak_time = speed, t
                    last_reading = now
            if last_reading is not None and now - last_reading > args.gap:
                print(f"   --> PEAK {abs(peak):.1f} mph at {peak_time:.3f} s\n")
                peak, last_reading = 0.0, None
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
