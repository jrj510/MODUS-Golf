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

The TI board must sit the way OpenFlight's enclosure holds it: turned so the
TX antennas are ABOVE the RX antennas (the 8-element elevation array upright).
Its mounting geometry (tee and net distance, tilt, antenna and ball height,
azimuth) comes from start_kiosk.sh and must be measured, not guessed: a wrong
value biases every launch angle without raising an error.
"""

import dataclasses
import inspect
import logging
import math
import os
import sys
import threading
import time

# Our club names (start menu, ballflight.py) -> OpenFlight's ClubType values.
# OpenFlight needs the real club: the TI ball tracker ignores anything slower
# than that club class's slowest real ball (radial: wedge 26.5 m/s, 9-6 iron
# 34, 5 iron and longer 40, driver and woods 50), and the OPS processing
# handles wedges and their spin differently. Left alone, both radars assume a
# driver, so wedge and short-iron balls were thrown out by the TI tracker.
OPENFLIGHT_CLUBS = {
    "driver": "driver", "3w": "3-wood", "5w": "5-wood", "hybrid": "3-hybrid",
    "4i": "4-iron", "5i": "5-iron", "6i": "6-iron", "7i": "7-iron", "8i": "8-iron",
    "9i": "9-iron", "pw": "pw", "gw": "gw", "sw": "sw", "lw": "lw",
}


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
    return {"launch_angle": None, "launch_dir": None, "ball_speed": None,
            "quality": None, "error": error}


def openflight_club_name(name):
    """OpenFlight's club name for one of ours ('52' -> 'gw', '7i' -> '7-iron')."""
    from ballflight import club_defaults
    return OPENFLIGHT_CLUBS.get(club_defaults(name)[2], "unknown")


def openflight_club(name):
    """OpenFlight's ClubType for one of our club names, or None if this copy of
    OpenFlight doesn't have one that matches (then nothing is set)."""
    try:
        from openflight.clubs import ClubType
    except ImportError:
        try:                                  # older OpenFlight layouts
            from openflight.launch_monitor import ClubType
        except ImportError:
            return None
    try:
        return ClubType(openflight_club_name(name))
    except ValueError:
        return None


def _number(v):
    """v as a finite float, or None."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def read_measurement(m):
    """Launch angle, launch direction and status from OpenFlight's TI result.

    Current OpenFlight returns an LCMFResult: the launch angle is in
    ``angle_deg``, and ``accepted`` says whether it passed OpenFlight's quality
    gates (status "accepted" or "accepted_low_confidence_recovery"). This is
    exactly what OpenFlight's own server reads. Older builds returned a
    ShotMeasurement, with a ``launch_angle_deg`` property and a ``quality`` of
    ok / low / reject; that shape is handled too. A result that was not
    accepted gives no angle, and its status becomes the error.

    Launch direction is ``horizontal_deg``: TrackMan convention, positive =
    starting right of the target line, already including the azimuth offset.
    """
    status = str(getattr(m, "status", None) or getattr(m, "quality", None) or "")
    angle = _number(getattr(m, "angle_deg", None))
    if angle is None:
        angle = _number(getattr(m, "launch_angle_deg", None))
    accepted = getattr(m, "accepted", None)
    if accepted is None:
        accepted = angle is not None and "reject" not in status
    out = {"launch_angle": None, "launch_dir": None, "quality": status or None, "error": None}
    if accepted and angle is not None:
        out["launch_angle"] = angle
        out["launch_dir"] = _number(getattr(m, "horizontal_deg", None))
    else:
        out["error"] = status or "no ball in the radar data"
    return out


def spin_trusted(shot):
    """Whether OpenFlight trusts this shot's measured spin enough to show it.

    OpenFlight reports every spin it computes, but marks how far to trust it:
    a reading stuck at either end of its search range found nothing real, and
    one with a confidence below SPIN_CONFIDENCE_RELIABLE (0.6) is diagnostic
    only (OpenFlight's own carry then uses the club's typical spin instead).
    Its "ungated multitaper" spin is always below that level. Older copies of
    OpenFlight without these marks: only readings at the ends of the old search
    range (about 1,500 and 11,000 rpm) are left out."""
    spin = getattr(shot, "spin_rpm", None)
    if spin is None:
        return False
    if getattr(shot, "spin_at_lower_rail", False) or getattr(shot, "spin_at_upper_rail", False):
        return False
    confidence = getattr(shot, "spin_confidence", None)
    if confidence is not None:
        try:
            from openflight.launch_monitor import SPIN_CONFIDENCE_RELIABLE as reliable
        except Exception:
            reliable = 0.6
        try:
            return float(confidence) >= reliable
        except (TypeError, ValueError):
            return False
    try:
        return 1600.0 < float(spin) < 10900.0
    except (TypeError, ValueError):
        return False


def ops_speed_corrector(args):
    """OpenFlight's ball-speed cosine correction for our geometry, or None.

    The OPS243 reads the ball's speed along its line of sight. The ball leaves
    upward at the launch angle while the radar sits low behind it, so the
    reading is short of the true speed (OpenFlight measured about 2 mph on
    average against TrackMan). OpenFlight's server corrects it whenever an angle
    radar is in use, using the TI geometry for both radars; on this faceplate
    the two antennas sit side by side, so that holds here too.

    Returns f(measured_mph, launch_deg) -> corrected mph.
    """
    try:
        _openflight_root(args)
        from openflight.speed_correction import correct_ball_speed
    except Exception as e:
        print(f"Ball-speed correction not available ({type(e).__name__}: {e})")
        return None
    distance_ft = args.iwr_tee_m * 3.28084
    above_ft = (args.iwr_ball_height_m - args.iwr_radar_height_m) * 3.28084

    def correct(measured_mph, launch_deg):
        return correct_ball_speed(measured_mph, launch_deg, distance_ft, above_ft)
    return correct


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
        # then apply our mounting geometry. Tilt is the antenna face leaning
        # back from vertical (boresight pointing up), positive = up. Heights are
        # both from the same floor/ground surface.
        cal = Calibration.load(path(args.iwr_cal))
        cal.tee_range_m = args.iwr_tee_m
        cal.tee_ball_height_m = args.iwr_ball_height_m
        cal.tilt_rad = math.radians(args.iwr_tilt_deg)
        cal.meta["radar_height_m"] = args.iwr_radar_height_m

        self.on_trigger = on_trigger
        self.lock = threading.Lock()
        self.events = []   # one per speed-radar shot
        self.club = openflight_club_name(getattr(args, "club", None))

        out = os.path.join(args.out, "iwr")
        os.makedirs(out, exist_ok=True)
        # OpenFlight's monitor owns the sound-trigger GPIO. We hear about each
        # trigger through the observer below.
        gpio = getattr(args, "gate_gpio", 17)
        self.monitor = IWR6843CaptureMonitor(
            config_path=config, output_dir=out, port=args.iwr_port, gpio_pin=gpio,
            save_dumps=args.iwr_save_dumps, trigger_observers=[self._observer])
        extra = {}
        azimuth = getattr(args, "iwr_azimuth_offset_deg", 0.0) or 0.0
        if azimuth:
            # Positive = the radar points right of the target line.
            extra["azimuth_offset_deg"] = azimuth
        self.runtime = IWR6843Runtime(
            capture_monitor=self.monitor, calibration=cal, net_range_m=args.iwr_net_m,
            tx_order=tx_order, capture_timeout_s=25.0, tdm_sign_policy="positive", **extra)
        self.monitor.start(armed=True)

        print(f"TI geometry: tee {args.iwr_tee_m} m, net {args.iwr_net_m} m, "
              f"tilt {args.iwr_tilt_deg} deg up, antenna height {args.iwr_radar_height_m} m, "
              f"ball height {args.iwr_ball_height_m} m, azimuth {azimuth} deg, "
              f"club {self.club}, {tx_order} TX order")
        self.has_ops = ops is not None
        if self.has_ops:
            ops.listeners.append(self._on_ops_shot)
            if ops.trigger_type == "speed":
                ops.trigger_listeners.append(self._software_trigger)
                print(f"TI radar ready on {args.iwr_port} (triggered by the speed radar, "
                      f"guided by its shot data)")
            else:
                print(f"TI radar ready on {args.iwr_port} (sound trigger on GPIO{gpio}, "
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
            # The speed radar's shot carries the club we set on it; fall back
            # to the start-menu club if it doesn't.
            club = getattr(shot, "club", None)
            club = getattr(club, "value", club) or self.club
            # Raw (uncorrected) OPS speed, exactly as OpenFlight's server
            # passes it: the TI tracker works in radial speed.
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
                print(f"[{time.strftime('%H:%M:%S')}] TI radar details: {_summary(m)}")
                result.update(read_measurement(m))
                if result["launch_angle"] is not None:
                    dir_text = ("" if result["launch_dir"] is None
                                else f", direction {result['launch_dir']:+.1f} deg")
                    print(f"[{time.strftime('%H:%M:%S')}] TI launch angle "
                          f"{result['launch_angle']:.1f} deg{dir_text} ({result['quality']})")
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {e}"
        event["result"] = result
        event["done"].set()

    def set_club(self, name):
        """Club changed from the kiosk's Club button (used for the next shots)."""
        self.club = openflight_club_name(name)

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

    It also keeps track of the camera's trigger pulses (pulsed / outcome), so
    the kiosk can ask, for each camera trigger, whether the radar saw a ball
    fly away. While the radar is reading out its recording after a pulse it
    can't record another one: outcome() says so too.
    """

    BUSY_S = 10.0   # a pulse still unanswered after this long is given up on
    NOTHING_FLEW = ("no_outbound_speed", "shot_validation_failed", "no_ball_speed")

    def __init__(self, args):
        _openflight_root(args)
        from openflight.rolling_buffer import RollingBufferMonitor

        self.lock = threading.Lock()
        self.shots = []      # (arrival time, Shot)
        self.answers = []    # (arrival time, "ball" or "none", details): the radar's verdict on a trigger
        self.pulses = {}     # camera trigger time -> True if the radar was free to record it
        self.waiting = None  # time of the camera pulse the radar is still working on
        self.reports_no_ball = False   # does this OpenFlight copy say when nothing flew away?
        self.listeners = []  # called with (shot, arrival time) for every shot
        self.trigger_listeners = []   # speed mode: called the moment the OPS triggers
        self.trigger_type = getattr(args, "ops_trigger", "sound")
        if self.trigger_type == "speed":
            root = logging.getLogger()
            if root.level > logging.INFO:
                root.setLevel(logging.INFO)
            root.addHandler(_SpeedTriggerTap(self._on_trigger))
        # How much of the radar's 136 ms buffer (32 blocks of ~4.3 ms) comes from
        # before the trigger. OpenFlight's default suits a sound trigger, which
        # fires at impact. The camera triggers later (it waits 4 frames to be
        # sure the ball has gone), so more of the buffer has to come from before
        # the trigger, or the club coming in is already gone and there is no
        # club speed. Set again by OpenFlight on every re-arm.
        kw = {}
        pre = getattr(args, "ops_pre_trigger", None)
        if pre is not None and self.trigger_type == "sound":
            kw["pre_trigger_segments"] = max(0, min(32, int(pre)))
        try:
            self.monitor = RollingBufferMonitor(port=args.radar_port, trigger_type=self.trigger_type,
                                                sample_rate_ksps=args.ops_ksps, **kw)
        except TypeError:
            if not kw:
                raise
            print("This OpenFlight copy can't set the speed radar's pre-trigger window; "
                  "using its default")
            kw = {}
            self.monitor = RollingBufferMonitor(port=args.radar_port, trigger_type=self.trigger_type,
                                                sample_rate_ksps=args.ops_ksps)
        segs = getattr(getattr(self.monitor, "trigger", None), "pre_trigger_segments", None)
        if not self.monitor.connect():
            raise RuntimeError(f"could not connect on {args.radar_port}")
        if self.trigger_type == "speed":
            # OpenFlight's 20 mph default fires on anything moving away from the
            # radar (people, the net, a fan), so a shot started the moment a
            # ball was set down. Only something this fast counts as a shot.
            mph = getattr(args, "ops_trigger_mph", None)
            trig = getattr(self.monitor, "trigger", None)
            if mph and hasattr(trig, "min_trigger_speed_mph"):
                trig.min_trigger_speed_mph = float(mph)
            if trig is not None and hasattr(trig, "min_trigger_speed_mph"):
                print(f"Speed trigger fires at {trig.min_trigger_speed_mph:.0f} mph outbound or faster")
        # Without this OpenFlight assumes a driver for every shot. Its shots
        # also carry this club to the TI radar (see OPENFLIGHT_CLUBS).
        self.club = openflight_club(getattr(args, "club", None))
        if self.club is not None and hasattr(self.monitor, "set_club"):
            self.monitor.set_club(self.club)
            club_text = f"club {self.club.value}"
        else:
            club_text = "club NOT set: this OpenFlight copy has no matching club setting"
        # OpenFlight reports every trigger it has finished with (diagnostic
        # callback), not only shots: accepted=False means nothing usable flew
        # away. Copies without that callback only report shots.
        try:
            params = inspect.signature(self.monitor.start).parameters
            self.reports_no_ball = "diagnostic_callback" in params
        except (TypeError, ValueError):
            self.reports_no_ball = False
        if self.reports_no_ball:
            self.monitor.start(shot_callback=self._on_shot, diagnostic_callback=self._on_trigger_report)
        else:
            self.monitor.start(shot_callback=self._on_shot)
        window = (f", keeps {segs} of 32 blocks ({segs * 4096 / 32 / (args.ops_ksps * 1000) * 1000:.0f} ms) "
                  f"from before the trigger" if isinstance(segs, int) and self.trigger_type == "sound" else "")
        print(f"Speed radar ready on {args.radar_port} (rolling-buffer mode, "
              f"{self.trigger_type} trigger, {club_text}{window})")

    def _on_trigger(self):
        for listener in list(self.trigger_listeners):
            listener()

    def _answer(self, now, kind, details):
        """Record the radar's verdict on the trigger it was working on (lock held)."""
        self.answers = [a for a in self.answers if now - a[0] < 120] + [(now, kind, details)]
        self.waiting = None

    def _on_trigger_report(self, report):
        """OpenFlight's report on one trigger. accepted=False: nothing usable
        flew away (no ball, or the recording couldn't be processed). Shots
        arrive through _on_shot, so accepted reports are left to that."""
        try:
            if not isinstance(report, dict) or report.get("accepted", True):
                return
            details = {"reason": str(report.get("reason") or ""),
                       "peak_mph": report.get("peak_outbound_mph")}
            # Only these mean "looked, and nothing flew away fast enough". A
            # recording that couldn't be read or processed says nothing either way.
            kind = "none" if details["reason"] in self.NOTHING_FLEW else "error"
            with self.lock:
                self._answer(time.monotonic(), kind, details)
        except Exception as e:
            print(f"Speed radar trigger report error: {e}")

    def pulsed(self, t):
        """The camera has just sent its trigger pulse for its trigger at time t
        (time.monotonic()). Called from the camera thread: quick."""
        with self.lock:
            free = self.waiting is None or t - self.waiting > self.BUSY_S
            if free:
                self.waiting = t
            self.pulses = {k: v for k, v in self.pulses.items() if t - k < 120}
            self.pulses[t] = free

    def outcome(self, t):
        """What the radar made of the camera trigger at time t:
          ("ball", details)  it saw a ball fly away (a shot is on its way),
          ("none", details)  nothing flew away (OpenFlight dropped it),
          ("error", details) it couldn't use its recording (can't say either way),
          ("busy", None)     it was still reading out an earlier trigger, so it
                             couldn't record this one,
          ("unknown", None)  no pulse was sent for this trigger,
          None               no answer yet."""
        with self.lock:
            free = self.pulses.get(t)
            if free is None:
                return ("unknown", None)
            if not free:
                return ("busy", None)
            for when, kind, details in self.answers:
                if when >= t:
                    return (kind, details)
        return None

    def _on_shot(self, shot):
        now = time.monotonic()
        with self.lock:
            self.shots = [s for s in self.shots if now - s[0] < 120] + [(now, shot)]
            self._answer(now, "ball", {"ball_mph": getattr(shot, "ball_speed_mph", None)})
        print(f"[{time.strftime('%H:%M:%S')}] Speed radar shot: "
              f"ball {getattr(shot, 'ball_speed_mph', None)} mph, "
              f"club {getattr(shot, 'club_speed_mph', None)} mph, "
              f"spin {getattr(shot, 'spin_rpm', None)} rpm"
              f"{'' if spin_trusted(shot) else ' (spin not trusted by OpenFlight: not shown)'}")
        for listener in list(self.listeners):
            try:
                listener(shot, now)
            except Exception as e:
                print(f"Speed radar listener error: {e}")

    def set_club(self, name):
        """Club changed from the kiosk's Club button: OpenFlight's processing
        handles wedges and their spin differently, so it is told straight away."""
        club = openflight_club(name)
        if club is not None and hasattr(self.monitor, "set_club"):
            self.monitor.set_club(club)
            self.club = club
            return club.value
        return None

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
                        "spin": getattr(shot, "spin_rpm", None) if spin_trusted(shot) else None,
                        "spin_raw": getattr(shot, "spin_rpm", None),
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
