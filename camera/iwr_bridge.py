"""
Bridge between our kiosk and OpenFlight's IWR6843 code.

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


class IWRBridge:
    def __init__(self, args, on_trigger=None):
        root = os.path.expanduser(args.openflight)
        src = os.path.join(root, "src")
        if src not in sys.path:
            sys.path.insert(0, src)
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
