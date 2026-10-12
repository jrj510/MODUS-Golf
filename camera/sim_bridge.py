"""
Sends each shot to a golf simulator (OpenGolfSim, GSPro or PAR-TEE) using
OpenFlight's simulator connector code.

OpenGolfSim: pick the "Developer API" launch monitor in OpenGolfSim. It then
listens on TCP port 3111 for shots in its own JSON format (one JSON message per
line, see help.opengolfsim.com/desktop/apis). That format is written here
directly. GSPro and PAR-TEE use OpenFlight's OpenConnect V1 connector.

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
import socket
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
        self._resolve = resolve_shot
        self.lock = threading.Lock()
        self.state = "connecting"
        self.player = PlayerState()
        club = _club(args.sim_club)
        if club is not None:
            self.player.club = club

        if args.sim_type == "opengolfsim":
            self.connector = OpenGolfSimClient(args.sim_host, args.sim_port or 3111,
                                               on_status=self._on_status)
            self.cfg = self.connector
            self.connector.start()
            print(f"Simulator: sending shots to OpenGolfSim at "
                  f"{args.sim_host}:{args.sim_port or 3111} (club {self.player.club})")
            return

        try:
            from openflight.sim.codec import build_connector
        except ImportError:
            from openflight.sim.connector import build_connector

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
            # The simulator's club (or --sim-club) decides the typical launch and
            # spin used for anything the radars didn't measure.
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


class OpenGolfSimClient:
    """OpenGolfSim's Developer API: newline-separated JSON over TCP (port 3111).

    Connects in the background, tells OpenGolfSim the device is ready, keeps
    reconnecting if the connection drops, and prints the carry OpenGolfSim
    reports back for each shot."""

    def __init__(self, host, port, on_status=None):
        self.host, self.port = host, port
        self.on_status = on_status
        self.sock = None
        self.lock = threading.Lock()
        self.running = False

    def _status(self, state, message=""):
        if self.on_status:
            self.on_status("opengolfsim", _Status(state, message))

    def start(self):
        self.running = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while self.running:
            try:
                sock = socket.create_connection((self.host, self.port), timeout=5)
                sock.settimeout(None)
                with self.lock:
                    self.sock = sock
                self._write({"type": "device", "status": "ready"})
                self._status("connected")
                self._read(sock)          # returns when the connection closes
            except OSError as e:
                self._status("reconnecting", str(e))
            with self.lock:
                self.sock = None
            if self.running:
                time.sleep(3)

    def _read(self, sock):
        buf = b""
        while self.running:
            data = sock.recv(4096)
            if not data:
                return
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if msg.get("type") == "result":
                    r = (msg.get("data") or msg).get("result") or {}
                    carry = r.get("carry")
                    total = r.get("total")
                    if carry is not None:
                        print(f"[{time.strftime('%H:%M:%S')}] OpenGolfSim: carry "
                              f"{carry * 1.0936:.0f} yd" + (f", total {total * 1.0936:.0f} yd"
                                                            if total is not None else ""))

    def _write(self, payload):
        data = (json.dumps(payload) + "\n").encode()
        with self.lock:
            if self.sock is None:
                raise OSError("not connected")
            self.sock.sendall(data)

    def is_connected(self):
        with self.lock:
            return self.sock is not None

    def send_shot(self, resolved):
        clamp = lambda v, lo, hi: max(lo, min(hi, float(v or 0.0)))
        self._write({"type": "shot", "unit": "imperial", "shot": {
            "ballSpeed": round(float(resolved.ball_speed_mph), 2),
            "verticalLaunchAngle": round(clamp(resolved.vla, 0, 45), 2),
            "horizontalLaunchAngle": round(clamp(resolved.hla, -45, 45), 2),
            "spinSpeed": round(float(resolved.total_spin_rpm or 0.0)),
            "spinAxis": round(clamp(resolved.spin_axis_deg, -45, 45), 2)}})

    def stop(self):
        self.running = False
        with self.lock:
            sock, self.sock = self.sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        self._status("stopped")


class _Status:
    def __init__(self, state, message=""):
        self.state = type("S", (), {"value": state})()
        self.message = message


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
