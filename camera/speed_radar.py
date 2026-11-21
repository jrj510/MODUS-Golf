"""MODUS Golf: the speed radar as the kiosk sees it.

Runs the OPS243-A in rolling-buffer mode (ops_capture.py: the radar records
raw I/Q nonstop; on a trigger we read its recording and work out the speeds
with our own FFT) and decides shots together with the camera
(shot_fusion.py). Gives the kiosk the calls it uses:

    result_for(trigger_time, wait_s) -> {"ball_speed", "club_speed", ...} or None
    outcome(t)                       -> None (not decided yet), ("ball", d) or ("none", d)
    camera_fired(t, source)          -> tell it the camera triggered at t
    stop()

When the radar's own speed trigger fires it says so at once
({"trigger_velocity_detected": ...}), ~2 s before its recording has come
over. If the camera is Ready, that notice starts a camera capture right away
(start_capture), so the shot keeps its frames of the ball leaving (launch
angle, replay) even when the camera's own trigger misses it. Its numbers are
then filed under that capture's time.

What starts a radar recording:
  * the radar's own speed trigger (something moving away faster than
    --ops-speed-trigger-mph: the club coming through), so it needs nothing else
  * the camera's pulse on J3 pin 3 (--trigger-out-gpio), or, without that
    wire, an S! over the serial line when the camera triggers

Then:
  * camera trigger + radar shot        -> confirmed: the radar's numbers go with
                                          the camera's capture
  * radar shot, camera never triggered -> if the ball is still on its spot,
                                          rejected; otherwise a shot with the
                                          radar's numbers (the camera's frames
                                          from back then are gone by the time
                                          the radar's recording has come over)
  * camera trigger, no radar shot      -> a shot with no speeds (or, with
                                          --radar-confirm on, the kiosk calls
                                          it no shot)
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from ops243 import DetectorConfig
from ops_capture import Capture, CaptureConfig, RollingBufferRadar, find_shot
from shot_fusion import FusedShot, FusionConfig, ShotFusion

MATCH_S = 0.02   # a stored result belongs to a trigger time within this
NEAR_S = 0.5     # ...or, failing that, the radar shot nearest it within this


class SpeedRadar:
    reports_no_ball = True    # it answers "nothing flew away" too (for --radar-confirm)

    def __init__(self, args,
                 trigger_camera: Callable[[float], None],
                 ball_present: Callable[[], Optional[bool]] = lambda: None,
                 radar: Optional[RollingBufferRadar] = None,
                 start_capture: Optional[Callable[[float], bool]] = None):
        self.trigger_camera = trigger_camera
        self.start_capture = start_capture    # (t) -> True if a camera capture started at t
        self.notice_t: Optional[float] = None  # Pi time of the last capture a notice started
        self.cond = threading.Condition()
        self.results: list[tuple[float, Optional[dict], FusedShot]] = []  # (trigger time, numbers, shot)
        self.listeners: list[Callable] = []
        self.trigger_listeners: list[Callable] = []
        self.hw_pulse = bool(getattr(args, "trigger_out_gpio", 0))
        self.dcfg = DetectorConfig(min_ball_mph=getattr(args, "ops_min_ball", 30.0))
        self.last_capture: Optional[Capture] = None
        # Camera-only shots are always passed on; with --radar-confirm on the
        # kiosk turns them down itself (outcome() answers "none").
        self.fusion = ShotFusion(self._on_shot, ball_present=ball_present,
                                 cfg=FusionConfig(camera_only="keep"),
                                 on_reject=lambda why: print(f"[{time.strftime('%H:%M:%S')}] "
                                                             f"Speed radar: not a shot ({why})"))
        self.fusion.start()
        if radar is None:
            trig = getattr(args, "ops_speed_trigger_mph", 40.0)
            cfg = CaptureConfig(split=getattr(args, "ops_split", 10),
                                speed_trigger_mph=trig if trig and trig > 0 else None)
            print(f"Speed radar: rolling buffer on {args.radar_port} "
                  f"({cfg.split} of 32 blocks before the trigger; speed trigger "
                  + (f"{cfg.speed_trigger_mph:g} mph" if cfg.speed_trigger_mph else "off") + ")")
            radar = RollingBufferRadar(args.radar_port, cfg,
                                       reset_gpio=getattr(args, "ops_reset_gpio", 23))
            radar.setup()
        self.radar = radar
        self.radar.start(self._on_capture, self._on_notice)

    # ---- radar side -------------------------------------------------------
    def _on_notice(self, t: float) -> None:
        """The radar's speed trigger fired (club or ball moving away fast)."""
        if self.start_capture is None:
            return
        try:
            started = bool(self.start_capture(t))
        except Exception as e:
            print(f"Speed radar: could not start a capture ({type(e).__name__}: {e})")
            started = False
        if started:
            self.notice_t = t
            print(f"[{time.strftime('%H:%M:%S')}] Speed radar triggered: camera capture started")

    def _notice_for(self, t0: float, t1: float) -> Optional[float]:
        """The capture a notice started for a recording from t0 to t1 (Pi clock)."""
        n = self.notice_t
        if n is not None and t0 - 0.05 <= n <= t1 + 0.3:
            return n
        return None

    def _file(self, t: float, nums: Optional[dict], fs: FusedShot) -> None:
        with self.cond:
            self.results = [r for r in self.results if r[0] > t - 60] + [(t, nums, fs)]
            self.cond.notify_all()

    def _on_capture(self, cap: Capture) -> None:
        self.last_capture = cap
        took = time.monotonic() - cap.received
        shot, reports = find_shot(cap, dcfg=DetectorConfig(min_ball_mph=self.dcfg.min_ball_mph))
        t0 = cap.pi_time(cap.sample_time)
        t1 = cap.pi_time(cap.sample_time + cap.duration)
        stamp = time.strftime('%H:%M:%S')
        if shot is None:
            fastest = max((r.speeds[0] for r in reports), default=0.0)
            print(f"[{stamp}] Speed radar: recording read ({took:.1f} s), no ball in it"
                  + (f" (fastest {fastest:.0f} mph)" if fastest else ""))
            n = self._notice_for(t0, t1)
            if n is not None:          # the capture it started: no radar numbers for it
                self.notice_t = None
                self._file(n, None, FusedShot("camera_only", n, camera_t=n, camera_source="radar",
                                              notes=["radar recording had no ball"]))
            self.fusion.radar_nothing(t0, t1)
            return
        print(f"[{stamp}] Speed radar: recording read ({took:.1f} s): ball {shot.ball_mph:.1f} mph"
              + (f", club {shot.club_mph:.1f} mph" if shot.club_mph else ""))
        self.fusion.radar_shot(shot)

    # ---- camera side ------------------------------------------------------
    def camera_fired(self, t: float, source: str) -> None:
        if source == "radar":       # our own request coming back
            return
        self.fusion.camera_trigger(t, source)
        if not self.hw_pulse:
            self.radar.trigger()    # no pulse wire: trigger it over the serial line

    def pulsed(self, t: float) -> None:
        """The kiosk's pulse on J3 pin 3 went out; the radar triggers on it itself."""

    # ---- decisions ---------------------------------------------------------
    def _on_shot(self, fs: FusedShot) -> None:
        nums = None
        if fs.ball_mph is not None:
            nums = {"ball_speed": fs.ball_mph, "club_speed": fs.club_mph,
                    "club_speed_how": "rolling buffer, club peak" if fs.club_mph is not None else None,
                    "smash": fs.smash, "source": fs.source}
        t = fs.camera_t
        notice = None
        if fs.source == "radar_only":
            notice = self._notice_for(fs.t_impact - 0.25, fs.t_impact)
            if notice is not None:      # the camera is already capturing this shot
                t, self.notice_t = notice, None
            else:
                t = fs.t_impact + self.fusion.cfg.cam_delay_est_s   # where a camera trigger would be
        speeds = (f"ball {fs.ball_mph:.1f} mph" + (f", club {fs.club_mph:.1f} mph" if fs.club_mph else "")
                  if fs.ball_mph is not None else "no speeds")
        print(f"[{time.strftime('%H:%M:%S')}] Shot ({fs.source.replace('_', ' ')}): {speeds}"
              + (f"; {'; '.join(fs.notes)}" if fs.notes else ""))
        self._file(t, nums, fs)
        if fs.source == "radar_only" and notice is None:
            try:
                self.trigger_camera(t)      # a shot on screen with the radar's numbers
            except Exception as e:
                print(f"Speed radar: could not start a shot ({type(e).__name__}: {e})")
        for fn in list(self.listeners):
            try:
                fn(fs, time.monotonic())
            except Exception as e:
                print(f"Speed radar listener: {type(e).__name__}: {e}")

    def _find(self, t: float):
        for rt, nums, fs in reversed(self.results):
            if abs(rt - t) <= MATCH_S:
                return nums, fs
        near = [(abs(rt - t), nums, fs) for rt, nums, fs in self.results
                if nums is not None and abs(rt - t) <= NEAR_S]
        if near:
            _, nums, fs = min(near, key=lambda x: x[0])
            return nums, fs
        return None

    def result_for(self, trigger_time: float, wait_s: float = 12.0) -> Optional[dict]:
        """The radar's numbers for the capture at trigger_time (None if it had none)."""
        end = time.monotonic() + wait_s
        with self.cond:
            while True:
                hit = self._find(trigger_time)
                if hit is not None:
                    return hit[0]
                left = end - time.monotonic()
                if left <= 0:
                    return None
                self.cond.wait(min(left, 0.1))

    def outcome(self, t: float):
        """For the radar check: None until decided, then ("ball", d) or ("none", d)."""
        with self.cond:
            hit = self._find(t)
        if hit is None:
            return None
        nums, fs = hit
        if nums is None:
            return ("none", {"reason": "no_radar_shot", "peak_mph": None})
        return ("ball", {"ball_mph": nums["ball_speed"]})

    def stop(self) -> None:
        self.fusion.stop()
        try:
            self.radar.close()
        except Exception:
            pass
