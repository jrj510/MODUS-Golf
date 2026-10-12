#!/usr/bin/env python3
"""
Send a pretend shot to the simulator, to check the connection without hitting.

Stop the kiosk first (only one program should talk to OpenGolfSim at a time),
open OpenGolfSim on the laptop with the Developer API selected, then:

    python3 camera/sim_test.py                       # 60 mph, 30 deg, sand wedge
    python3 camera/sim_test.py --speed 110 --launch 18 --club 7i
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sim_bridge import SimBridge  # noqa: E402


class FakeShot:
    """Looks like OpenFlight's shot; any field not set here reads as None."""

    def __init__(self, **fields):
        self.__dict__.update(fields)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)   # keep Python's own machinery working
        return None


def main():
    p = argparse.ArgumentParser(description="Send a test shot to the golf simulator")
    p.add_argument("--speed", type=float, default=60.0, help="ball speed, mph")
    p.add_argument("--launch", type=float, default=30.0, help="vertical launch angle, degrees")
    p.add_argument("--spin", type=float, default=0.0, help="spin, rpm (0 = the club's typical spin)")
    p.add_argument("--club", default="sw")
    p.add_argument("--count", type=int, default=1, help="how many shots, 8 seconds apart")
    p.add_argument("--openflight", default="~/openflight")
    p.add_argument("--sim-type", default="opengolfsim")
    p.add_argument("--sim-host", default="192.168.137.1")
    p.add_argument("--sim-port", type=int, default=0)
    args = p.parse_args()
    args.sim_club = args.club

    sim = SimBridge(args)
    for _ in range(50):                      # wait up to 5 s for the connection
        if sim.connector.is_connected():
            break
        time.sleep(0.1)
    try:
        for i in range(args.count):
            if i:
                time.sleep(8)
            shot = FakeShot(ball_speed_mph=args.speed, spin_rpm=args.spin or None,
                            spin_confidence=1.0 if args.spin else 0.0,
                            club=sim.player.club)
            sim.send(shot, launch_angle=args.launch)
        time.sleep(1.0)                      # let it go out before closing
    finally:
        sim.stop()


if __name__ == "__main__":
    main()
