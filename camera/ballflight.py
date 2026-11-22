"""
Golf ball flight: where a shot goes, from ball speed, launch angle and spin.

A point-mass model stepped through time: gravity, air drag and lift from
backspin (the Magnus effect). Drag grows with the spin factor
S = r * omega / v; lift rises with it and levels off: CL = CLMAX * S / (S + CL_HALF).
The four coefficients were fitted (Nov 2026) to TrackMan's carry for shots
whose ball speed, launch and spin TrackMan measured: our 11 shots beside the
MSU TrackMan simulator (21 Nov 2026) and the 24 shots of OpenFlight's public
TrackMan session (session_logs/comparison_20260506.csv, used as data only),
while keeping TrackMan's published PGA Tour averages (carry, height, landing
angle) close. Mean carry miss: 2.9% on ours and 2.5% on theirs (the old
linear-lift coefficients: 4.1% and 7.2%); fitted on either set alone, the
other set still improves. Tour averages now:

    driver 167 mph, 10.9 deg, 2686 rpm -> 272 yd carry (TrackMan: 275)
    7-iron 120 mph, 16.3 deg, 7097 rpm -> 169 yd       (TrackMan: 172)
    PW     102 mph, 24.2 deg, 9304 rpm -> 130 yd       (TrackMan: 136)

Also here, all MODUS's own models (no OpenFlight code or formulas):
  - estimate_spin(): backspin from the club, its speed and the contact;
  - spin_limits(): the only check on that spin: what is physically possible
    for the club's loft, the ball speed, club speed and launch angle;
  - contact quality: how well the ball was struck for that club;
  - rollout(): how far the ball runs after landing.
How each was built and checked is written above it.

Coordinates of the returned path: x = down the range, y = height,
z = right of the target line (all in yards).
"""

import math

MASS = 0.04593          # kg
RADIUS = 0.02134        # m
AIR = 1.2               # kg/m^3
G = 9.81
CD0, CDK = 0.2182, 0.2748          # drag: CD0 + CDK * S
CLMAX, CL_HALF = 0.3401, 0.0733    # lift: CLMAX * S / (S + CL_HALF)
SPIN_DECAY_S = 25.0     # spin falls off by e every 25 s
def coefficients(s):
    """Drag and lift coefficients at spin factor s = r * omega / v."""
    return CD0 + CDK * s, CLMAX * s / (s + CL_HALF)

YD = 0.9144
MPH = 0.44704           # m/s per mph

# Typical launch angle (deg) and spin (rpm) when they aren't measured
# (TrackMan PGA Tour averages; used for the launch angle and as the reference
# for the club, not for the spin of a shot: see estimate_spin).
CLUBS = {
    "driver": (11.0, 2700), "3w": (11.5, 3600), "5w": (12.5, 4300),
    "hybrid": (13.5, 4500), "3i": (12.5, 4100), "4i": (13.5, 4700), "5i": (14.5, 5300),
    "6i": (15.5, 6200), "7i": (16.5, 7000), "8i": (18.5, 7900),
    "9i": (20.5, 8600), "pw": (24.0, 9300), "gw": (28.0, 9600),
    "sw": (31.0, 10000), "lw": (34.0, 10300),
}
ALIASES = {"dr": "driver", "d": "driver", "52": "gw", "50": "gw", "aw": "gw",
           "54": "sw", "56": "sw", "58": "lw", "60": "lw", "48": "pw",
           "3wood": "3w", "5wood": "5w", "hy": "hybrid"}


def club_defaults(club):
    """(launch deg, spin rpm, club name) typical for a club name like '7i' or '52'."""
    name = str(club or "").strip().lower().replace(" ", "")
    name = ALIASES.get(name, name)
    if name.endswith("iron"):
        name = name[:-4] + "i"
    launch, spin = CLUBS.get(name, CLUBS["7i"])
    return launch, spin, name if name in CLUBS else "7i"


# --- Spin -------------------------------------------------------------------
#
# Backspin comes from the club face rubbing up the back of the ball. If the
# ball leaves rolling up the face, impulse physics gives
#     spin = (5/7) * Vclub * sin(spin loft) / r       (r = ball radius)
# where spin loft is the angle between where the face points and where the
# club is moving (dynamic loft minus attack angle). We keep that form and fit
# its constant to measured data: the USGA's launch-condition study (R22-01,
# TrackMan data for 10 groups of 6-iron golfers, tour players down to high
# handicaps, men and women, with spin loft measured) gives
#     spin = K * Vclub(m/s) * sin(spin loft),  K = 352 rpm per m/s
# (1.10 x the bare physics), within 8% for every group (median 3%).
#
# Spin loft isn't measured on our device, so each club gets a typical
# amateur spin loft: TrackMan's 2024 PGA Tour per-club spin and club speed
# turned back into spin loft with K, then 1-1.5 deg lower for amateurs (the
# USGA study's handicap golfers averaged 23.5 deg with a 6-iron, tour players
# 25). Drivers are different: measured amateur driver spin hardly changes
# with swing speed (USGA: about 2,700-3,300 rpm from 60 to 100 mph), and tour
# players at 115 mph spin it about 2,500. So the driver's spin loft is 13 deg
# at 85 mph club speed, 0.15 deg less per mph faster (more per mph slower),
# kept between 8 and 16 deg.
#
# When the launch angle IS measured (the camera), a higher launch than usual
# for an iron, hybrid or wedge means more dynamic loft, so more spin loft:
# 1.0 deg of spin loft per degree of launch (launch is roughly 0.75 of dynamic
# loft, less some attack-angle change; 1.3 overshot, and 1.0 was best on both
# our 21 Nov 2026 TrackMan session and OpenFlight's public one). Woods are
# left alone: a teed driver's launch comes mostly from the attack angle (ours
# hit up 3-5 deg and launched 16-19 deg with LESS spin than usual), which we
# don't measure; adding the launch made those drives spin 61-84% too high.
#
# Contact: smash factor (ball speed / club speed) against what a solid strike
# with that club gives. A mishit loses ball speed and, less so, spin: here
# half of the loss, i.e. spin scales with sqrt(smash / reference). That split
# is our assumption, to be checked against a reference launch monitor.
#
# Checked against the reference data: the USGA 6-iron groups within 14%
# (median 3%), its driver groups within 24% (median 8%), TrackMan's PGA Tour
# irons within 5%. Fairway woods have no amateur data to check against. Real
# amateur spin varies about +/-20% shot to shot at the same speed (the USGA
# spreads), so this is an estimate, shown as "est."

SPIN_K = 352.0          # rpm per m/s of club speed per unit sin(spin loft)

# club -> (static loft deg, typical amateur spin loft deg, solid-strike smash)
CLUB_PHYS = {
    "driver": (10.5, 13.0, 1.48), "3w": (15.0, 15.5, 1.46), "5w": (18.0, 17.5, 1.45),
    "hybrid": (21.0, 18.5, 1.44), "3i": (19.0, 17.0, 1.44), "4i": (22.0, 19.0, 1.42), "5i": (25.0, 21.0, 1.40),
    "6i": (28.0, 24.0, 1.37), "7i": (32.0, 28.5, 1.33), "8i": (36.0, 33.5, 1.31),
    "9i": (40.0, 38.0, 1.27), "pw": (45.0, 43.0, 1.23), "gw": (50.0, 47.5, 1.19),
    "sw": (55.0, 51.5, 1.15), "lw": (59.0, 55.5, 1.11),
}
SPIN_PER_LAUNCH_DEG = 1.0     # deg of spin loft per deg of launch above the club's usual (not woods)
SPIN_MAX = 12000.0            # about the most backspin any full golf shot has
DRIVER_SL_AT, DRIVER_SL_SLOPE, DRIVER_SL_RANGE = 85.0, 0.15, (8.0, 16.0)   # see above
CONTACT_SOLID, CONTACT_FAIR = 0.96, 0.90   # smash / reference: at or above = solid / fair


def contact_quality(club, ball_mph, club_mph):
    """How well the ball was struck for this club: (label, efficiency).

    efficiency = smash / the club's solid-strike smash. Label "solid"
    (>= 0.96), "fair" (>= 0.90) or "poor"; (None, None) without a club speed."""
    if not ball_mph or not club_mph:
        return None, None
    name = club_defaults(club)[2]
    eff = (float(ball_mph) / float(club_mph)) / CLUB_PHYS[name][2]
    label = "solid" if eff >= CONTACT_SOLID else ("fair" if eff >= CONTACT_FAIR else "poor")
    return label, round(eff, 3)


def estimate_spin(club, ball_mph, club_mph=None, launch_deg=None):
    """Backspin (rpm) estimated for a shot, with how it was worked out.

    club_mph: a trusted club speed, or None (then it is ball speed divided by
    the club's solid-strike smash, and contact is taken as solid).
    launch_deg: a MEASURED launch angle, or None.
    Returns {"spin" (checked), "model_spin" (before the check), "limits"
    (lowest, highest possible: spin_limits), "check" (ok / raised / lowered),
    "note", "spin_loft", "club_mph", "contact", "efficiency", "inputs"};
    spin is None without a ball speed."""
    name = club_defaults(club)[2]
    loft, spin_loft, smash_ref = CLUB_PHYS[name]
    out = {"spin": None, "spin_loft": None, "club_mph": None, "contact": None,
           "efficiency": None, "inputs": [], "model_spin": None, "limits": None, "note": None,
           "check": None}
    if not ball_mph or float(ball_mph) <= 0:
        return out
    ball_mph = float(ball_mph)
    contact, eff = contact_quality(name, ball_mph, club_mph)
    if contact is not None:
        v_club = float(club_mph)
        out["inputs"].append("club speed")
        factor = math.sqrt(min(eff, 1.05))
    else:
        v_club = ball_mph / smash_ref
        factor = 1.0
    if name == "driver":
        lo, hi = DRIVER_SL_RANGE
        spin_loft = min(hi, max(lo, spin_loft - DRIVER_SL_SLOPE * (v_club - DRIVER_SL_AT)))
    if launch_deg is not None and name not in WOODS:
        usual = club_defaults(name)[0]
        adj = SPIN_PER_LAUNCH_DEG * (float(launch_deg) - usual)
        spin_loft = spin_loft + max(-8.0, min(8.0, adj))
        out["inputs"].append("launch angle")
    spin = SPIN_K * v_club * MPH * math.sin(math.radians(spin_loft)) * factor
    spin = min(spin, SPIN_MAX)      # (a wrong club picked for a fast shot)
    # The only check: is this spin physically possible for this club's loft,
    # this ball speed, club speed and launch angle (spin_limits)? If not, it
    # is brought to the nearest possible value.
    lim = spin_limits(name, ball_mph, club_mph if contact is not None else None, launch_deg)
    checked = min(max(spin, lim["low"]), lim["high"])
    out.update(spin=round(checked), spin_loft=round(spin_loft, 1), club_mph=round(v_club, 1),
               contact=contact, efficiency=eff, model_spin=round(spin),
               limits=(round(lim["low"]), round(lim["high"])), note=lim["note"],
               check="ok" if checked == spin else ("raised" if checked > spin else "lowered"))
    return out


# --- Spin: what is physically possible ----------------------------------------
#
# Our spin estimate above is checked against what the shot could physically
# have, from the same physics: spin = K * Vclub * sin(spin loft), where spin
# loft = dynamic loft - attack angle, and nothing else:
#   - club loft (from the club picked): the face at impact (dynamic loft) is
#     between 0.65 x the club's loft (hands well ahead, a punch shot) and the
#     loft + 8 deg (hands behind, flipped);
#   - launch angle, when measured: the ball leaves at 0.6-0.95 of the dynamic
#     loft (lower share for the lofted clubs, whose ball slides up the face),
#     so the launch pins the dynamic loft down. A launch that doesn't fit the
#     club at all (a topped or skied shot, or the wrong club picked) is said
#     so, and the launch decides;
#   - attack angle: irons and wedges -8 to +2 deg (down into the ball), woods
#     -5 to +6 deg (a teed driver can hit up);
#   - club speed: the trusted reading +/- 3%, or when there is none, what the
#     ball speed allows: ball speed / (the club's solid smash + 4%) up to
#     ball speed / 0.8 (the worst mishit we still count);
#   - contact: a mishit keeps 60-105% of a solid strike's spin.
# The lowest and highest spin those allow are the limits. They are wide on
# purpose: this only catches impossible numbers (a topped iron can't spin
# like a full one), it doesn't second-guess the estimate.

DYN_LOFT_SHARE_MIN, DYN_LOFT_PLUS = 0.65, 8.0
LAUNCH_SHARE = (0.60, 0.95)
ATTACK_IRON, ATTACK_WOOD = (-8.0, 2.0), (-5.0, 6.0)
SMASH_WORST, SMASH_MARGIN, CLUB_TOL = 0.80, 1.04, 0.03
CONTACT_SPIN = (0.60, 1.05)
WOODS = ("driver", "3w", "5w")


def spin_limits(club, ball_mph, club_mph=None, launch_deg=None):
    """The lowest and highest backspin (rpm) physically possible for this
    shot (see above). club_mph: a trusted club speed or None; launch_deg: a
    MEASURED launch angle or None. Returns {"low", "high", "spin_loft"
    (lowest, highest deg), "dynamic_loft", "club_mph" (lowest, highest),
    "fits" (the launch fits the club), "note"}."""
    name = club_defaults(club)[2]
    loft, _, smash_ref = CLUB_PHYS[name]
    ball_mph = max(float(ball_mph or 0.0), 0.1)
    d_lo, d_hi = DYN_LOFT_SHARE_MIN * loft, loft + DYN_LOFT_PLUS
    fits, note = True, None
    if launch_deg is not None and float(launch_deg) > 0.5:
        la = float(launch_deg)
        l_lo, l_hi = la / LAUNCH_SHARE[1], la / LAUNCH_SHARE[0]
        if l_lo > d_hi or l_hi < d_lo:
            fits = False
            note = (f"launch {la:g} deg doesn't fit a {name} ({loft:g} deg loft): a topped or skied "
                    f"shot, or the wrong club picked; the launch decides")
            d_lo, d_hi = l_lo, l_hi
        else:
            d_lo, d_hi = max(d_lo, l_lo), min(d_hi, l_hi)
    a_lo, a_hi = ATTACK_WOOD if name in WOODS else ATTACK_IRON
    s_lo, s_hi = max(d_lo - a_hi, 1.0), min(d_hi - a_lo, 89.0)
    if club_mph:
        v_lo, v_hi = float(club_mph) * (1 - CLUB_TOL), float(club_mph) * (1 + CLUB_TOL)
    else:
        v_lo, v_hi = ball_mph / (smash_ref * SMASH_MARGIN), ball_mph / SMASH_WORST
    low = SPIN_K * v_lo * MPH * math.sin(math.radians(s_lo)) * CONTACT_SPIN[0]
    high = SPIN_K * v_hi * MPH * math.sin(math.radians(s_hi)) * CONTACT_SPIN[1]
    return {"low": low, "high": max(min(high, SPIN_MAX), low), "spin_loft": (round(s_lo, 1), round(s_hi, 1)),
            "dynamic_loft": (round(d_lo, 1), round(d_hi, 1)), "club_mph": (round(v_lo, 1), round(v_hi, 1)),
            "fits": fits, "note": note}


# --- Rollout ------------------------------------------------------------------
#
# When a spinning ball lands, friction with the ground slows its slide. Two
# cases (Penner's golf-ball bounce model):
#   - grip: friction is strong enough to turn the slide into a roll; the
#     ball's angular momentum about the contact point is kept, so it rolls
#     away at (5 * v * cos(landing angle) - 2 * r * backspin) / 7, of which
#     the share ROLL_BETA survives the bounce into the turf;
#   - slide: friction can take away at most ROLL_MU_E times the landing's
#     downward speed (friction x the bounce's normal impulse), so a shallow
#     landing keeps most of its forward speed and runs out.
# The ball leaves with the larger of the two speeds; roll = ROLL_C * speed^2.
# Steep, spinning landings check up; low, shallow ones (a thin iron, a low
# 3-iron) run 25-30 yd, as TrackMan showed. Fitted to the roll (total - carry)
# of our 11 shots beside the MSU TrackMan simulator (21 Nov 2026), with the
# landings from our flight model: mean miss 0.9 yd, and 1.1 yd when each shot
# is left out of the fit (the old grip-only model: 5.7 yd). TrackMan's PGA
# Tour averages then roll about 9 (driver), 4 (7-iron) and 2 yd (PW). Flat
# fairway as TrackMan's simulator plays it; firm or wet ground, slopes and
# greens are not modelled, so it is a display estimate.

ROLL_C, ROLL_MU_E, ROLL_BETA = 0.1481, 0.7348, 0.5495


def rollout(landing_mph, landing_angle_deg, landing_spin_rpm):
    """Roll after landing, in yards (flat average fairway), from the ball's
    speed (mph), descent angle (deg) and backspin (rpm) as it lands."""
    v = max(float(landing_mph), 0.0) * MPH
    w = max(float(landing_spin_rpm), 0.0) * 2 * math.pi / 60
    a = math.radians(landing_angle_deg)
    v_along, v_down = v * math.cos(a), v * math.sin(a)
    slide = v_along - ROLL_MU_E * v_down                       # friction can't stop the slide
    grip = ROLL_BETA * (5 * v_along - 2 * RADIUS * w) / 7      # friction turns it into a roll
    return ROLL_C * max(0.0, slide, grip) ** 2


def fly(speed_mph, launch_deg, spin_rpm, direction_deg=0.0, spin_axis_deg=0.0,
        dt=0.01, points=60):
    """Simulate one shot. Returns a dict with carry, apex, side (yards), flight
    time (s), landing angle (deg), speed (mph) and spin (rpm), roll and total
    (carry + roll, yards) and a path of about `points` [x, y, z] points in yards."""
    v = max(float(speed_mph), 0.1) * MPH
    th, ph = math.radians(launch_deg), math.radians(direction_deg)
    tilt = math.radians(spin_axis_deg)
    vx, vy, vz = v * math.cos(th) * math.cos(ph), v * math.sin(th), v * math.cos(th) * math.sin(ph)
    x = y = z = 0.0
    w = max(float(spin_rpm), 0.0) * 2 * math.pi / 60
    area = math.pi * RADIUS ** 2
    t, path, apex = 0.0, [(0.0, 0.0, 0.0)], 0.0
    while t < 20.0:
        speed = math.sqrt(vx * vx + vy * vy + vz * vz)
        horiz = math.hypot(vx, vz) or 1e-9
        s = RADIUS * w / speed
        cd, cl = coefficients(s)
        k = 0.5 * AIR * area * speed / MASS
        # Lift is at right angles to the flight, upward, leaning sideways with
        # the spin axis (a tilted axis curves the ball: draw or fade).
        hx, hz = vx / horiz, vz / horiz
        ux, uy, uz = -vy * hx, horiz, -vy * hz
        n = math.sqrt(ux * ux + uy * uy + uz * uz)
        ux, uy, uz = ux / n, uy / n, uz / n
        rx, rz = -hz, hx                       # sideways, to the right of the flight
        lx = ux * math.cos(tilt) + rx * math.sin(tilt)
        ly = uy * math.cos(tilt)
        lz = uz * math.cos(tilt) + rz * math.sin(tilt)
        vx += (-k * cd * vx + k * cl * speed * lx) * dt
        vy += (-k * cd * vy + k * cl * speed * ly - G) * dt
        vz += (-k * cd * vz + k * cl * speed * lz) * dt
        x, y, z = x + vx * dt, y + vy * dt, z + vz * dt
        t += dt
        w *= math.exp(-dt / SPIN_DECAY_S)
        if y < 0:
            break
        apex = max(apex, y)
        path.append((x, y, z))
    path.append((x, 0.0, z))
    horiz = math.hypot(vx, vz) or 1e-9
    landing_angle = math.degrees(math.atan2(-vy, horiz))
    landing_speed = math.sqrt(vx * vx + vy * vy + vz * vz) / MPH
    landing_spin = w * 60 / (2 * math.pi)
    carry = x / YD
    roll = rollout(landing_speed, landing_angle, landing_spin)
    step = max(1, len(path) // points)
    pts = path[::step]
    if pts[-1] != path[-1]:
        pts.append(path[-1])
    return {"carry": round(carry, 1), "apex": round(apex / YD, 1), "side": round(z / YD, 1),
            "time": round(t, 2), "landing_angle": round(landing_angle, 1),
            "landing_speed": round(landing_speed, 1), "landing_spin": round(landing_spin),
            "roll": round(roll, 1), "total": round(carry + roll, 1),
            "path": [[round(a / YD, 2), round(b / YD, 2), round(c / YD, 2)] for a, b, c in pts]}


def shot_flight(ball_speed, club, launch_angle=None, spin=None, direction=None, club_speed=None):
    """The flight for a measured shot. Anything not measured is filled in:
    launch from the club's typical value, spin from estimate_spin (club,
    ball speed, club speed if given, and the launch angle if measured).
    Says which inputs were assumed or estimated."""
    t_launch, t_spin, name = club_defaults(club)
    launch = launch_angle if launch_angle is not None else t_launch
    est = None
    if spin:
        spin_used = spin
    else:
        est = estimate_spin(name, ball_speed, club_speed, launch_angle)
        spin_used = est["spin"] or t_spin
    f = fly(ball_speed, launch, spin_used, direction or 0.0)
    f.update({"ball_speed": round(float(ball_speed), 1), "launch": round(float(launch), 1),
              "spin": round(float(spin_used)), "direction": round(float(direction or 0.0), 1),
              "club": name,
              "spin_estimate": est,
              "assumed": [k for k, v in (("launch", launch_angle), ("spin", spin),
                                         ("direction", direction)) if v is None]})
    return f
