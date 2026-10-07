#!/usr/bin/env python3
"""
Kiosk mode for the launch monitor camera.

Shows a full-screen status on the touchscreen:
    Looking for Ball  ->  Ready  ->  Recorded Shot
After a shot it replays the clip on a loop and asks Keep or Delete, then goes
back to looking for the next ball.

This file must sit in the same folder as shot_capture.py, which it reuses.

Run from a terminal on the Pi's own screen, inside vision-env:
    python3 camera/kiosk.py

Tap "Exit" in the top right corner to leave kiosk mode.
"""

import argparse
import json
import os
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np
from picamera2 import Picamera2
from ultralytics import YOLO

from shot_capture import (HEIGHT, STREAM, WIDTH, Shared, camera_thread, new_track,
                          save_shot, update_ready)

DEFAULT_MODEL = "~/openflight/models/golf_ball_yolo11n_new_256.onnx"
REPLAY_FPS = 30

PAGE = b"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
html,body{margin:0;height:100%;background:#0b0f14;color:#fff;font-family:sans-serif;
  overflow:hidden;user-select:none;cursor:none}
#wrap{height:100%;display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:10px}
#status{font-size:64px;font-weight:700}
#sub{font-size:22px;color:#9aa7b4;min-height:26px}
img{max-height:52%;max-width:92%;border-radius:8px}
#buttons{display:none;gap:28px;margin-top:6px}
button{font-size:30px;padding:16px 48px;border:0;border-radius:12px;color:#fff}
#keep{background:#1f9d55}#del{background:#c0392b}
#quit{position:fixed;top:6px;right:8px;font-size:14px;padding:6px 12px;
  background:#1c232c;color:#7c8894}
</style></head><body>
<button id="quit" onclick="post('quit')">Exit</button>
<div id="wrap">
  <div id="status">Starting</div>
  <div id="sub"></div>
  <img id="view">
  <div id="buttons">
    <button id="keep" onclick="post('keep')">Keep</button>
    <button id="del" onclick="post('delete')">Delete</button>
  </div>
</div>
<script>
const T={
  STARTING:['Starting','#9aa7b4','Loading'],
  SEARCHING:['Looking for Ball','#f0b429','Place a ball in view'],
  BALL:['Looking for Ball','#f0b429','Ball found, keep it still'],
  READY:['Ready','#2ecc71','Take your shot'],
  WAIT:['Get Set','#f0b429','Swing test starting'],
  SWINGTEST:['Ready','#2ecc71','Swing test: no ball needed'],
  CAPTURING:['Recording','#c77dff',''],
  RECORDED:['Recorded Shot','#4dabf7',''],
  REVIEW:['Recorded Shot','#4dabf7','Keep this video?']};
const st=document.getElementById('status'),sub=document.getElementById('sub'),
      view=document.getElementById('view'),buttons=document.getElementById('buttons');
let mode='';
function post(a){fetch('/'+a,{method:'POST'});}
async function tick(){
  try{
    const s=await (await fetch('/state')).json();
    const t=T[s.state]||[s.state,'#fff',''];
    st.textContent=t[0];st.style.color=t[1];sub.textContent=t[2];
    const m=s.state=='REVIEW'?'replay'+s.shot:
            (s.state=='RECORDED'||s.state=='STARTING'?'none':'live');
    if(m!=mode){
      mode=m;
      view.style.display=(m=='none')?'none':'';
      if(m=='live')view.src='/stream.mjpg';
      else if(m!='none')view.src='/replay.mjpg?'+s.shot;
      buttons.style.display=m.startsWith('replay')?'flex':'none';
    }
  }catch(e){}
  setTimeout(tick,250);
}
tick();
</script></body></html>"""


class Kiosk:
    def __init__(self):
        self.state = "STARTING"
        self.shot = 0          # counts shots, so the page knows a replay is new
        self.replay = []       # JPEG frames of the last shot
        self.decision = None   # "keep", "delete" or "quit"
        self.quit = False


K = Kiosk()


class Handler(BaseHTTPRequestHandler):
    def _mjpeg_headers(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _send_jpeg(self, jpeg):
        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n")
        self.wfile.write(jpeg)
        self.wfile.write(b"\r\n")

    def do_GET(self):
        path = self.path.split("?")[0]
        try:
            if path == "/state":
                body = json.dumps({"state": K.state, "shot": K.shot}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            elif path == "/stream.mjpg":
                self._mjpeg_headers()
                while not K.quit:
                    jpeg = STREAM.get()
                    if jpeg is not None:
                        self._send_jpeg(jpeg)
            elif path == "/replay.mjpg":
                self._mjpeg_headers()
                shot, frames = K.shot, K.replay
                while not K.quit and K.state == "REVIEW" and K.shot == shot and frames:
                    for jpeg in frames:
                        if K.state != "REVIEW" or K.shot != shot:
                            break
                        self._send_jpeg(jpeg)
                        time.sleep(1.0 / REPLAY_FPS)
                    time.sleep(0.4)  # short pause before the clip repeats
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(PAGE)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        action = self.path.strip("/")
        if action == "quit":
            K.quit = True
            K.decision = "quit"
        elif action in ("keep", "delete") and K.state == "REVIEW":
            K.decision = action
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


def open_browser(url):
    """Open Chromium full screen on the Pi's own display."""
    exe = shutil.which("chromium") or shutil.which("chromium-browser")
    if exe is None:
        print(f"Chromium not found. Open {url} in a browser yourself.")
        return None
    env = dict(os.environ)
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    if "WAYLAND_DISPLAY" not in env and "DISPLAY" not in env:
        env["WAYLAND_DISPLAY"] = "wayland-0"   # lets this work when started over SSH
    profile = os.path.expanduser("~/.config/modus-kiosk")
    try:
        return subprocess.Popen(
            [exe, "--kiosk", "--noerrdialogs", "--disable-infobars", "--no-first-run",
             "--password-store=basic", f"--user-data-dir={profile}", url],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        print(f"Could not start the browser ({e}). Open {url} yourself.")
        return None


def main():
    p = argparse.ArgumentParser(description="Launch monitor camera kiosk")
    p.add_argument("--model", default=DEFAULT_MODEL, help="path to the golf ball model")
    p.add_argument("--imgsz", type=int, default=256)
    p.add_argument("--conf", type=float, default=0.5, help="minimum model confidence, 0-1")
    p.add_argument("--fps", type=float, default=200.0, help="camera frame rate to request")
    p.add_argument("--checks-per-second", type=float, default=8.0)
    p.add_argument("--still-pixels", type=float, default=12.0)
    p.add_argument("--still-seconds", type=float, default=1.0)
    p.add_argument("--hold-seconds", type=float, default=3.0,
                   help="how long to stay Ready when the ball is covered")
    p.add_argument("--pre", type=float, default=0.25, help="seconds kept from before the trigger")
    p.add_argument("--post", type=float, default=0.5, help="seconds recorded after the trigger")
    p.add_argument("--trigger", default="motion", help="motion, sound, or both: motion,sound")
    p.add_argument("--motion-threshold", type=float, default=25.0)
    p.add_argument("--exposure", type=int, default=0)
    p.add_argument("--gain", type=float, default=0.0)
    p.add_argument("--out", default="shots", help="folder to save shots into")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--no-ball", action="store_true",
                   help="swing test: skip ball detection and record when a fast swing passes")
    p.add_argument("--swing-fraction", type=float, default=0.015,
                   help="share of the picture that must change in one frame to count as a swing")
    p.add_argument("--no-browser", action="store_true", help="do not open the full-screen browser")
    args = p.parse_args()
    args.triggers = {t.strip() for t in args.trigger.split(",") if t.strip()}
    args.swing_test = args.no_ball
    if args.swing_test:
        args.triggers.discard("motion")  # there is no ball patch to watch

    url = f"http://localhost:{args.port}"
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    browser = None if args.no_browser else open_browser(url)
    print(f"Kiosk page: {url}  (also http://modus.local:{args.port} from the laptop)")

    model = None
    if not args.swing_test:
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
            gate = DigitalInputDevice(17, pull_up=False)
            gate.when_activated = lambda: sh.trigger("sound")
            print("Sound trigger on GPIO17")
        except Exception as e:
            print(f"Sound trigger not available ({e}); continuing without it")

    ball, trk = None, new_track()
    rearm_at = time.monotonic() + 2.0
    period = 1.0 / args.checks_per_second
    K.state = "SEARCHING"

    try:
        while not K.quit:
            loop_start = time.monotonic()

            # A shot was captured: save it, replay it, and wait for Keep/Delete.
            if sh.pending is not None:
                K.state = "RECORDED"
                window = sh.pending[2]
                folder = save_shot(sh.pending, args.out)
                K.replay = [cv2.imencode(".jpg", np.ascontiguousarray(f[2]),
                                         [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()
                            for f in window]
                time.sleep(1.2)
                K.decision = None
                K.shot += 1
                K.state = "REVIEW"
                while K.decision is None and not K.quit:
                    time.sleep(0.05)
                if K.decision == "delete" and folder:
                    shutil.rmtree(folder, ignore_errors=True)
                    print(f"Deleted {folder}")
                elif K.decision == "keep":
                    print(f"Kept {folder}")
                K.replay = []
                with sh.lock:
                    sh.pending = None
                    sh.roi = sh.roi_ref = None
                ball, trk = None, new_track()
                rearm_at = time.monotonic() + 2.0
                K.state = "SEARCHING"
                continue

            gray = sh.latest
            if gray is None:
                time.sleep(0.01)
                continue

            if sh.trigger_time is not None:
                K.state = "CAPTURING"
            elif args.swing_test:
                # No ball needed: arm shortly after start-up or the last shot.
                if not sh.armed and time.monotonic() >= rearm_at:
                    sh.armed = True
                K.state = "SWINGTEST" if sh.armed else "WAIT"
            else:
                bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
                result = model.predict(bgr, imgsz=args.imgsz, conf=args.conf, verbose=False)[0]
                ball = None
                if len(result.boxes):
                    i = int(result.boxes.conf.argmax())
                    ball = [int(v) for v in result.boxes.xyxy[i]]

                K.state = update_ready(sh, args, gray, ball, trk, time.monotonic())
                ball = trk["box"]

            # Live picture for the kiosk page, with a box round the ball.
            view = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            if ball and K.state in ("BALL", "READY"):
                color = (0, 255, 0) if K.state == "READY" else (0, 200, 255)
                cv2.rectangle(view, (ball[0], ball[1]), (ball[2], ball[3]), color, 2)
            ok, jpeg = cv2.imencode(".jpg", view, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if ok:
                STREAM.put(jpeg.tobytes())

            spare = period - (time.monotonic() - loop_start)
            if spare > 0:
                time.sleep(spare)
    except KeyboardInterrupt:
        pass
    finally:
        print("\nStopping.")
        K.quit = True
        sh.running = False
        if browser is not None:
            browser.terminate()
        time.sleep(0.2)
        cam.stop()
        server.shutdown()


if __name__ == "__main__":
    main()
