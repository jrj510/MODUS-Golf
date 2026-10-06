#!/usr/bin/env python3
"""
Golf ball "ready" detector for Raspberry Pi 5 + OV9281 global shutter camera
(ribbon/CSI), running the sensor in its fast 640x400 mode.

Method: everything darker than a brightness cutoff is turned black and
everything brighter is turned white, then the white shapes are checked for
one that is round and the right size.

States reported:
    NO BALL  -> nothing found
    BALL     -> a ball is visible but has not settled yet
    READY    -> the ball has sat still long enough to arm for a shot

Live view (camera picture on the left, black/white mask on the right):
    http://modus.local:8000

Install once on the Pi:
    sudo apt install -y python3-picamera2 python3-opencv

Run:
    python3 ball_detect.py
    python3 ball_detect.py --threshold 180
    python3 ball_detect.py --threshold 0          (0 = pick the cutoff automatically)
    python3 ball_detect.py --fps 120 --exposure 2000 --gain 4

Stop with Ctrl+C.
"""

import argparse
import math
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np
from picamera2 import Picamera2

WIDTH, HEIGHT = 640, 400  # fast binned mode of the OV9281
STREAM_FPS = 20           # browser view rate; kept low so it doesn't slow detection
KERNEL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

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
    """Return ((x, y, r) or None, mask). The mask is the black/white image."""
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    if args.threshold > 0:
        _, mask = cv2.threshold(blurred, args.threshold, 255, cv2.THRESH_BINARY)
    else:
        _, mask = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Remove specks, then fill small holes left by the logo and dimples.
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, KERNEL)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, KERNEL)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best, best_score = None, 0.0
    for c in contours:
        area = cv2.contourArea(c)
        if area < 30:
            continue
        (x, y), r = cv2.minEnclosingCircle(c)
        if not args.min_radius <= r <= args.max_radius:
            continue
        perimeter = cv2.arcLength(c, True)
        if perimeter == 0:
            continue
        # 1.0 is a perfect circle; long or ragged shapes score much lower.
        circularity = 4 * math.pi * area / (perimeter * perimeter)
        # How much of the surrounding circle the shape actually fills.
        fill = area / (math.pi * r * r)
        if circularity < args.min_circularity or fill < args.min_fill:
            continue
        score = circularity * fill
        if score > best_score:
            best, best_score = (int(round(x)), int(round(y)), int(round(r))), score
    return best, mask


def main():
    p = argparse.ArgumentParser(description="Golf ball ready detector")
    p.add_argument("--port", type=int, default=8000, help="web stream port")
    p.add_argument("--fps", type=float, default=309.0, help="camera frame rate to request")
    p.add_argument("--threshold", type=int, default=200,
                   help="brightness cutoff 1-254: brighter becomes white, darker becomes black (0 = automatic)")
    p.add_argument("--min-radius", type=int, default=10, help="smallest ball radius, pixels")
    p.add_argument("--max-radius", type=int, default=150, help="largest ball radius, pixels")
    p.add_argument("--min-circularity", type=float, default=0.75,
                   help="how round the white shape must be, 0-1")
    p.add_argument("--min-fill", type=float, default=0.75,
                   help="how much of its circle the shape must fill, 0-1")
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
            ball, mask = find_ball(gray, args)

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

            # Browser view: camera picture on the left, mask on the right.
            if now - last_stream >= 1.0 / STREAM_FPS:
                last_stream = now
                view = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
                mask_view = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
                color = {"NO BALL": (0, 0, 255), "BALL": (0, 200, 255),
                         "READY": (0, 255, 0)}[state]
                if ball:
                    for img in (view, mask_view):
                        cv2.circle(img, (ball[0], ball[1]), ball[2], color, 2)
                        cv2.circle(img, (ball[0], ball[1]), 2, color, -1)
                cv2.putText(view, f"{state}  {fps:.0f} fps", (10, 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                both = np.hstack((view, mask_view))
                ok, jpeg = cv2.imencode(".jpg", both, [cv2.IMWRITE_JPEG_QUALITY, 70])
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
