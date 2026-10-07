#!/usr/bin/env python3
"""
IWR6843LEVM radar test, for a board running TI's standard "out-of-box"
mmWave demo firmware.

Step 1, see what firmware is on the board:
    python3 ti_test.py --info

Step 2, start the radar and print what it detects:
    python3 ti_test.py

In step 2 the script sends a standard configuration, then prints, about ten
times a second, how many points the radar sees and where the nearest few are:
x (left/right), y (distance in front), z (up/down) in metres, and speed toward
or away in m/s. Wave a hand in front of the antenna to see points appear.

No extra libraries needed. Stop with Ctrl+C.
"""

import argparse
import os
import select
import struct
import termios
import time
import tty

MAGIC = bytes([2, 1, 4, 3, 6, 5, 8, 7])
HEADER = struct.Struct("<8sIIIIIIII")   # 40 bytes
TLV_POINTS = 1

# Standard 3D profile for the 68xx out-of-box demo (about 10 frames a second).
CONFIG = """
sensorStop
flushCfg
dfeDataOutputMode 1
channelCfg 15 7 0
adcCfg 2 1
adcbufCfg -1 0 1 1 1
profileCfg 0 60 359 7 57.14 0 0 70 1 256 5209 0 0 158
chirpCfg 0 0 0 0 0 0 0 1
chirpCfg 1 1 0 0 0 0 0 4
chirpCfg 2 2 0 0 0 0 0 2
frameCfg 0 2 16 0 100 1 0
lowPower 0 0
guiMonitor -1 1 0 0 0 0 0
cfarCfg -1 0 2 8 4 3 0 15 1
cfarCfg -1 1 0 4 2 3 1 15 1
multiObjBeamForming -1 1 0.5
clutterRemoval -1 0
calibDcRangeSig -1 0 -5 8 256
extendedMaxVelocity -1 0
lvdsStreamCfg -1 0 0 0
compRangeBiasAndRxChanPhase 0.0 1 0 1 0 1 0 1 0 1 0 1 0 1 0 1 0 1 0 1 0 1 0 1 0
measureRangeBiasAndRxChanPhase 0 1.5 0.2
CQRxSatMonitor 0 3 5 121 0
CQSigImgMonitor 0 127 4
analogMonitor 0 0
aoaFovCfg -1 -90 90 -90 90
cfarFovCfg -1 0 0 8.92
cfarFovCfg -1 1 -1 1.00
calibData 0 0 0
sensorStart
"""


def open_serial(path, baud):
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY)
    tty.setraw(fd)
    attrs = termios.tcgetattr(fd)
    speed = getattr(termios, f"B{baud}")
    attrs[4] = attrs[5] = speed
    attrs[2] |= termios.CLOCAL | termios.CREAD
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    termios.tcflush(fd, termios.TCIOFLUSH)
    return fd


def read_for(fd, seconds):
    """Collect whatever arrives on a port for a short time."""
    end, data = time.monotonic() + seconds, b""
    while time.monotonic() < end:
        ready, _, _ = select.select([fd], [], [], 0.05)
        if ready:
            data += os.read(fd, 4096)
    return data.decode(errors="replace")


def command(cli, line, wait=0.15):
    os.write(cli, (line + "\n").encode())
    reply = read_for(cli, wait)
    lines = [l.strip() for l in reply.splitlines()
             if l.strip() and l.strip() != line and not l.strip().endswith(":/>")]
    return lines


def main():
    p = argparse.ArgumentParser(description="IWR6843LEVM out-of-box demo test")
    p.add_argument("--cli", default="/dev/ttyUSB0", help="command port")
    p.add_argument("--data", default="/dev/ttyUSB1", help="data port")
    p.add_argument("--info", action="store_true", help="only ask the board what firmware it runs")
    p.add_argument("--show", type=int, default=3, help="how many points to print per frame")
    args = p.parse_args()

    cli = open_serial(args.cli, 115200)

    if args.info:
        print(f"Asking the board on {args.cli} for its version...\n")
        os.write(cli, b"\n")
        read_for(cli, 0.3)
        os.write(cli, b"version\n")
        reply = read_for(cli, 1.0).strip()
        print(reply if reply else
              "No reply. Try --cli /dev/ttyUSB1, press the board's reset button, "
              "or check its mode switches.")
        os.close(cli)
        return

    print("Sending configuration...")
    failed = False
    for line in CONFIG.strip().splitlines():
        reply = command(cli, line, wait=0.6 if line == "sensorStart" else 0.15)
        bad = [r for r in reply if "error" in r.lower() or "not recognized" in r.lower()
               or "invalid" in r.lower()]
        if bad:
            failed = True
            print(f"  REJECTED: {line}\n            board said: {' | '.join(reply)}")
    if failed:
        print("\nThe board rejected part of the configuration, so it may not start.\n"
              "Send those lines back so the configuration can be matched to this firmware.\n")
    else:
        print("Configuration accepted. Radar started.\n")

    data = open_serial(args.data, 921600)
    print(f"Reading detections from {args.data}. Ctrl+C to stop.\n")
    buffer, last_frame = b"", time.monotonic()
    try:
        while True:
            ready, _, _ = select.select([data], [], [], 0.5)
            if ready:
                buffer += os.read(data, 65536)
            elif time.monotonic() - last_frame > 3:
                print("No data arriving. If the configuration was rejected above, that is why. "
                      "Otherwise try swapping --cli and --data.")
                last_frame = time.monotonic()
            while True:
                start = buffer.find(MAGIC)
                if start < 0:
                    buffer = buffer[-7:]
                    break
                if len(buffer) - start < HEADER.size:
                    buffer = buffer[start:]
                    break
                (_, _, total, _, frame, _, n_obj, n_tlv, _) = HEADER.unpack_from(buffer, start)
                if total < HEADER.size or total > 100000:
                    buffer = buffer[start + 8:]
                    continue
                if len(buffer) - start < total:
                    buffer = buffer[start:]
                    break
                packet = buffer[start:start + total]
                buffer = buffer[start + total:]
                last_frame = time.monotonic()

                points, pos = [], HEADER.size
                for _ in range(n_tlv):
                    if pos + 8 > len(packet):
                        break
                    kind, length = struct.unpack_from("<II", packet, pos)
                    pos += 8
                    if kind == TLV_POINTS:
                        for i in range(length // 16):
                            points.append(struct.unpack_from("<ffff", packet, pos + 16 * i))
                    pos += length
                points.sort(key=lambda q: (q[0] ** 2 + q[1] ** 2 + q[2] ** 2))
                text = "   ".join(f"x={x:+.2f} y={y:.2f} z={z:+.2f} v={v:+.2f}"
                                  for x, y, z, v in points[:args.show])
                print(f"frame {frame:6d}  points {n_obj:3d}   {text}")
    except KeyboardInterrupt:
        print("\nStopping the radar.")
        command(cli, "sensorStop")
    finally:
        os.close(data)
        os.close(cli)


if __name__ == "__main__":
    main()
