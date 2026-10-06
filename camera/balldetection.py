#!/usr/bin/env python3
"""
Golf ball "ready" detector for Raspberry Pi 5 + Arducam OV9281 (ribbon/CSI).

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
    python3 ball_detect.py --min-radius 8 --max-radius 40 --exposure 3000

Stop with Ctrl+C.
"""

import argparse
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np
from picamera2 import Picamera2

WIDTH, HEIGHT = 640, 400  # native binned mode of the OV9281

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
    """Return (x, y, r) of the best ball candidate, or None."""
    blurred = cv2.GaussianBlur(gray, (7, 7), 1.5)
    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=HEIGHT // 4,
        param1=args.edge,
        param2=args.votes,
        minRadius=args.min_radius,
        maxRadius=args.max_radius,
    )
    if circles is None:
        return None

    best, best_score = None, 0.0
    for x, y, r in np.round(circles[0]).astype(int):
        # A golf ball is bright against its surroundings, so score each
        # circle by how much brighter its inside is than a ring around it.
        inner = np.zeros(gray.shape, np.uint8)
        cv2.circle(inner, (x, y), max(int(r * 0.8), 1), 255, -1)
        ring = np.zeros(gray.shape, np.uint8)
        cv2.circle(ring, (x, y), int(r * 1.6), 255, -1)
        cv2.circle(ring, (x, y), int(r * 1.15), 0, -1)
        inside = cv2.mean(gray, mask=inner)[0]
        outside = cv2.mean(gray, mask=ring)[0]
        score = inside - outside
        if inside >= args.min_brightness and score > best_score:
            best, best_score = (x, y, r), score

    if best_score < args.min_contrast:
        return None
    return best


def main():
    p = argparse.ArgumentParser(description="Golf ball ready detector")
    p.add_argument("--port", type=int, default=8000, help="web stream port")
    p.add_argument("--min-radius", type=int, default=6, help="smallest ball radius, pixels")
    p.add_argument("--max-radius", type=int, default=60, help="largest ball radius, pixels")
    p.add_argument("--edge", type=int, default=100, help="edge strength (Hough param1)")
    p.add_argument("--votes", type=int, default=28, help="circle strictness (Hough param2); raise to cut false hits")
    p.add_argument("--min-brightness", type=int, default=90, help="ball must be at least this bright (0-255)")
    p.add_argument("--min-contrast", type=int, default=20, help="ball must beat its surroundings by this much")
    p.add_argument("--still-pixels", type=float, default=4.0, help="max movement that still counts as still")
    p.add_argument("--still-frames", type=int, default=20, help="still frames needed before READY")
    p.add_argument("--exposure", type=int, default=0, help="exposure in microseconds (0 = auto)")
    p.add_argument("--gain", type=float, default=0.0, help="analogue gain (0 = auto)")
    args = p.parse_args()

    cam = Picamera2()
    cam.configure(cam.create_video_configuration(
        main={"size": (WIDTH, HEIGHT), "format": "RGB888"}))
    controls = {}
    if args.exposure > 0:
        controls["ExposureTime"] = args.exposure
    if args.gain > 0:
        controls["AnalogueGain"] = args.gain
    if controls:
        cam.set_controls(controls)
    cam.start()
    time.sleep(1.0)  # let exposure settle

    server = ThreadingHTTPServer(("0.0.0.0", args.port), StreamHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Live view: http://modus.local:{args.port}   (Ctrl+C to stop)")

    state = None
    last_center = None
    still_count = 0
    frames, t0, fps = 0, time.time(), 0.0

    try:
        while True:
            frame = cam.capture_array("main")
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            ball = find_ball(gray, args)

            if ball is None:
                new_state = "NO BALL"
                last_center, still_count = None, 0
            else:
                x, y, r = ball
                if last_center is not None and \
                        np.hypot(x - last_center[0], y - last_center[1]) <= args.still_pixels:
                    still_count += 1
                else:
                    still_count = 0
                    last_center = (x, y)
                new_state = "READY" if still_count >= args.still_frames else "BALL"

            if new_state != state:
                state = new_state
                detail = f" at x={ball[0]} y={ball[1]} r={ball[2]}" if ball else ""
                print(f"[{time.strftime('%H:%M:%S')}] {state}{detail}")

            # Annotated view for the browser
            view = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            color = {"NO BALL": (0, 0, 255), "BALL": (0, 200, 255), "READY": (0, 255, 0)}[state]
            if ball:
                cv2.circle(view, (ball[0], ball[1]), ball[2], color, 2)
                cv2.circle(view, (ball[0], ball[1]), 2, color, -1)
            cv2.putText(view, f"{state}  {fps:.0f} fps", (10, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            ok, jpeg = cv2.imencode(".jpg", view, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if ok:
                BUFFER.put(jpeg.tobytes())

            frames += 1
            if frames == 20:
                now = time.time()
                fps = frames / (now - t0)
                frames, t0 = 0, now
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        cam.stop()
        server.shutdown()


if __name__ == "__main__":
    main()