"""MODUS Golf: decide what counts as a shot from the radar AND the camera.

Both sensors trigger on their own:
  * the speed radar (camera/ops_capture.py, rolling buffer) reports a shot
    with a ball speed, club speed and impact time once its recording has
    come over the serial line, ~2 s after impact;
  * the camera (shot_capture.py, sh.on_fire) reports when it sees the ball
    leave its spot, ~40-90 ms after impact.

The camera waits up to cam_wait_s (3 s) for the radar's answer; a radar shot
that arrives with no camera trigger waits radar_wait_s for one. Then:

  radar + camera                -> "confirmed" shot (the normal case)
  radar only, ball still there  -> rejected: the radar saw something fast but
                                   our ball never moved (next bay's shot, a
                                   practice swing that slipped through, noise)
  radar only, ball not watched  -> "radar_only" shot: the camera wasn't Ready
                                   (lost the ball, sun, etc.), so trust the radar
  camera only                   -> "camera_only" shot with no speeds (a chip
                                   under the radar's minimum, or the radar
                                   missed it); set camera_only="drop" to ignore

Every shot carries an impact time: the radar's when it has one, otherwise
estimated from the camera's trigger. The kiosk uses that time to pull the
right camera frames for launch angle and the replay.

Hook-up (kiosk):
    fusion = ShotFusion(on_shot=show_shot, ball_present=lambda: <camera Ready and ball still seen>)
    ops243.ShotDetector(fusion.radar_shot)        # radar side
    sh.on_fire = lambda src: fusion.camera_trigger(time.monotonic(), src)
    fusion.start()                                # handles the timeouts
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from ops243 import Shot


@dataclass
class FusionConfig:
    cam_wait_s: float = 3.0       # a camera trigger waits this long for the radar's answer
    radar_wait_s: float = 0.25    # a radar shot waits this long for a camera trigger
    cam_after_min_s: float = -0.25  # a camera trigger this long before the radar's impact time...
    cam_after_max_s: float = 0.40   # ...to this long after it is the same shot. Wide: the two
                                    # clocks and triggers line up less tightly than planned
                                    # (2026-11-22: real pairs missed at 0.2 s), and shots are
                                    # seconds apart, so a wide window can't pair the wrong ones
    cam_delay_est_s: float = 0.06  # impact ~ this long before a camera-only trigger
    camera_only: str = "keep"     # "keep" (shot with no speeds) or "drop"
    cooldown_s: float = 1.5       # ignore both sensors this long after a shot


@dataclass
class FusedShot:
    source: str                   # "confirmed", "radar_only" or "camera_only"
    t_impact: float
    ball_mph: Optional[float] = None
    club_mph: Optional[float] = None
    smash: Optional[float] = None
    camera_t: Optional[float] = None
    camera_source: Optional[str] = None   # "motion", "swing", ...
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        r = lambda v, n: None if v is None else round(v, n)
        return {"source": self.source, "t_impact": r(self.t_impact, 4),
                "ball_mph": r(self.ball_mph, 1), "club_mph": r(self.club_mph, 1),
                "smash": r(self.smash, 2), "camera_source": self.camera_source,
                "notes": self.notes}


class ShotFusion:
    def __init__(self, on_shot: Callable[[FusedShot], None],
                 ball_present: Callable[[], Optional[bool]] = lambda: None,
                 cfg: Optional[FusionConfig] = None,
                 on_reject: Optional[Callable[[str], None]] = None,
                 clock: Callable[[], float] = time.monotonic):
        """ball_present() -> True if the camera is Ready and still sees the
        ball at rest, False if it is Ready and the ball is gone, None if the
        camera isn't watching a ball right now."""
        self.on_shot = on_shot
        self.ball_present = ball_present
        self.cfg = cfg or FusionConfig()
        self.on_reject = on_reject or (lambda why: print(f"Not a shot: {why}"))
        self.clock = clock
        self.lock = threading.Lock()
        self.radar: Optional[tuple[float, Shot]] = None                  # (arrived, shot)
        self.camera: Optional[tuple[float, str]] = None                  # (trigger time, source)
        self.quiet_until = 0.0
        self._stop = threading.Event()

    # ---- inputs -----------------------------------------------------------
    def radar_shot(self, shot: Shot) -> None:
        now = self.clock()
        with self.lock:
            if shot.t_impact < self.quiet_until:
                return
            self.radar = (now, shot)
            self._match(now)

    def camera_trigger(self, t: float, source: str = "motion") -> None:
        with self.lock:
            if t < self.quiet_until:
                return
            self.camera = (t, source)
            self._match(self.clock())

    def radar_nothing(self, t0: float, t1: float) -> None:
        """The radar's recording from t0 to t1 (Pi clock) had no ball in it:
        a camera trigger in that time needn't wait any longer."""
        with self.lock:
            if self.camera and t0 - 0.05 <= self.camera[0] <= t1 + 0.25:
                self._camera_alone()

    def camera_cancel(self, t: float) -> None:
        """The kiosk decided the camera trigger at t was no shot (the ball is
        still there): forget it, so it can't become a camera-only shot or
        block the real one."""
        with self.lock:
            if self.camera and abs(self.camera[0] - t) <= 0.05:
                self.camera = None

    def poll(self) -> None:
        """Settle anything that has waited long enough. Call often (or start())."""
        with self.lock:
            self._match(self.clock(), timeout_only=True)

    def start(self, every_s: float = 0.02) -> None:
        def loop() -> None:
            while not self._stop.wait(every_s):
                self.poll()
        threading.Thread(target=loop, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    # ---- decisions (called with the lock held) ----------------------------
    def _fits(self, shot: Shot, cam_t: float) -> bool:
        d = cam_t - shot.t_impact
        return self.cfg.cam_after_min_s <= d <= self.cfg.cam_after_max_s

    def _match(self, now: float, timeout_only: bool = False) -> None:
        cfg = self.cfg
        if self.radar and self.camera:
            gap = self.camera[0] - self.radar[1].t_impact
            print(f"Pairing: camera trigger {1000 * gap:+.0f} ms from the radar's impact time")
        if self.radar and self.camera and self._fits(self.radar[1], self.camera[0]):
            _, shot = self.radar
            cam_t, cam_src = self.camera
            self._emit(FusedShot("confirmed", shot.t_impact, shot.ball_mph, shot.club_mph,
                                 shot.smash, cam_t, cam_src))
            return
        if self.radar and self.camera:
            # Both fired but too far apart to be the same shot: settle the older
            # one on its own and keep the newer one for its own pairing.
            if self.radar[1].t_impact < self.camera[0]:
                keep, self.camera = self.camera, None
                self._radar_alone()
                self.camera = keep
            else:
                keep, self.radar = self.radar, None
                self._camera_alone()
                self.radar = keep
            return
        if self.radar and now - self.radar[0] >= cfg.radar_wait_s:
            self._radar_alone()
        elif self.camera and now - self.camera[0] >= cfg.cam_wait_s:
            self._camera_alone()

    def _radar_alone(self) -> None:
        _, shot = self.radar
        self.radar = None
        # Asked only now, after the wait: right at impact the ball may still be
        # leaving the spot, which the camera can't tell from "still there" yet.
        try:
            present = self.ball_present()
        except Exception:
            present = None
        if present is True:
            self.on_reject(f"radar saw {shot.ball_mph:.0f} mph but the ball never left the mat")
            return
        notes = ["camera wasn't watching a ball"] if present is None else \
                ["camera saw the ball gone but didn't trigger"]
        self._emit(FusedShot("radar_only", shot.t_impact, shot.ball_mph, shot.club_mph,
                             shot.smash, notes=notes))

    def _camera_alone(self) -> None:
        cam_t, cam_src = self.camera
        self.camera = None
        if self.cfg.camera_only == "drop":
            self.on_reject(f"camera trigger ({cam_src}) with no radar shot")
            return
        self._emit(FusedShot("camera_only", cam_t - self.cfg.cam_delay_est_s,
                             camera_t=cam_t, camera_source=cam_src,
                             notes=["no radar reading (chip, or the radar missed it)"]))

    def _emit(self, fs: FusedShot) -> None:
        self.radar = self.camera = None
        self.quiet_until = fs.t_impact + self.cfg.cooldown_s
        try:
            self.on_shot(fs)
        except Exception as e:  # never let the display kill the trigger
            print(f"Shot handler error: {type(e).__name__}: {e}")
