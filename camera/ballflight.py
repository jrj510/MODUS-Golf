"""
Golf ball flight: where a shot goes, from ball speed, launch angle and spin.

A point-mass model stepped through time: gravity, air drag and lift from
backspin (the Magnus effect). Drag and lift grow with the spin factor
S = r * omega / v. The coefficients were tuned so tour-average shots land where
TrackMan's published averages say they do:

    driver 167 mph, 10.9 deg, 2686 rpm -> 271 yd carry (TrackMan: 275)
    7-iron 120 mph, 16.3 deg, 7097 rpm -> 174 yd       (TrackMan: 172)
    PW     102 mph, 24.2 deg, 9304 rpm -> 134 yd       (TrackMan: 136)

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

# Typical launch angle (deg) and spin (rpm) when they aren't measured.
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


def fly(speed_mph, launch_deg, spin_rpm, direction_deg=0.0, spin_axis_deg=0.0,
        dt=0.01, points=60):
    """Simulate one shot. Returns a dict with carry, apex, side (yards), flight
    time (s) and a path of about `points` [x, y, z] points in yards."""
    v = max(float(speed_mph), 0.1) * 0.44704
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
    step = max(1, len(path) // points)
    pts = path[::step]
    if pts[-1] != path[-1]:
        pts.append(path[-1])
    return {"carry": round(x / YD, 1), "apex": round(apex / YD, 1), "side": round(z / YD, 1),
            "time": round(t, 2),
            "path": [[round(a / YD, 2), round(b / YD, 2), round(c / YD, 2)] for a, b, c in pts]}


def shot_flight(ball_speed, club, launch_angle=None, spin=None, direction=None):
    """The flight for a measured shot, filling in typical club values for
    anything that wasn't measured. Says which inputs were assumed."""
    t_launch, t_spin, name = club_defaults(club)
    launch = launch_angle if launch_angle is not None else t_launch
    spin_used = spin if spin else t_spin
    f = fly(ball_speed, launch, spin_used, direction or 0.0)
    f.update({"ball_speed": round(float(ball_speed), 1), "launch": round(float(launch), 1),
              "spin": round(float(spin_used)), "direction": round(float(direction or 0.0), 1),
              "club": name,
              "assumed": [k for k, v in (("launch", launch_angle), ("spin", spin),
                                         ("direction", direction)) if v is None]})
    return f
