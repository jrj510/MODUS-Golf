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
    """Stand-in for OpenFlight's shot, used if its own Shot class can't be built."""

    def __init__(self, **fields):
        self.__dict__.update(fields)


def make_shot(club, speed, launch, spin):
    """A pretend shot, built from OpenFlight's own Shot class when possible so
    its simulator code sees exactly what a real shot looks like."""
    values = dict(ball_speed_mph=speed, launch_angle_vertical=launch,
                  launch_angle_horizontal=0.0, spin_rpm=spin or None,
                  spin_confidence=1.0 if spin else 0.0, spin_axis_deg=0.0,
                  club=club, club_speed_mph=None, club_path_deg=0.0,
                  estimated_carry_yards=0.0, carry_spin_adjusted=None,
                  has_launch_angle=True, timestamp=time.time(),
                  impact_timestamp=time.time())
    try:
        import dataclasses
        import inspect
        from openflight.sim import resolver
        Shot = getattr(resolver, "Shot", None)
        if Shot is not None and dataclasses.is_dataclass(Shot):
            kwargs = {}
            for f in dataclasses.fields(Shot):
                if not f.init:
                    continue
                if f.name in values:
                    kwargs[f.name] = values[f.name]
                elif (f.default is dataclasses.MISSING
                      and f.default_factory is dataclasses.MISSING):
                    kwargs[f.name] = 0.0      # a required field we have no value for
            shot = Shot(**kwargs)
            for k, v in values.items():       # fields that are properties or init=False
                try:
                    setattr(shot, k, v)
                except Exception:
                    pass
            return shot
    except Exception as e:
        print(f"(using a stand-in shot: {type(e).__name__}: {e})")
    return FakeShot(**values)


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
            shot = make_shot(sim.player.club, args.speed, args.launch, args.spin)
            sim.send(shot, launch_angle=args.launch)
        time.sleep(1.0)                      # let it go out before closing
    finally:
        sim.stop()


if __name__ == "__main__":
    main()
