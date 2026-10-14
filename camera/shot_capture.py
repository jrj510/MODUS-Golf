#!/usr/bin/env python3
"""
Shot capture for the launch monitor: Raspberry Pi 5 + OV9281 camera.

How it works
    1. SEARCHING  The trained model checks a few frames a second for a ball.
    2. BALL       A ball is visible but has not settled yet.
    3. READY      The ball has sat still. The script is armed.
    4. SHOT       A trigger fires. The frames from just before and just after
                  are saved to a folder under shots/.
    Then it goes back to SEARCHING.

The camera runs at full speed the whole time and the most recent frames are
always held in memory, so the moment of impact is already recorded when the
trigger arrives.

Triggers (any of them fires a capture)
    sound   the SparkFun sound detector GATE pin on GPIO17 (only when READY)
    motion  the picture changes where the ball was sitting (only when READY)
    key     press Enter in this terminal (any time, for testing)

Live view:  http://modus.local:8000

Run (inside vision-env):
    python3 shot_capture.py --model ~/openflight/models/golf_ball_yolo11n_new_256.onnx
    python3 shot_capture.py --model <path> --trigger motion,key
"""

import argparse
import collections
import json
import os
import shutil
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np
from picamera2 import Picamera2
from ultralytics import YOLO

WIDTH, HEIGHT = 640, 400
SOUND_GPIO = 17

PAGE = (
    b"<html><body style='margin:0;background:#111;text-align:center'>"
    b"<img src='/stream.mjpg' style='max-width:100%'></body></html>"
)


class FrameBuffer:
    def __init__(self):
        self.jpeg = None
        self.cond = threading.Condition()

    def put(self, jpeg):
        with self.cond:
            self.jpeg = jpeg
            self.cond.notify_all()

    def get(self):
        with self.cond:
            self.cond.wait(timeout=2)
            return self.jpeg


STREAM = FrameBuffer()


class StreamHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/stream.mjpg":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(PAGE)
            return
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        try:
            while True:
                jpeg = STREAM.get()
                if jpeg is None:
                    continue
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n")
                self.wfile.write(jpeg)
                self.wfile.write(b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):
        pass


class Shared:
    """State shared between the camera thread and the main loop."""

    def __init__(self, maxlen):
        self.lock = threading.Lock()
        self.frames = collections.deque(maxlen=maxlen)  # (time, sensor_ns, image)
        self.latest = None
        self.running = True
        self.armed = False
        self.roi = None           # (x0, y0, x1, y1) where the ball is sitting
        self.roi_ref = None       # what that patch looked like when armed
        self.trigger_time = None  # when a trigger fired
        self.trigger_source = None
        self.pending = None       # frames handed over for saving
        self.camera_fps = 0.0
        self.exposure = (None, None)  # (microseconds, gain) the sensor last used

    def trigger(self, source, need_armed=True):
        with self.lock:
            if self.trigger_time is not None or self.pending is not None:
                return  # already capturing a shot
            if need_armed and not self.armed:
                return
            self.trigger_time = time.monotonic()
            self.trigger_source = source


# --- Exposure ---------------------------------------------------------------
#
# libcamera's own auto exposure meters the whole picture and keeps changing
# while the ball sits READY. Outdoors that left the picture washed out, and any
# change while READY also alters the patch the motion trigger compares against.
# So exposure is set by hand from a ladder of shutter/gain pairs, picked by
# measuring the area around the ball, and held still while armed or recording.
#
# The ladder and brightness limits are OpenFlight's (camera/auto_exposure.py),
# tested on the same OV9281, with two darker steps added for full sun. Short
# shutters also keep a flying ball sharp; gain is raised before shutter.
EXPOSURE_STEPS = (
    (50, 1.0), (100, 1.0), (100, 2.0), (150, 3.0), (200, 3.0),
    (250, 4.0),     # outdoor sun
    (300, 5.0),
    (350, 6.0),     # outdoor shade
    (400, 8.0),
    (450, 10.0),    # evening
    (500, 12.0),    # indoor bright
    (500, 15.0),
    (650, 15.0),    # indoor dark
    (800, 18.0), (1000, 20.0), (1250, 16.0))
DEFAULT_STEP = (500, 12.0)
EXPOSURE_FILE = "exposure.json"   # last good setting, kept in the shots folder


def _metering_area(args):
    """Where brightness is measured: the tapped search area plus a margin (the
    mat around the ball), or the centre-lower part of the picture."""
    if getattr(args, "search_area", None):
        x0, y0, x1, y1 = _search_area(args)
        return (max(x0 - 60, 0), max(y0 - 40, 0), min(x1 + 60, WIDTH), min(y1 + 40, HEIGHT))
    return (int(WIDTH * 0.2), int(HEIGHT * 0.45), int(WIDTH * 0.8), int(HEIGHT * 0.9))


def measure_exposure(gray, area):
    """Rate the brightness inside area: (status, stats). Status is "good",
    "marginal", "too_bright" or "too_dark"."""
    x0, y0, x1, y1 = area
    region = gray[y0:y1:2, x0:x1:2]
    if region.size == 0:
        return "marginal", {}
    p10, median, p90 = (float(v) for v in np.percentile(region, (10, 50, 90)))
    clipped = float(np.mean(region >= 250)) * 100.0
    stats = {"median": round(median), "p10": round(p10), "p90": round(p90),
             "clipped_pct": round(clipped, 1)}
    if clipped >= 8.0 or median >= 205.0:
        return "too_bright", stats
    if median < 35.0 or p90 < 70.0:
        return "too_dark", stats
    if clipped <= 2.0 and 45.0 <= median <= 180.0:
        return "good", stats
    return "marginal", stats


class ExposureControl:
    """Picks the camera's shutter and gain from EXPOSURE_STEPS.

    At start-up it jumps quickly (a check every 0.3 s) until the ball area is
    well exposed. After that it checks every 2 s and only moves when the area
    has been too bright or too dark twice in a row, so it doesn't hunt. Nothing
    changes while the ball is READY or a shot is being recorded.
    """

    STARTUP_ADJUSTMENTS = 8
    SETTLE_S = 0.3
    CHECK_S = 2.0

    def __init__(self, camera_controls, args):
        self.args, self.cam = args, None
        frame_us = int(1_000_000 / args.fps)
        lo_us, hi_us = _limits(camera_controls, "ExposureTime", 1, frame_us - 100)
        lo_g, hi_g = _limits(camera_controls, "AnalogueGain", 1.0, 16.0)
        hi_us = min(hi_us, frame_us - 100)    # a shutter can't outlast its frame
        steps = []
        for us, gain in EXPOSURE_STEPS:
            step = (int(min(max(us, lo_us), hi_us)), float(min(max(gain, lo_g), hi_g)))
            if not steps or step[0] * step[1] > steps[-1][0] * steps[-1][1]:
                steps.append(step)
        self.steps = steps
        self.index = self._nearest(self._saved() or DEFAULT_STEP)
        self.startup_left = self.STARTUP_ADJUSTMENTS
        self.bad_checks = 0
        self.next_check = 0.0
        self.state, self.message, self.stats = "starting", "Setting exposure", {}
        self._saved_index = None

    # Settings ----------------------------------------------------------------
    def controls(self):
        """libcamera controls for the current step (manual: auto exposure off)."""
        us, gain = self.steps[self.index]
        return {"AeEnable": False, "ExposureTime": us, "AnalogueGain": gain}

    def _nearest(self, step):
        signal = max(step[0] * step[1], 1.0)
        return min(range(len(self.steps)),
                   key=lambda i: abs(np.log(self.steps[i][0] * self.steps[i][1] / signal)))

    def _path(self):
        return os.path.join(getattr(self.args, "out", "shots"), EXPOSURE_FILE)

    def _saved(self):
        try:
            with open(self._path()) as f:
                s = json.load(f)
            if int(s.get("fps", 0)) == int(self.args.fps):
                return (float(s["exposure_us"]), float(s["gain"]))
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def _save(self):
        if self._saved_index == self.index:
            return
        us, gain = self.steps[self.index]
        try:
            os.makedirs(os.path.dirname(self._path()) or ".", exist_ok=True)
            with open(self._path(), "w") as f:
                json.dump({"fps": self.args.fps, "exposure_us": us, "gain": gain}, f)
            self._saved_index = self.index
        except OSError as e:
            print(f"Could not save the exposure setting: {e}")

    # Control loop --------------------------------------------------------------
    def update(self, gray, now, hold=False):
        """Call a few times a second with the latest frame. hold=True while the
        ball is READY or a shot is being recorded. Returns True when the
        exposure was just changed (frames for the next ~0.1 s are in between)."""
        if self.cam is None or gray is None or hold or now < self.next_check:
            return False
        status, self.stats = measure_exposure(gray, _metering_area(self.args))
        startup = self.startup_left > 0
        if status in ("good", "marginal"):
            self.state = "ok"
            self.message = "" if status == "good" else "Exposure usable"
            self.startup_left, self.bad_checks = 0, 0
            if status == "good":
                self._save()
            self.next_check = now + self.CHECK_S
            return False
        if not startup:
            self.bad_checks += 1
            if self.bad_checks < 2:            # wait for a second opinion
                self.next_check = now + 0.5
                return False
        self.bad_checks = 0
        target = self._target(status, self.stats, big_jumps=startup)
        if target == self.index:               # already at the end of the ladder
            self.state = "limit"
            self.message = ("Too bright for the camera even at its shortest exposure: "
                            "shade the hitting area or fit an ND filter to the lens"
                            if status == "too_bright" else
                            "Too dark for the camera even at its longest exposure: "
                            "add light on the ball")
            self.startup_left = 0
            self.next_check = now + self.CHECK_S
            print(f"Exposure: {self.message} ({self.stats})")
            return False
        old = self.steps[self.index]
        self.index = target
        self.startup_left = max(self.startup_left - 1, 0)
        self.state = "adjusting"
        self.message = "Adjusting exposure"
        self.cam.set_controls(self.controls())
        self.next_check = now + self.SETTLE_S
        us, gain = self.steps[self.index]
        print(f"Exposure: {old[0]} us x{old[1]:g} -> {us} us x{gain:g} "
              f"({status.replace('_', ' ')}: median {self.stats.get('median')}, "
              f"{self.stats.get('clipped_pct')}% clipped)")
        return True

    def _target(self, status, stats, big_jumps):
        """The step to move to: aims the area's median at about 110. A clipped
        picture hides how bright it really is, so it steps down hard."""
        us, gain = self.steps[self.index]
        median = max(float(stats.get("median", 110)), 1.0)
        factor = min(max(110.0 / median, 1 / 8), 8.0)
        if stats.get("clipped_pct", 0) > 40:
            factor = min(factor, 0.25)
            big_jumps = True
        want = self._nearest((us * gain * factor, 1.0))
        if status == "too_bright":
            want = min(want, self.index - 1)
        else:
            want = max(want, self.index + 1)
        if not big_jumps:                      # small, steady corrections
            want = min(max(want, self.index - 2), self.index + 2)
        return min(max(want, 0), len(self.steps) - 1)

    def summary(self, actual=(None, None)):
        """For the screen: what is set, what the sensor used, and any warning."""
        us, gain = self.steps[self.index]
        return {"exposure_us": us, "gain": gain, "state": self.state,
                "message": self.message, "median": self.stats.get("median"),
                "clipped_pct": self.stats.get("clipped_pct"),
                "actual_us": actual[0], "actual_gain": actual[1]}


def _limits(camera_controls, name, lo, hi):
    """(min, max) of a camera control as picamera2 reports it."""
    try:
        cmin, cmax = camera_controls[name][0], camera_controls[name][1]
        return (max(lo, cmin) if cmin else lo), (min(hi, cmax) if cmax else hi)
    except (KeyError, TypeError, IndexError):
        return lo, hi


def add_exposure_args(p):
    """Exposure options (shared with kiosk.py). --exposure / --gain still fix
    the exposure by hand."""
    p.add_argument("--exposure-mode", default="ladder", choices=("ladder", "auto"),
                   help="ladder: pick shutter and gain from tested steps by measuring the area "
                        "around the ball (default); auto: libcamera's own auto exposure")


def start_camera(args):
    """Open and start the OV9281 at args.fps. Returns (cam, exposure control or None)."""
    frame_us = int(1_000_000 / args.fps)
    controls = {"FrameDurationLimits": (frame_us, frame_us)}
    cam = Picamera2()
    ae = None
    if args.exposure > 0:                      # fixed by hand
        controls["ExposureTime"] = min(args.exposure, frame_us - 100)
        if args.gain > 0:
            controls["AnalogueGain"] = args.gain
    elif getattr(args, "exposure_mode", "ladder") == "ladder":
        ae = ExposureControl(getattr(cam, "camera_controls", {}) or {}, args)
        controls.update(ae.controls())
        us, gain = ae.steps[ae.index]
        print(f"Exposure: starting at {us} us x{gain:g} (ladder of {len(ae.steps)} steps)")
    elif args.gain > 0:
        controls["AnalogueGain"] = args.gain
    cam.configure(cam.create_video_configuration(
        main={"size": (WIDTH, HEIGHT), "format": "YUV420"},
        sensor={"output_size": (WIDTH, HEIGHT), "bit_depth": args.bit_depth},
        controls=controls, buffer_count=8))
    cam.start()
    if ae is not None:
        ae.cam = cam
    time.sleep(1.0)
    return cam, ae


# --- Ball finding and the READY logic -------------------------------------------

def new_track():
    """Bookkeeping for the ready logic."""
    return {"center": None, "still_since": None, "lost_since": None, "box": None,
            "far": False, "confirmed_at": None, "blob": False,
            "misses": 0,          # checks in a row the followed ball wasn't found
            "spots": [],          # new-ball candidates: [center, checks seen, diameter, box]
            "blobs": [],          # the same, from the small-ball finder alone
            "rivals": [],         # the same, for things other than the followed ball
            "takeover": [],       # balls set down elsewhere while following an unsure one
            "sure": False,        # the followed ball was more than a small-ball-finder guess
            "mine": None,         # (sum, count) of the followed ball's model confidence
            "source": None,       # which finder placed the box, for the screen and log
            "found_by": None}     # which finder first took this ball on, for the log


def _patch_diff(sh, gray):
    """How much the patch where the ball sat has changed (0-255), or None."""
    roi, ref = sh.roi, sh.roi_ref
    if roi is None or ref is None:
        return None
    x0, y0, x1, y1 = roi
    patch = gray[y0:y1, x0:x1]
    if patch.shape != ref.shape:
        return None
    return float(cv2.absdiff(patch, ref).mean())


def _set_patch(sh, gray, ball):
    """Remember the middle of the ball's box for the motion trigger."""
    w, h = ball[2] - ball[0], ball[3] - ball[1]
    x0 = max(int(ball[0] + 0.2 * w), 0)
    y0 = max(int(ball[1] + 0.2 * h), 0)
    x1 = min(int(ball[2] - 0.2 * w), WIDTH)
    y1 = min(int(ball[3] - 0.2 * h), HEIGHT)
    if x1 > x0 and y1 > y0:
        sh.roi = None
        sh.roi_ref = gray[y0:y1, x0:x1].copy()
        sh.roi = (x0, y0, x1, y1)


def add_blob_args(p):
    """Options for the small-ball finder (shared with kiosk.py)."""
    p.add_argument("--blob", action="store_true",
                   help="also find a distant ball the model misses (a small spot that stands out from the mat)")
    p.add_argument("--blob-contrast", type=float, default=18.0,
                   help="how much the ball must differ from the mat around it, percent of its brightness")
    p.add_argument("--blob-min-radius", type=float, default=3.0, help="smallest ball radius, pixels")
    p.add_argument("--blob-max-radius", type=float, default=25.0, help="largest ball radius, pixels")
    p.add_argument("--search-area", default=None,
                   help="only look for the ball inside x0,y0,x1,y1 (pixels): the mat")


def add_tracking_args(p):
    """Options that keep the ball box on the ball (shared with kiosk.py)."""
    p.add_argument("--confirm-checks", type=int, default=2,
                   help="times a NEW ball must be seen at the same spot before the box goes on it")
    p.add_argument("--miss-checks", type=int, default=3,
                   help="checks the followed ball may go unseen before the box is dropped")
    p.add_argument("--keep-conf", type=float, default=0.3,
                   help="lower model confidence accepted for the ball already being followed")
    p.add_argument("--switch-checks", type=int, default=4,
                   help="times something else must be seen, rated clearly higher on average "
                        "(0.1 more confidence) than the followed ball, before the box moves to it")
    p.add_argument("--place-contrast", type=float, default=0.2,
                   help="hitting zone: how much brighter than the empty zone (relative to the "
                        "pixels around it, 0.2 = 20%%) a spot must become to count as a ball set down")
    p.add_argument("--assist-conf", type=float, default=0.15,
                   help="lowest model confidence that still backs up a ball seen being set down "
                        "(or one that was tapped)")


def _search_area(args):
    """The --search-area box (x0,y0,x1,y1 in pixels), or the whole frame."""
    area = getattr(args, "search_area", None)
    if not area:
        return 0, 0, WIDTH, HEIGHT
    x0, y0, x1, y1 = [int(float(v)) for v in str(area).split(",")]
    return max(x0, 0), max(y0, 0), min(x1, WIDTH), min(y1, HEIGHT)


def _inside_area(args, box):
    """True if a box from the model could be the ball: not much taller than
    wide, at most twice as wide as tall (a ball sitting down in turf shows
    only its top, so its box comes out wide and short), not huge, and (with
    --search-area) entirely inside the search area."""
    w, h = box[2] - box[0], box[3] - box[1]
    if w <= 0 or h <= 0 or not (0.6 <= w / h <= 2.0) or max(w, h) > 120:
        return False
    x0, y0, x1, y1 = _search_area(args)
    m = 4   # small allowance at the edges
    return box[0] >= x0 - m and box[1] >= y0 - m and box[2] <= x1 + m and box[3] <= y1 + m


def find_ball_spot(gray, args, near=None):
    """The most ball-like spot (see find_ball_spots), as a box, or None."""
    spots = find_ball_spots(gray, args, near=near, limit=1)
    return spots[0][0] if spots else None


def find_ball_spots(gray, args, near=None, limit=3):
    """Find a small ball the model misses. Returns up to `limit` (box, score)
    pairs, most ball-like first.

    Lit from above, a ball on the mat has a bright top and a dark, shadowed
    bottom, so it is found as a small, roughly round spot that differs from the
    mat around it (brighter or darker). The mat's own edges run across the
    picture, so each pixel is compared with the average of its own row; long
    edges then vanish while the ball stands out.

    A dark spot on its own (a divot, a shadow, a hole in the mat) is only
    accepted right next to a ball already being followed, never as a new ball.
    """
    x0, y0, x1, y1 = _search_area(args)
    if near is not None:   # only look around where the ball was last seen
        r = 40
        x0, y0 = max(x0, int(near[0]) - r), max(y0, int(near[1]) - r)
        x1, y1 = min(x1, int(near[0]) + r), min(y1, int(near[1]) + r)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return []
    img = cv2.GaussianBlur(gray[y0:y1, x0:x1].astype(np.float32), (5, 5), 0)  # calm the noise
    dev = img - cv2.blur(img, (51, 1))
    # The threshold follows the picture's brightness, so a dark, fast-exposure
    # frame works as well as a bright one (18 means 18% of the mat's brightness).
    c = getattr(args, "blob_contrast", 18.0) * max(float(img.mean()), 20.0) / 100.0
    rmin, rmax = getattr(args, "blob_min_radius", 3.0), getattr(args, "blob_max_radius", 25.0)
    kernel = np.ones((3, 3), np.uint8)

    def parts(mask):
        """Connected spots in a mask: (x0, y0, x1, y1, pixel count)."""
        mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, kernel)
        n, _, st, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        return [(st[i][0], st[i][1], st[i][0] + st[i][2], st[i][1] + st[i][3], st[i][4])
                for i in range(1, n)]

    bright, dark = parts(dev > c), parts(dev < -c)
    # A ball lit from above is a bright cap with its own shadow right under it:
    # join each such pair into one candidate.
    candidates = [(b, False) for b in bright]
    if near is not None:
        candidates += [(d, False) for d in dark]
    for b in bright:
        for d in dark:
            overlap = min(b[2], d[2]) - max(b[0], d[0])
            if overlap > 0.5 * min(b[2] - b[0], d[2] - d[0]) and 0 <= d[1] - b[3] <= 3 \
                    and d[1] >= b[1]:
                joined = (min(b[0], d[0]), b[1], max(b[2], d[2]), d[3], b[4] + d[4])
                candidates.append((joined, True))

    found = []
    for (bx0, by0, bx1, by1, count), pair in candidates:
        bw, bh = bx1 - bx0, by1 - by0
        r = (bw + bh) / 4.0
        if not (rmin <= r <= rmax) or not (0.6 <= bw / max(bh, 1) <= 1.7):
            continue
        if count / float(bw * bh) < 0.45:
            continue
        patch = np.abs(dev[by0:by1, bx0:bx1])
        score = float(patch[patch > c].mean()) if (patch > c).any() else 0.0
        score *= 1.0 - min(abs(np.log(bw / max(bh, 1))), 0.5)   # rounder is better
        if pair:
            score *= 1.5               # bright top and shadowed bottom: looks like a ball
        if near is not None:
            cx, cy = (bx0 + bx1) / 2 + x0, (by0 + by1) / 2 + y0
            score /= 1.0 + np.hypot(cx - near[0], cy - near[1]) / 20.0
        if score > 0:
            found.append(([int(bx0 + x0), int(by0 + y0), int(bx1 + x0), int(by1 + y0)], score))
    # Best first; a bright cap and the pair it belongs to are one ball, so a
    # spot overlapping a better one is dropped.
    found.sort(key=lambda f: -f[1])
    kept = []
    for box, score in found:
        if all(np.hypot(*np.subtract(_center(box), _center(k))) > 0.5 * _diameter(k) for k, _ in kept):
            kept.append((box, score))
        if len(kept) >= limit:
            break
    return kept


def _center(box):
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def _diameter(box):
    return ((box[2] - box[0]) + (box[3] - box[1])) / 2.0


def _matches_track(box, trk, strict=False):
    """True if box is plausibly the ball being followed: close to where it was
    last seen (within 2.5 ball widths, at least 20 px) and about the same size.
    strict (used for the small-ball finder): within about half a ball width,
    so it can't creep sideways onto a bump in the turf next to the ball."""
    ref = trk.get("box")
    if ref is None:
        return False
    d_ref, d = max(_diameter(ref), 1.0), _diameter(box)
    (cx, cy), (rx, ry) = _center(box), _center(ref)
    reach = max(0.6 * d_ref, 5.0) if strict else max(2.5 * d_ref, 20.0)
    return np.hypot(cx - rx, cy - ry) <= reach and 0.6 <= d / d_ref <= 1.7


def _confirmed(trk, found, args, key="spots", need=None, hold=1, better_than=0.0, slow=None):
    """Count sightings per spot; return the box of a spot seen at least `need`
    times (default --confirm-checks) whose average confidence is at least
    better_than, else None. slow=(n, rating): a spot rated lower is still
    accepted once it has been seen n times with at least that average.

    found: (box, confidence) pairs from this check. A spot not seen keeps its
    count for `hold` checks (the real ball is missed now and then), then is
    forgotten. Only a spot seen this check can be returned, and of several the
    one the model rates highest on average wins. So a one-off false detection
    never gets the box, and of two look-alikes the more ball-like one is chosen.
    """
    old, kept = list(trk.get(key, [])), []
    for box, conf in found:
        c = _center(box)
        prev = next((s for s in old if np.hypot(c[0] - s["c"][0], c[1] - s["c"][1])
                     <= max(1.5 * s["d"], 12.0)), None)
        if prev is not None:
            old.remove(prev)
        kept.append({"c": c, "d": _diameter(box), "box": box, "seen": True, "idle": 0,
                     "n": (prev["n"] if prev else 0) + 1,
                     "total": (prev["total"] if prev else 0.0) + conf})
    kept += [dict(s, seen=False, idle=s["idle"] + 1) for s in old if s["idle"] < hold]
    trk[key] = kept
    need = max(need if need is not None else getattr(args, "confirm_checks", 2), 1)
    ready = [s for s in kept if s["seen"] and (
        (s["n"] >= need and s["total"] / s["n"] >= better_than)
        or (slow is not None and s["n"] >= slow[0] and s["total"] / s["n"] >= slow[1]))]
    return max(ready, key=lambda s: s["total"] / s["n"])["box"] if ready else None


def _seen(trk, box, blob=False, keep_rivals=False, conf=None, source=None, sure=None):
    """The followed (or newly confirmed) ball was found. sure (set when a new
    ball is taken on): False if only the small-ball finder vouched for it."""
    trk["misses"], trk["spots"], trk["blobs"], trk["blob"] = 0, [], [], blob
    trk["source"] = source or ("spot finder" if blob else
                               (f"model {conf:.2f}" if conf is not None else "model"))
    if sure is not None:                      # a new ball taken on
        trk["sure"], trk["takeover"], trk["found_by"] = sure, [], trk["source"]
    if not keep_rivals:
        trk["rivals"], trk["mine"] = [], None
    return box


def detect_ball(model, gray, args, trk, zone=None):
    """The ball's box [x0, y0, x1, y1], or None.

    The box stays on one ball:
      - while a ball is being followed, only a detection near it, of about its
        size, counts (at a lower confidence, --keep-conf);
      - if it goes unseen, nothing else is taken for --miss-checks checks (the
        READY logic keeps the old box meanwhile);
      - a new ball must be seen at the same spot --confirm-checks times (one
        or two misses in between are allowed);
      - while the followed ball is still seen, the box only moves to something
        else that has been seen --switch-checks times and that the model rates
        clearly higher on average (the box had settled on a tee, say).

    How a new ball is recognised:
      - the model on its own needs its full --conf;
      - with a hitting zone (zone: a ZoneWatch, see below), a ball being SET
        DOWN in the zone is noticed: a still, ball-sized spot that wasn't
        there in the empty zone. It is taken once the model (at any
        confidence) or the small-ball finder also sees a ball right there,
        or on its own after a few more checks;
      - the small-ball finder (--blob) on its own needs two extra sightings,
        and isn't used on its own once the zone is known to be empty (then
        anything it finds there is part of the mat).
    A tap on the Camera view (trk["hint"]) takes the ball found right there
    at once. With --search-area, anything outside the area is ignored.
    """
    following = trk.get("box") is not None and trk["center"] is not None
    use_blob = getattr(args, "blob", False)
    in_zone = (zone is not None and zone.active and getattr(args, "search_area", None)
               and 0 < getattr(args, "tile", 0) < WIDTH)

    if trk.get("hint") is not None:
        box = _ball_at_hint(model, gray, args, trk)
        if box is not None:
            return box

    placed = zone.placed if (in_zone and not following) else []
    if model is None:
        cands = []
    elif in_zone:
        cands = _zone_model_candidates(model, gray, args, trk, following, placed)
    else:
        cands = list(_model_candidates(model, gray, args, trk, following))
    strong = [c for c in cands if c[1] >= args.conf]

    if following and in_zone and not trk.get("sure"):
        # The box is on something only the small-ball finder vouched for (at
        # start-up it may be a look-alike on the mat). A ball seen being set
        # down elsewhere in the zone takes over.
        elsewhere = [p for p in zone.placed if not _matches_track(p[0], trk)]
        found = _new_ball_evidence(gray, args, [], elsewhere, use_blob)
        box = _confirmed(trk, [(b, s) for b, s, _ in found], args, key="takeover", hold=2,
                         better_than=args.conf, slow=(getattr(args, "confirm_checks", 2) + 3, 0.4))
        if box is not None:
            _, rating, source = next(f for f in found if f[0] is box)
            trk["switched"], trk["far"] = True, True     # update_ready starts over on it
            return _seen(trk, box, blob=source.endswith("spot finder"), conf=rating,
                         source=source, sure=True)

    if following:
        # A ball that is lying still doesn't move: only a find right on it
        # counts, so a missed check can't hand the box to a look-alike a ball
        # or two away. (A new ball is only taken once it was seen at the same
        # spot twice, so it is lying still from the start; one that rolls off
        # is dropped after --miss-checks and found again where it stops.)
        mine = [c for c in cands if _matches_track(c[0], trk, strict=True)]
        if mine:
            box, conf, far = max(mine, key=lambda c: c[1])
            total, n = trk.get("mine") or (0.0, 0)
            trk["mine"] = (total + conf, n + 1)          # the followed ball's average rating
            # Something else at a steady spot takes over once it has been seen
            # --switch-checks times and the model rates it, on average, clearly
            # higher (0.1) than the followed ball: e.g. the box had settled on
            # a tee before the ball was put down. Two equally ball-like things
            # never trade places.
            others = [c for c in cands if not _matches_track(c[0], trk)]
            rival = _confirmed(trk, [(b, c) for b, c, _ in others], args, key="rivals",
                               need=getattr(args, "switch_checks", 4), hold=8,
                               better_than=max(args.conf, (total + conf) / (n + 1) + 0.1))
            if rival is not None:
                trk["far"] = next(f for b, _, f in others if b is rival)
                trk["switched"] = True          # update_ready starts over on it
                return _seen(trk, rival, conf=next(c for b, c, _ in others if b is rival), sure=True)
            trk["far"] = far
            return _seen(trk, box, keep_rivals=True, conf=conf)

    if following and use_blob:
        # The model missed the ball it was following: try the small-ball
        # finder right where it was, and only accept a spot right there.
        box = find_ball_spot(gray, args, near=_center(trk["box"]))
        if box and _matches_track(box, trk, strict=True):
            return _seen(trk, box, blob=True)

    if following and in_zone and any(_matches_track(b, trk, strict=True) for b, _ in zone.placed):
        # Neither finder saw it this time, but the zone still shows a ball
        # set down right there: keep the box where it is.
        return _seen(trk, trk["box"], blob=trk.get("blob", False), keep_rivals=True,
                     source=trk.get("source"))

    if following and trk["misses"] < getattr(args, "miss_checks", 3):
        # The ball we follow wasn't seen this time. Don't jump to anything else
        # yet; it is usually just a missed detection.
        trk["misses"] += 1
        return None

    # A new ball: a confident model find, or a spot where one was set down.
    found = _new_ball_evidence(gray, args, cands, placed, use_blob)
    need = getattr(args, "confirm_checks", 2)
    # The zone's tiles are looked at in turn, so a find may only come back
    # every few checks: keep it in mind that long.
    hold = max(2, min(len(_zone_tiles(args)), 4)) if in_zone else 2
    box = _confirmed(trk, [(b, s) for b, s, _ in found], args, hold=hold,
                     better_than=args.conf, slow=(need + 3, 0.4))
    if box is not None:
        _, rating, source = next(f for f in found if f[0] is box)
        trk["far"] = next((fl for b, _, fl in cands if b is box), True)
        return _seen(trk, box, blob=source.endswith("spot finder"), conf=rating, source=source,
                     sure=True)
    if found:                       # something is being confirmed: wait for it
        trk["misses"] += 1
        return None

    if use_blob and not (in_zone and zone.trusted):
        spots = find_ball_spots(gray, args)
        if in_zone and len(spots) > 1:
            # Several ball-like spots in the zone and none seen being set
            # down: don't guess (most are marks on the mat). The ball is
            # taken when it's set down, or tapped.
            spots = []
        box = _confirmed(trk, spots, args, key="blobs", hold=1, need=need + 2)
        if box is not None:
            return _seen(trk, box, blob=True, sure=False)
    else:
        trk["blobs"] = []
    trk["misses"] += 1
    return None


def _new_ball_evidence(gray, args, cands, placed, use_blob):
    """Possible new balls this check, as (box, rating, source). Ratings are on
    the model's 0-1 scale; --conf (0.5) or more counts after --confirm-checks
    sightings, 0.4 or more after three more.

    A spot set down in the zone rates 0.45 on its own, 0.6 when the small-ball
    finder sees a ball right there and at least 0.75 when the model does, at
    any confidence (two independent signs agreeing). The model on its own
    rates what it says, and only counts from --conf up."""
    found, used = [], []
    for pbox, _ in placed:
        pc, pd = _center(pbox), max(_diameter(pbox), 6.0)
        reach = max(0.8 * pd, 8.0)
        near = [c for c in cands if np.hypot(*np.subtract(_center(c[0]), pc)) <= reach
                and 0.4 <= _diameter(c[0]) / pd <= 2.5]
        if near:
            b, c, _ = max(near, key=lambda f: f[1])
            used += [n[0] for n in near]
            found.append((b, max(0.75, c), f"set down + model {c:.2f}"))
            continue
        if use_blob:
            spot = find_ball_spot(gray, args, near=pc)
            if spot is not None and np.hypot(*np.subtract(_center(spot), pc)) <= reach:
                found.append((spot, 0.6, "set down + spot finder"))
                continue
        found.append((pbox, 0.45, "set down"))
    for b, c, _ in cands:
        if c >= args.conf and not any(b is u for u in used):
            found.append((b, c, f"model {c:.2f}"))
    return found


def _ball_at_hint(model, gray, args, trk):
    """A tap on the Camera view said "the ball is here": take the ball found
    within 40 px of the tap straight away (the model at any confidence, else
    the small-ball finder). Tried for a few checks, then given up."""
    hx, hy, tries = trk["hint"]
    trk["hint"] = (hx, hy, tries - 1) if tries > 1 else None
    reach = 40.0

    def dist(box):
        return float(np.hypot(*np.subtract(_center(box), (hx, hy))))

    if model is not None and 0 < getattr(args, "tile", 0) < WIDTH:
        T = min(args.tile, HEIGHT)
        ox, oy = _tile_at((hx, hy), T)
        low = min(getattr(args, "assist_conf", 0.15), args.conf)
        near = [(b, c) for b, c, _ in _run_model(model, gray, args, ox, oy, T, low)
                if dist(b) <= reach]
        if near:
            b, c = max(near, key=lambda f: f[1] / (1.0 + dist(f[0]) / reach))
            trk["hint"], trk["far"] = None, True
            print(f"Ball found where you tapped: {b} (model {c:.2f})")
            return _seen(trk, b, conf=c, source=f"tapped + model {c:.2f}", sure=True)
    spot = find_ball_spot(gray, args, near=(hx, hy))
    if spot is not None and dist(spot) <= reach:
        trk["hint"], trk["far"] = None, True
        print(f"Ball found where you tapped: {spot} (spot finder)")
        return _seen(trk, spot, blob=True, source="tapped + spot finder", sure=True)
    if trk["hint"] is None:
        print(f"No ball seen where you tapped ({hx}, {hy}); still searching the zone")
    return None


def _tile_starts(a0, a1, size, limit, overlap=40):
    """Start positions of size-long windows covering a0..a1 within 0..limit,
    evenly spread and overlapping by at least `overlap` pixels so a ball on a
    seam is still whole in one of them."""
    if a1 - a0 <= size:
        return [int(min(max((a0 + a1) / 2 - size / 2, 0), limit - size))]
    n = int(np.ceil((a1 - a0 - size) / float(size - overlap))) + 1
    starts = np.linspace(a0, a1 - size, n)
    return sorted({int(min(max(round(v), 0), limit - size)) for v in starts})


def _model_regions(gray, args, trk):
    """Where the model looks, most likely first: (image, x offset, y offset, tile?).

    The model sees a small square picture. Shrinking the whole frame to that size
    makes a distant ball a few pixels wide, too small to recognise, so the frame
    is also cut into overlapping tiles looked at in full detail. With a tapped
    search area, only the tile(s) covering that area are used: faster, and
    nothing outside it can be mistaken for the ball.
    """
    T = min(args.tile, HEIGHT)
    if T <= 0 or T >= WIDTH:
        yield gray, 0, 0, False
        return
    if getattr(args, "search_area", None):
        x0, y0, x1, y1 = _search_area(args)
        for oy in _tile_starts(y0, y1, T, HEIGHT):
            for ox in _tile_starts(x0, x1, T, WIDTH):
                yield gray[oy:oy + T, ox:ox + T], ox, oy, True
        return
    if trk["far"] and trk["center"] is not None:     # following a distant ball
        ox = int(min(max(trk["center"][0] - T / 2, 0), WIDTH - T))
        oy = int(min(max(trk["center"][1] - T / 2, 0), HEIGHT - T))
        yield gray[oy:oy + T, ox:ox + T], ox, oy, True
    yield gray, 0, 0, False                           # whole frame: a close, large ball
    for oy in sorted({0, HEIGHT - T}):
        for ox in sorted({0, (WIDTH - T) // 2, WIDTH - T}):
            yield gray[oy:oy + T, ox:ox + T], ox, oy, True


def _model_candidates(model, gray, args, trk, following):
    """Every plausible ball the model reports, as (box, confidence, tile?),
    region by region. Stops early once a region has a confident find (or,
    when following, the caller has what it needs)."""
    low = min(getattr(args, "keep_conf", 0.3), args.conf) if following else args.conf
    for img, ox, oy, tile in _model_regions(gray, args, trk):
        bgr = cv2.cvtColor(np.ascontiguousarray(img), cv2.COLOR_GRAY2BGR)
        r = model.predict(bgr, imgsz=args.imgsz, conf=low, verbose=False)[0]
        found = []
        for i in range(len(r.boxes)):
            x0, y0, x1, y1 = [float(v) for v in r.boxes.xyxy[i]]
            box = [int(x0 + ox), int(y0 + oy), int(x1 + ox), int(y1 + oy)]
            if _inside_area(args, box):
                found.append((box, float(r.boxes.conf[i]), tile))
        found.sort(key=lambda f: -f[1])
        yield from found
        if any(c >= args.conf or (following and _matches_track(b, trk)) for b, c, _ in found):
            return


# --- The hitting zone ---------------------------------------------------------

_ROTATION = [0]     # which of the zone's tiles the model looks at next


def _zone_tiles(args):
    """Top-left corners of the full-detail tiles covering the hitting zone."""
    if not getattr(args, "search_area", None) or not 0 < getattr(args, "tile", 0) < WIDTH:
        return []
    T = min(args.tile, HEIGHT)
    x0, y0, x1, y1 = _search_area(args)
    return [(ox, oy) for oy in _tile_starts(y0, y1, T, HEIGHT) for ox in _tile_starts(x0, x1, T, WIDTH)]


def _tile_at(point, T):
    """Top-left corner of a T x T tile centred (as far as the frame allows) on point."""
    ox = int(min(max(point[0] - T / 2, 0), WIDTH - T))
    oy = int(min(max(point[1] - T / 2, 0), HEIGHT - T))
    return ox, oy


def _run_model(model, gray, args, ox, oy, T, low):
    """The model on one tile: (box, confidence, True) for each find inside the area."""
    bgr = cv2.cvtColor(np.ascontiguousarray(gray[oy:oy + T, ox:ox + T]), cv2.COLOR_GRAY2BGR)
    r = model.predict(bgr, imgsz=args.imgsz, conf=low, verbose=False)[0]
    found = []
    for i in range(len(r.boxes)):
        x0, y0, x1, y1 = [float(v) for v in r.boxes.xyxy[i]]
        box = [int(x0 + ox), int(y0 + oy), int(x1 + ox), int(y1 + oy)]
        if _inside_area(args, box):
            found.append((box, float(r.boxes.conf[i]), True))
    return found


def _zone_model_candidates(model, gray, args, trk, following, placed):
    """The model's finds inside the hitting zone, best first, as (box, confidence, True).

    Each check the model looks at one tile centred on the followed ball; or,
    while no ball is followed, at tiles centred on up to two spots where
    something was just set down, plus one or two of the zone's own tiles in
    turn (so a ball already lying there is found too). That keeps it to one
    to three looks a check however big the zone is. Low confidences are kept
    (down to --assist-conf): on their own they don't count, but they back up
    a set-down spot."""
    T = min(args.tile, HEIGHT)
    zone = _zone_tiles(args)
    if following:
        tiles = [_tile_at(trk["center"], T)]
        low = min(getattr(args, "keep_conf", 0.3), args.conf)
    else:
        low = min(getattr(args, "assist_conf", 0.15), args.conf)
        if len(zone) <= 1:
            tiles = list(zone)                 # one tile already covers the whole zone
        else:
            tiles = [_tile_at(_center(b), T) for b, _ in placed[:2]]
            per = 1 if tiles else 2
            start = _ROTATION[0] % len(zone)
            _ROTATION[0] = (start + per) % len(zone)
            tiles += [zone[(start + i) % len(zone)] for i in range(min(per, len(zone)))]
    done, found = [], []
    for ox, oy in tiles:
        if any(abs(ox - a) < 32 and abs(oy - b) < 32 for a, b in done):
            continue                           # practically the same tile
        done.append((ox, oy))
        for box, conf, tile in _run_model(model, gray, args, ox, oy, T, low):
            same = next((i for i, f in enumerate(found) if np.hypot(*np.subtract(
                _center(f[0]), _center(box))) < 0.5 * max(_diameter(f[0]), 1.0)), None)
            if same is None:
                found.append((box, conf, tile))
            elif conf > found[same][1]:
                found[same] = (box, conf, tile)
    found.sort(key=lambda f: -f[1])
    return found


class ZoneWatch:
    """Notices a ball being set down in the hitting zone.

    It keeps a picture of the empty zone and compares each check with it. A
    ball put down shows up as a small, roundish spot that has become clearly
    brighter than it was (a white ball on turf or a mat). Every pixel is
    measured against the pixels around it rather than by its raw brightness,
    so an exposure change, a cloud or the golfer's soft shadow hardly
    registers, while a ball does. A ball taken away (darker than before) is
    ignored.

    The empty picture is taken:
      - at start-up, at the first quiet moment once the exposure is set (if a
        ball is already lying there it becomes part of the picture; the
        model, the small-ball finder or a tap still find it);
      - after each shot, at the first quiet moment once the ball has left;
      - again if much of the zone has changed and stayed that way for a few
        seconds with no ball followed (the box was bumped, say).
    In between it slowly follows gradual light changes, except on a spot
    being watched (a ball just set down, or the ball being followed).

    `trusted` means the empty picture is known to have no ball in it, so the
    small-ball finder on its own is no longer needed there.
    """

    QUIET = 0.003     # share of the zone that may change between two checks and still be "quiet"
    BUSY = 0.05       # more than this share changed: someone is in the zone (or the camera moved)
    BLEND = 0.05      # how fast the empty picture follows slow light changes, per check
    _K3 = np.ones((3, 3), np.uint8)

    def __init__(self, args):
        self.args = args
        self.area = None
        self.ball_d = None        # size of the last ball followed, pixels (set by the caller)
        self.reset()

    def reset(self):
        self.bg = None            # neighbourhood-relative picture of the empty zone
        self.prev = None
        self.quiet = 0            # checks in a row with (almost) nothing moving
        self.placed = []          # (box, strength) of spots set down, most distinct first
        self.trusted = False
        self.after_shot = None    # (earliest time to retake the picture, where the ball was)
        self.leftover = None      # box of a ball still lying where it was after a "shot"
        self.busy_since = None
        self.noise = None         # picture noise, in the same relative units

    @property
    def active(self):
        return self.area is not None

    def _relative(self, gray):
        """Each pixel's brightness relative to its surroundings (1.0 = like
        them). The surroundings are wide (at least 41 px, several ball widths)
        so a ball set down hardly changes them: only the ball itself shows."""
        k = int(max(41, 3.5 * (self.ball_d or 0))) | 1
        x0, y0, x1, y1 = self.area
        m = k // 2
        X0, Y0, X1, Y1 = max(x0 - m, 0), max(y0 - m, 0), min(x1 + m, WIDTH), min(y1 + m, HEIGHT)
        z = cv2.GaussianBlur(gray[Y0:Y1, X0:X1].astype(np.float32), (5, 5), 0)
        rel = z / (cv2.blur(z, (k, k)) + 8.0)
        return rel[y0 - Y0:y1 - Y0, x0 - X0:x1 - X0]

    def shot_taken(self, ball_box, now):
        """A shot was just recorded: take a new empty picture once the zone is quiet."""
        self.after_shot = (now + 0.3, ball_box)
        self.placed = []

    def update(self, gray, now, protect=None, allow_new=True):
        """Call once per check with the latest frame. protect: the box of the
        ball being followed, never blended into the empty picture.
        allow_new=False holds off a new empty picture (exposure still being set)."""
        area = _search_area(self.args) if getattr(self.args, "search_area", None) else None
        if area != self.area:
            self.area = area
            self.reset()
        if area is None or gray is None:
            return
        rel = self._relative(gray)
        thr = getattr(self.args, "place_contrast", 0.2)
        if self.prev is None or self.prev.shape != rel.shape:
            moved = 1.0
        else:
            step = np.abs(rel - self.prev)
            # Noise, measured from frame to frame (the median ignores anything
            # that really moved). In a dim, noisy picture every threshold is
            # raised with it, so noise can't look like a ball or like motion.
            n = 1.4826 * float(np.median(step)) / 1.414
            self.noise = n if self.noise is None else 0.8 * self.noise + 0.2 * n
            thr = max(thr, 4.0 * self.noise)
            moved = float(np.mean(step > 1.414 * thr))
        self.prev = rel
        self.quiet = self.quiet + 1 if moved <= self.QUIET else 0

        if self.bg is None or self.after_shot is not None:
            self.placed = []
            if allow_new and self.quiet >= 2 and (self.after_shot is None or now >= self.after_shot[0]):
                self._take(gray, rel)
            return

        diff = rel - self.bg
        busy = float(np.mean(np.abs(diff) > thr))
        if protect is not None:
            self.leftover = None              # a ball is being followed again
        if busy <= self.BUSY:
            # Follow slow light changes, except where a ball is (or may be)
            # lying. Not while someone is in the zone: they would be blended
            # in, and so would a ball they have just put down.
            blend = np.ones(diff.shape, bool)
            x0, y0 = area[:2]
            for b in [p for p, _ in self.placed] + ([protect] if protect is not None else []):
                blend[max(b[1] - y0 - 4, 0):max(b[3] - y0 + 4, 0),
                      max(b[0] - x0 - 4, 0):max(b[2] - x0 + 4, 0)] = False
            self.bg[blend] += self.BLEND * diff[blend]
        else:
            # Someone is in the zone or the camera moved: no "set down" spots
            # now. If it stays like this, quietly, for 3 s with no ball being
            # followed, the zone itself has changed: start again from it.
            self.placed = []
            if protect is None and self.quiet >= 2:
                self.busy_since = self.busy_since or now
                if now - self.busy_since >= 3.0:
                    print("Hitting zone: the picture changed and stayed changed; "
                          "taking a new picture of the empty zone")
                    self._take(gray, rel)
            else:
                self.busy_since = None
            return
        self.busy_since = None
        self.placed = self._spots(diff, thr)
        if self.leftover is not None and not any(
                np.hypot(*np.subtract(_center(b), _center(self.leftover))) <= _diameter(self.leftover)
                for b, _ in self.placed):
            self.placed.insert(0, (list(self.leftover), 1.0))

    def _take(self, gray, rel):
        """Remember the zone as it is now as "empty"."""
        self.bg = rel.copy()
        self.placed = []
        self.busy_since = None
        lying = find_ball_spots(gray, self.args, limit=8)   # anything ball-like there now
        if self.after_shot is not None:
            old = self.after_shot[1]
            still = None if old is None else next(
                (b for b, _ in lying
                 if np.hypot(*np.subtract(_center(b), _center(old))) <= max(0.6 * _diameter(old), 5.0)),
                None)
            # The rest of the zone is known to be empty either way. A ball
            # still lying where it was (the trigger fired but it wasn't hit)
            # is offered again as if just set down.
            self.trusted, self.leftover = True, still
            if still is not None:
                print("Hitting zone: the ball still seems to be where it was; looking at it again")
        else:
            self.trusted, self.leftover = not lying, None
        self.after_shot = None
        print(f"Hitting zone: empty picture taken ({'no ball in it' if self.trusted else 'a ball may be in it'})")

    def _spots(self, diff, thr):
        """Ball-sized spots that have become brighter than the empty zone, with
        nothing else changed around them: (box, strength). (The edge of a hand
        or club can look like a small bright spot; a ball sits on its own.)"""
        changed = np.abs(diff) > thr
        mask = (diff > thr).astype(np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self._K3)    # lone noisy pixels
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self._K3)
        n, _, st, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        lo = 2 * getattr(self.args, "blob_min_radius", 3.0)
        hi = 2 * getattr(self.args, "blob_max_radius", 25.0)
        if self.ball_d:                        # about the size of the last ball
            lo, hi = max(lo, 0.5 * self.ball_d), min(hi, 1.8 * self.ball_d)
        x0, y0 = self.area[:2]
        out = []
        for i in range(1, n):
            x, y, w, h, count = (int(v) for v in st[i])
            # A ball lit from above can show just its bright top: wider than tall.
            if not (lo <= (w + h) / 2.0 <= hi) or not (0.5 <= w / float(h) <= 2.5) \
                    or count < 0.4 * w * h:
                continue
            # On its own: hardly anything else changed in a ring round it.
            r = max(w, h, 10)
            rx0, ry0 = max(x - r, 0), max(y - r, 0)
            rx1, ry1 = min(x + w + r, diff.shape[1]), min(y + h + r, diff.shape[0])
            ring = int(changed[ry0:ry1, rx0:rx1].sum()) - int(changed[y:y + h, x:x + w].sum())
            ring_px = (rx1 - rx0) * (ry1 - ry0) - w * h
            if ring > 0.06 * ring_px:
                continue
            strength = float(diff[y:y + h, x:x + w][mask[y:y + h, x:x + w] > 0].mean())
            side = max(w, h)
            cx = x0 + x + w / 2.0
            box = [int(max(cx - side / 2.0, 0)), int(y0 + y),
                   int(min(cx + side / 2.0, WIDTH)), int(min(y0 + y + side, HEIGHT))]
            out.append((box, strength))
        out.sort(key=lambda s: -s[1])
        return out[:3]


def smooth_box(shown, box, weight=0.4):
    """The box to draw on screen: eased towards the latest detection so it
    doesn't flicker by a pixel or two; jumps straight there if the ball moved."""
    if shown is None or box is None or np.hypot(*np.subtract(_center(box), _center(shown))) \
            > max(_diameter(box), 10.0):
        return list(box) if box is not None else None
    return [int(round(s + weight * (b - s))) for s, b in zip(shown, box)]


def update_ready(sh, args, gray, ball, trk, now):
    """Decide SEARCHING / BALL / READY from the model's latest answer.

    Once READY, the script stays READY even if the model loses the ball (for
    example when the club is set down next to it), as long as the patch of
    picture where the ball sits still looks the same.
    """
    center = None
    if ball is not None:
        center = ((ball[0] + ball[2]) / 2, (ball[1] + ball[3]) / 2)

    if trk.pop("switched", False) and ball is not None:
        # detect_ball moved the box to something the model rates clearly
        # higher (the old box was on a look-alike): start over on the new one.
        sh.armed = False
        sh.roi = sh.roi_ref = None
        keep = {k: trk.get(k) for k in ("source", "found_by", "sure", "blob", "far")}
        trk.update(new_track())
        trk.update(keep)

    if sh.armed and trk["center"] is not None:
        diff = _patch_diff(sh, gray)
        same = center is not None and np.hypot(
            center[0] - trk["center"][0], center[1] - trk["center"][1]) <= args.still_pixels
        if same:
            trk["lost_since"] = None
            trk["confirmed_at"] = now
            trk["box"] = ball
            if diff is not None and diff <= args.motion_threshold * 0.5:
                _set_patch(sh, gray, ball)  # follow slow lighting changes
            return "READY"
        blind = now - (trk["confirmed_at"] or now)
        if diff is not None and diff <= args.motion_threshold \
                and blind <= getattr(args, "blind_seconds", 30.0):
            trk["lost_since"] = None
            return "READY"  # the ball's patch is unchanged, so it is still there
        if trk["lost_since"] is None:
            trk["lost_since"] = now
        if now - trk["lost_since"] < args.hold_seconds:
            return "READY"  # briefly covered; give it a moment
        sh.armed = False
        sh.roi = sh.roi_ref = None
        trk.update(new_track())

    if center is None:
        if trk["center"] is not None and trk.get("misses", 0) <= getattr(args, "miss_checks", 3):
            return "BALL"   # missed for a moment: keep the box where it was, don't arm
        spots, blobs = trk.get("spots", []), trk.get("blobs", [])  # new-ball sightings being confirmed
        trk.update(new_track())
        trk["spots"], trk["blobs"] = spots, blobs
        sh.armed = False
        return "SEARCHING"
    if trk["center"] is not None and np.hypot(
            center[0] - trk["center"][0], center[1] - trk["center"][1]) <= args.still_pixels:
        if trk["still_since"] is None:
            trk["still_since"] = now
    else:
        trk["center"], trk["still_since"] = center, None
    trk["box"] = ball
    if trk["still_since"] is not None and now - trk["still_since"] >= args.still_seconds:
        _set_patch(sh, gray, ball)
        sh.armed = True
        trk["lost_since"] = None
        trk["confirmed_at"] = now
        return "READY"
    return "BALL"


class PatchWatch:
    """Tells a shot apart from the club being set down behind the ball.

    It is fed, frame by frame, how much the ball's patch differs from its
    reference picture.

    A shot: the patch changes all at once (the ball is there in one frame and
    gone a frame or two later) and then stays put. That returns "trigger".

    A club arriving at address: the patch keeps changing over many frames as
    the club creeps in, then settles. That does not trigger. Once it has been
    steady for a moment it returns "reref", meaning "accept this as the new
    normal picture", so the shot can still be caught from there.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.hist = collections.deque(maxlen=16)
        self.n = 0
        self.cand = None
        self.steady_since = None

    def step(self, diff, now, thr):
        h = self.hist
        h.append(diff)
        self.n += 1
        # A jump of most of the threshold within three frames starts a check.
        # The patch must have been still just before the jump: a club that is
        # already creeping in does not count.
        if self.cand is None and len(h) >= 7 and diff - h[-4] > 0.8 * thr \
                and abs(h[-4] - h[-7]) < 0.25 * thr:
            self.cand = (self.n, h[-4])
        if self.cand is not None:
            k, base = self.cand
            if self.n - k == 4:
                self.cand = None
                rise_end = diff - base        # change four frames after the jump
                rise_early = h[-4] - base     # change one frame after the jump
                # A shot has finished changing almost at once; a creeping club
                # is still changing four frames later.
                if rise_end > 0.8 * thr and rise_early >= 0.75 * rise_end:
                    return "trigger"
        if self.cand is None and len(h) >= 4 and diff > 0.5 * thr \
                and abs(diff - h[-4]) < 0.15 * thr:
            if self.steady_since is None:
                self.steady_since = now
            elif now - self.steady_since >= 0.4:
                self.reset()
                return "reref"
        else:
            self.steady_since = None
        return None


def camera_thread(cam, sh, args):
    """Grab every frame at full speed into the rolling memory."""
    count, t0 = 0, time.monotonic()
    prev_small = None
    watch = PatchWatch()
    while sh.running:
        req = cam.capture_request()
        try:
            img = req.make_array("main")[:HEIGHT, :WIDTH]
            md = req.get_metadata()
            sensor_ns = md.get("SensorTimestamp", 0)
            sh.exposure = (md.get("ExposureTime"), md.get("AnalogueGain"))
        finally:
            req.release()
        now = time.monotonic()
        sh.frames.append((now, sensor_ns, img))
        sh.latest = img

        # Motion trigger: has the ball suddenly gone from where it was sitting?
        if "motion" in args.triggers and sh.armed and sh.trigger_time is None:
            diff = _patch_diff(sh, img)
            if diff is None:
                watch.reset()
            else:
                verdict = watch.step(diff, now, args.motion_threshold)
                if verdict == "trigger":
                    watch.reset()
                    sh.trigger("motion")
                elif verdict == "reref" and sh.roi is not None:
                    # Something (usually the club) has settled beside the ball.
                    x0, y0, x1, y1 = sh.roi
                    sh.roi_ref = img[y0:y1, x0:x1].copy()
        else:
            watch.reset()

        # Swing test (no ball): fire when a lot of the picture changes between two
        # consecutive frames. A club at full speed does that; slow movement at
        # address does not. The average change is removed first so flickering
        # room lights don't count.
        if getattr(args, "swing_test", False):
            small = img[::4, ::4].astype(np.int16)
            if prev_small is not None and sh.armed and sh.trigger_time is None:
                d = small - prev_small
                d -= int(d.mean())
                if np.count_nonzero(np.abs(d) > 30) > args.swing_fraction * d.size:
                    sh.trigger("swing")
            prev_small = small

        # After a trigger, keep recording for the "after" time, then hand over.
        tt = sh.trigger_time
        if tt is not None and now >= tt + args.post:
            with sh.lock:
                window = [f for f in sh.frames if tt - args.pre <= f[0] <= tt + args.post]
                sh.pending = (tt, sh.trigger_source, window)
                sh.trigger_time = None
                sh.armed = False

        count += 1
        if now - t0 >= 1.0:
            sh.camera_fps = count / (now - t0)
            count, t0 = 0, now


SHOT_FOLDER = "shot_%Y%m%d_%H%M%S"
KEEP_MARKER = "KEEP"       # a shot folder holding this file is never pruned


def shot_folder(out_dir):
    """A new folder name for a shot (not created yet)."""
    return os.path.join(out_dir, time.strftime(SHOT_FOLDER))


def save_shot(pending, out_dir, video=True, folder=None):
    """Write a shot's frames (frames.npy, times.npy, sensor_ns.npy) and, with
    video=True, a slow-motion preview.avi. Returns the folder."""
    tt, source, window = pending
    if not window:
        print("Trigger fired but no frames were in memory.")
        return None
    folder = folder or shot_folder(out_dir)
    os.makedirs(folder, exist_ok=True)
    frames = np.stack([f[2] for f in window])
    times = np.array([f[0] - tt for f in window])          # seconds relative to trigger
    sensor = np.array([f[1] for f in window], dtype=np.int64)
    np.save(os.path.join(folder, "frames.npy"), frames)
    np.save(os.path.join(folder, "times.npy"), times)
    np.save(os.path.join(folder, "sensor_ns.npy"), sensor)

    if video:
        # Slow-motion preview that plays in any video player.
        writer = cv2.VideoWriter(os.path.join(folder, "preview.avi"),
                                 cv2.VideoWriter_fourcc(*"MJPG"), 30, (WIDTH, HEIGHT), False)
        for img in frames:
            writer.write(np.ascontiguousarray(img))
        writer.release()

    span = times[-1] - times[0]
    rate = (len(times) - 1) / span if span > 0 else 0
    print(f"SHOT ({source}): saved {len(frames)} frames, "
          f"{times[0] * 1000:.0f} ms to +{times[-1] * 1000:.0f} ms, "
          f"about {rate:.0f} fps, in {folder}")
    return folder


def prune_shots(out_dir, keep):
    """Delete the oldest shot folders beyond the newest `keep`, except any a
    person chose to keep (they hold a KEEP file). keep <= 0 keeps everything."""
    if keep <= 0:
        return
    try:
        names = sorted(n for n in os.listdir(out_dir) if n.startswith("shot_")
                       and os.path.isdir(os.path.join(out_dir, n)))
    except OSError:
        return
    for name in names[:-keep]:
        path = os.path.join(out_dir, name)
        if not os.path.exists(os.path.join(path, KEEP_MARKER)):
            shutil.rmtree(path, ignore_errors=True)


def set_frame_rate(cam, fps):
    """Change the camera's frame rate while it runs (manual exposure only)."""
    us = int(1_000_000 / fps)
    cam.set_controls({"FrameDurationLimits": (us, us)})


def main():
    p = argparse.ArgumentParser(description="Find the ball, arm, and capture the shot")
    p.add_argument("--model", required=True, help="path to the golf ball .onnx or .pt model")
    p.add_argument("--imgsz", type=int, default=256, help="size the model looks at")
    p.add_argument("--conf", type=float, default=0.5, help="minimum model confidence, 0-1")
    p.add_argument("--tile", type=int, default=256,
                   help="size of the full-detail tiles used to find a distant ball (0 = whole frame only)")
    p.add_argument("--fps", type=float, default=200.0,
                   help="camera frame rate to request (309 timed out on this board)")
    p.add_argument("--checks-per-second", type=float, default=8.0, help="how often the model runs")
    p.add_argument("--still-pixels", type=float, default=12.0, help="movement that still counts as still")
    p.add_argument("--still-seconds", type=float, default=1.0, help="time the ball must sit still before READY")
    p.add_argument("--hold-seconds", type=float, default=3.0,
                   help="how long to stay READY when the ball is covered and the model cannot see it")
    p.add_argument("--pre", type=float, default=0.25, help="seconds to keep from before the trigger")
    p.add_argument("--post", type=float, default=0.5, help="seconds to record after the trigger")
    p.add_argument("--trigger", default="sound,motion,key", help="which triggers to use, comma separated")
    p.add_argument("--motion-threshold", type=float, default=25.0,
                   help="how much the ball's patch must change to count as a shot (0-255)")
    p.add_argument("--bit-depth", type=int, default=8, choices=(8, 10),
                   help="sensor bit depth; 8 allows the fastest frame rates")
    p.add_argument("--exposure", type=int, default=0,
                   help="fix the exposure in microseconds (0 = automatic, see --exposure-mode)")
    p.add_argument("--gain", type=float, default=0.0, help="analogue gain with --exposure (0 = auto)")
    p.add_argument("--out", default="shots", help="folder to save shots into")
    p.add_argument("--port", type=int, default=8000, help="web stream port")
    add_blob_args(p)
    add_tracking_args(p)
    add_exposure_args(p)
    args = p.parse_args()
    args.triggers = {t.strip() for t in args.trigger.split(",") if t.strip()}

    print("Loading model...")
    model = YOLO(os.path.expanduser(args.model), task="detect")
    model.predict(np.zeros((HEIGHT, WIDTH, 3), np.uint8), imgsz=args.imgsz, verbose=False)

    cam, ae = start_camera(args)

    sh = Shared(maxlen=int(args.fps * (args.pre + args.post) * 1.3) + 20)
    threading.Thread(target=camera_thread, args=(cam, sh, args), daemon=True).start()

    if "sound" in args.triggers:
        try:
            from gpiozero import DigitalInputDevice
            gate = DigitalInputDevice(SOUND_GPIO, pull_up=False)
            gate.when_activated = lambda: sh.trigger("sound")
            print(f"Sound trigger on GPIO{SOUND_GPIO}")
        except Exception as e:  # sensor library missing or pin busy
            print(f"Sound trigger not available ({e}); continuing without it")

    if "key" in args.triggers:
        def keys():
            for _ in sys.stdin:
                sh.trigger("key", need_armed=False)
        threading.Thread(target=keys, daemon=True).start()
        print("Press Enter at any time to capture a test shot")

    server = ThreadingHTTPServer(("0.0.0.0", args.port), StreamHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Live view: http://modus.local:{args.port}   (Ctrl+C to stop)")

    state, ball, shown = None, None, None
    trk = new_track()
    period = 1.0 / args.checks_per_second

    try:
        while True:
            loop_start = time.monotonic()

            if sh.pending is not None:
                save_shot(sh.pending, args.out)
                with sh.lock:
                    sh.pending = None
                    sh.roi = sh.roi_ref = None
                trk, ball = new_track(), None
                state = None
                continue

            gray = sh.latest
            if gray is None:
                time.sleep(0.01)
                continue

            capturing = sh.trigger_time is not None
            if ae is not None:
                ae.update(gray, time.monotonic(), hold=sh.armed or capturing)
            if not capturing:
                ball = detect_ball(model, gray, args, trk)
                new_state = update_ready(sh, args, gray, ball, trk, time.monotonic())
                ball = trk["box"] if new_state in ("BALL", "READY") else None
            else:
                new_state = "CAPTURING"

            if new_state != state:
                state = new_state
                print(f"[{time.strftime('%H:%M:%S')}] {state}  (camera {sh.camera_fps:.0f} fps)")

            view = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            color = {"SEARCHING": (0, 0, 255), "BALL": (0, 200, 255),
                     "READY": (0, 255, 0), "CAPTURING": (255, 0, 255)}[state]
            shown = smooth_box(shown, ball)
            if shown:
                cv2.rectangle(view, (shown[0], shown[1]), (shown[2], shown[3]), color, 2)
            us, gain = sh.exposure
            expo = f"  {us} us x{gain:.1f}" if us and gain else ""
            cv2.putText(view, f"{state}  camera {sh.camera_fps:.0f} fps{expo}", (10, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            ok, jpeg = cv2.imencode(".jpg", view, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if ok:
                STREAM.put(jpeg.tobytes())

            spare = period - (time.monotonic() - loop_start)
            if spare > 0:
                time.sleep(spare)
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        sh.running = False
        time.sleep(0.1)
        cam.stop()
        server.shutdown()


if __name__ == "__main__":
    main()
