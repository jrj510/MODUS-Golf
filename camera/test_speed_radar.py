"""Tests for camera/speed_radar.py with a fake radar (real clock, ~2 s total).

Run:  python -m pytest camera/test_speed_radar.py -q
"""
import time
from types import SimpleNamespace

from speed_radar import SpeedRadar
from test_ops243 import fig5_swing


class FakeRadar:
    def configure(self, *a, **k):
        pass

    def start(self, cb):
        self.cb = cb

    def close(self):
        pass

    def swing(self, **kw):
        """Play a Figure 5 swing whose impact was ~0.1 s ago; returns impact time."""
        t0 = time.monotonic() - 0.11
        for r in fig5_swing(t_start=t0, **kw):
            self.cb(r, "")
        return t0 + 0.022


def make(ball_present=None, confirm="off"):
    fake, asked = FakeRadar(), []
    args = SimpleNamespace(radar_port="x", radar_confirm=confirm)
    sr = SpeedRadar(args, trigger_camera=asked.append,
                    ball_present=lambda: ball_present, radar=fake)
    return sr, fake, asked


def test_camera_and_radar_confirmed():
    sr, fake, asked = make(ball_present=False)
    impact = fake.swing()
    cam_t = impact + 0.07
    sr.camera_fired(cam_t, "motion")
    o = sr.result_for(cam_t, wait_s=1.0)
    assert o is not None and abs(o["ball_speed"] - 132) < 2 and o["source"] == "confirmed"
    assert sr.outcome(cam_t)[0] == "ball"
    assert asked == []
    sr.stop()


def test_radar_only_asks_camera_to_capture():
    sr, fake, asked = make(ball_present=None)
    fake.swing()
    time.sleep(0.6)
    assert len(asked) == 1
    o = sr.result_for(asked[0], wait_s=0.5)
    assert o is not None and o["source"] == "radar_only"
    sr.stop()


def test_radar_only_with_ball_still_there_is_ignored():
    sr, fake, asked = make(ball_present=True)
    fake.swing()
    time.sleep(0.6)
    assert asked == [] and sr.results == []
    sr.stop()


def test_camera_only_has_no_numbers():
    sr, fake, asked = make()
    t = time.monotonic()
    sr.camera_fired(t, "motion")
    assert sr.outcome(t) is None            # still waiting for the radar
    assert sr.result_for(t, wait_s=1.0) is None
    assert sr.outcome(t)[0] == "none"
    sr.stop()


def test_late_camera_trigger_still_gets_the_numbers():
    sr, fake, asked = make(ball_present=None)
    fake.swing()
    time.sleep(0.6)                          # radar gave up waiting, asked the camera
    late = asked[0] + 0.1                    # the camera's own trigger time was a bit later
    o = sr.result_for(late, wait_s=0.2)
    assert o is not None and abs(o["ball_speed"] - 132) < 2
    sr.stop()
