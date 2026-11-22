"""
MODUS-Golf's own calibration for each radar: the OPS243-A speed radar and the
TI IWR6843 angle radar. Fitted by camera/calibrate_radars.py, used by the
kiosk (kiosk.py, iwr_bridge.py).

Credit: the ideas behind both parts come from OpenFlight
(github.com/open-flight/openflight, AGPL-3.0): its ball-speed cosine
correction (speed_correction.py, checked there against TrackMan) and its TI
corner-reflector array calibration (iwr6843/calibration.py). The code and
the models here are MODUS's own, conformed to our box, our trigger and our
flight model. OpenFlight's speed correction is still run on every shot as a
check and written to the log next to ours.

SPEED RADAR (OPS243-A)
----------------------
The OPS243 measures the ball's speed along its line of sight (the Doppler
shift), not its true speed. The radar sits low, about 1.6 m behind the ball,
and the ball leaves climbing at the launch angle, so the line of sight and
the flight are at an angle and the reading is low by its cosine. As the ball
flies on, the line of sight turns toward the flight and the reading rises,
while air drag slows the ball and the reading falls. The radar's processing
reports about the highest speed that holds in its buffer (OpenFlight's
"mode-based" pick: the fastest 1-mph bin seen in 2 or more of its 4.3 ms FFT
windows), i.e. the peak of that rise-and-fall. OpenFlight divides the
reading by that peak's predicted fraction of the true speed; so do we.

What is ours:
  - the flight over the buffer: our own ball-flight model (ballflight.py:
    drag and lift that depend on the ball's speed and spin, gravity), not a
    fixed slowdown. At iron speeds the two agree; at driver speeds drag is
    about twice as strong, which OpenFlight's fixed 0.027 mph/ms leaves out;
  - full 3-D: the launch direction and the radar's own aim count, not just
    the launch angle;
  - the part of the flight the radar can see on OUR box: the ~90 ms of ball
    flight our camera-triggered buffer holds (start_kiosk.sh,
    *_OPS_PRE_TRIGGER), the net inside (the ball stops there), and the
    radar's beam (OPS243 datasheet: 20 x 24 deg at -3 dB);
  - a trim for THIS unit, fitted against a reference launch monitor (any
    unit that exports a CSV: TrackMan, GCQuad, Mevo+, R10 ...), because
    no model knows this box's exact distances and quirks.
With OpenFlight's own settings (fixed drag, 70 ms, no gravity, lift, net or
beam) this model gives OpenFlight's numbers to within 0.1 mph (tested).

Club speed is ours too (club_speed_from_readings): the peak of the club
head's climb in the radar's readings, read without OpenFlight's club types.
OpenFlight's club speed is kept only as a logged check.

TI RADAR (IWR6843)
------------------
Two layers:
  - Angle trim: the TI's launch angle and direction against the camera's
    (inside, good fits) or a reference launch monitor's. An offset (and,
    with a wide spread of angles, a scale). A constant offset is what a
    mis-measured TILT_DEG does, so it is also reported as a tilt.
  - Array calibration for THIS board: each of the 8 virtual antenna elements
    has its own small phase and gain error, measured with a corner reflector
    held still at tape-measured spots. OpenFlight ships one board's
    measurement as a "validated starting point"; this solves ours. Our solver
    also models the reflector's echo off the floor (a second, mirror-image
    path that otherwise bends the calibration), and with a capture of the
    empty scene it removes the room's static clutter first. Until it has
    been run, OpenFlight's reference array is used.
"""

import csv
import json
import math
import os
import time
from dataclasses import dataclass

from ballflight import AIR, G, MASS, RADIUS, club_defaults, coefficients

MPH = 0.44704                  # m/s per mph
WAVELENGTH_M = 299792458.0 / 24.125e9   # the OPS243-A radar wave (24.125 GHz): 12.43 mm
OPS_FILE = "ops_calibration.json"
TI_FILE = "ti_calibration.json"


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _read_json(path):
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


# =========================================================================
# Speed radar (OPS243-A)
# =========================================================================

@dataclass
class SpeedRadarSetup:
    """Where the speed radar sits and what part of the flight it sees.

    The geometry is the TI's (start_kiosk.sh): both radars are on the same
    faceplate, side by side. Heights are from the ground the ball sits on."""
    distance_m: float = 1.575          # radar antenna to ball centre, slant (TEE_M)
    radar_height_m: float = 0.06985    # RADAR_H
    ball_height_m: float = 0.021       # BALL_H
    tilt_deg: float = 10.0             # faceplate leans back (radar points up), TILT_DEG
    aim_deg: float = 0.0               # radar points right of the target line, AZIMUTH_DEG
    side_m: float = 0.0                # radar sits right (+) of the target line
    net_m: float = None                # inside: radar to the net along the target line; None = no net
    window_s: float = 0.090            # ball flight held in the radar's buffer
    beam_deg: tuple = (20.0, 24.0)     # OPS243 -3 dB beam widths: across, up-down (datasheet)
    beam_reach: float = 1.5            # still read out to this many -3 dB half-widths off the beam's centre

    @classmethod
    def from_args(cls, args, overrides=None):
        net = getattr(args, "iwr_net_m", None) if getattr(args, "speed_net", "off") == "on" else None
        s = cls(distance_m=float(args.iwr_tee_m), radar_height_m=float(args.iwr_radar_height_m),
                ball_height_m=float(args.iwr_ball_height_m), tilt_deg=float(args.iwr_tilt_deg),
                aim_deg=float(getattr(args, "iwr_azimuth_offset_deg", 0.0) or 0.0),
                net_m=float(net) if net else None,
                window_s=float(getattr(args, "ops_window_ms", 90.0)) / 1000.0)
        for k, v in (overrides or {}).items():       # from the calibration file, if a unit needs them
            if k in ("side_m", "window_s", "beam_reach") and isinstance(v, (int, float)):
                setattr(s, k, float(v))
        return s

    def text(self):
        return (f"radar {self.distance_m:g} m from the ball, {self.radar_height_m:g} m up, "
                f"tilted {self.tilt_deg:g} deg"
                + (f", net at {self.net_m:g} m" if self.net_m else ", no net")
                + f", {self.window_s * 1000:.0f} ms of flight in its buffer")


def radial_reading(speed_mps, launch_deg, direction_deg=0.0, spin_rpm=3000.0, setup=None,
                   physics=True, fixed_drag_mph_per_ms=None, dt=0.001):
    """What the speed radar should read for a ball with this true launch speed.

    Returns (fraction of the true speed it reads, details). The ball is flown
    from where it sits for the buffer's length; at each instant its speed
    along the line of sight from the radar is worked out, and the reading is
    the highest of those while the radar can see the ball (before the net,
    inside the beam, inside the buffer).

    physics=False with fixed_drag_mph_per_ms: a straight line at a fixed
    slowdown, no gravity or lift (only to check against OpenFlight's model).
    """
    s = setup or SpeedRadarSetup()
    v0 = max(float(speed_mps), 0.1)
    dh = s.ball_height_m - s.radar_height_m
    ground = math.sqrt(max(s.distance_m ** 2 - dh * dh, 0.01))
    # x down the target line, y up, z right; the radar at the origin.
    px, py, pz = ground, dh, -s.side_m
    th, ph = math.radians(launch_deg), math.radians(direction_deg or 0.0)
    ux, uy, uz = v0 * math.cos(th) * math.cos(ph), v0 * math.sin(th), v0 * math.cos(th) * math.sin(ph)
    w = max(float(spin_rpm or 0.0), 0.0) * 2 * math.pi / 60
    area = math.pi * RADIUS ** 2
    tilt, aim = math.radians(s.tilt_deg), math.radians(s.aim_deg)
    half_az = math.radians(s.beam_deg[0] / 2 * s.beam_reach)
    half_el = math.radians(s.beam_deg[1] / 2 * s.beam_reach)
    best, t_best, first, t, why = None, 0.0, None, 0.0, "buffer"
    while t <= s.window_s + 1e-9:
        if s.net_m is not None and px >= s.net_m:
            why = "net"
            break
        r = math.sqrt(px * px + py * py + pz * pz)
        radial = (ux * px + uy * py + uz * pz) / r
        if first is None:
            first = radial
        el = math.atan2(py, math.hypot(px, pz)) - tilt
        az = math.atan2(pz, px) - aim
        if (az / half_az) ** 2 + (el / half_el) ** 2 <= 1.0:
            if best is None or radial > best:
                best, t_best = radial, t
        sp = math.sqrt(ux * ux + uy * uy + uz * uz)
        if physics:
            spin_factor = RADIUS * w / sp
            cd, cl = coefficients(spin_factor)
            k = 0.5 * AIR * area * sp / MASS
            ax, ay, az_ = -k * cd * ux, -k * cd * uy - G, -k * cd * uz
            # Lift from backspin: at right angles to the flight, upward.
            horiz = math.hypot(ux, uz) or 1e-9
            lx, ly, lz = -uy * ux / horiz, horiz, -uy * uz / horiz
            n = math.sqrt(lx * lx + ly * ly + lz * lz)
            ax, ay, az_ = ax + k * cl * sp * lx / n, ay + k * cl * sp * ly / n, az_ + k * cl * sp * lz / n
        else:
            dec = (fixed_drag_mph_per_ms or 0.0) * MPH * 1000.0
            ax, ay, az_ = -dec * ux / sp, -dec * uy / sp, -dec * uz / sp
        ux, uy, uz = ux + ax * dt, uy + ay * dt, uz + az_ * dt
        px, py, pz = px + ux * dt, py + uy * dt, pz + uz * dt
        t += dt
    if best is None:                    # never in the beam: the first reading is all there is
        best, t_best, why = first if first is not None else v0, 0.0, "beam"
    frac = min(max(best / v0, 0.5), 1.0)
    return frac, {"peak_ms": round(t_best * 1000, 1), "limit": why}


class OPSCalibration:
    """The speed radar's calibration: our line-of-sight model plus this unit's trim.

    correct(raw_mph, launch_deg, direction=None, club=None) -> true ball speed (mph).
    The trim (shots/ops_calibration.json) is fitted by calibrate_radars.py:
        speed = scale * model_speed + offset_mph   (scale 1, offset 0 until fitted)"""

    def __init__(self, setup, path=None):
        self.path = path
        self.data = _read_json(path) if path else {}
        self.setup = setup
        trim = self.data.get("trim") or {}
        self.scale = float(trim.get("scale", 1.0) or 1.0)
        self.offset = float(trim.get("offset_mph", 0.0) or 0.0)

    @classmethod
    def from_args(cls, args):
        path = os.path.join(args.out, OPS_FILE)
        data = _read_json(path)
        return cls(SpeedRadarSetup.from_args(args, data.get("setup")), path)

    @property
    def trimmed(self):
        return abs(self.scale - 1.0) > 1e-9 or abs(self.offset) > 1e-9

    def model(self, raw_mph, launch_deg, direction=None, club=None, spin_rpm=None):
        """Our line-of-sight model alone (no trim): (mph, details)."""
        raw = float(raw_mph)
        if raw <= 0:
            return raw, {}
        launch = club_defaults(club)[0] if launch_deg is None else float(launch_deg)
        launch = min(max(launch, -10.0), 60.0)
        spin = spin_rpm if spin_rpm else club_defaults(club)[1]
        v, info = raw * MPH, {}
        for _ in range(3):        # the drag depends on the true speed, so solve for it (settles in 2)
            frac, info = radial_reading(v, launch, direction or 0.0, spin, self.setup)
            v = raw * MPH / frac
        info["factor"] = round(raw * MPH / v, 4)
        return v / MPH, info

    def correct(self, raw_mph, launch_deg, direction=None, club=None):
        mph, _ = self.model(raw_mph, launch_deg, direction, club)
        return self.scale * mph + self.offset if raw_mph and raw_mph > 0 else mph

    def text(self):
        fit = self.data.get("fit") or {}
        trim = ("not trimmed yet (fit it against a reference launch monitor: "
                "python3 camera/calibrate_radars.py ops REFERENCE.csv)")
        if self.trimmed:
            trim = (f"trim x{self.scale:.4f} {self.offset:+.2f} mph"
                    + (f" from {fit.get('pairs')} shots vs {fit.get('reference')} ({fit.get('date')})"
                       if fit else ""))
        return f"MODUS line-of-sight model ({self.setup.text()}); {trim}"

    def save(self, scale, offset, fit):
        self.data["trim"] = {"scale": round(float(scale), 5), "offset_mph": round(float(offset), 3)}
        self.data["fit"] = fit
        self.data["model"] = "modus-los-v1"
        self.scale, self.offset = float(scale), float(offset)
        _write_json(self.path, self.data)


def fit_trim(pairs, unit="mph", spread_for_scale=25.0, min_pairs=8):
    """Robust trim from (ours, reference) pairs: reference ~ scale * ours + offset.

    Pairs far off the rest (a mismatched shot, a misread) are left out
    (more than 3 robust standard deviations, at least `floor`). The scale is
    only fitted when the values spread over `spread_for_scale` or more and
    there are 15+ pairs; otherwise it stays 1 and only the offset is fitted.
    Returns a dict (scale, offset, kept, dropped, before/after errors) or
    raises ValueError if there are too few pairs."""
    pairs = [(float(a), float(b)) for a, b in pairs
             if a is not None and b is not None and math.isfinite(float(a)) and math.isfinite(float(b))]
    if len(pairs) < min_pairs:
        raise ValueError(f"only {len(pairs)} matched pairs; need at least {min_pairs}")
    floor = 1.5 if unit == "mph" else 1.0
    diffs = sorted(b - a for a, b in pairs)
    med = _median(diffs)
    mad = _median(sorted(abs(d - med) for d in diffs)) * 1.4826
    lim = max(3.0 * mad, floor)
    kept = [(a, b) for a, b in pairs if abs((b - a) - med) <= lim]
    dropped = [(a, b) for a, b in pairs if abs((b - a) - med) > lim]
    xs = sorted(a for a, _ in kept)
    spread = xs[int(0.9 * (len(xs) - 1))] - xs[int(0.1 * (len(xs) - 1))]

    def stats(f):
        e = [b - f(a) for a, b in kept]
        m = sum(e) / len(e)
        return {"mean": round(m, 2), "mean_abs": round(sum(abs(x) for x in e) / len(e), 2),
                "sd": round(math.sqrt(sum((x - m) ** 2 for x in e) / max(len(e) - 1, 1)), 2)}
    scale, offset = 1.0, sum(b - a for a, b in kept) / len(kept)
    if spread >= spread_for_scale and len(kept) >= 15:
        n = len(kept)
        mx, my = sum(a for a, _ in kept) / n, sum(b for _, b in kept) / n
        sxx = sum((a - mx) ** 2 for a, _ in kept)
        if sxx > 0:
            s_fit = sum((a - mx) * (b - my) for a, b in kept) / sxx
            o_fit = my - s_fit * mx
            # Keep the scale only if it really explains the differences (the
            # scatter left drops by a tenth or more); otherwise it is noise.
            sd_off = stats(lambda a: a + offset)["sd"]
            sd_fit = stats(lambda a: s_fit * a + o_fit)["sd"]
            if sd_fit <= 0.9 * sd_off:
                scale, offset = s_fit, o_fit
    return {"scale": scale, "offset": offset, "kept": kept, "dropped": dropped,
            "spread": round(spread, 1), "scaled": scale != 1.0,
            "before": stats(lambda a: a), "after": stats(lambda a: scale * a + offset)}


def _median(sorted_values):
    v = sorted(sorted_values)
    n = len(v)
    if not n:
        return 0.0
    return v[n // 2] if n % 2 else 0.5 * (v[n // 2 - 1] + v[n // 2])


# =========================================================================
# Speed radar (OPS243-A): club-head speed, our own
# =========================================================================
#
# Through the downswing the club head is the fastest thing moving away from
# the radar, and it keeps speeding up until it meets the ball. In the radar's
# readings (one set of speed peaks per 4.3 ms FFT window, a window every
# 1.07 ms) that is a branch that climbs steadily, about 1-2 mph per window.
# At impact the head gives up its speed: right after, its readings drop away,
# and the ball appears. How the ball appears decides how we read the club:
#
#   - "jump": the ball comes in as a sudden jump, well above anything the
#     club could reach in one window, and stays there (drivers, woods, irons,
#     pitching wedges: the ball is 20-40% faster than the head). The club
#     speed is the peak of the club's climb in the 12 ms before that jump.
#   - "merge": no jump. The club's readings run straight into the ball's,
#     because the ball leaves at about the club's speed along the radar's
#     line of sight (sand and lob wedges, and thin or heeled strikes with any
#     club). The club speed is where that climb levels off.
#
# The club's branch is followed on the strong peaks only (at least a tenth
# as strong as the strongest echo around the shot): weak ones are mostly
# glints off the shaft and FFT sidelobes. A share, not a fixed strength,
# because how strong the echoes are depends on the box and the distances. Each value is the middle of
# 3 neighbouring windows, so a single noisy window can't set the speed.
# A very strong club echo overloads the radar's input and makes false copies
# of itself at 2x and 3x its speed, some folded back by the sample rate (at
# 30,000 samples a second everything wraps every 417 mph: a 3x copy of an
# 82 mph club shows up near 172 mph). In the recordings these looked like the
# ball arriving, so any peak at such a copy of a stronger peak in the same
# window is dropped first (but never one at the ball's own speed).
# The club picked on the kiosk isn't needed for any of this: jump or merge is
# read from the readings themselves. (Afterwards kiosk.py still checks the
# smash factor against what that club can really give: SMASH_MAX.)
#
# Checked on the 22 real recordings that have TrackMan's club speed for the
# same swings (OpenFlight's public sample session of 6 May 2026: 7-iron,
# driver, pitching wedge, incl. one thin pitching-wedge strike that merges):
# median miss 1.0 mph, 21 of 22 within 2 mph, worst +3.5 mph. OpenFlight's
# own club-speed pick on the same recordings: median 3.6 mph, 8 of 22 within
# 2 mph, worst -15.3 mph. On 17 more driver recordings from that project
# (no TrackMan) it gave a believable smash factor on all but one, where the
# ball speed itself was misread. No sand- or lob-wedge recordings were
# available, so the merge case has been seen on one shot only: check it
# against a reference launch monitor (club_speed_check_mph in the session
# CSV is OpenFlight's club speed, for comparison).

CLUB_SPAN_MS = (-30.0, 5.0)  # readings used: around the ball's strongest reading
CLUB_MIN_MPH = 15.0          # slower: the golfer, the net, room clutter
CLUB_MIN_SHARE = 0.10        # peaks weaker than this share of the strongest one are left out of the club's branch
BALL_JUMP_MPH = 8.0          # the ball arriving: this much faster than the club's last 3 windows
BALL_LEVEL = 0.88            # ... at no less than this share of the ball speed
BALL_NEAR = 0.04             # ... and seen again (within 4%, at least 3 mph) in 2 of the next 3 windows
CLUB_LOOK_MS = 12.0          # the club's peak is looked for this far before the jump
MERGE_TOP = 1.02             # merge: club readings up to 2% above the ball's speed
ECHO_COPIES = (2, 3)         # false copies of a strong echo: at 2x and 3x its speed ...
ECHO_FOLD_KSPS = 30          # ... or folded back by the radar's sample rate (ksps)
ECHO_MATCH = 0.02            # ... within 2% (never a peak at the ball's own speed)
MERGE_FROM = 0.45            # merge: the climb ends at a jump only past this share of the ball speed


def _echo_copy(speed, stronger, fold_mph):
    """Is speed a false copy (2x, 3x, or folded back) of one of the stronger peaks?"""
    for c in stronger:
        for k in ECHO_COPIES:
            for copy in (k * c, fold_mph - k * c):
                if abs(speed - copy) <= ECHO_MATCH * speed:
                    return True
    return False


def club_speed_from_readings(readings, ball_mph, ball_ms, sample_ksps=ECHO_FOLD_KSPS):
    """Club-head speed from the speed radar's FFT readings (see above).

    readings: (time ms, speed mph, strength) for every peak moving away from
    the radar, from each FFT window of the recording; ball_mph, ball_ms: the
    ball's speed and the time of its strongest reading; sample_ksps: the
    radar's sample rate (thousand samples a second).
    Returns {"club_mph": speed or None, "how": "jump" / "merge" / None,
    "ball_arrives_ms": time of the jump or None}."""
    out = {"club_mph": None, "how": None, "ball_arrives_ms": None}
    try:
        ball_mph, ball_ms = float(ball_mph), float(ball_ms)
    except (TypeError, ValueError):
        return out
    if not ball_mph > CLUB_MIN_MPH:
        return out
    fold_mph = sample_ksps * 1000.0 * WAVELENGTH_M / 2.0 / MPH     # 417 mph at 30 ksps
    windows = {}
    for t, s, m in readings:
        if s is None or t is None or s < CLUB_MIN_MPH:
            continue
        if ball_ms + CLUB_SPAN_MS[0] <= t <= ball_ms + CLUB_SPAN_MS[1]:
            windows.setdefault(t, []).append((s, m if m is not None else 0.0))
    strongest = max((m for peaks in windows.values() for _, m in peaks), default=0.0)
    every, strong = {}, {}
    for t, peaks in windows.items():
        peaks.sort(key=lambda p: -p[1])                 # strongest first
        for i, (s, m) in enumerate(peaks):
            at_ball = abs(s - ball_mph) <= max(3.0, BALL_NEAR * ball_mph)
            if not at_ball and _echo_copy(s, [p[0] for p in peaks[:i]], fold_mph):
                continue
            every.setdefault(t, []).append(s)
            if m >= CLUB_MIN_SHARE * strongest:
                strong.setdefault(t, []).append(s)
    times = sorted(every)
    top = {t: max(v) for t, v in strong.items()}       # the fastest strong peak in each window

    def seen(t, level):
        return any(abs(s - level) <= max(3.0, BALL_NEAR * level) for s in every.get(t, ()))

    arrives = level = None
    for i, t in enumerate(times):
        before = [top[x] for x in times[max(0, i - 3):i] if x in top]
        if len(before) < 2:
            continue
        for lvl in sorted(every[t], reverse=True):
            if lvl < BALL_LEVEL * ball_mph:
                break
            if lvl - max(before) >= BALL_JUMP_MPH and sum(seen(x, lvl) for x in times[i + 1:i + 4]) >= 2:
                arrives, level = t, lvl
                break
        if arrives is not None:
            break

    def smoothed(cap):
        """The fastest strong peak under cap in each window, as the middle of 3 neighbours."""
        tops = {t: max(v for v in vals if v < cap) for t, vals in strong.items() if any(v < cap for v in vals)}
        tt = sorted(tops)
        return [(tt[i], sorted((tops[tt[i - 1]], tops[tt[i]], tops[tt[i + 1]]))[1]) for i in range(1, len(tt) - 1)]

    if arrives is not None:
        # The club is slower than the ball that has just jumped in.
        values = [v for t, v in smoothed(level - BALL_JUMP_MPH / 2) if arrives - CLUB_LOOK_MS <= t < arrives]
        how = "jump"
    else:
        # The club's climb, up to where it levels off: it ends once the ball's
        # strongest reading has passed, or at a sudden jump once the club is
        # well under way (something faster than the club has come in, even if
        # the ball speed doesn't say so).
        values = []
        for t, v in smoothed(MERGE_TOP * ball_mph):
            if t > ball_ms + 2.0:
                break
            if values and values[-1] >= MERGE_FROM * ball_mph and v - values[-1] >= BALL_JUMP_MPH:
                break
            values.append(v)
        how = "merge"
    if values:
        out.update(club_mph=max(values), how=how, ball_arrives_ms=arrives)
    return out


# =========================================================================
# TI radar (IWR6843): angle trim
# =========================================================================

class TICalibration:
    """The TI radar's calibration (shots/ti_calibration.json).

    trim:  launch = scale * TI launch + offset_deg; direction = TI direction + dir_offset_deg
    array: this board's element phases and gains, range bias (solve_array), or absent."""

    def __init__(self, path=None):
        self.path = path
        self.data = _read_json(path) if path else {}
        trim = self.data.get("trim") or {}
        self.scale = float(trim.get("scale", 1.0) or 1.0)
        self.offset = float(trim.get("offset_deg", 0.0) or 0.0)
        self.dir_offset = float(trim.get("dir_offset_deg", 0.0) or 0.0)
        self.array = self.data.get("array") or None

    @classmethod
    def from_args(cls, args):
        return cls(os.path.join(args.out, TI_FILE))

    @property
    def trimmed(self):
        return abs(self.scale - 1.0) > 1e-9 or abs(self.offset) > 1e-9 or abs(self.dir_offset) > 1e-9

    def apply(self, launch, direction):
        """(launch, direction) after the trim; None stays None."""
        if launch is not None:
            launch = self.scale * float(launch) + self.offset
        if direction is not None:
            direction = float(direction) + self.dir_offset
        return launch, direction

    def text(self, tilt_deg=None):
        out = []
        if self.trimmed:
            fit = (self.data.get("trim") or {}).get("fit") or {}
            out.append(f"angle trim x{self.scale:.3f} {self.offset:+.2f} deg, direction {self.dir_offset:+.2f} deg"
                       + (f" ({fit.get('pairs')} shots vs {fit.get('reference')}, {fit.get('date')})" if fit else ""))
        else:
            out.append("no angle trim yet (fit it against the camera: python3 camera/calibrate_radars.py ti)")
        if self.array:
            a = self.array
            out.append(f"MODUS array calibration from {len(a.get('positions', []))} reflector spots "
                       f"({a.get('date')}, fit residual {a.get('residual', 0):.1%})")
            if tilt_deg is not None and a.get("tilt_deg") is not None \
                    and abs(float(a["tilt_deg"]) - float(tilt_deg)) > 0.5:
                out.append(f"WARNING: the array was calibrated with TILT_DEG {a['tilt_deg']:g}, "
                           f"now {tilt_deg:g}: capture and solve it again")
        else:
            out.append("array: OpenFlight's reference board (run our array calibration once the TI works)")
        return "; ".join(out)

    def save_trim(self, scale, offset, dir_offset, fit):
        self.data["trim"] = {"scale": round(float(scale), 4), "offset_deg": round(float(offset), 3),
                             "dir_offset_deg": round(float(dir_offset), 3), "fit": fit}
        self.scale, self.offset, self.dir_offset = float(scale), float(offset), float(dir_offset)
        _write_json(self.path, self.data)

    def save_array(self, array):
        self.data["array"] = array
        self.array = array
        _write_json(self.path, self.data)

    def clear(self, part):
        self.data.pop(part, None)
        _write_json(self.path, self.data)

    def openflight_calibration(self, calibration_cls):
        """Our array as the Calibration object OpenFlight's TI processing takes
        (its convention: applied to the snapshot in physical order,
        x * exp(-j phase) / gain). None without an array calibration."""
        if not self.array:
            return None
        import numpy as np
        a = self.array
        corr = np.exp(-1j * np.asarray(a["elem_phase_rad"], dtype=float)) / np.asarray(a["elem_gain"], dtype=float)
        meta = {"name": "MODUS array calibration", "date": a.get("date"),
                "radar_height_m": a.get("radar_height_m", 0.152), "source": "modus"}
        return calibration_cls(elem_correction=corr, tilt_rad=math.radians(float(a.get("tilt_deg", 10.0))),
                               range_bias_m=float(a.get("range_bias_m", 0.0)), source=self.path, meta=meta)


# =========================================================================
# TI radar: array calibration (corner reflector at tape-measured spots)
# =========================================================================
#
# The 8 virtual elements (2 TX x 4 RX, in physical order bottom to top) sit
# half a wavelength apart, so a still target at angle theta off the array's
# centre line gives element m the phase pi * sin(theta) * m (the same
# convention as OpenFlight's processing). Each element adds its own small
# phase and gain error c[m]; the reflector's echo off the floor arrives as a
# second, weaker copy from below (the mirror image of the reflector). So for
# reflector spot i:
#     x_i[m] = c[m] * (s_i * a(direct_i)[m] + q_i * a(floor_i)[m])
# s_i, q_i: the direct and floor echoes' strengths (unknown, per spot);
# a(theta)[m] = exp(j pi sin(theta) m). Spots at different heights and
# distances pin down c. With TILT_DEG fixed at its measured value, a small
# tilt error is soaked up by c as a phase slope that the same tilt undoes
# later (to first order), so the tilt does not have to be solved here.

N_ELEMENTS = 8


def steering(theta_rad, n=N_ELEMENTS):
    import numpy as np
    return np.exp(1j * np.pi * math.sin(theta_rad) * np.arange(n))


def spot_angles(ground_m, height_m, radar_height_m, tilt_deg):
    """(direct, floor-echo) angles off the array's centre line for a spot."""
    t = math.radians(tilt_deg)
    return (math.atan2(height_m - radar_height_m, ground_m) - t,
            math.atan2(-(height_m + radar_height_m), ground_m) - t)


def solve_array(spots, radar_height_m, tilt_deg, floor_echo=True, iterations=200):
    """Each element's phase and gain from reflector spots.

    spots: [{"snapshot": 8 complex (physical order), "ground_m", "height_m",
             "range_m" (measured, optional)}]
    Returns {"elem_phase_rad", "elem_gain", "residual", "echo", "range_bias_m",
             "per_spot": [...]}. Needs 3+ spots."""
    import numpy as np
    if len(spots) < 3:
        raise ValueError(f"{len(spots)} reflector spots; need at least 3 (better 4-6, at different heights)")
    X = np.array([np.asarray(s["snapshot"], dtype=complex) for s in spots])
    if X.shape[1] != N_ELEMENTS:
        raise ValueError(f"snapshots have {X.shape[1]} elements, expected {N_ELEMENTS}")
    angles = [spot_angles(s["ground_m"], s["height_m"], radar_height_m, tilt_deg) for s in spots]
    A_d = np.array([steering(d) for d, _ in angles])
    A_f = np.array([steering(f) for _, f in angles])

    # Start: direct path only. Y[i, m] = x_i[m] / a_i[m] = s_i * c[m] is one
    # column times one row; its best such fit is the top singular vector.
    Y = X * np.conj(A_d)
    _, _, vh = np.linalg.svd(Y)
    c = np.conj(vh[0])
    S = np.zeros(len(spots), dtype=complex)
    Q = np.zeros(len(spots), dtype=complex)

    def amplitudes(c):
        for i in range(len(spots)):
            if floor_echo:
                B = np.stack([c * A_d[i], c * A_f[i]], axis=1)
                (S[i], Q[i]), *_ = np.linalg.lstsq(B, X[i], rcond=None)
            else:
                b = c * A_d[i]
                S[i] = np.vdot(b, X[i]) / np.vdot(b, b)
                Q[i] = 0

    for _ in range(iterations):
        amplitudes(c)
        Bm = S[:, None] * A_d + Q[:, None] * A_f            # what each spot looks like without c
        new = (np.conj(Bm) * X).sum(axis=0) / np.maximum((np.abs(Bm) ** 2).sum(axis=0), 1e-30)
        new /= np.mean(np.abs(new))
        new *= np.exp(-1j * np.angle(new[0]))
        if np.max(np.abs(new - c)) < 1e-10:
            c = new
            break
        c = new
    amplitudes(c)
    model = c[None, :] * (S[:, None] * A_d + Q[:, None] * A_f)
    resid = float(np.sum(np.abs(X - model) ** 2) / max(np.sum(np.abs(X) ** 2), 1e-30))
    phase = np.unwrap(np.angle(c))
    phase -= phase.mean()
    gain = np.abs(c) / np.mean(np.abs(c))
    per_spot, biases = [], []
    for i, s in enumerate(spots):
        slant = math.hypot(s["ground_m"], s["height_m"] - radar_height_m)
        row = {"ground_m": s["ground_m"], "height_m": s["height_m"],
               "angle_deg": round(math.degrees(angles[i][0]), 2),
               "echo": round(float(abs(Q[i]) / max(abs(S[i]), 1e-30)), 3),
               "fit_error": round(float(np.sum(np.abs(X[i] - model[i]) ** 2)
                                        / max(np.sum(np.abs(X[i]) ** 2), 1e-30)), 4)}
        if s.get("range_m") is not None:
            row["range_m"], row["slant_m"] = round(float(s["range_m"]), 4), round(slant, 4)
            biases.append(float(s["range_m"]) - slant)
        per_spot.append(row)
    return {"elem_phase_rad": [round(float(p), 6) for p in phase],
            "elem_gain": [round(float(g), 6) for g in gain],
            "residual": resid, "floor_echo": bool(floor_echo),
            "range_bias_m": round(sorted(biases)[len(biases) // 2], 4) if biases else 0.0,
            "per_spot": per_spot}


def static_snapshot(raw, expected_m, tx_order="normal", gate_m=0.35, background=None):
    """The 8-element snapshot of a still reflector, from one TI capture (dump bytes).

    Uses the frames whose range window holds the reflector, all loops summed
    (the reflector doesn't move, so they add up in step). With `background`
    (a capture of the same scene without the reflector), the room's still
    clutter is taken away first, bin by bin. The reflector is the strongest
    bin within gate_m of where it was measured to be.
    Returns (snapshot in physical order, measured range m, bins-to-noise ratio)."""
    import numpy as np
    from openflight.iwr6843.dump import is_range_snapshot, parse_dump, parse_header, project_tx_pair
    from openflight.iwr6843.shot import geometry_from_header

    def per_bin(blob):
        if parse_header(blob)["n_tx"] == 3:
            blob = project_tx_pair(blob, (0, 2))   # TX1 + TX3 = the elevation array
        meta, cube = parse_dump(blob)
        geo = geometry_from_header(meta)
        data = cube if is_range_snapshot(meta) else np.fft.fft(cube, axis=-1)
        n_frames, cpf, n_rx, _ = data.shape
        loops = cpf // 2
        sums, counts = {}, {}
        for f in range(n_frames):
            start = geo.frame_bin_start(f) if geo.range_bin_starts is not None else geo.range_bin_start
            count = geo.frame_bin_count(f) if geo.range_bin_counts is not None else data.shape[-1]
            tdm = data[f].reshape(loops, 2, n_rx, -1)
            mean = tdm[..., :count].mean(axis=0)               # [2 TX, n_rx, bins]
            for k in range(count):
                b = start + k
                sums[b] = sums.get(b, 0) + mean[:, :, k]
                counts[b] = counts.get(b, 0) + 1
        return {b: sums[b] / counts[b] for b in sums}, geo.range_res_m

    bins, res = per_bin(raw)
    if background is not None:
        bg, _ = per_bin(background)
        bins = {b: v - bg[b] for b, v in bins.items() if b in bg}
    if not bins:
        raise ValueError("no range bins in this capture")
    lo, hi = (expected_m - gate_m) / res, (expected_m + gate_m) / res
    power = {b: float(np.sum(np.abs(v) ** 2)) for b, v in bins.items()}
    near = [b for b in power if lo <= b <= hi]
    if not near:
        raise ValueError(f"the capture's range windows don't reach {expected_m:.2f} m "
                         f"(bins {min(bins)}-{max(bins)} = {min(bins) * res:.2f}-{max(bins) * res:.2f} m)")
    peak = max(near, key=lambda b: power[b])
    frac = 0.0
    if peak - 1 in power and peak + 1 in power:    # between bins: fit a parabola to the log power
        a, b0, c = (math.log(max(power[peak + d], 1e-30)) for d in (-1, 0, 1))
        den = a - 2 * b0 + c
        frac = 0.5 * (a - c) / den if den < 0 else 0.0
    noise = sorted(power.values())[len(power) // 2] or 1e-30
    v = bins[peak]
    early, late = v[0], v[1]
    blocks = (early, late) if tx_order == "normal" else (late, early)
    snap = np.concatenate(blocks)[::-1]           # physical order (this board's RX are reversed)
    return snap, (peak + frac) * res, power[peak] / noise


def read_positions(path):
    """Reflector spots from a CSV: file, ground_m, height_m (one row per
    capture; several rows may share a spot). A row with file only and
    ground_m 'empty' is the empty-scene capture."""
    rows, empty = [], None
    base = os.path.dirname(os.path.abspath(path))
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            f = (row.get("file") or "").strip()
            if not f:
                continue
            f = f if os.path.isabs(f) else os.path.join(base, f)
            g = (row.get("ground_m") or "").strip().lower()
            if g == "empty":
                empty = f
                continue
            rows.append({"file": f, "ground_m": float(g), "height_m": float(row["height_m"])})
    return rows, empty


def array_from_captures(positions_csv, radar_height_m, tilt_deg, tx_order="normal", floor_echo=True):
    """Read the captures listed in positions_csv and solve the array."""
    import numpy as np
    rows, empty = read_positions(positions_csv)
    background = open(empty, "rb").read() if empty else None
    spots = {}
    for r in rows:
        slant = math.hypot(r["ground_m"], r["height_m"] - radar_height_m)
        snap, rng, snr = static_snapshot(open(r["file"], "rb").read(), slant, tx_order, background=background)
        key = (round(r["ground_m"], 3), round(r["height_m"], 3))
        spots.setdefault(key, []).append((snap, rng, snr, os.path.basename(r["file"])))
    merged = []
    for (g, h), caps in sorted(spots.items()):
        # Captures of one spot: line up their overall phase, then average.
        ref = caps[0][0]
        acc = sum(s * np.exp(-1j * np.angle(np.vdot(ref, s))) for s, *_ in caps)
        merged.append({"snapshot": acc / len(caps), "ground_m": g, "height_m": h,
                       "range_m": sum(c[1] for c in caps) / len(caps),
                       "snr": min(c[2] for c in caps), "files": [c[3] for c in caps]})
    result = solve_array(merged, radar_height_m, tilt_deg, floor_echo=floor_echo)
    for row, m in zip(result["per_spot"], merged):
        row["files"], row["snr"] = m["files"], round(float(m["snr"]), 1)
    result.update({"date": _now(), "tilt_deg": float(tilt_deg), "radar_height_m": float(radar_height_m),
                   "tx_order": tx_order, "background": bool(background), "positions": result.pop("per_spot")})
    return result


# =========================================================================
# Reading other launch monitors' CSV exports, and matching shots
# =========================================================================

def _num(text):
    try:
        v = float(str(text).strip().replace(",", ""))
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def read_reference(path):
    """Shots from another launch monitor's CSV export: [{speed_mph, launch, direction}].

    Finds the columns by name (Ball Speed, Launch Angle / VLA, Launch
    Direction / HLA); a units row under the header (TrackMan) or units in
    the name ("(km/h)", "[m/s]") are understood. mph unless it says otherwise."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = [r for r in csv.reader(fh)]
    head_i = next((i for i, r in enumerate(rows)
                   if any("ball" in c.lower() and "speed" in c.lower() for c in r)), None)
    if head_i is None:
        raise ValueError(f"{path}: no 'Ball Speed' column found")
    head = [c.strip().lower() for c in rows[head_i]]
    units = rows[head_i + 1] if head_i + 1 < len(rows) else []
    units_row = bool(units) and all(_num(c) is None for c in units if c.strip())

    def col(test):
        return next((i for i, h in enumerate(head) if test(h)), None)
    i_speed = col(lambda h: "ball" in h and "speed" in h and "club" not in h)
    i_launch = col(lambda h: ("launch" in h and ("angle" in h or "vert" in h)) or h in ("vla", "launch v")
                   or h.startswith("vla"))
    i_dir = col(lambda h: ("launch" in h and ("dir" in h or "horiz" in h)) or h in ("hla",) or h.startswith("hla"))
    unit_text = head[i_speed] + " " + (units[i_speed].lower() if units_row and i_speed < len(units) else "")
    k = 1.0
    if "km/h" in unit_text or "kph" in unit_text or "kmh" in unit_text:
        k = 1 / 1.609344
    elif "m/s" in unit_text or "mps" in unit_text:
        k = 1 / MPH
    shots = []
    for r in rows[head_i + (2 if units_row else 1):]:
        sp = _num(r[i_speed]) if i_speed < len(r) else None
        if sp is None or sp <= 0:
            continue
        shots.append({"speed_mph": sp * k,
                      "launch": _num(r[i_launch]) if i_launch is not None and i_launch < len(r) else None,
                      "direction": _num(r[i_dir]) if i_dir is not None and i_dir < len(r) else None})
    return shots


def match_shots(ours, theirs, key=lambda s: s, tolerance=8.0, search=15.0):
    """Line up two lists of shots in order, allowing shots that only one
    device caught (a missed read, a practice swing): the pairing that keeps
    the most shots whose speeds agree within `tolerance`, with the smallest
    differences. The two devices may disagree by a steady amount (that is
    what is being calibrated), so every steady difference up to `search` is
    tried and the one that lines up best is used for the pairing.
    Returns [(i, j)] index pairs."""
    a = [key(x) for x in ours]
    b = [key(y) for y in theirs]
    best = (-1.0, [])
    steps = int(round(search / 0.5))
    for k in range(-steps, steps + 1):
        shift = 0.5 * k
        score, pairs = _align(a, [None if v is None else v - shift for v in b], tolerance)
        if score > best[0]:
            best = (score, pairs)
    return best[1]


def _align(a, b, tolerance):
    """Ordered pairing of a and b (dynamic programming); (score, pairs)."""
    n, m = len(a), len(b)
    NEG = -1e18
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    move = [[0] * (m + 1) for _ in range(n + 1)]   # 0 diag, 1 skip ours, 2 skip theirs
    for i in range(1, n + 1):
        move[i][0] = 1
    for j in range(1, m + 1):
        move[0][j] = 2
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d = abs(a[i - 1] - b[j - 1]) if a[i - 1] is not None and b[j - 1] is not None else 1e9
            diag = score[i - 1][j - 1] + (tolerance - d) if d < tolerance else NEG
            best, mv = diag, 0
            if score[i - 1][j] > best:
                best, mv = score[i - 1][j], 1
            if score[i][j - 1] > best:
                best, mv = score[i][j - 1], 2
            score[i][j], move[i][j] = best, mv
    out, i, j = [], n, m
    while i > 0 and j > 0:
        mv = move[i][j]
        if mv == 0:
            out.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif mv == 1:
            i -= 1
        else:
            j -= 1
    return score[n][m], out[::-1]


def read_sessions(paths):
    """Our own session CSVs (logs/sessions/) as a list of row dicts, oldest first."""
    out = []
    for p in paths:
        try:
            with open(p, newline="") as fh:
                for row in csv.DictReader(fh):
                    row["_file"] = os.path.basename(p)
                    out.append(row)
        except OSError:
            continue
    return out
