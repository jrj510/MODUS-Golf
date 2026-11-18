"""
Golf ball flight: where a shot goes, from ball speed, launch angle and spin.

A point-mass model stepped through time: gravity, air drag and lift from
backspin (the Magnus effect). Drag and lift grow with the spin factor
S = r * omega / v. The coefficients were tuned so tour-average shots land where
TrackMan's published averages say they do:

    driver 167 mph, 10.9 deg, 2686 rpm -> 271 yd carry (TrackMan: 275)
    7-iron 120 mph, 16.3 deg, 7097 rpm -> 174 yd       (TrackMan: 172)
    PW     102 mph, 24.2 deg, 9304 rpm -> 134 yd       (TrackMan: 136)

Also here, all MODUS's own models (no OpenFlight code or formulas):
  - estimate_spin(): backspin from the club, its speed and the contact;
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
CD0, CDK = 0.24, 0.21   # drag: CD0 + CDK * S
CLK, CLMAX = 1.8, 0.32  # lift: min(CLMAX, CLK * S)
SPIN_DECAY_S = 25.0     # spin falls off by e every 25 s
YD = 0.9144
MPH = 0.44704           # m/s per mph

# Typical launch angle (deg) and spin (rpm) when they aren't measured
# (TrackMan PGA Tour averages; used for the launch angle and as the reference
# for the club, not for the spin of a shot: see estimate_spin).
CLUBS = {
    "driver": (11.0, 2700), "3w": (11.5, 3600), "5w": (12.5, 4300),
    "hybrid": (13.5, 4500), "4i": (13.5, 4700), "5i": (14.5, 5300),
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
# When the launch angle IS measured (TI radar, or later the camera), a higher
# launch than usual for the club means more dynamic loft, so more spin loft:
# about 1.3 deg of spin loft per degree of launch (launch is roughly 0.75 of
# dynamic loft for irons; any change in attack angle is ignored).
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
    "hybrid": (21.0, 18.5, 1.44), "4i": (22.0, 19.0, 1.42), "5i": (25.0, 21.0, 1.40),
    "6i": (28.0, 24.0, 1.37), "7i": (32.0, 28.5, 1.33), "8i": (36.0, 33.5, 1.31),
    "9i": (40.0, 38.0, 1.27), "pw": (45.0, 43.0, 1.23), "gw": (50.0, 47.5, 1.19),
    "sw": (55.0, 51.5, 1.15), "lw": (59.0, 55.5, 1.11),
}
SPIN_PER_LAUNCH_DEG = 1.3     # deg of spin loft per deg of launch above the club's usual
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
    Returns {"spin", "spin_loft", "club_mph", "contact", "efficiency",
    "inputs"}; spin is None without a ball speed."""
    name = club_defaults(club)[2]
    loft, spin_loft, smash_ref = CLUB_PHYS[name]
    out = {"spin": None, "spin_loft": None, "club_mph": None, "contact": None,
           "efficiency": None, "inputs": []}
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
    if launch_deg is not None:
        usual = club_defaults(name)[0]
        adj = SPIN_PER_LAUNCH_DEG * (float(launch_deg) - usual)
        spin_loft = spin_loft + max(-8.0, min(8.0, adj))
        out["inputs"].append("launch angle")
    spin = SPIN_K * v_club * MPH * math.sin(math.radians(spin_loft)) * factor
    spin = min(spin, SPIN_MAX)      # (a wrong club picked for a fast shot)
    out.update(spin=round(spin), spin_loft=round(spin_loft, 1), club_mph=round(v_club, 1),
               contact=contact, efficiency=eff)
    return out


# --- Rollout ------------------------------------------------------------------
#
# When a spinning ball lands, friction with the ground turns its slide into
# a roll. With friction the only sideways force at the contact point, the
# ball's angular momentum about that point is kept, so the speed it rolls
# away at is
#     v_roll = (5 * v * cos(landing angle) - 2 * r * backspin) / 7
# (the standard bounce result used in Penner's golf-ball bounce model). Steep
# landings and backspin both leave less forward speed; enough backspin stops
# the ball (we show no negative roll: on a range it checks up).
# The distance then follows the energy left: roll = C * v_roll^2. C is set so
# an average PGA Tour drive (171 mph, 10.9 deg, 2545 rpm, landing as our
# flight model lands it: 62 mph, 38 deg, 1900 rpm) rolls 15 yd: ShotLink's
# average driving distance minus TrackMan's average carry was 13.6-16.1 yd in
# 2023-2025. For the typical landings measured by Johnson et al. (driver
# 29.5 m/s, 36 deg, 1950 rpm; 5-iron 25 m/s, 44 deg, 4440 rpm; sand wedge
# 22 m/s, 51 deg, 9060 rpm) that gives about 18, 7 and 1 yd.
# Flat, average fairway; firm or wet ground, slopes and greens are not
# modelled, so it is a display estimate.

ROLL_C = 0.0727         # yd per (m/s)^2 of rolling-away speed (see above)


def rollout(landing_mph, landing_angle_deg, landing_spin_rpm):
    """Roll after landing, in yards (flat average fairway), from the ball's
    speed (mph), descent angle (deg) and backspin (rpm) as it lands."""
    v = max(float(landing_mph), 0.0) * MPH
    w = max(float(landing_spin_rpm), 0.0) * 2 * math.pi / 60
    v_roll = (5 * v * math.cos(math.radians(landing_angle_deg)) - 2 * RADIUS * w) / 7
    return ROLL_C * max(0.0, v_roll) ** 2


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
        cd, cl = CD0 + CDK * s, min(CLMAX, CLK * s)
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
