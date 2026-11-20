"""Tests for camera/ops_capture.py with synthetic I/Q captures.

A capture is built the way the radar records it: 4096 I/Q samples at 30 ksps
(12-bit ADC around ~1850, like the real dump), with the club's and ball's
Doppler tones following AN-029 Figure 5, plus noise.

Run:  python -m pytest camera/test_ops_capture.py -q
"""
import json
import math

import numpy as np

from ops_capture import (BLOCK, MPH_PER_MPS, MPS_PER_HZ, Capture, block_spectra,
                         capture_reports, find_shot, parse_dump, speed_axis)

RATE = 30000.0


def tone_hz(mph):
    return mph / MPH_PER_MPS / MPS_PER_HZ


def synth(club_peak=105.0, ball=132.0, impact_ms=60.0, sign=-1, noise=6.0, amp_ball=40.0,
          amp_club=70.0, seed=0, extra=None):
    """I/Q of a swing. impact_ms: impact time from the first sample."""
    rng = np.random.default_rng(seed)
    n = 4096
    t = np.arange(n) / RATE
    tm = t * 1000.0
    phase_c = np.zeros(n)
    phase_b = np.zeros(n)
    # club: climbs to its peak at impact, then falls away; gone 35 ms after
    club = np.where(tm <= impact_ms,
                    0.68 * club_peak + 0.32 * club_peak * np.sin(0.5 * math.pi * np.clip(tm / impact_ms, 0, 1)),
                    club_peak - 1.1 * (tm - impact_ms))
    club_on = tm <= impact_ms + 35
    ball_mph = ball - 0.025 * (tm - impact_ms)
    ball_on = tm >= impact_ms
    phase_c = 2 * np.pi * np.cumsum(tone_hz(club)) / RATE
    phase_b = 2 * np.pi * np.cumsum(tone_hz(ball_mph)) / RATE
    z = (amp_club * club_on * np.exp(1j * sign * phase_c)
         + amp_ball * ball_on * np.exp(1j * sign * phase_b))
    if extra is not None:
        z = z + extra(t)
    z = z + noise * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
    i = np.round(1850 + z.real)
    q = np.round(1850 + z.imag)
    return Capture(sample_time=100.0, trigger_time=100.0 + 0.085, i=i, q=q,
                   received=500.0, rate=RATE)


def test_speed_axis_matches_radar_resolution():
    v = speed_axis(RATE, 4096)
    assert abs(abs(v[1] - v[0]) - 0.1017) < 0.001   # the radar reports 0.1017 mph


def test_single_tone_speed():
    n = 4096
    t = np.arange(n) / RATE
    z = 30 * np.exp(1j * 2 * np.pi * tone_hz(120.0) * t)
    cap = Capture(0.0, 0.05, 1850 + z.real, 1850 + z.imag, 10.0, RATE)
    reps = capture_reports(cap)
    assert len(reps) == 32
    assert all(abs(r.speeds[0] - 120.0) < 0.3 for r in reps)


def test_figure5_capture():
    shot, reps = find_shot(synth())
    assert shot is not None
    assert abs(shot.ball_mph - 132) < 1.5
    assert abs(shot.club_mph - 105) < 4
    assert 1.2 < shot.smash < 1.35


def test_either_doppler_sign():
    shot, _ = find_shot(synth(sign=+1))
    assert shot is not None and abs(shot.ball_mph - 132) < 1.5


def test_many_swings():
    for seed in range(15):
        club = 70 + 3 * seed
        ball = club * 1.3
        shot, _ = find_shot(synth(club_peak=club, ball=ball, seed=seed, noise=8.0))
        assert shot is not None, seed
        assert abs(shot.ball_mph - ball) < 2, seed
        assert shot.club_mph is not None and abs(shot.club_mph - club) < 5, seed


def test_practice_swing_has_no_ball():
    shot, _ = find_shot(synth(amp_ball=0.0))
    assert shot is None


def test_slow_body_motion_is_ignored():
    body = lambda t: 200 * np.exp(1j * 2 * np.pi * tone_hz(4.0) * t)   # strong, slow
    shot, reps = find_shot(synth(extra=body))
    assert shot is not None and abs(shot.ball_mph - 132) < 1.5
    assert all(min(r.speeds) >= 10 for r in reps)


def test_pi_clock_mapping():
    cap = synth()
    # dump started arriving at Pi time 500.0, right after the last sample
    assert abs(cap.pi_time(cap.sample_time + cap.duration) - 500.0) < 1e-9
    shot, _ = find_shot(cap)
    impact_pi = cap.pi_time(cap.sample_time + 0.060)
    assert abs(shot.t_impact - impact_pi) < 0.01


def test_parse_dump_lines():
    cap = synth()
    lines = [json.dumps({"sample_time": cap.sample_time}),
             json.dumps({"trigger_time": cap.trigger_time}),
             json.dumps({"I": cap.i.astype(int).tolist()}),
             json.dumps({"Q": cap.q.astype(int).tolist()}), ""]
    got = parse_dump(lines, received=500.0, rate=RATE)
    assert got is not None and len(got.i) == 4096 and got.trigger_time == cap.trigger_time
    assert parse_dump(lines[:3], 500.0, RATE) is None


def test_real_dump_from_the_pi_has_no_shot():
    # The 13:53 S! test: radar sitting still, values ~1840-1950. Noise only.
    rng = np.random.default_rng(5)
    i = 1850 + rng.normal(0, 25, 4096)
    q = 1850 + rng.normal(0, 25, 4096)
    cap = Capture(1209.576, 1209.627, i, q, 0.0, RATE)
    assert find_shot(cap)[0] is None
