"""
Bridges between our kiosk and OpenFlight's radar code.

IWRBridge: the TI IWR6843LEVM (launch angle).
OPSBridge: the OPS243-A in rolling-buffer mode (ball speed, club speed, spin).
Both are driven by one shot trigger: the sound detector (OpenFlight's default),
or, with --ops-trigger speed, the OPS243-A's own speed trigger. In speed mode
there is nothing on GPIO17, so each OPS trigger is passed to the TI radar in
software (IWR6843CaptureMonitor.notify_trigger) and to the camera.

The TI radar is processed exactly the way OpenFlight's own app does it: its
capture is handed to OpenFlight's IWR6843Runtime together with the speed
radar's shot (ball speed, club speed, impact time), which guides the search for
the ball. Everything else (camera, screen, shot handling) stays ours.

Needs a copy of OpenFlight at ~/openflight (or wherever --openflight points)
with the custom firmware already flashed onto the radar.
"""

import dataclasses
import logging
import math
import os
import sys
import threading
import time

ANGLE_FIELDS = ("vertical_deg", "launch_angle_deg", "vertical_launch_deg",
                "launch_deg", "elevation_deg")


def _openflight_root(args):
    root = os.path.expanduser(args.openflight)
    src = os.path.join(root, "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    return root


def _summary(m):
    """The small fields of an OpenFlight result (numbers, text, flags), so the
    log shows why a capture was rejected. Big arrays are left out."""
    try:
        fields = dict(vars(m)) if hasattr(m, "__dict__") else {
            f.name: getattr(m, f.name) for f in dataclasses.fields(m)}
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


def _empty(error):
    return {"launch_angle": None, "ball_speed": None, "quality": None, "error": error}


class IWRBridge:
    def __init__(self, args, on_trigger=None, ops=None):
        root = _openflight_root(args)
        from openflight.iwr6843 import Calibration
        from openflight.iwr6843.monitor import IWR6843CaptureMonitor, tx_order_from_config
        from openflight.iwr6843.runtime import IWR6843Runtime

        def path(p):
            return p if os.path.isabs(p) else os.path.join(root, p)

        config = path(args.iwr_config)
        tx_order = tx_order_from_config(config)

        # Same as OpenFlight's server: start from the reference calibration,
        # then apply our mounting geometry.
        cal = Calibration.load(path(args.iwr_cal))
        cal.tee_range_m = args.iwr_tee_m
        cal.tee_ball_height_m = args.iwr_ball_height_m
        cal.tilt_rad = math.radians(args.iwr_tilt_deg)
        cal.meta["radar_height_m"] = args.iwr_radar_height_m

        self.on_trigger = on_trigger
        self.lock = threading.Lock()
        self.events = []   # one per speed-radar shot

        out = os.path.join(args.out, "iwr")
        os.makedirs(out, exist_ok=True)
        # OpenFlight's monitor owns the sound trigger pin (--gate-gpio, GPIO17 by default). We hear about
        # each trigger through the observer below.
        self.monitor = IWR6843CaptureMonitor(
            config_path=config, output_dir=out, port=args.iwr_port, gpio_pin=getattr(args, "gate_gpio", 17),
            save_dumps=args.iwr_save_dumps, trigger_observers=[self._observer])
        self.runtime = IWR6843Runtime(
            capture_monitor=self.monitor, calibration=cal, net_range_m=args.iwr_net_m,
            tx_order=tx_order, capture_timeout_s=25.0, tdm_sign_policy="positive")
        self.monitor.start(armed=True)

        self.has_ops = ops is not None
        if self.has_ops:
            ops.listeners.append(self._on_ops_shot)
            if ops.trigger_type == "speed":
                ops.trigger_listeners.append(self._software_trigger)
                print(f"TI radar ready on {args.iwr_port} (triggered by the speed radar, "
                      f"guided by its shot data)")
            else:
                print(f"TI radar ready on {args.iwr_port} (sound trigger on GPIO{getattr(args, 'gate_gpio', 17)}, "
                      f"guided by the speed radar)")
        else:
            print(f"TI radar ready on {args.iwr_port}, but it needs the speed radar (--ops) "
                  f"to find the ball, so it will not give launch angles")

    def _observer(self, *details):
        print(f"[{time.strftime('%H:%M:%S')}] Sound trigger received; TI radar capturing")
        if self.on_trigger is not None:
            try:
                self.on_trigger()
            except Exception as e:
                print(f"Trigger handler error: {e}")

    def _software_trigger(self):
        """The speed radar saw a shot: start the TI capture as a GPIO edge would."""
        try:
            self.monitor.notify_trigger()
        except Exception as e:
            print(f"TI software trigger error: {type(e).__name__}: {e}")
        print(f"[{time.strftime('%H:%M:%S')}] Speed trigger; TI radar capturing")
        if self.on_trigger is not None:
            try:
                self.on_trigger()     # the camera (ignored if it already triggered itself)
            except Exception as e:
                print(f"Trigger handler error: {e}")

    def _on_ops_shot(self, shot, arrival):
        event = {"t": arrival, "done": threading.Event(), "result": None}
        with self.lock:
            self.events = [e for e in self.events if arrival - e["t"] < 120] + [event]
        threading.Thread(target=self._process, args=(shot, event), daemon=True).start()

    def _process(self, shot, event):
        """Run OpenFlight's TI estimator for one speed-radar shot."""
        result = _empty(None)
        try:
            club = getattr(shot, "club", None)
            club = getattr(club, "value", club)
            r = self.runtime.process_shot(
                impact_timestamp=getattr(shot, "impact_timestamp", None),
                ball_speed_mph=shot.ball_speed_mph,
                club=club,
                club_speed_mph=getattr(shot, "club_speed_mph", None))
            m = r.measurement
            if r.capture is None:
                result["error"] = "no TI capture for this shot"
            elif not getattr(r.capture, "valid", True):
                result["error"] = getattr(r.capture, "error", None) or "invalid TI capture"
            elif m is None:
                result["error"] = "TI estimator returned nothing"
            else:
                info = _summary(m)
                print(f"[{time.strftime('%H:%M:%S')}] TI radar details: {info}")
                status = str(info.get("status", "") or "")
                result["quality"] = info.get("quality") or status or None
                angle = next((info[f] for f in ANGLE_FIELDS
                              if isinstance(info.get(f), (int, float))), None)
                if angle is not None and "reject" not in status:
                    result["launch_angle"] = angle
                else:
                    result["error"] = status or "no ball in the radar data"
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {e}"
        event["result"] = result
        event["done"].set()

    def result_for(self, shot_time, wait_s=45.0):
        """The TI result for the speed-radar shot that goes with a camera shot."""
        if not self.has_ops:
            return _empty("TI radar needs the speed radar (--ops)")
        deadline = time.monotonic() + wait_s
        while True:
            with self.lock:
                near = [e for e in self.events if shot_time - 1.0 <= e["t"] <= shot_time + 30.0]
            if near:
                event = min(near, key=lambda e: abs(e["t"] - shot_time))
                if event["done"].wait(max(0.0, deadline - time.monotonic())):
                    return event["result"]
                return _empty("TI result timed out")
            if time.monotonic() > deadline:
                return _empty("no speed-radar shot to guide the TI radar")
            time.sleep(0.1)

    def stop(self):
        for step in (getattr(self.runtime, "stop", None), self.monitor.stop):
            try:
                if step is not None:
                    step()
            except Exception as e:
                print(f"TI radar stop: {e}")


def _force_ops_power(level):
    """Make OpenFlight use our OPS243-A transmit power instead of its fixed
    level 3. Level 0 is the strongest; higher numbers are weaker. OpenFlight
    turns the power down to stop overload when the ball is close; with the ball
    about 5 ft away more power gives a stronger echo."""
    import inspect
    from openflight import ops243
    patched = 0
    for _, cls in inspect.getmembers(ops243, inspect.isclass):
        original = cls.__dict__.get("set_transmit_power")
        if original is None or getattr(original, "_modus", False):
            continue

        def forced(self, _level, _orig=original):
            return _orig(self, level)
        forced._modus = True
        cls.set_transmit_power = forced
        patched += 1
    if patched:
        print(f"Speed radar transmit power: level {level} (0 = strongest, OpenFlight uses 3)")
    else:
        print("Speed radar transmit power could not be changed; using OpenFlight's")


class _SpeedTriggerTap(logging.Handler):
    """OpenFlight's speed trigger has no callback; it logs "[TRIGGER] Speed
    trigger: ..." the moment it fires. This turns that log line into a call."""

    def __init__(self, callback):
        super().__init__(level=logging.INFO)
        self.callback = callback

    def emit(self, record):
        if str(record.msg).startswith("[TRIGGER] Speed trigger:"):
            try:
                self.callback()
            except Exception as e:
                print(f"Speed trigger tap error: {e}")


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

        power = getattr(args, "ops_power", None)
        if power is not None:
            _force_ops_power(int(power))

        self.lock = threading.Lock()
        self.shots = []      # (arrival time, Shot)
        self.listeners = []  # called with (shot, arrival time) for every shot
        self.trigger_listeners = []   # speed mode: called the moment the OPS triggers
        self.trigger_type = getattr(args, "ops_trigger", "sound")
        if self.trigger_type == "speed":
            root = logging.getLogger()
            if root.level > logging.INFO:
                root.setLevel(logging.INFO)
            self._tap = _SpeedTriggerTap(self._on_trigger)
            root.addHandler(self._tap)
        self.monitor = RollingBufferMonitor(port=args.radar_port, trigger_type=self.trigger_type,
                                            sample_rate_ksps=args.ops_ksps)
        if not self.monitor.connect():
            raise RuntimeError(f"could not connect on {args.radar_port}")
        self.monitor.start(shot_callback=self._on_shot)
        print(f"Speed radar ready on {args.radar_port} (rolling-buffer mode, {self.trigger_type} trigger)")

    def _on_trigger(self):
        for listener in list(self.trigger_listeners):
            listener()

    def _on_shot(self, shot):
        now = time.monotonic()
        with self.lock:
            self.shots = [s for s in self.shots if now - s[0] < 120] + [(now, shot)]
        print(f"[{time.strftime('%H:%M:%S')}] Speed radar shot: "
              f"ball {getattr(shot, 'ball_speed_mph', None)} mph, "
              f"club {getattr(shot, 'club_speed_mph', None)} mph, "
              f"spin {getattr(shot, 'spin_rpm', None)} rpm")
        for listener in list(self.listeners):
            try:
                listener(shot, now)
            except Exception as e:
                print(f"Speed radar listener error: {e}")

    def result_for(self, shot_time, wait_s=35.0):
        """The speed radar's shot that goes with a camera shot, or None.

        Its data arrives a few seconds after impact, so this waits."""
        deadline = time.monotonic() + wait_s
        while True:
            with self.lock:
                near = [s for s in self.shots if shot_time - 1.0 <= s[0] <= shot_time + 30.0]
            if near:
                shot = min(near, key=lambda s: abs(s[0] - shot_time))[1]
                return {"ball_speed": getattr(shot, "ball_speed_mph", None),
                        "club_speed": getattr(shot, "club_speed_mph", None),
                        "spin": getattr(shot, "spin_rpm", None),
                        "carry": getattr(shot, "estimated_carry_yards", None),
                        "shot": shot}
            if time.monotonic() > deadline:
                return None
            time.sleep(0.1)

    def stop(self):
        for step in (self.monitor.stop, self.monitor.disconnect):
            try:
                step()
            except Exception as e:
                print(f"Speed radar stop: {e}")
