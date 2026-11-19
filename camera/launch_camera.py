"""Launch angle from the camera: a pixel-to-angle grid and the ball's first
frames of flight. (Our own code; numpy and OpenCV only.)

How it works
------------
1. The grid (CameraGrid). Every sensor pixel looks along one direction. Which
   direction depends on the lens (its focal length in pixels) and on how the
   camera is pointed. The focal length is calibrated once: a ball at rest at a
   measured distance from the lens (CAM_BALL_M) shows a known number of pixels
   across (a golf ball is 42.67 mm), so f = pixels x distance / 42.67 mm
   (FocalCalibration keeps a running median over many balls and saves it).
   For each shot the ball at rest then fixes everything else: its size gives
   its distance, and with the lens height (CAM_HEIGHT_M) that gives how far
   below the camera it is seen; the camera's pitch and heading are whatever
   puts the ball exactly where it shows in the picture. So every pixel gets a
   real direction: "up" is up and straight ahead is the line from the camera
   to the ball (the target line when the box is aimed down it).

2. The flight (track_flight). In the frames after impact the ball is the
   small blob that moves away from where it sat: up, shrinking, along a
   nearly straight line in the picture. The frames just before the ball's
   spot first changes (their median) are the background. Only changes of the
   ball's own polarity count: a white ball is brighter than the net behind
   it, while the club head and the ball's now-empty spot are darker. Blobs
   too big (the club head), too thin (the shaft) or in the wrong place are
   dropped; the ball is the chain of blobs that keeps moving away from its
   spot and getting smaller.

3. The angle (solve_launch). The ball leaves its spot at time t0 with speed v
   at launch angle theta and direction phi, and falls under gravity. For any
   (theta, phi, t0, v) the grid says where in each frame it would show and
   how big. A least-squares fit (Levenberg-Marquardt) finds the values that
   match the frames, with the speed radar's ball speed as a prior on v when
   there is one. Its spread gives the uncertainty, used to judge the result
   and, with the TI radar, to weight the two (fuse_launch).

Conventions: world origin at the camera; x forward (horizontal, towards the
ball), y left, z up. Launch direction is reported right-positive, like the
radar's. Sensor pixels are full-array (1280 x 800) coordinates.
"""
import json
import math
import os

import cv2
import numpy as np

BALL_D = 0.04267            # golf ball diameter, m (USGA minimum)
G = 9.81
SENSOR_W, SENSOR_H = 1280, 800


class CameraGrid:
    """Direction of every sensor pixel in the world, once placed by setup()."""

    def __init__(self, focal_px, height_m, ball_height_m=0.021, roll_deg=0.0,
                 cx=SENSOR_W / 2.0, cy=SENSOR_H / 2.0):
        self.f = float(focal_px)
        self.h = float(height_m)
        self.hb = float(ball_height_m)
        self.roll = math.radians(roll_deg)
        self.cx, self.cy = float(cx), float(cy)
        self.R = None               # camera -> world rotation (3x3)
        self.ball = None            # ball centre at rest, world (m)
        self.range0 = None

    # -- pixel -> camera-frame direction (camera: x right, y down, z forward)
    def _cam_dir(self, u, v):
        return np.array([(u - self.cx) / self.f, (v - self.cy) / self.f, 1.0])

    def _rroll(self):
        c, s = math.cos(self.roll), math.sin(self.roll)          # camera turned about its axis
        return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])

    def setup(self, u0, v0, diameter_px):
        """Place the camera for this shot from the ball at rest: centre
        (u0, v0) and diameter in sensor pixels."""
        r0 = self.f * BALL_D / float(diameter_px)
        drop = self.h - self.hb
        eps = math.asin(max(-0.99, min(0.99, drop / r0)))       # ball seen this far below level
        d = self._cam_dir(u0, v0)
        d = self._rroll() @ (d / np.linalg.norm(d))              # as if the camera were level
        dx, dy, dz = d
        # Pitch p (camera looking down by p): world elevation of the ray must be -eps.
        k = math.hypot(dy, dz)
        p = math.asin(max(-1.0, min(1.0, math.sin(eps) / k))) - math.atan2(dy, dz)
        a = dz * math.cos(p) - dy * math.sin(p)
        yaw = math.atan2(dx, a)                                  # ... and straight ahead
        cp, sp, cy_, sy = math.cos(p), math.sin(p), math.cos(yaw), math.sin(yaw)
        xc = np.array([sy, -cy_, 0.0])
        zc = np.array([cp * cy_, cp * sy, -sp])
        yc = np.cross(zc, xc)
        R = np.stack([xc, yc, zc], axis=1)                       # columns: camera axes in the world
        self.R = R @ self._rroll()
        self.ball = r0 * np.array([math.cos(eps), 0.0, -math.sin(eps)])
        self.range0, self.pitch_deg = r0, math.degrees(p)
        self.yaw_deg = math.degrees(yaw)
        return self

    def project(self, P):
        """World points (N x 3, m) -> sensor pixels (N x 2) and apparent
        ball diameter (N), pixels."""
        P = np.atleast_2d(P)
        c = P @ self.R                                           # world -> camera frame
        z = np.maximum(c[:, 2], 1e-6)
        u, v = self.cx + self.f * c[:, 0] / z, self.cy + self.f * c[:, 1] / z
        return np.stack([u, v], axis=1), self.f * BALL_D / np.linalg.norm(P, axis=1)

    def ray(self, u, v):
        """Unit world direction of a sensor pixel."""
        d = self.R @ self._cam_dir(u, v)
        return d / np.linalg.norm(d)


def ball_path(grid, theta, phi, t0, v, times):
    """Ball centre (world, m) at each time: leaves its spot at t0 with speed v
    (m/s), launch angle theta and direction phi (radians, phi left-positive),
    then falls."""
    tau = np.maximum(np.asarray(times, float) - t0, 0.0)
    w = np.array([math.cos(theta) * math.cos(phi), math.cos(theta) * math.sin(phi), math.sin(theta)])
    P = grid.ball[None, :] + v * tau[:, None] * w[None, :]
    P[:, 2] -= 0.5 * G * tau ** 2
    return P


# ---------------------------------------------------------------- the flight
def _measure_blob(diff, lab, j, box, thr):
    """Centre, size and top edge of blob j (picture px): (u, v, d, peak, top,
    width), or None if it is cut off by the picture's edge.

    Centre and size from the whole ball, not its brightest side: the pixels
    above half the threshold (or 30% of the peak) that join this blob, each
    counted once. Lit from above, a ball's underside can fade into the
    background, so its centre is measured from the parts that always show:
    left and right (the width, and the middle between them) and the top edge
    (to a fraction of a pixel, column by column)."""
    H, W = diff.shape
    x, y, w, h = box
    ex0, ey0 = max(x - 3, 0), max(y - 3, 0)
    ex1, ey1 = min(x + w + 3, W), min(y + h + 3, H)
    local = diff[ey0:ey1, ex0:ex1]
    peak = float(local[lab[ey0:ey1, ex0:ex1] == j].max())
    low = (local > max(0.5 * thr, 0.3 * peak)).astype(np.uint8)
    k2, lab2 = cv2.connectedComponents(low, connectivity=8)
    seed = np.argwhere((lab[ey0:ey1, ex0:ex1] == j) & (low > 0))
    if not len(seed):
        return None
    whole = lab2 == lab2[seed[0][0], seed[0][1]]
    yy, xx = np.nonzero(whole)
    cu, cv_ = float(xx.mean() + ex0), float(yy.mean() + ey0)
    d_eq = 2.0 * math.sqrt(len(xx) / math.pi)
    r_eq = d_eq / 2.0
    if cv_ - r_eq < 1 or cu - r_eq < 1 or cu + r_eq > W - 2:
        return None                                              # cut off by the picture's edge
    width = float(max(np.ptp(xx[yy == r]) + 1 for r in np.unique(yy)))
    tops = []
    for c in range(int(round(cu - ex0 - 0.25 * width)), int(round(cu - ex0 + 0.25 * width)) + 1):
        col = np.nonzero(whole[:, c])[0] if 0 <= c < whole.shape[1] else []
        if len(col) == 0:
            continue
        r1 = int(col[0])
        v1 = float(local[r1, c])
        v0 = float(local[r1 - 1, c]) if r1 > 0 else 0.0
        frac = (v1 - 0.5 * peak) / (v1 - v0) if v1 > v0 and v1 >= 0.5 * peak else 0.5
        tops.append(r1 - min(max(frac, 0.0), 1.0) + 0.5)
    top = float(np.median(tops)) + ey0 if tops else float(yy.min() + ey0)
    return cu, cv_, d_eq, peak, top, width


def _rest_measure(bg, frames, first, rest_box, sign, thr):
    """The ball at rest measured the same way as in flight: what is missing
    from its spot once it has gone (the background, which has it, minus the
    later frames, which don't). Median of a few frames. None if it can't be
    measured (the spot still covered)."""
    x0, y0, x1, y1 = [int(round(c)) for c in rest_box]
    bw, bh = x1 - x0, y1 - y0
    H, W = bg.shape
    m = max(bw, bh)
    X0, Y0, X1, Y1 = max(x0 - m, 0), max(y0 - m, 0), min(x1 + m, W), min(y1 + m, H)
    got = []
    for f in frames[first:first + 6]:
        diff = cv2.GaussianBlur(sign * (bg[Y0:Y1, X0:X1] - f[Y0:Y1, X0:X1].astype(np.float32)), (3, 3), 0)
        mask = (diff > thr).astype(np.uint8)
        k, lab, st, cen = cv2.connectedComponentsWithStats(mask, 8)
        cu, cv_ = 0.5 * (x0 + x1) - X0, 0.5 * (y0 + y1) - Y0
        best = None
        for j in range(1, k):
            x, y, w, h, area = st[j]
            if not (x <= cu <= x + w and y <= cv_ <= y + h):
                continue
            d_eq = 2.0 * math.sqrt(area / math.pi)
            if 0.5 * 0.5 * (bw + bh) <= d_eq <= 1.6 * 0.5 * (bw + bh):
                best = j
        if best is None:
            continue
        mres = _measure_blob(diff, lab, best, st[best][:4], thr)
        if mres is not None and 0.6 * bw <= mres[5] <= 1.5 * bw:
            got.append((mres[0] + X0, mres[4] + Y0, mres[5]))
    if len(got) < 2:
        return None
    u, top, wd = (float(np.median([g[i] for g in got])) for i in range(3))
    return u, top + 0.5 * wd, wd


def track_flight(frames, times, rest_box, scale=2, origin=(0, 0), max_frames=10, impact=None):
    """Find the ball in the frames after impact.

    frames: list of grey pictures (H x W, the kiosk's view); times: their
    times (s, any zero). rest_box: the ball at rest (x0, y0, x1, y1) in
    picture pixels. scale/origin: picture -> sensor pixels (View).
    Returns dict: impact index, rest centre/diameter (sensor px), and obs: a
    list of (time, u, v, diameter) in sensor pixels; or None with "why".
    """
    n = len(frames)
    if n < 6:
        return {"why": "too few frames", "obs": []}
    x0, y0, x1, y1 = [int(round(c)) for c in rest_box]
    bw, bh = x1 - x0, y1 - y0
    d_rest = 0.5 * (bw + bh)
    cxr, cyr = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
    H, W = frames[0].shape[:2]
    # Impact: the first frame where the ball's middle no longer looks like it
    # did in the first frame (the window starts before the shot).
    m = max(2, int(0.2 * min(bw, bh)))
    pa, pb = (max(x0 + m, 0), max(y0 + m, 0)), (min(x1 - m, W), min(y1 - m, H))
    ref = frames[0][pa[1]:pb[1], pa[0]:pb[0]].astype(np.float32)
    if ref.size == 0:
        return {"why": "ball box outside the picture", "obs": []}
    if impact is None:
        for i in range(1, n):
            p = frames[i][pa[1]:pb[1], pa[0]:pb[0]].astype(np.float32)
            if float(np.mean(np.abs(p - ref))) > 12.0:
                impact = i
                break
    if impact is None or impact < 3:
        return {"why": "impact not in the frames (ball never left, or the frames start too late)",
                "obs": [], "impact": impact}
    # Background: median of the frames before the ball's spot first changed
    # (the club arriving, or the ball leaving).
    k0 = max(0, impact - 6)
    bg = np.median(np.stack([f.astype(np.float32) for f in frames[k0:impact]]), axis=0)
    noise = float(np.median(np.abs(frames[max(0, impact - 2)].astype(np.float32) - bg)))
    thr = max(14.0, 6.0 * 1.4826 * noise)
    # The ball's polarity: brighter or darker than what is round it.
    inner = bg[int(cyr - 0.25 * bh):int(cyr + 0.25 * bh) + 1, int(cxr - 0.25 * bw):int(cxr + 0.25 * bw) + 1]
    ring = np.concatenate([bg[max(0, y0 - bh // 2):max(0, y0), max(0, x0):x1].ravel(),
                           bg[max(0, y0):y1, max(0, x0 - bw // 2):max(0, x0)].ravel(),
                           bg[max(0, y0):y1, x1:x1 + bw // 2].ravel()])
    sign = 1.0 if (inner.size == 0 or ring.size == 0 or float(np.mean(inner)) >= float(np.median(ring))) else -1.0
    obs, last = [], None
    misses = 0
    for i in range(impact, min(n, impact + max_frames + 3)):
        diff = cv2.GaussianBlur(sign * (frames[i].astype(np.float32) - bg), (3, 3), 0)
        diff[int(min(H, cyr + 0.6 * bh)):, :] = 0                 # nothing below the ball's spot
        mask = (diff > thr).astype(np.uint8)
        k, lab, st, cen = cv2.connectedComponentsWithStats(mask, 8)
        cands = []
        for j in range(1, k):
            x, y, w, h, area = st[j]
            if area < 4:
                continue
            d_eq = 2.0 * math.sqrt(area / math.pi)
            if not (0.12 * d_rest <= d_eq <= 1.25 * d_rest):    # club head, or a speck
                continue
            if max(w, h) > 3.0 * max(1, min(w, h)):              # shaft, an edge
                continue
            mres = _measure_blob(diff, lab, j, (x, y, w, h), thr)
            if mres is None:
                continue
            cands.append(mres)
        pick = None
        if cands:
            if last is None:
                # First sighting: closest to the spot, a little above it
                pick = min(cands, key=lambda c: math.hypot(c[0] - cxr, c[1] - (cyr - 0.5 * d_rest)))
                if math.hypot(pick[0] - cxr, pick[1] - cyr) > 12 * d_rest:
                    pick = None
            else:
                lu, lv, ld = last[1], last[2], last[3]
                r_last = math.hypot(lu - cxr, lv - cyr)
                ok = [c for c in cands if math.hypot(c[0] - cxr, c[1] - cyr) > r_last - 0.3 * d_rest
                      and c[2] <= 1.3 * ld + 2]
                if len(obs) >= 2:
                    # Along the line so far, the step about as far as the last
                    (au, av), (bu, bv) = (obs[-2][1], obs[-2][2]), (obs[-1][1], obs[-1][2])
                    pu, pv = 2 * bu - au, 2 * bv - av
                    ok = [c for c in ok if math.hypot(c[0] - pu, c[1] - pv) < max(2.5 * d_rest,
                                                                                0.8 * math.hypot(bu - au, bv - av))]
                    if ok:
                        pick = min(ok, key=lambda c: math.hypot(c[0] - pu, c[1] - pv))
                elif ok:
                    pick = min(ok, key=lambda c: math.hypot(c[0] - lu, c[1] - lv))
        if pick is None:
            misses += 1
            if obs and misses >= 2:
                break
            continue
        misses = 0
        last = (times[i], pick[0], pick[1], pick[2], pick[4], pick[5])
        obs.append(last)
        if pick[1] < 2 or pick[0] < 2 or pick[0] > W - 3:
            break                                                # leaving the picture
    sx, sy = origin
    to_s = lambda u, v: (u * scale + sx, v * scale + sy)
    # The ball at rest, measured like the flight (its spot once it has gone),
    # so both share any bias of the measurement; the model's box if not.
    rest = _rest_measure(bg, frames, impact + 5, rest_box, sign, thr) if obs else None
    rest_source = "frames" if rest else "box"
    if rest is None:
        rest = (cxr, cyr, d_rest)
    rest_u, rest_v = to_s(rest[0], rest[1])
    d_rest = rest[2]
    # The ball left after the last frame its spot was unchanged and before
    # the first frame it is seen in flight.
    out = {"impact": impact, "before_time": times[impact - 1],
           "impact_time": obs[0][0] if obs else times[impact],
           "rest": (rest_u, rest_v, d_rest * scale), "rest_source": rest_source,
           "thr": thr, "polarity": "bright" if sign > 0 else "dark",
           # (time, centre u, centre v, diameter, top edge v, width), sensor px
           "obs": [(t, *to_s(u, v), d * scale, top * scale + sy, wd * scale) for t, u, v, d, top, wd in obs]}
    if not obs:
        out["why"] = "ball not seen in the frames after impact"
    return out


# ---------------------------------------------------------------- the angle
def solve_launch(grid, track, speed_prior=None, speed_sigma=None, px_sigma=1.0):
    """Fit launch angle and direction to the tracked frames. speed_prior:
    ball speed (m/s) from the radar, or None (then the ball's shrinking sets
    the speed). Returns dict with launch_angle, launch_dir (deg, right
    positive), speed (m/s), sigma_angle, sigma_dir, frames, quality; or None
    values with "why"."""
    obs = track.get("obs") or []
    res = {"launch_angle": None, "launch_dir": None, "frames": len(obs), "quality": None}
    if len(obs) < (1 if speed_prior else 2):
        res["why"] = track.get("why") or (f"ball seen in {len(obs)} frame after impact (need 2, or 1 "
                                          f"with the radar's ball speed)")
        return res
    t = np.array([o[0] for o in obs])
    U = np.array([[o[1], o[2]] for o in obs])
    D = np.array([o[3] for o in obs])
    top = np.array([o[4] if len(o) > 4 else o[2] - o[3] / 2 for o in obs])
    wid = np.array([o[5] if len(o) > 5 else o[3] for o in obs])
    half = 0.5 * float(track.get("exposure_s") or 0.0)
    t_lo, t_hi = track["before_time"], track["impact_time"]
    d_sig = np.maximum(1.5, 0.12 * np.array([o[5] if len(o) > 5 else o[3] for o in obs]))
    ru, rv, rd = track["rest"]
    # A sighting still overlapping the ball's spot is only part of the ball.
    p_sig = np.where(np.hypot(U[:, 0] - ru, U[:, 1] - rv) < rd, 3.0 * px_sigma, px_sigma)

    def resid(q):
        th, ph, t0, v = q
        P = ball_path(grid, th, ph, t0, v, t)
        uv, dd = grid.project(P)
        # The top edge shows where the ball was at the end of the exposure.
        uv_end, dd_end = grid.project(ball_path(grid, th, ph, t0, v, t + half)) if half else (uv, dd)
        r = [(uv[:, 0] - U[:, 0]) / p_sig, (uv_end[:, 1] - 0.5 * dd_end - top) / p_sig,
             (dd - wid) / d_sig]
        # impact between the last still frame and the first moved one
        span = max(t_hi - t_lo, 1e-4)
        r.append(np.array([max(0.0, t_lo - t0) / (0.25 * span), max(0.0, t0 - t_hi) / (0.25 * span)]))
        if speed_prior is not None:
            r.append(np.array([(v - speed_prior) / (speed_sigma or 1.0)]))
        return np.concatenate(r)

    # Coarse search, then Levenberg-Marquardt.
    v_try = [speed_prior] if speed_prior else [15.0, 30.0, 45.0, 60.0, 75.0]
    best = None
    for v0 in v_try:
        for th in np.radians(np.arange(-6, 62, 3.0)):
            for ph in np.radians(np.arange(-24, 25, 4.0)):
                q = np.array([th, ph, 0.5 * (t_lo + t_hi), v0])
                c = float(np.sum(resid(q) ** 2))
                if best is None or c < best[0]:
                    best = (c, q)
    q = best[1].copy()
    lam = 1e-2
    cost = float(np.sum(resid(q) ** 2))
    steps = np.array([1e-4, 1e-4, 1e-5, 1e-3])
    for _ in range(60):
        r0 = resid(q)
        J = np.empty((r0.size, 4))
        for k in range(4):
            dq = np.zeros(4); dq[k] = steps[k]
            J[:, k] = (resid(q + dq) - r0) / steps[k]
        A = J.T @ J
        g = J.T @ r0
        improved = False
        for _ in range(8):
            try:
                delta = -np.linalg.solve(A + lam * np.diag(np.diag(A) + 1e-9), g)
            except np.linalg.LinAlgError:
                break
            qn = q + delta
            qn[3] = max(qn[3], 1.0)
            cn = float(np.sum(resid(qn) ** 2))
            if cn < cost:
                q, cost, lam, improved = qn, cn, max(lam / 3, 1e-6), True
                break
            lam *= 4
        if not improved or np.max(np.abs(delta) / (steps * 10)) < 1e-3:
            break
    r = resid(q)
    J = np.empty((r.size, 4))
    for k in range(4):
        dq = np.zeros(4); dq[k] = steps[k]
        J[:, k] = (resid(q + dq) - r) / steps[k]
    dof = max(1, r.size - 4)
    s2 = max(1.0, float(np.sum(r ** 2)) / dof)
    try:
        cov = np.linalg.inv(J.T @ J) * s2
        sig = np.sqrt(np.maximum(np.diag(cov), 0))
    except np.linalg.LinAlgError:
        sig = np.array([np.inf] * 4)
    th, ph, t0, v = q
    res.update({
        "launch_angle": round(math.degrees(th), 1),
        "launch_dir": round(-math.degrees(ph), 1),          # right positive
        "speed_mps": round(float(v), 2), "t0": float(t0),
        "sigma_angle": round(math.degrees(sig[0]), 2), "sigma_dir": round(math.degrees(sig[1]), 2),
        "fit_rms_px": round(math.sqrt(float(np.mean(r[:2 * len(obs)] ** 2))) * px_sigma, 2),
    })
    sa = res["sigma_angle"]
    res["quality"] = ("good" if len(obs) >= 3 and sa <= 1.0 else
                      "fair" if sa <= 2.5 else "poor")
    if not (-10.0 <= res["launch_angle"] <= 70.0):
        res["quality"] = "poor"
        res["why"] = "angle out of any club's range"
    return res


def fuse_launch(cam, ti):
    """Combine the camera's and the TI radar's launch angle (each a dict with
    launch_angle and a sigma; either may be missing). Inverse-variance
    weighted when both are there and agree; when they disagree by more than
    3 sigma, the more certain one. Returns (angle, source, sigma)."""
    c = cam if cam and cam.get("launch_angle") is not None and cam.get("quality") in ("good", "fair") else None
    r = ti if ti and ti.get("launch_angle") is not None else None
    if c is None and r is None:
        return None, None, None
    if r is None:
        return c["launch_angle"], "camera", c.get("sigma_angle")
    sr = r.get("sigma_angle") or 1.5
    if c is None:
        return r["launch_angle"], "ti", sr
    sc = max(c.get("sigma_angle") or 1.5, 0.3)
    if abs(c["launch_angle"] - r["launch_angle"]) > 3.0 * math.hypot(sc, sr):
        return (c["launch_angle"], "camera (TI disagreed)", sc) if sc < sr else \
            (r["launch_angle"], "ti (camera disagreed)", sr)
    w1, w2 = 1.0 / sc ** 2, 1.0 / sr ** 2
    return round((w1 * c["launch_angle"] + w2 * r["launch_angle"]) / (w1 + w2), 1), "camera+ti", \
        round(1.0 / math.sqrt(w1 + w2), 2)


# ---------------------------------------------------------------- calibration
class FocalCalibration:
    """The lens's focal length in sensor pixels, from balls at rest at a
    measured distance from the lens: f = diameter_px x distance / 42.67 mm.

    Two kinds of measurement: the ball model's box when a ball goes Ready
    (kind "box", to get going), and after each shot the ball's width measured
    from its empty spot (kind "shot": the same measurement the flight uses,
    so the more exact; used once there are 3). A running median of the last
    of each, saved to a small JSON file so it survives restarts
    (camera_grid.json in the shots folder). A focal length from a printed grid
    (or set by hand) can be written there as "focal_px" with "source": "grid";
    it is then kept and not overwritten by balls."""

    def __init__(self, path, distance_m, keep=40):
        self.path, self.distance, self.keep = path, float(distance_m), keep
        self.samples, self.shot_samples, self.fixed = [], [], None
        try:
            with open(path) as fh:
                d = json.load(fh)
            if d.get("source") == "grid" and d.get("focal_px"):
                self.fixed = float(d["focal_px"])
            self.samples = [float(x) for x in d.get("samples", [])][-keep:]
            self.shot_samples = [float(x) for x in d.get("shot_samples", [])][-keep:]
        except (OSError, ValueError, TypeError):
            pass

    @property
    def source(self):
        return "grid" if self.fixed else "shots" if len(self.shot_samples) >= 3 else \
            "balls" if len(self.samples) >= 3 else None

    @property
    def focal(self):
        if self.fixed:
            return self.fixed
        if len(self.shot_samples) >= 3:
            return float(np.median(self.shot_samples))
        if len(self.samples) >= 3:
            return float(np.median(self.samples))
        return None

    def add(self, diameter_px, kind="box"):
        """A ball at rest at the measured distance, diameter in sensor px."""
        if self.fixed or not (4 <= diameter_px <= 400):
            return
        f = diameter_px * self.distance / BALL_D
        if kind == "shot":
            self.shot_samples = (self.shot_samples + [f])[-self.keep:]
        else:
            self.samples = (self.samples + [f])[-self.keep:]
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "w") as fh:
                json.dump({"focal_px": round(self.focal, 1) if self.focal else None, "source": self.source,
                           "distance_m": self.distance, "samples": [round(x, 1) for x in self.samples],
                           "shot_samples": [round(x, 1) for x in self.shot_samples]}, fh, indent=1)
        except OSError:
            pass


def camera_launch(frames, times, rest_box, view_scale, view_origin, focal_px, height_m,
                  ball_height_m=0.021, speed_mps=None, speed_sigma=None, azimuth_deg=0.0,
                  exposure_s=0.0, track=None):
    """Everything for one shot: track the ball (or use a track already made),
    place the grid, fit the angle."""
    if track is None:
        track = track_flight(frames, times, rest_box, view_scale, view_origin)
    track["exposure_s"] = exposure_s
    out = {"track": {k: v for k, v in track.items() if k != "obs"}, "obs": track.get("obs", [])}
    if not focal_px:
        out.update(launch_angle=None, launch_dir=None, quality=None,
                   why="lens not calibrated yet (needs a few balls at rest at the measured distance)")
        return out
    if "rest" not in track:
        out.update(launch_angle=None, launch_dir=None, quality=None, why=track.get("why"))
        return out
    u0, v0, d0 = track["rest"]
    grid = CameraGrid(focal_px, height_m, ball_height_m).setup(u0, v0, d0)
    res = solve_launch(grid, track, speed_mps, speed_sigma)
    if res.get("launch_dir") is not None:
        res["launch_dir"] = round(res["launch_dir"] - azimuth_deg, 1)
    res.update(ball_range_m=round(grid.range0, 3), camera_pitch_deg=round(grid.pitch_deg, 2))
    out.update(res)
    return out
