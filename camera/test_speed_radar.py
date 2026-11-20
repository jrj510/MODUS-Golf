"""Tests for camera/speed_radar.py with a fake rolling-buffer radar.

Run:  python -m pytest camera/test_speed_radar.py -q
"""
import time
from types import SimpleNamespace

from speed_radar import SpeedRadar
from test_ops_capture import synth


class FakeRadar:
    def __init__(self):
        self.triggers = 0

    def start(self, cb):
        self.cb = cb

    def trigger(self):
        self.triggers += 1

    def close(self):
        pass

    def deliver(self, impact_pi, **kw):
        """A capture whose impact happened at Pi time impact_pi."""
        cap = synth(**kw)                      # impact 60 ms after its first sample
        cap.received = impact_pi + (cap.sample_time + cap.duration - (cap.sample_time + 0.060))
        self.cb(cap)


def make(ball_present=None, pulse=21):
    fake, asked = FakeRadar(), []
    args = SimpleNamespace(radar_port="x", radar_confirm="off", trigger_out_gpio=pulse)
    sr = SpeedRadar(args, trigger_camera=asked.append,
                    ball_present=lambda: ball_present, radar=fake)
    return sr, fake, asked


def test_camera_then_radar_recording_is_confirmed():
    sr, fake, asked = make(ball_present=False)
    impact = time.monotonic() - 2.0
    cam_t = impact + 0.07
    sr.camera_fired(cam_t, "motion")
    fake.deliver(impact)                       # the dump arrives ~2 s later
    o = sr.result_for(cam_t, wait_s=1.0)
    assert o is not None and o["source"] == "confirmed"
    assert abs(o["ball_speed"] - 132) < 2 and abs(o["club_speed"] - 105) < 4
    assert sr.outcome(cam_t)[0] == "ball" and asked == []
    sr.stop()


def test_radar_only_puts_a_shot_up():
    sr, fake, asked = make(ball_present=None)
    fake.deliver(time.monotonic() - 2.0)
    time.sleep(0.5)
    assert len(asked) == 1
    o = sr.result_for(asked[0], wait_s=0.5)
    assert o is not None and o["source"] == "radar_only"
    sr.stop()


def test_radar_only_with_ball_still_there_is_ignored():
    sr, fake, asked = make(ball_present=True)
    fake.deliver(time.monotonic() - 2.0)
    time.sleep(0.5)
    assert asked == [] and sr.results == []
    sr.stop()


def test_camera_trigger_with_empty_recording_is_decided_at_once():
    sr, fake, asked = make()
    impact = time.monotonic() - 2.0
    cam_t = impact + 0.07
    sr.camera_fired(cam_t, "motion")
    assert sr.outcome(cam_t) is None
    fake.deliver(impact, amp_ball=0.0, amp_club=0.0)   # radar recorded nothing moving
    time.sleep(0.1)
    assert sr.outcome(cam_t)[0] == "none"
    assert sr.result_for(cam_t, wait_s=0.2) is None
    sr.stop()


def test_without_pulse_wire_camera_triggers_radar_over_serial():
    sr, fake, _ = make(pulse=0)
    sr.camera_fired(time.monotonic(), "motion")
    assert fake.triggers == 1
    sr.camera_fired(time.monotonic(), "radar")         # our own request: not passed back
    assert fake.triggers == 1
    sr.stop()


def test_with_pulse_wire_no_serial_trigger():
    sr, fake, _ = make(pulse=21)
    sr.camera_fired(time.monotonic(), "motion")
    assert fake.triggers == 0
    sr.stop()
