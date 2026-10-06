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


def camera_thread(cam, sh, args):
    """Grab every frame at full speed into the rolling memory."""
    count, t0 = 0, time.monotonic()
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

        # Motion trigger: has the patch where the ball sat changed a lot?
        if "motion" in args.triggers and sh.armed and sh.trigger_time is None:
            roi, ref = sh.roi, sh.roi_ref
            if roi is not None and ref is not None:
                x0, y0, x1, y1 = roi
                diff = cv2.absdiff(img[y0:y1, x0:x1], ref)
                if float(diff.mean()) > args.motion_threshold:
                    sh.trigger("motion")

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


def main():
    p = argparse.ArgumentParser(description="Find the ball, arm, and capture the shot")
    p.add_argument("--model", required=True, help="path to the golf ball .onnx or .pt model")
    p.add_argument("--imgsz", type=int, default=256, help="size the model looks at")
    p.add_argument("--conf", type=float, default=0.5, help="minimum model confidence, 0-1")
    p.add_argument("--fps", type=float, default=309.0, help="camera frame rate to request")
    p.add_argument("--checks-per-second", type=float, default=8.0, help="how often the model runs")
    p.add_argument("--still-pixels", type=float, default=12.0, help="movement that still counts as still")
    p.add_argument("--still-seconds", type=float, default=1.0, help="time the ball must sit still before READY")
    p.add_argument("--pre", type=float, default=0.25, help="seconds to keep from before the trigger")
    p.add_argument("--post", type=float, default=0.5, help="seconds to record after the trigger")
    p.add_argument("--trigger", default="sound,motion,key", help="which triggers to use, comma separated")
    p.add_argument("--motion-threshold", type=float, default=25.0,
                   help="how much the ball's patch must change to count as a shot (0-255)")
    p.add_argument("--exposure", type=int, default=0, help="exposure in microseconds (0 = auto)")
    p.add_argument("--gain", type=float, default=0.0, help="analogue gain (0 = auto)")
    p.add_argument("--out", default="shots", help="folder to save shots into")
    p.add_argument("--port", type=int, default=8000, help="web stream port")
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
        sensor={"output_size": (WIDTH, HEIGHT), "bit_depth": 10},
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
    last_center, still_since = None, None
    period = 1.0 / args.checks_per_second

    try:
        while True:
            loop_start = time.monotonic()

            if sh.pending is not None:
                save_shot(sh.pending, args.out)
                with sh.lock:
                    sh.pending = None
                    sh.roi = sh.roi_ref = None
                last_center, still_since, ball = None, None, None
                state = None
                continue

            gray = sh.latest
            if gray is None:
                time.sleep(0.01)
                continue

            capturing = sh.trigger_time is not None
            if not capturing:
                bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
                result = model.predict(bgr, imgsz=args.imgsz, conf=args.conf, verbose=False)[0]
                ball = None
                if len(result.boxes):
                    i = int(result.boxes.conf.argmax())
                    ball = [int(v) for v in result.boxes.xyxy[i]]

                now = time.monotonic()
                if ball is None:
                    new_state = "SEARCHING"
                    last_center, still_since = None, None
                    sh.armed = False
                else:
                    cx, cy = (ball[0] + ball[2]) / 2, (ball[1] + ball[3]) / 2
                    if last_center is not None and \
                            np.hypot(cx - last_center[0], cy - last_center[1]) <= args.still_pixels:
                        if still_since is None:
                            still_since = now
                    else:
                        last_center, still_since = (cx, cy), None
                        sh.armed = False
                    ready = still_since is not None and now - still_since >= args.still_seconds
                    new_state = "READY" if ready else "BALL"
                    if ready and not sh.armed:
                        # Remember the middle of the ball's box for the motion trigger.
                        w, h = ball[2] - ball[0], ball[3] - ball[1]
                        x0 = max(int(ball[0] + 0.2 * w), 0)
                        y0 = max(int(ball[1] + 0.2 * h), 0)
                        x1 = min(int(ball[2] - 0.2 * w), WIDTH)
                        y1 = min(int(ball[3] - 0.2 * h), HEIGHT)
                        if x1 > x0 and y1 > y0:
                            sh.roi_ref = gray[y0:y1, x0:x1].copy()
                            sh.roi = (x0, y0, x1, y1)
                        sh.armed = True
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
