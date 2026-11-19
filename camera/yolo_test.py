#!/usr/bin/env python3
"""
Step 1 test: does a trained golf-ball model find the ball with our camera?

Grabs frames from the OV9281, runs the model on each, prints what it found
and how long it took, and saves the last annotated frame as yolo_test.jpg.

Run (inside the vision-env environment):
    python3 yolo_test.py --model ~/MODUS-Golf/models/modus_ball_256.onnx
"""

import argparse
import os
import time

import cv2
from picamera2 import Picamera2
from ultralytics import YOLO

WIDTH, HEIGHT = 640, 400

p = argparse.ArgumentParser()
p.add_argument("--model", required=True, help="path to the .onnx or .pt model file")
p.add_argument("--imgsz", type=int, default=256, help="size the model looks at")
p.add_argument("--conf", type=float, default=0.35, help="minimum confidence, 0-1")
p.add_argument("--frames", type=int, default=20, help="how many frames to test")
args = p.parse_args()

model = YOLO(os.path.expanduser(args.model), task="detect")

cam = Picamera2()
cam.configure(cam.create_video_configuration(
    main={"size": (WIDTH, HEIGHT), "format": "YUV420"}))
cam.start()
time.sleep(1.0)

view = None
try:
    for i in range(args.frames):
        gray = cam.capture_array("main")[:HEIGHT, :WIDTH]
        frame = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)  # model expects 3 channels
        t = time.time()
        result = model.predict(frame, imgsz=args.imgsz, conf=args.conf, verbose=False)[0]
        ms = (time.time() - t) * 1000
        view = frame.copy()
        found = []
        for box in result.boxes:
            x1, y1, x2, y2 = [int(v) for v in box.xyxy[0]]
            c = float(box.conf[0])
            found.append(f"ball at x={(x1 + x2) // 2} y={(y1 + y2) // 2} "
                         f"size={x2 - x1}x{y2 - y1} confidence={c:.2f}")
            cv2.rectangle(view, (x1, y1), (x2, y2), (0, 255, 0), 2)
        print(f"frame {i + 1}: {ms:.0f} ms  " + ("; ".join(found) if found else "no ball"))
finally:
    cam.stop()

if view is not None:
    cv2.imwrite("yolo_test.jpg", view)
    print("Saved yolo_test.jpg")
