"""
Sends each shot to a golf simulator (OpenGolfSim, GSPro or PAR-TEE) using
OpenFlight's simulator connector code.

OpenGolfSim: pick the "Developer API" launch monitor in OpenGolfSim. It then
listens on TCP port 3111 for shots in the OpenConnect V1 format, the same format
GSPro uses. OpenFlight's connector keeps the connection open, reconnects if it
drops and sends a heartbeat.

What is sent for each shot: ball speed (speed radar), vertical launch angle (TI
radar; if it has none, OpenFlight's per-club typical value), horizontal launch
angle, spin (measured if confident, otherwise a per-club typical value) and spin
axis. The simulator works out the flight and carry itself.
"""

import copy
import dataclasses
import json
import os
import pathlib
import tempfile
import threading
import time

from iwr_bridge import _openflight_root


class SimBridge:
    def __init__(self, args):
        _openflight_root(args)
        from openflight.sim.config import load_sim_config
        from openflight.sim.resolver import resolve_shot
        from openflight.sim.types import PlayerState
        try:
            from openflight.sim.codec import build_connector
        except ImportError:
            from openflight.sim.connector import build_connector

        self._resolve = resolve_shot
        self.lock = threading.Lock()
        self.state = "connecting"

        # Let OpenFlight's own config loader fill in its defaults for this
        # simulator type (units, device ID, heartbeat).
        entry = {"type": args.sim_type, "enabled": True, "host": args.sim_host}
        if args.sim_port:
            entry["port"] = args.sim_port
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"connectors": [entry]}, f)
            path = f.name
        try:
            cfgs = load_sim_config(pathlib.Path(path))   # OpenFlight expects a Path
        finally:
            os.unlink(path)
        if not cfgs:
            raise RuntimeError("OpenFlight did not accept the simulator settings")
        self.cfg = cfgs[0]

        self.player = PlayerState()
        club = _club(args.sim_club)
        if club is not None:
            self.player.club = club
        self.connector = build_connector(self.cfg, on_status=self._on_status,
                                         on_inbound=self._on_inbound)
        self.connector.start()
        print(f"Simulator: sending shots to {args.sim_type} at "
              f"{self.cfg.host}:{self.cfg.port} (club {self.player.club})")

    def _on_status(self, name, event):
        state = getattr(getattr(event, "state", None), "value", str(event))
        with self.lock:
            changed = state != self.state
            self.state = state
        if changed:
            msg = getattr(event, "message", "")
            print(f"[{time.strftime('%H:%M:%S')}] Simulator {name}: {state}"
                  + (f" ({msg})" if msg else ""))

    def _on_inbound(self, name, event):
        kind = type(event).__name__
        if kind == "PlayerUpdate":
            self.player.apply(event)
            print(f"[{time.strftime('%H:%M:%S')}] Simulator {name}: club is now "
                  f"{self.player.club}")
        elif kind == "SimError":
            print(f"[{time.strftime('%H:%M:%S')}] Simulator {name} error: "
                  f"{getattr(event, 'message', '')}")

    def send(self, shot, launch_angle=None):
        """Send one speed-radar shot, with the TI radar's launch angle if any."""
        if shot is None:
            return
        try:
            if launch_angle is not None:
                shot = _with(shot, launch_angle_vertical=float(launch_angle))
            if getattr(shot, "club", None) is None:
                shot = _with(shot, club=self.player.club)
            resolved = self._resolve(shot, self.player)
        except Exception as e:
            print(f"Simulator: shot not sent ({type(e).__name__}: {e})")
            return
        if not self.connector.is_connected():
            print(f"Simulator: not connected ({self.state}); shot not sent. "
                  f"Is OpenGolfSim open with the Developer API selected?")
            return
        try:
            self.connector.send_shot(resolved)
        except OSError as e:
            print(f"Simulator: sending failed ({e})")
            return
        src = getattr(resolved, "provenance", {}) or {}
        print(f"[{time.strftime('%H:%M:%S')}] Sent to simulator: "
              f"ball {resolved.ball_speed_mph:.1f} mph, "
              f"launch {resolved.vla:.1f} deg ({src.get('vla', '?')}), "
              f"spin {resolved.total_spin_rpm:.0f} rpm ({src.get('total_spin_rpm', src.get('spin', '?'))})")

    def stop(self):
        try:
            self.connector.stop()
        except Exception as e:
            print(f"Simulator stop: {e}")


def _with(obj, **changes):
    """A copy of OpenFlight's shot with some fields changed."""
    if dataclasses.is_dataclass(obj):
        try:
            return dataclasses.replace(obj, **changes)
        except TypeError:
            pass
    obj = copy.copy(obj)
    for k, v in changes.items():
        setattr(obj, k, v)
    return obj


def _club(name):
    """OpenFlight's club for a name like 'driver', 'pw' or '52', or None."""
    if not name:
        return None
    from openflight.sim.types import ClubType
    want = str(name).strip().lower()
    for c in ClubType:
        if want in (c.name.lower(), str(c.value).lower()):
            return c
    for c in ClubType:   # looser match, e.g. "52" in "WEDGE_52"
        if want in c.name.lower() or want in str(c.value).lower():
            return c
    print(f"Simulator: unknown club '{name}'. Choices: "
          + ", ".join(str(c.value) for c in ClubType))
    return None
