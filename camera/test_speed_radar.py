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

    def start(self, cb, on_notice=None):
        self.cb = cb
        self.on_notice = on_notice

    def trigger(self):
        self.triggers += 1

    def set_speed_trigger(self, mph):
        self.speed_trigger = mph

    def close(self):
        pass

    def deliver(self, impact_pi, **kw):
        """A capture whose impact happened at Pi time impact_pi."""
        cap = synth(**kw)                      # impact 60 ms after its first sample
        cap.received = impact_pi + (cap.sample_time + cap.duration - (cap.sample_time + 0.060))
        self.cb(cap)


def make(ball_present=None, pulse=21, camera_ready=None, from_camera="off"):
    """camera_ready: None = no notice hook; True/False = the camera is/isn't
    Ready when the radar's trigger notice arrives (started captures go in .started)."""
    fake, asked = FakeRadar(), []
    args = SimpleNamespace(radar_port="x", radar_confirm="off", trigger_out_gpio=pulse,
                           radar_from_camera=from_camera)
    started = []

    def start_capture(t):
        if camera_ready:
            started.append(t)
            return True
        return False
    sr = SpeedRadar(args, trigger_camera=asked.append, ball_present=lambda: ball_present,
                    radar=fake, start_capture=None if camera_ready is None else start_capture)
    sr.started = started
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


def test_camera_and_radar_independent_by_default():
    sr, fake, _ = make(pulse=0)
    sr.camera_fired(time.monotonic(), "motion")
    assert fake.triggers == 0                           # the camera never triggers the radar
    sr.stop()


def test_without_pulse_wire_camera_triggers_radar_over_serial():
    sr, fake, _ = make(pulse=0, from_camera="on")
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


def test_trigger_notice_starts_a_capture_and_gets_the_numbers():
    sr, fake, asked = make(ball_present=None, camera_ready=True)
    impact = time.monotonic() - 2.0
    fake.on_notice(impact + 0.025)            # the radar's message, right at its trigger
    assert len(sr.started) == 1
    cap_t = sr.started[0]                     # ~50 ms on: impact and the ball's first frames
    assert impact - 0.05 < cap_t < impact + 0.2
    fake.deliver(impact)                      # ~2 s later the recording arrives
    o = sr.result_for(cap_t, wait_s=1.0)      # the kiosk asks for its capture's numbers
    assert o is not None and abs(o["ball_speed"] - 132) < 2
    assert o["source"] == "radar_trigger"
    assert asked == []                        # no second, frameless capture
    sr.stop()


def test_trigger_notice_with_no_ball_answers_none():
    sr, fake, asked = make(camera_ready=True)
    impact = time.monotonic() - 2.0
    fake.on_notice(impact + 0.025)
    cap_t = sr.started[0]
    fake.deliver(impact, amp_ball=0.0, amp_club=0.0)
    assert sr.result_for(cap_t, wait_s=0.5) is None
    assert sr.outcome(cap_t)[0] == "none"
    sr.stop()


def test_trigger_notice_when_camera_not_ready_falls_back():
    sr, fake, asked = make(ball_present=None, camera_ready=False)
    impact = time.monotonic() - 2.0
    fake.on_notice(impact - 0.02)
    fake.deliver(impact)
    time.sleep(0.5)
    assert len(asked) == 1                    # the old radar-only shot, as before
    sr.stop()


def test_notice_delay_is_learned():
    sr, fake, asked = make(camera_ready=True)
    for k in range(8):
        impact = time.monotonic() - 2.0
        # the radar's own trigger is 20 ms before impact (synth: impact 60 ms in,
        # trigger 85 ms in, so here: trigger = impact + 25 ms); message 200 ms late
        trig = impact + 0.025
        fake.on_notice(trig + 0.200)
        fake.deliver(impact)
    assert abs(sr.notice_delay - 0.200) < 0.02
    # the next capture is placed ~50 ms after the radar's trigger, not after the message
    fake.on_notice(trig + 0.200)
    assert abs(sr.started[-1] - (trig + 0.05)) < 0.02
    sr.stop()


def test_trigger_speed_follows_the_club():
    from speed_radar import trigger_mph_for
    assert trigger_mph_for("driver") == 75 and trigger_mph_for("56") == 40
    assert trigger_mph_for("3i") == 65 and trigger_mph_for("7i") == 55
    assert trigger_mph_for("7i", "48") == 48           # a fixed number wins
    assert trigger_mph_for("7i", "0") is None          # off
    sr, fake, _ = make()
    sr.set_club("driver")
    assert fake.speed_trigger == 75
    sr.stop()
