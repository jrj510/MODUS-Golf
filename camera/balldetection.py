#!/usr/bin/env python3
"""
Golf ball "ready" detector for Raspberry Pi 5 + OV9281 global shutter camera
(ribbon/CSI), running the sensor in its fast 640x400 mode (up to ~309 fps).

Finds a golf ball in the camera view and reports one of three states:
    NO BALL  -> nothing found
    BALL     -> a ball is visible but has not settled yet
    READY    -> the ball has sat still long enough to arm for a shot

A live annotated view is served to any browser on the same network:
    http://modus.local:8000

Install once on the Pi:
    sudo apt install -y python3-picamera2 python3-opencv

Run:
    python3 ball_detect.py
    python3 ball_detect.py --min-radius 60 --max-radius 120 --min-contrast 10
    python3 ball_detect.py --fps 120 --exposure 2000 --gain 4

Stop with Ctrl+C.
"""

import argparse
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np
from picamera2 import Picamera2

WIDTH, HEIGHT = 640, 400  # fast binned mode of the OV9281
STREAM_FPS = 20           # browser view rate; kept low so it doesn't slow detection

PAGE = (
    b"<html><body style='margin:0;background:#111;text-align:center'>"
    b"<img src='/stream.mjpg' style='max-width:100%'></body></html>"
)


class FrameBuffer:
    """Holds the newest JPEG so the web stream can hand it to browsers."""

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


BUFFER = FrameBuffer()


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
                jpeg = BUFFER.get()
                if jpeg is None:
                    continue
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n")
                self.wfile.write(jpeg)
                self.wfile.write(b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass  # browser tab closed

    def log_message(self, *args):
        pass  # keep the terminal clean


def find_ball(gray, args):
    """Return (x, y, r) of the best ball candidate in full-size pixels, or None."""
    s = args.scale
    small = gray if s == 1.0 else cv2.resize(
        gray, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    blurred = cv2.GaussianBlur(small, (5, 5), 1.2)
    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=small.shape[0] // 4,
        param1=args.edge,
        param2=args.votes,
        minRadius=max(int(args.min_radius * s), 3),
        maxRadius=max(int(args.max_radius * s), 4),
    )
    if circles is None:
        return None

    best, best_score = None, 0.0
    for cx, cy, cr in circles[0][:6]:
        x, y, r = int(round(cx / s)), int(round(cy / s)), int(round(cr / s))
        # A golf ball is bright against its surroundings, so score each circle
        # by how much brighter its inside is than a ring around it. Only a
        # small crop around the circle is examined, to keep this fast.
        pad = int(r * 1.6) + 1
        x0, y0 = max(x - pad, 0), max(y - pad, 0)
        x1, y1 = min(x + pad, WIDTH), min(y + pad, HEIGHT)
        crop = gray[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        c = (x - x0, y - y0)
        inner = np.zeros(crop.shape, np.uint8)
        cv2.circle(inner, c, max(int(r * 0.8), 1), 255, -1)
        ring = np.zeros(crop.shape, np.uint8)
        cv2.circle(ring, c, int(r * 1.6), 255, -1)
        cv2.circle(ring, c, int(r * 1.15), 0, -1)
        inside = cv2.mean(crop, mask=inner)[0]
        outside = cv2.mean(crop, mask=ring)[0]
        score = inside - outside
        if inside >= args.min_brightness and score > best_score:
            best, best_score = (x, y, r), score

    if best_score < args.min_contrast:
        return None
    return best


def main():
    p = argparse.ArgumentParser(description="Golf ball ready detector")
    p.add_argument("--port", type=int, default=8000, help="web stream port")
    p.add_argument("--fps", type=float, default=309.0, help="camera frame rate to request")
    p.add_argument("--min-radius", type=int, default=20, help="smallest ball radius, pixels")
    p.add_argument("--max-radius", type=int, default=120, help="largest ball radius, pixels")
    p.add_argument("--scale", type=float, default=0.5,
                   help="shrink factor for the circle search (smaller = faster; use 1.0 for small/far balls)")
    p.add_argument("--edge", type=int, default=100, help="edge strength (Hough param1)")
    p.add_argument("--votes", type=int, default=28, help="circle strictness (Hough param2); raise to cut false hits")
    p.add_argument("--min-brightness", type=int, default=90, help="ball must be at least this bright (0-255)")
    p.add_argument("--min-contrast", type=int, default=15, help="ball must beat its surroundings by this much")
    p.add_argument("--still-pixels", type=float, default=4.0, help="max movement that still counts as still")
    p.add_argument("--still-seconds", type=float, default=0.7, help="time the ball must sit still before READY")
    p.add_argument("--exposure", type=int, default=0, help="exposure in microseconds (0 = auto)")
    p.add_argument("--gain", type=float, default=0.0, help="analogue gain (0 = auto)")
    args = p.parse_args()

    frame_us = int(1_000_000 / args.fps)
    controls = {"FrameDurationLimits": (frame_us, frame_us)}
    if args.exposure > 0:
        # Exposure can never be longer than one frame.
        controls["ExposureTime"] = min(args.exposure, frame_us - 100)
    if args.gain > 0:
        controls["AnalogueGain"] = args.gain

    cam = Picamera2()
    cam.configure(cam.create_video_configuration(
        main={"size": (WIDTH, HEIGHT), "format": "YUV420"},
        sensor={"output_size": (WIDTH, HEIGHT), "bit_depth": 10},
        controls=controls,
        buffer_count=6,
    ))
    cam.start()
    time.sleep(1.0)  # let exposure settle

    server = ThreadingHTTPServer(("0.0.0.0", args.port), StreamHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Live view: http://modus.local:{args.port}   (Ctrl+C to stop)")
    print(f"Camera asked for {args.fps:.0f} fps")

    state = None
    last_center = None
    still_since = None
    frames, t0, fps = 0, time.time(), 0.0
    last_stream = 0.0
    reported_rate = False

    try:
        while True:
            # In YUV420 the first HEIGHT rows are the brightness image, which
            # is all a black-and-white sensor has, so no conversion is needed.
            gray = cam.capture_array("main")[:HEIGHT, :WIDTH]
            now = time.time()
            ball = find_ball(gray, args)

            if ball is None:
                new_state = "NO BALL"
                last_center, still_since = None, None
            else:
                x, y, r = ball
                if last_center is not None and \
                        np.hypot(x - last_center[0], y - last_center[1]) <= args.still_pixels:
                    if still_since is None:
                        still_since = now
                else:
                    last_center, still_since = (x, y), None
                settled = still_since is not None and now - still_since >= args.still_seconds
                new_state = "READY" if settled else "BALL"

            if new_state != state:
                state = new_state
                detail = f" at x={ball[0]} y={ball[1]} r={ball[2]}" if ball else ""
                print(f"[{time.strftime('%H:%M:%S')}] {state}{detail}")

            # Annotated view for the browser, sent at a modest rate.
            if now - last_stream >= 1.0 / STREAM_FPS:
                last_stream = now
                view = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
                color = {"NO BALL": (0, 0, 255), "BALL": (0, 200, 255),
                         "READY": (0, 255, 0)}[state]
                if ball:
                    cv2.circle(view, (ball[0], ball[1]), ball[2], color, 2)
                    cv2.circle(view, (ball[0], ball[1]), 2, color, -1)
                cv2.putText(view, f"{state}  {fps:.0f} fps", (10, 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                ok, jpeg = cv2.imencode(".jpg", view, [cv2.IMWRITE_JPEG_QUALITY, 70])
                if ok:
                    BUFFER.put(jpeg.tobytes())

            frames += 1
            if now - t0 >= 1.0:
                fps = frames / (now - t0)
                frames, t0 = 0, now
                if not reported_rate:
                    reported_rate = True
                    print(f"Processing {fps:.0f} frames per second")
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        cam.stop()
        server.shutdown()


if __name__ == "__main__":
    main()
