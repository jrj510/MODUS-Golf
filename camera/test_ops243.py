"""Tests for camera/ops243.py using swings shaped like AN-029 Figure 5.

Run:  python -m pytest camera/test_ops243.py -q
"""
import math
import random

from ops243 import DetectorConfig, Report, ShotDetector, find_ball, measure_shot, parse_line

DT = 0.005  # ~200 Hz report rate


def fig5_swing(club_peak=105.0, ball=132.0, t_impact=0.022, noise=0.6, seed=1,
               t_start=0.0):
    """Club climbs to its peak at impact then falls; ball is a flat line after."""
    rng = random.Random(seed)
    reps = []
    t = 0.0
    while t <= 0.102:
        speeds = []
        if t <= t_impact:
            club = 72 + (club_peak - 72) * math.sin(0.5 * math.pi * t / t_impact)
        else:
            club = club_peak - 1100 * (t - t_impact)
        if club > 20 and t <= 0.055:
            speeds.append(club + rng.gauss(0, noise))
        if t >= t_impact:
            speeds.append(ball - 25 * (t - t_impact) + rng.gauss(0, noise / 2))
        if speeds:
            reps.append(Report(t_start + t, sorted(speeds, reverse=True)))
        t += DT
    return reps


def run(reports, cfg=None):
    shots = []
    det = ShotDetector(shots.append, cfg)
    for r in reports:
        det.feed(r)
    det.flush()
    return shots


def test_parse_plain_and_json():
    assert parse_line("132.4", 1.0).speeds == [132.4]
    assert parse_line("-98.1,132.4", 1.0).speeds == [132.4, 98.1]
    assert parse_line('{"speed":[132.4, -98.1]}', 1.0).speeds == [132.4, 98.1]
    assert parse_line('{"SampleRate":30000}', 1.0) is None
    assert parse_line("Sampling Rate set to 30k", 1.0) is None
    assert parse_line("", 1.0) is None


def test_figure5_swing():
    shots = run(fig5_swing())
    assert len(shots) == 1
    s = shots[0]
    assert abs(s.ball_mph - 132) < 1.5
    assert abs(s.club_mph - 105) < 3
    assert 1.2 < s.smash < 1.32
    assert abs(s.t_impact - 0.025) < 0.01


def test_many_swings_with_noise():
    for seed in range(30):
        club = 70 + seed * 1.5
        ball = club * 1.3
        s = run(fig5_swing(club_peak=club, ball=ball, seed=seed, noise=1.0))
        assert len(s) == 1, seed
        assert abs(s[0].ball_mph - ball) < 2, seed
        assert s[0].club_mph is not None and abs(s[0].club_mph - club) < 4, seed


def test_practice_swing_is_not_a_shot():
    reps = [r for r in fig5_swing() if r.t < 0.022]  # club only, no ball
    reps += [Report(0.03 + i * DT, [80 - 5 * i]) for i in range(8)]
    assert run(reps) == []


def test_two_shots_and_cooldown():
    a = fig5_swing(seed=2)
    b = fig5_swing(seed=3, ball=120, club_peak=92, t_start=5.0)
    shots = run(a + b)
    assert len(shots) == 2
    assert abs(shots[0].ball_mph - 132) < 1.5 and abs(shots[1].ball_mph - 120) < 1.5


def test_single_spike_cannot_set_club():
    reps = fig5_swing(noise=0)
    reps[2].speeds = [125.0]  # one wild club reading before impact
    s = run(reps)[0]
    assert abs(s.club_mph - 105) < 3


def test_bad_club_reading_is_dropped():
    # A club "speed" faster than the ball makes no sense -> no club/smash.
    reps = fig5_swing()
    cfg = DetectorConfig(smash_min=1.4)  # forces the smash check to fail
    s = run(reps, cfg)[0]
    assert s.club_mph is None and s.smash is None
