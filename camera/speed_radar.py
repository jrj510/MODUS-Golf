"""MODUS Golf: the speed radar as the kiosk sees it.

Runs the OPS243-A on our own driver (ops243.py) and decides shots together
with the camera (shot_fusion.py). Gives the kiosk the calls it uses:

    result_for(trigger_time, wait_s) -> {"ball_speed", "club_speed", ...} or None
    outcome(t)                       -> None (not decided yet), ("ball", d) or ("none", d)
    camera_fired(t, source)          -> tell it the camera triggered at t
    stop()

Both sensors trigger on their own:
  * camera trigger + radar shot        -> confirmed: the radar's numbers go with
                                          the camera's capture
  * radar shot, camera never triggered -> if the ball is still on its spot,
                                          rejected; otherwise the camera is told
                                          to capture (trigger_camera) so the shot
                                          still gets frames, launch angle, replay
  * camera trigger, no radar shot      -> a shot with no speeds (or, with
                                          --radar-confirm on, the kiosk calls
                                          it no shot)
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from ops243 import OPS243, DetectorConfig, ShotDetector
from shot_fusion import FusedShot, FusionConfig, ShotFusion

MATCH_S = 0.02   # a stored result belongs to a trigger time within this
NEAR_S = 0.5     # ...or, failing that, the radar shot nearest it within this
                 # (the camera triggered late, after the radar had asked it to)


class SpeedRadar:
    reports_no_ball = True    # it answers "nothing flew away" too (for --radar-confirm)

    def __init__(self, args,
                 trigger_camera: Callable[[float], None],
                 ball_present: Callable[[], Optional[bool]] = lambda: None,
                 radar: Optional[OPS243] = None):
        self.trigger_camera = trigger_camera
        self.cond = threading.Condition()
        self.results: list[tuple[float, Optional[dict], FusedShot]] = []  # (trigger time, numbers, shot)
        self.listeners: list[Callable] = []
        self.trigger_listeners: list[Callable] = []
        # Camera-only shots are always passed on; with --radar-confirm on the
        # kiosk turns them down itself (outcome() answers "none").
        self.fusion = ShotFusion(self._on_shot, ball_present=ball_present,
                                 cfg=FusionConfig(camera_only="keep"),
                                 on_reject=lambda why: print(f"[{time.strftime('%H:%M:%S')}] "
                                                             f"Speed radar: not a shot ({why})"))
        self.detector = ShotDetector(self.fusion.radar_shot,
                                     DetectorConfig(min_ball_mph=getattr(args, "ops_min_ball", 40.0)))
        self._last_report = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()

        self.radar = radar or OPS243(args.radar_port, getattr(args, "ops_baud", 57600))
        print("Speed radar: sending the golf settings (AN-029)")
        self.radar.configure()
        self.radar.start(self._on_report)
        threading.Thread(target=self._tick, daemon=True).start()

    # ---- radar side -------------------------------------------------------
    def _on_report(self, rep, line) -> None:
        with self._lock:
            self._last_report = rep.t
            self.detector.feed(rep)

    def _tick(self) -> None:
        """Every 20 ms: finish a shot once the radar goes quiet, settle timeouts."""
        while not self._stop.wait(0.02):
            with self._lock:
                if self.detector.pending is not None and time.monotonic() - self._last_report > 0.1:
                    self.detector.flush()
            self.fusion.poll()

    # ---- camera side ------------------------------------------------------
    def camera_fired(self, t: float, source: str) -> None:
        if source != "radar":       # our own request coming back
            self.fusion.camera_trigger(t, source)

    def pulsed(self, t: float) -> None:
        """Kept for the kiosk's trigger-out pulse; this radar doesn't need it."""

    # ---- decisions ---------------------------------------------------------
    def _on_shot(self, fs: FusedShot) -> None:
        nums = None
        if fs.ball_mph is not None:
            nums = {"ball_speed": fs.ball_mph, "club_speed": fs.club_mph,
                    "club_speed_how": "ops243 club peak" if fs.club_mph is not None else None,
                    "smash": fs.smash, "source": fs.source}
        t = fs.camera_t
        if fs.source == "radar_only":
            t = fs.t_impact + self.fusion.cfg.cam_delay_est_s   # where a camera trigger would be
        stamp = time.strftime('%H:%M:%S')
        speeds = (f"ball {fs.ball_mph:.1f} mph" + (f", club {fs.club_mph:.1f} mph" if fs.club_mph else "")
                  if fs.ball_mph is not None else "no speeds")
        print(f"[{stamp}] Shot ({fs.source.replace('_', ' ')}): {speeds}"
              + (f"; {'; '.join(fs.notes)}" if fs.notes else ""))
        with self.cond:
            self.results = [r for r in self.results if r[0] > t - 60] + [(t, nums, fs)]
            self.cond.notify_all()
        if fs.source == "radar_only":
            try:
                self.trigger_camera(t)
            except Exception as e:
                print(f"Speed radar: could not start a camera capture ({type(e).__name__}: {e})")
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
        self._stop.set()
        self.fusion.stop()
        try:
            self.radar.close()
        except Exception:
            pass
