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
import os
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

    def trigger(self, source, need_armed=True):
        with self.lock:
            if self.trigger_time is not None or self.pending is not None:
                return  # already capturing a shot
            if need_armed and not self.armed:
                return
            self.trigger_time = time.monotonic()
            self.trigger_source = source


def new_track():
    """Bookkeeping for the ready logic."""
    return {"center": None, "still_since": None, "lost_since": None, "box": None,
            "far": False, "confirmed_at": None, "blob": False}


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


def _search_area(args):
    """The --search-area box (x0,y0,x1,y1 in pixels), or the whole frame."""
    area = getattr(args, "search_area", None)
    if not area:
        return 0, 0, WIDTH, HEIGHT
    x0, y0, x1, y1 = [int(float(v)) for v in str(area).split(",")]
    return max(x0, 0), max(y0, 0), min(x1, WIDTH), min(y1, HEIGHT)


def _inside_area(args, box):
    """True if a box from the model could be the ball: roughly square, not
    huge, and (with --search-area) entirely inside the search area."""
    w, h = box[2] - box[0], box[3] - box[1]
    if w <= 0 or h <= 0 or not (0.6 <= w / h <= 1.6) or max(w, h) > 120:
        return False
    x0, y0, x1, y1 = _search_area(args)
    m = 4   # small allowance at the edges
    return box[0] >= x0 - m and box[1] >= y0 - m and box[2] <= x1 + m and box[3] <= y1 + m


def find_ball_spot(gray, args, near=None):
    """Find a small ball the model misses. Returns a box or None.

    Lit from above, a ball on the mat has a bright top and a dark, shadowed
    bottom, so it is found as a small, roughly round spot that differs from the
    mat around it (brighter or darker). The mat's own edges run across the
    picture, so each pixel is compared with the average of its own row; long
    edges then vanish while the ball stands out.
    """
    x0, y0, x1, y1 = _search_area(args)
    if near is not None:   # only look around where the ball was last seen
        r = 40
        x0, y0 = max(x0, int(near[0]) - r), max(y0, int(near[1]) - r)
        x1, y1 = min(x1, int(near[0]) + r), min(y1, int(near[1]) + r)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
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
    candidates = [(b, False) for b in bright] + [(d, False) for d in dark]
    for b in bright:
        for d in dark:
            overlap = min(b[2], d[2]) - max(b[0], d[0])
            if overlap > 0.5 * min(b[2] - b[0], d[2] - d[0]) and 0 <= d[1] - b[3] <= 3 \
                    and d[1] >= b[1]:
                joined = (min(b[0], d[0]), b[1], max(b[2], d[2]), d[3], b[4] + d[4])
                candidates.append((joined, True))

    best, best_score = None, 0.0
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
        if score > best_score:
            best_score = score
            best = [int(bx0 + x0), int(by0 + y0), int(bx1 + x0), int(by1 + y0)]
    return best


def detect_ball(model, gray, args, trk):
    """The ball's box [x0, y0, x1, y1], or None: the model first, then (with
    --blob) the small-ball finder. With --search-area, anything found outside
    that area is ignored."""
    use_blob = getattr(args, "blob", False)
    if use_blob and trk.get("blob") and trk["center"] is not None:
        ball = find_ball_spot(gray, args, near=trk["center"])   # cheap: keep following it
        if ball:
            return ball
    ball = _detect_with_model(model, gray, args, trk)
    if ball and _inside_area(args, ball):
        trk["blob"] = False
        return ball
    if use_blob:
        ball = find_ball_spot(gray, args)
        if ball:
            trk["blob"] = True
            return ball
    return None


def _detect_with_model(model, gray, args, trk):
    """Ask the model where the ball is. Returns [x0, y0, x1, y1] or None.

    The model looks at a small square picture. Shrinking the whole frame down
    to that size makes a distant ball only a few pixels wide, too small to
    recognise. So besides the whole frame, the frame is also cut into
    overlapping tiles that are checked at full detail. Once a distant ball is
    found, only the tile around it is checked, which keeps things fast.
    """
    def run(img, ox, oy):
        bgr = cv2.cvtColor(np.ascontiguousarray(img), cv2.COLOR_GRAY2BGR)
        r = model.predict(bgr, imgsz=args.imgsz, conf=args.conf, verbose=False)[0]
        if not len(r.boxes):
            return None
        i = int(r.boxes.conf.argmax())
        x0, y0, x1, y1 = [float(v) for v in r.boxes.xyxy[i]]
        return [int(x0 + ox), int(y0 + oy), int(x1 + ox), int(y1 + oy)]

    T = min(args.tile, HEIGHT)
    if T <= 0 or T >= WIDTH:
        return run(gray, 0, 0)

    # Already following a distant ball: look only around where it was.
    if trk["far"] and trk["center"] is not None:
        ox = int(min(max(trk["center"][0] - T / 2, 0), WIDTH - T))
        oy = int(min(max(trk["center"][1] - T / 2, 0), HEIGHT - T))
        ball = run(gray[oy:oy + T, ox:ox + T], ox, oy)
        if ball:
            return ball

    ball = run(gray, 0, 0)          # whole frame: finds a close, large ball
    if ball:
        trk["far"] = False
        return ball
    for oy in sorted({0, HEIGHT - T}):
        for ox in sorted({0, (WIDTH - T) // 2, WIDTH - T}):
            ball = run(gray[oy:oy + T, ox:ox + T], ox, oy)
            if ball:
                trk["far"] = True
                return ball
    return None


def update_ready(sh, args, gray, ball, trk, now):
    """Decide SEARCHING / BALL / READY from the model's latest answer.

    Once READY, the script stays READY even if the model loses the ball (for
    example when the club is set down next to it), as long as the patch of
    picture where the ball sits still looks the same.
    """
    center = None
    if ball is not None:
        center = ((ball[0] + ball[2]) / 2, (ball[1] + ball[3]) / 2)

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
        trk.update(new_track())
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
            sensor_ns = req.get_metadata().get("SensorTimestamp", 0)
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


def save_shot(pending, out_dir):
    tt, source, window = pending
    if not window:
        print("Trigger fired but no frames were in memory.")
        return
    folder = os.path.join(out_dir, time.strftime("shot_%Y%m%d_%H%M%S"))
    os.makedirs(folder, exist_ok=True)
    frames = np.stack([f[2] for f in window])
    times = np.array([f[0] - tt for f in window])          # seconds relative to trigger
    sensor = np.array([f[1] for f in window], dtype=np.int64)
    np.save(os.path.join(folder, "frames.npy"), frames)
    np.save(os.path.join(folder, "times.npy"), times)
    np.save(os.path.join(folder, "sensor_ns.npy"), sensor)

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
    p.add_argument("--exposure", type=int, default=0, help="exposure in microseconds (0 = auto)")
    p.add_argument("--gain", type=float, default=0.0, help="analogue gain (0 = auto)")
    p.add_argument("--out", default="shots", help="folder to save shots into")
    p.add_argument("--port", type=int, default=8000, help="web stream port")
    add_blob_args(p)
    args = p.parse_args()
    args.triggers = {t.strip() for t in args.trigger.split(",") if t.strip()}

    print("Loading model...")
    model = YOLO(os.path.expanduser(args.model), task="detect")
    model.predict(np.zeros((HEIGHT, WIDTH, 3), np.uint8), imgsz=args.imgsz, verbose=False)

    frame_us = int(1_000_000 / args.fps)
    controls = {"FrameDurationLimits": (frame_us, frame_us)}
    if args.exposure > 0:
        controls["ExposureTime"] = min(args.exposure, frame_us - 100)
    if args.gain > 0:
        controls["AnalogueGain"] = args.gain
    cam = Picamera2()
    cam.configure(cam.create_video_configuration(
        main={"size": (WIDTH, HEIGHT), "format": "YUV420"},
        sensor={"output_size": (WIDTH, HEIGHT), "bit_depth": args.bit_depth},
        controls=controls, buffer_count=8))
    cam.start()
    time.sleep(1.0)

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

    state, ball = None, None
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
            if not capturing:
                ball = detect_ball(model, gray, args, trk)
                new_state = update_ready(sh, args, gray, ball, trk, time.monotonic())
                ball = trk["box"]
            else:
                new_state = "CAPTURING"

            if new_state != state:
                state = new_state
                print(f"[{time.strftime('%H:%M:%S')}] {state}  (camera {sh.camera_fps:.0f} fps)")

            view = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            color = {"SEARCHING": (0, 0, 255), "BALL": (0, 200, 255),
                     "READY": (0, 255, 0), "CAPTURING": (255, 0, 255)}[state]
            if ball:
                cv2.rectangle(view, (ball[0], ball[1]), (ball[2], ball[3]), color, 2)
            cv2.putText(view, f"{state}  camera {sh.camera_fps:.0f} fps", (10, 25),
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
