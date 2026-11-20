"""Tests for camera/shot_fusion.py with a fake clock.

Run:  python -m pytest camera/test_shot_fusion.py -q
"""
from ops243 import Shot
from shot_fusion import FusionConfig, ShotFusion


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def make(ball_present=None, **cfg):
    clock = Clock()
    shots, rejects = [], []
    f = ShotFusion(shots.append, ball_present=lambda: ball_present,
                   cfg=FusionConfig(**cfg), on_reject=rejects.append, clock=clock)
    return f, clock, shots, rejects


def radar(t_impact, ball=132.0, club=101.0):
    return Shot(t_impact=t_impact, ball_mph=ball, club_mph=club,
                smash=ball / club, ball_reports=3)


def test_radar_first_then_camera_is_confirmed():
    f, clk, shots, _ = make(ball_present=False)
    clk.t = 100.06; f.radar_shot(radar(100.0))
    clk.t = 100.08; f.camera_trigger(100.08, "motion")
    assert len(shots) == 1 and shots[0].source == "confirmed"
    assert shots[0].ball_mph == 132.0 and shots[0].t_impact == 100.0


def test_camera_first_then_radar_is_confirmed():
    f, clk, shots, _ = make()
    clk.t = 100.05; f.camera_trigger(100.05, "motion")
    clk.t = 100.07; f.radar_shot(radar(100.0))
    assert [s.source for s in shots] == ["confirmed"]


def test_radar_only_with_ball_still_there_is_rejected():
    f, clk, shots, rejects = make(ball_present=True)
    clk.t = 100.06; f.radar_shot(radar(100.0))
    clk.t = 100.40; f.poll()
    assert shots == [] and len(rejects) == 1


def test_radar_only_when_camera_not_watching_counts():
    f, clk, shots, _ = make(ball_present=None)
    clk.t = 100.06; f.radar_shot(radar(100.0))
    clk.t = 100.20; f.poll()
    assert shots == []          # still waiting for the camera
    clk.t = 100.40; f.poll()
    assert [s.source for s in shots] == ["radar_only"]


def test_camera_only_keeps_a_no_speed_shot():
    f, clk, shots, _ = make()
    clk.t = 100.05; f.camera_trigger(100.05, "motion")
    clk.t = 100.40; f.poll()
    assert [s.source for s in shots] == ["camera_only"]
    assert shots[0].ball_mph is None
    assert abs(shots[0].t_impact - 99.99) < 1e-6


def test_camera_only_can_be_dropped():
    f, clk, shots, rejects = make(camera_only="drop")
    clk.t = 100.05; f.camera_trigger(100.05, "motion")
    clk.t = 100.40; f.poll()
    assert shots == [] and len(rejects) == 1


def test_far_apart_events_are_not_paired():
    f, clk, shots, _ = make(ball_present=None)
    clk.t = 100.05; f.camera_trigger(100.05, "motion")   # camera fires on its own
    clk.t = 100.20; f.radar_shot(radar(100.14))          # impact after the camera trigger
    sources = [s.source for s in shots]
    assert sources == ["camera_only"]                    # radar shot falls in the cooldown


def test_cooldown_blocks_double_count():
    f, clk, shots, _ = make(ball_present=False)
    clk.t = 100.06; f.radar_shot(radar(100.0))
    clk.t = 100.08; f.camera_trigger(100.08)
    clk.t = 100.50; f.camera_trigger(100.50)             # ball rolling / bounce
    clk.t = 101.00; f.poll()
    assert len(shots) == 1
    clk.t = 105.06; f.radar_shot(radar(105.0))
    clk.t = 105.08; f.camera_trigger(105.08)
    assert len(shots) == 2
