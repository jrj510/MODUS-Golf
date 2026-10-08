"""
Bridges between our kiosk and OpenFlight's radar code.

IWRBridge: the TI IWR6843LEVM (launch angle).
OPSBridge: the OPS243-A in rolling-buffer mode (ball speed, club speed, spin).
Both are driven by the shared sound trigger.

OpenFlight's code handles the TI radar: it watches the sound trigger on GPIO17,
tells the radar to hand over its capture, and turns that capture into a launch
angle. Everything else (camera, screen, shot handling) stays ours.

Needs a copy of OpenFlight at ~/openflight (or wherever --openflight points)
with the custom firmware already flashed onto the radar.
"""

import dataclasses
import math
import os
import sys
import threading
import time


def _openflight_root(args):
    root = os.path.expanduser(args.openflight)
    src = os.path.join(root, "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    return root


def _summary(m):
    """The small fields of OpenFlight's result (numbers, text, flags), so the
    log shows why a capture was rejected. Big arrays are left out."""
    try:
        fields = dataclasses.asdict(m) if dataclasses.is_dataclass(m) else dict(vars(m))
    except Exception:
        return repr(m)[:600]
    out = {}
    for k, v in fields.items():
        if getattr(v, "ndim", None) == 0 and hasattr(v, "item"):
            v = v.item()   # a single numpy number
        if isinstance(v, float):
            out[k] = round(v, 3)
        elif isinstance(v, (int, bool, str)) or v is None:
            out[k] = v if not isinstance(v, str) else v[:120]
        elif isinstance(v, (list, tuple)) and len(v) <= 8 and all(
                isinstance(x, (int, float, str, bool)) for x in v):
            out[k] = list(v)
    return out


class IWRBridge:
    def __init__(self, args, on_trigger=None):
        root = _openflight_root(args)
        from openflight.iwr6843 import Calibration, process_dump
        from openflight.iwr6843.monitor import IWR6843CaptureMonitor, tx_order_from_config

        self._process = process_dump
        config = args.iwr_config
        if not os.path.isabs(config):
            config = os.path.join(root, config)
        self.tx_order = tx_order_from_config(config)

        # Mounting geometry, measured from the centre of the radar's antenna.
        base = Calibration.identity(8)
        self.cal = dataclasses.replace(
            base,
            tilt_rad=math.radians(args.iwr_tilt_deg),
            tee_range_m=args.iwr_tee_m,
            tee_ball_height_m=args.iwr_ball_height_m,
            meta={**base.meta, "radar_height_m": args.iwr_radar_height_m},
            source="modus-kiosk",
        )
        self.net_m = args.iwr_net_m
        self.on_trigger = on_trigger
        self.lock = threading.Lock()
        self.events = []   # one per sound trigger

        out = os.path.join(args.out, "iwr")
        os.makedirs(out, exist_ok=True)
        # OpenFlight's monitor owns GPIO17 (the sound trigger). We hear about
        # each trigger through the observer below.
        self.monitor = IWR6843CaptureMonitor(
            config_path=config, output_dir=out, port=args.iwr_port, gpio_pin=17,
            save_dumps=args.iwr_save_dumps, trigger_observers=[self._observer])
        self.monitor.start(armed=True)
        print(f"TI radar ready on {args.iwr_port} (sound trigger on GPIO17)")

    def _observer(self, *details):
        stamp = details[0] if details and isinstance(details[0], (int, float)) else None
        event = {"t": time.monotonic(), "stamp": stamp, "done": threading.Event(),
                 "result": None}
        print(f"[{time.strftime('%H:%M:%S')}] Sound trigger received; TI radar capturing")
        with self.lock:
            now = time.monotonic()
            self.events = [e for e in self.events if now - e["t"] < 120] + [event]
        threading.Thread(target=self._collect, args=(event,), daemon=True).start()
        if self.on_trigger is not None:
            try:
                self.on_trigger()
            except Exception as e:
                print(f"Trigger handler error: {e}")

    def _collect(self, event):
        """Wait for the radar's capture for this trigger, then work out the angle."""
        result = {"launch_angle": None, "ball_speed": None, "quality": None, "error": None}
        try:
            capture = self.monitor.capture_for_shot(event["stamp"], timeout_s=25.0)
            if capture is None:
                result["error"] = "no capture arrived"
            elif not capture.valid:
                result["error"] = capture.error or "invalid capture"
            else:
                m = self._process(capture.raw, self.cal, net_range_m=self.net_m,
                                  tx_order=self.tx_order)
                result["quality"] = m.quality
                print(f"[{time.strftime('%H:%M:%S')}] TI radar details: {_summary(m)}")
                if m.ball_found and m.quality != "reject":
                    result["launch_angle"] = m.launch_angle_deg
                    result["ball_speed"] = m.ball_speed_corrected_mph or m.ball_speed_mph
                else:
                    result["error"] = "no ball in the radar data"
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {e}"
        event["result"] = result
        event["done"].set()

    def result_for(self, shot_time, window_s=1.5, wait_s=30.0):
        """The radar result for the sound trigger closest to a camera shot."""
        with self.lock:
            near = [e for e in self.events if abs(e["t"] - shot_time) <= window_s]
        if not near:
            return {"launch_angle": None, "ball_speed": None, "quality": None,
                    "error": "no sound trigger near this shot"}
        event = min(near, key=lambda e: abs(e["t"] - shot_time))
        if not event["done"].wait(wait_s):
            return {"launch_angle": None, "ball_speed": None, "quality": None,
                    "error": "radar result timed out"}
        return event["result"]

    def stop(self):
        try:
            self.monitor.stop()
        except Exception as e:
            print(f"TI radar stop: {e}")


class OPSBridge:
    """Runs OpenFlight's rolling-buffer monitor for the OPS243-A.

    It connects to the radar, keeps its trigger pin set up as an input, collects
    the raw samples after every sound trigger, re-arms the radar, and works out
    ball speed, club speed and spin. Only real shots come out: triggers with
    nothing flying away from the radar (claps) are dropped by OpenFlight's code.
    """

    def __init__(self, args):
        _openflight_root(args)
        from openflight.rolling_buffer import RollingBufferMonitor

        self.lock = threading.Lock()
        self.shots = []    # (arrival time, Shot)
        self.monitor = RollingBufferMonitor(port=args.radar_port, trigger_type="sound",
                                            sample_rate_ksps=args.ops_ksps)
        if not self.monitor.connect():
            raise RuntimeError(f"could not connect on {args.radar_port}")
        self.monitor.start(shot_callback=self._on_shot)
        print(f"Speed radar ready on {args.radar_port} (rolling-buffer mode)")

    def _on_shot(self, shot):
        now = time.monotonic()
        with self.lock:
            self.shots = [s for s in self.shots if now - s[0] < 120] + [(now, shot)]
        print(f"[{time.strftime('%H:%M:%S')}] Speed radar shot: "
              f"ball {getattr(shot, 'ball_speed_mph', None)} mph, "
              f"club {getattr(shot, 'club_speed_mph', None)} mph, "
              f"spin {getattr(shot, 'spin_rpm', None)} rpm")

    def result_for(self, shot_time, wait_s=35.0):
        """The speed radar's shot that goes with a camera shot, or None.

        Its data arrives a few seconds after impact (up to ~20 s when the TI
        radar is sending its capture at the same time), so this waits."""
        deadline = time.monotonic() + wait_s
        while True:
            with self.lock:
                near = [s for s in self.shots if shot_time - 1.0 <= s[0] <= shot_time + 30.0]
            if near:
                shot = min(near, key=lambda s: abs(s[0] - shot_time))[1]
                return {"ball_speed": getattr(shot, "ball_speed_mph", None),
                        "club_speed": getattr(shot, "club_speed_mph", None),
                        "spin": getattr(shot, "spin_rpm", None),
                        "carry": getattr(shot, "estimated_carry_yards", None)}
            if time.monotonic() > deadline:
                return None
            time.sleep(0.1)

    def stop(self):
        for step in (self.monitor.stop, self.monitor.disconnect):
            try:
                step()
            except Exception as e:
                print(f"Speed radar stop: {e}")
