#!/usr/bin/env python3
"""
Kiosk mode for the launch monitor.

The touchscreen shows a dashboard of shot numbers that is always on screen:
    Ball Speed, Club Speed, Smash Factor, Carry,
    Launch Angle, Launch Direction, Spin Rate, Club Path

Top left is the status indicator (Looking for Ball / Ready / Recording).
After a shot the numbers fill in and a "Shot Preview" button appears beside
the status. Tapping it opens the slow-motion replay with Save and Delete.

Nothing needs to be tapped between shots. The numbers and the replay stay
until the next shot replaces them. A replay that was neither saved nor
deleted is deleted when the next shot arrives, or when the kiosk exits.

Numbers that no connected sensor can measure yet are shown as "--".

This file must sit in the same folder as shot_capture.py, which it reuses.

Run from a terminal, inside vision-env:
    python3 camera/kiosk.py
    python3 camera/kiosk.py --no-ball          (swing test, no ball needed)
    python3 camera/kiosk.py --no-browser       (no screen attached; view from the laptop)
"""

import argparse
import collections
import json
import math
import os
import re
import select
import shutil
import subprocess
import termios
import threading
import time
import tty
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np
from picamera2 import Picamera2
from ultralytics import YOLO

from shot_capture import (HEIGHT, STREAM, WIDTH, Shared, add_blob_args, camera_thread,
                          detect_ball, new_track, save_shot, update_ready)

DEFAULT_MODEL = "~/openflight/models/golf_ball_yolo11n_new_256.onnx"
REPLAY_FPS = 30
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")

PAGE = b"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:#0b0f14;color:#fff;
  font-family:system-ui,sans-serif;overflow:hidden;user-select:none}
body{display:flex;flex-direction:column}
#top{display:flex;align-items:center;gap:10px;padding:8px 10px;height:15vh;min-height:52px}
#status{display:flex;align-items:center;gap:10px;background:#141b24;border-radius:999px;
  padding:0 18px;height:100%;font-size:4.4vh;font-weight:700;white-space:nowrap}
#dot{width:2.6vh;height:2.6vh;border-radius:50%;background:#9aa7b4}
#shotno{color:#7c8894;font-size:3vh;margin-left:auto;white-space:nowrap}
button{border:0;border-radius:12px;color:#fff;font-size:3.6vh;font-weight:600;
  padding:0 18px;height:100%;background:#22303f}
#pv{background:#2563a8}
#quit{background:#1c232c;color:#7c8894;font-size:2.6vh}
.hide{display:none!important}
.view{flex:1;min-height:0;padding:0 10px 10px}
#main{display:grid;grid-template-columns:repeat(4,1fr);grid-template-rows:1fr 1fr;gap:10px}
.tile{background:#141b24;border-radius:14px;display:flex;flex-direction:column;
  align-items:center;justify-content:center;padding:6px;min-width:0}
.lbl{color:#9aa7b4;font-size:3.1vh;text-align:center}
.val{font-size:11.5vh;font-weight:700;line-height:1.1;font-variant-numeric:tabular-nums}
.val.none{color:#3d4a59}
.unit{color:#7c8894;font-size:2.8vh;min-height:3.4vh}
.fresh .val{color:#4dabf7}
#preview,#camera{display:flex;flex-direction:column;align-items:center;gap:8px}
#preview img,#camera img{flex:1;min-height:0;max-width:100%;object-fit:contain;border-radius:8px}
.bar{display:flex;align-items:center;gap:14px;height:13vh;min-height:48px;width:100%;
  justify-content:center}
#keep{background:#1f9d55}#del{background:#c0392b}
#vmsg{font-size:3.4vh;color:#9aa7b4}
</style></head><body>
<div id="top">
  <div id="status"><span id="dot"></span><span id="stext">Starting</span></div>
  <button id="pv" class="hide" onclick="show('preview')">Shot Preview</button>
  <span id="shotno"></span>
  <button id="cam" onclick="show('camera')">Camera</button>
  <button id="quit" onclick="post('quit')">Exit</button>
</div>
<div id="main" class="view"></div>
<div id="preview" class="view hide">
  <img id="rep">
  <div class="bar">
    <button onclick="show('main')">Back</button>
    <span id="vmsg"></span>
    <button id="keep" onclick="post('keep')">Save</button>
    <button id="del" onclick="post('delete')">Delete</button>
  </div>
</div>
<div id="camera" class="view hide">
  <img id="live">
  <div class="bar"><button onclick="show('main')">Back</button>
    <span id="vmsg">Tap the ball to aim the camera there</span></div>
</div>
<script>
const TILES=[['ball_speed','Ball Speed','mph',1],['club_speed','Club Speed','mph',1],
  ['smash','Smash Factor','',2],['carry','Carry','yd',0],
  ['launch_angle','Launch Angle','deg',1],['launch_dir','Launch Direction','deg',1],
  ['spin','Spin Rate','rpm',0],['club_path','Club Path','deg',1]];
const STATUS={STARTING:['Starting','#9aa7b4'],SEARCHING:['Looking for Ball','#f0b429'],
  BALL:['Looking for Ball','#f0b429'],READY:['Ready','#2ecc71'],
  CAPTURING:['Recording','#c77dff'],WAIT:['Get Set','#f0b429'],
  SWINGTEST:['Ready','#2ecc71']};
const $=id=>document.getElementById(id);
const main=$('main');
for(const [k,label,unit] of TILES){
  const t=document.createElement('div');t.className='tile';t.id='t_'+k;
  t.innerHTML='<div class="lbl">'+label+'</div><div class="val none" id="m_'+k+'">--</div>'+
              '<div class="unit" id="u_'+k+'">'+unit+'</div>';
  main.appendChild(t);
}
let view='main',shot=-1,rev=-1,video='none';
function post(a){fetch('/'+a,{method:'POST'});}
// Tap the ball in the live view: the ball search moves to that spot.
$('live').addEventListener('click',e=>{
  const img=e.target,r=img.getBoundingClientRect();
  const s=Math.min(r.width/img.naturalWidth,r.height/img.naturalHeight);
  const w=img.naturalWidth*s,h=img.naturalHeight*s;
  const x=(e.clientX-r.left-(r.width-w)/2)/w,y=(e.clientY-r.top-(r.height-h)/2)/h;
  if(x>=0&&x<=1&&y>=0&&y<=1)fetch('/aim?x='+x.toFixed(4)+'&y='+y.toFixed(4),{method:'POST'});
});
function show(v){
  view=v;
  for(const n of ['main','preview','camera'])$(n).classList.toggle('hide',n!=v);
  $('rep').src=(v=='preview')?'/replay.mjpg?'+shot+'_'+Date.now():'';
  $('live').src=(v=='camera')?'/stream.mjpg':'';
}
async function tick(){
  try{
    const s=await (await fetch('/state')).json();
    const st=STATUS[s.state]||[s.state,'#fff'];
    $('stext').textContent=st[0];$('dot').style.background=st[1];
    if(s.rev!=rev){
      rev=s.rev;
      const waiting=s.metrics.radar_pending?['ball_speed','launch_angle','carry','launch_dir']:[];
      for(const [k,label,unit,dp] of TILES){
        const v=s.metrics[k],el=$('m_'+k),none=(v===null||v===undefined);
        el.textContent=none?(waiting.includes(k)?'...':'--'):Number(v).toFixed(dp);
        el.classList.toggle('none',none);
        $('u_'+k).textContent=unit+((k=='carry'&&s.metrics.carry_estimated&&!none)?' est.':'');
        $('t_'+k).classList.add('fresh');
      }
      setTimeout(()=>{for(const [k] of TILES)$('t_'+k).classList.remove('fresh');},1500);
    }
    if(s.shot!=shot){
      shot=s.shot;
      $('shotno').textContent=shot>0?'Shot '+shot:'';
      if(view=='preview')show(s.video=='none'||s.video=='deleted'?'main':'preview');
    }
    video=s.video;
    const has=(video=='pending'||video=='kept');
    $('pv').classList.toggle('hide',!has);
    $('keep').classList.toggle('hide',video!='pending');
    $('del').classList.toggle('hide',!has);
    $('vmsg').textContent=video=='kept'?'Saved':(video=='pending'?'Save this video?':'');
    if(view=='preview'&&!has)show('main');
  }catch(e){}
  setTimeout(tick,250);
}
tick();
</script></body></html>"""


def empty_metrics():
    return {"ball_speed": None, "club_speed": None, "smash": None, "carry": None,
            "carry_estimated": True, "launch_angle": None, "launch_dir": None,
            "spin": None, "club_path": None}


AREA_FILE = "search_area.txt"   # where a tapped search area is remembered


class Kiosk:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = "STARTING"
        self.shot = 0
        self.rev = 0           # goes up whenever the numbers on screen change
        self.metrics = empty_metrics()
        self.replay = []        # JPEG frames of the latest shot
        self.folder = None      # where the latest shot is saved
        self.video = "none"     # none / pending / kept / deleted
        self.quit = False
        self.args = None
        self.reset_track = False

    def aim(self, fx, fy):
        """Centre the ball search on a spot tapped in the live view (0-1 of the
        picture's width and height), and remember it for the next start."""
        if self.args is None:
            return
        x, y = int(fx * WIDTH), int(fy * HEIGHT)
        area = (max(x - 110, 0), max(y - 25, 0), min(x + 110, WIDTH), min(y + 30, HEIGHT))
        self.args.search_area = ",".join(str(v) for v in area)
        self.reset_track = True
        try:
            os.makedirs(self.args.out, exist_ok=True)
            with open(os.path.join(self.args.out, AREA_FILE), "w") as f:
                f.write(self.args.search_area)
        except OSError as e:
            print(f"Could not save the search area: {e}")
        print(f"Search area set by tap: {self.args.search_area}")

    def decide(self, action):
        """Save or delete the latest shot's video."""
        with self.lock:
            if action == "keep" and self.video == "pending":
                self.video = "kept"
                print(f"Kept {self.folder}")
            elif action == "delete" and self.video in ("pending", "kept"):
                if self.folder:
                    shutil.rmtree(self.folder, ignore_errors=True)
                    print(f"Deleted {self.folder}")
                self.video, self.replay, self.folder = "deleted", [], None

    def drop_undecided(self):
        """A video nobody saved is deleted by default."""
        with self.lock:
            if self.video == "pending" and self.folder:
                shutil.rmtree(self.folder, ignore_errors=True)
                print(f"No choice made, deleted {self.folder}")
                self.video, self.replay, self.folder = "deleted", [], None


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
                body = json.dumps({"state": K.state, "shot": K.shot, "rev": K.rev,
                                   "metrics": K.metrics, "video": K.video}).encode()
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
            elif path == "/frame.png":
                # The exact picture the ball finder last looked at, for tuning.
                gray = getattr(K, "latest_gray", None)
                ok, png = cv2.imencode(".png", gray) if gray is not None else (False, None)
                if not ok:
                    self.send_response(503)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Disposition", 'attachment; filename="frame.png"')
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(png.tobytes())
            elif path == "/replay.mjpg":
                self._mjpeg_headers()
                shot, frames = K.shot, K.replay
                while not K.quit and K.shot == shot and K.replay and frames:
                    for jpeg in frames:
                        if K.quit or K.shot != shot or not K.replay:
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
        action = self.path.split("?")[0].strip("/")
        if action == "aim":
            q = dict(p.split("=", 1) for p in self.path.split("?", 1)[-1].split("&") if "=" in p)
            try:
                K.aim(float(q["x"]), float(q["y"]))
            except (KeyError, ValueError):
                pass
        if action == "quit":
            K.quit = True
        elif action in ("keep", "delete"):
            K.decide(action)
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


class Radar:
    """Reads speeds from the OPS243-A in the background."""

    def __init__(self, port):
        self.readings = collections.deque(maxlen=5000)  # (time, mph)
        self.ok = False
        try:
            self.fd = os.open(port, os.O_RDWR | os.O_NOCTTY)
            tty.setraw(self.fd)
            termios.tcflush(self.fd, termios.TCIOFLUSH)
            for command in ("US", "SL"):   # mph, 50 kHz sample rate
                os.write(self.fd, command.encode())
                time.sleep(0.15)
            self.ok = True
            threading.Thread(target=self._run, daemon=True).start()
            print(f"Speed radar connected on {port}")
        except OSError as e:
            print(f"Speed radar not available on {port} ({e}); speeds will show as --")

    def _run(self):
        buffer = b""
        while not K.quit:
            try:
                ready, _, _ = select.select([self.fd], [], [], 0.2)
                if not ready:
                    continue
                buffer += os.read(self.fd, 4096)
            except OSError:
                self.ok = False
                print("Speed radar disconnected")
                return
            now = time.monotonic()
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                text = line.decode(errors="replace").strip()
                if not text or text.startswith("{"):
                    continue
                numbers = NUMBER.findall(text)
                if numbers:
                    self.readings.append((now, float(numbers[-1])))

    def window(self, t0, t1):
        return [(t, s) for t, s in list(self.readings) if t0 <= t <= t1]


def carry_estimate(ball_mph, launch_deg):
    """Rough carry in yards from ball speed and launch angle.

    A simple flight model with fixed drag and lift. Real carry depends on spin,
    which is not measured, so treat this as an estimate.
    """
    v = ball_mph * 0.44704
    a = math.radians(launch_deg)
    vx, vy, x, y = v * math.cos(a), v * math.sin(a), 0.0, 0.0
    k, cd, cl, dt = 0.0191, 0.23, 0.16, 0.002
    for _ in range(20000):
        s = math.hypot(vx, vy)
        ax = -k * cd * s * vx - k * cl * s * vy
        ay = -9.81 - k * cd * s * vy + k * cl * s * vx
        vx, vy = vx + ax * dt, vy + ay * dt
        x, y = x + vx * dt, y + vy * dt
        if y < 0:
            break
    return x * 1.09361


def shot_metrics(radar, trigger_time, args):
    """Work out the numbers for one shot from what the sensors recorded."""
    m = empty_metrics()
    if radar is not None and radar.ok:
        readings = [(t, abs(s)) for t, s in
                    radar.window(trigger_time - 0.6, time.monotonic())
                    if abs(s) >= args.min_speed]
        if readings:
            t_top, top = max(readings, key=lambda r: r[1])
            if args.swing_test:
                m["club_speed"] = round(top, 1)   # no ball, so the fastest thing is the club
            else:
                m["ball_speed"] = round(top, 1)
                # The club is the fastest reading before the ball that is clearly
                # slower than the ball. This is a first guess and needs checking
                # against real shots.
                earlier = [s for t, s in readings if t < t_top and top / 1.8 <= s <= top / 1.05]
                if earlier:
                    m["club_speed"] = round(max(earlier), 1)
                    m["smash"] = round(top / max(earlier), 2)
    if args.assume_launch > 0:
        m["launch_angle"] = args.assume_launch
    if m["ball_speed"] and m["launch_angle"]:
        m["carry"] = round(carry_estimate(m["ball_speed"], m["launch_angle"]))
    return m


def save_metrics(folder, metrics, radar_log):
    if folder and os.path.isdir(folder):
        with open(os.path.join(folder, "metrics.json"), "w") as f:
            json.dump({"metrics": metrics, "radar_readings": radar_log}, f, indent=2)


def _publish(shot, o, r, final):
    """Show the radar numbers for this shot. Returns the metrics, or None if a
    newer shot has replaced it."""
    with K.lock:
        if K.shot != shot:
            return None
        m = dict(K.metrics)
        m["radar_pending"] = not final
        if o:
            if o["ball_speed"] is not None:
                m["ball_speed"] = round(o["ball_speed"], 1)
            if o["club_speed"] is not None:
                m["club_speed"] = round(o["club_speed"], 1)
            if o["spin"] is not None:
                m["spin"] = round(o["spin"])
        if r:
            m["iwr_quality"], m["iwr_error"] = r["quality"], r["error"]
            if r["launch_angle"] is not None:
                m["launch_angle"] = round(r["launch_angle"], 1)
            if m.get("ball_speed") is None and r["ball_speed"] is not None:
                m["ball_speed"] = round(r["ball_speed"], 1)
        if m.get("ball_speed") and m.get("club_speed"):
            smash = m["ball_speed"] / m["club_speed"]
            if 0.8 <= smash <= 1.6:
                m["smash"] = round(smash, 2)
            else:
                # No real strike gives this ratio: the club reading is wrong.
                if final:
                    print(f"Shot {shot}: club speed {m['club_speed']} mph doesn't fit ball speed "
                          f"{m['ball_speed']} mph (smash {smash:.2f}); not shown")
                m["club_speed_rejected"] = m.pop("club_speed")
                m.pop("smash", None)
        if m.get("ball_speed") and m.get("launch_angle"):
            m["carry"] = round(carry_estimate(m["ball_speed"], m["launch_angle"]))
        elif o and o.get("carry"):
            m["carry"] = round(o["carry"])
        K.metrics = m
        K.rev += 1
        return m


def add_radar_results(iwr, ops, shot, trigger_time, folder, radar_log):
    """Put the radars' answers for this shot on screen: the speed radar's
    numbers as soon as they arrive (a few seconds), then the TI radar's launch
    angle when its capture has been processed (several seconds more)."""
    o = ops.result_for(trigger_time, wait_s=12.0) if ops is not None else None
    m = _publish(shot, o, None, final=(iwr is None or o is None))
    if m is None:
        return                          # a newer shot has already replaced this one
    r = None
    if iwr is not None:
        # The TI radar is guided by the speed radar's shot, so without one there
        # is nothing to wait for.
        r = iwr.result_for(trigger_time, wait_s=30.0) if o else {
            "launch_angle": None, "ball_speed": None, "quality": None,
            "error": "no speed-radar shot to guide the TI radar"}
        m = _publish(shot, o, r, final=True)
        if m is None:
            return
    save_metrics(folder if K.folder == folder else None, m, radar_log)
    if getattr(K, "sim", None) is not None and o:
        K.sim.send(o.get("shot"), r.get("launch_angle") if r else None)

    if ops is not None and not o:
        print(f"Shot {shot}: speed radar gave no reading (no ball seen flying away from it)")
    if r and r["error"]:
        print(f"Shot {shot}: TI radar gave no angle ({r['error']})")
    shown = {x: m[x] for x in ("ball_speed", "club_speed", "smash", "launch_angle", "spin", "carry")
             if m.get(x) is not None}
    print(f"Shot {shot}: {shown if shown else 'no radar numbers'}")

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
    p = argparse.ArgumentParser(description="Launch monitor kiosk")
    p.add_argument("--model", default=DEFAULT_MODEL, help="path to the golf ball model")
    p.add_argument("--imgsz", type=int, default=256)
    p.add_argument("--conf", type=float, default=0.5, help="minimum model confidence, 0-1")
    p.add_argument("--tile", type=int, default=256,
                   help="size of the full-detail tiles used to find a distant ball (0 = whole frame only)")
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
    p.add_argument("--bit-depth", type=int, default=8, choices=(8, 10),
                   help="sensor bit depth; 8 allows the fastest frame rates")
    p.add_argument("--exposure", type=int, default=0)
    p.add_argument("--gain", type=float, default=0.0)
    p.add_argument("--out", default="shots", help="folder to save shots into")
    p.add_argument("--port", type=int, default=8000)
    add_blob_args(p)
    p.add_argument("--no-ball", action="store_true",
                   help="swing test: skip ball detection and record when a fast swing passes")
    p.add_argument("--swing-fraction", type=float, default=0.015,
                   help="share of the picture that must change in one frame to count as a swing")
    p.add_argument("--radar-port", default="/dev/ttyACM0", help="OPS243-A serial port")
    p.add_argument("--ops-speed-mode", action="store_true",
                   help="read plain speed readings from the OPS243-A. Only for a radar NOT set up in "
                        "rolling-buffer mode; this sends it setup commands")
    p.add_argument("--ops", action="store_true",
                   help="use the OPS243-A in rolling-buffer mode through OpenFlight's code "
                        "(ball speed, club speed, spin)")
    p.add_argument("--ops-ksps", type=int, default=30, help="OPS243-A sample rate, thousands per second")
    p.add_argument("--iwr", action="store_true",
                   help="use the TI radar through OpenFlight's code for launch angle")
    p.add_argument("--openflight", default="~/openflight", help="where OpenFlight is installed")
    p.add_argument("--iwr-port", default="/dev/ttyUSB0")
    p.add_argument("--iwr-config", default="config/iwr6843_l3dump_wide_24f3ms_53bin_iq16.cfg")
    p.add_argument("--iwr-cal", default="config/iwr6843_calibration_reference.json",
                   help="TI radar calibration file (inside the OpenFlight folder)")
    p.add_argument("--iwr-tee-m", type=float, default=1.575, help="radar to tee distance, m")
    p.add_argument("--iwr-net-m", type=float, default=4.6, help="radar to net distance, m")
    p.add_argument("--iwr-tilt-deg", type=float, default=10.4, help="radar upward tilt, degrees")
    p.add_argument("--iwr-radar-height-m", type=float, default=0.1524,
                   help="antenna centre height above the floor, m")
    p.add_argument("--iwr-ball-height-m", type=float, default=0.040,
                   help="ball centre height above the floor, m")
    p.add_argument("--iwr-save-dumps", action="store_true", help="also save the raw TI radar captures")
    p.add_argument("--sim", action="store_true",
                   help="send each shot to a golf simulator (OpenGolfSim by default)")
    p.add_argument("--sim-type", default="opengolfsim", choices=("opengolfsim", "gspro", "partee"))
    p.add_argument("--sim-host", default="192.168.137.1",
                   help="IP address of the computer running the simulator")
    p.add_argument("--sim-port", type=int, default=0, help="0 = the simulator's usual port")
    p.add_argument("--sim-club", default="",
                   help="club the simulator should assume, e.g. driver, 7i, pw (default: OpenFlight's)")
    p.add_argument("--min-speed", type=float, default=10.0,
                   help="ignore radar readings slower than this (mph)")
    p.add_argument("--assume-launch", type=float, default=0.0,
                   help="launch angle in degrees to assume for the carry estimate until it is measured")
    p.add_argument("--no-browser", action="store_true", help="do not open the full-screen browser")
    args = p.parse_args()
    args.triggers = {t.strip() for t in args.trigger.split(",") if t.strip()}
    args.swing_test = args.no_ball
    if args.swing_test:
        args.triggers.discard("motion")  # there is no ball patch to watch
    # A search area set by tapping the ball last time wins over --search-area.
    try:
        with open(os.path.join(args.out, AREA_FILE)) as f:
            saved = f.read().strip()
        if saved:
            args.search_area = saved
            print(f"Using the search area you last tapped: {saved}")
    except OSError:
        pass
    K.args = args

    url = f"http://localhost:{args.port}"
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    browser = None if args.no_browser else open_browser(url)
    print(f"Kiosk page: {url}  (also http://modus.local:{args.port} from the laptop)")

    radar = Radar(args.radar_port) if args.ops_speed_mode else None

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
        sensor={"output_size": (WIDTH, HEIGHT), "bit_depth": args.bit_depth},
        controls=controls, buffer_count=8))
    cam.start()
    time.sleep(1.0)

    sh = Shared(maxlen=int(args.fps * (args.pre + args.post) * 1.3) + 20)
    threading.Thread(target=camera_thread, args=(cam, sh, args), daemon=True).start()

    ops = None
    if args.ops:
        if args.ops_speed_mode:
            print("--ops and --ops-speed-mode can't be used together; using --ops")
            radar = None
        try:
            from iwr_bridge import OPSBridge
            ops = OPSBridge(args)
        except Exception as e:
            print(f"Speed radar not available ({type(e).__name__}: {e}); continuing without it")
    K.sim = None
    if args.sim:
        if ops is None:
            print("Simulator needs the speed radar (--ops); not sending shots")
        else:
            try:
                from sim_bridge import SimBridge
                K.sim = SimBridge(args)
            except Exception as e:
                print(f"Simulator not available ({type(e).__name__}: {e}); continuing without it")
    bridge = None
    if args.iwr:
        try:
            from iwr_bridge import IWRBridge
            # OpenFlight's monitor owns GPIO17; each sound trigger is passed on to
            # the camera so it can capture the shot too.
            bridge = IWRBridge(args, on_trigger=lambda: sh.trigger("sound"), ops=ops)
        except Exception as e:
            print(f"TI radar not available ({type(e).__name__}: {e}); continuing without it")
    if "sound" in args.triggers and bridge is None:
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
            if K.reset_track:             # the search area was just moved by a tap
                K.reset_track = False
                trk.update(new_track())
                sh.armed = False
                sh.roi = sh.roi_ref = None

            # A shot was captured: save it, work out the numbers, and carry on.
            if sh.pending is not None:
                K.state = "CAPTURING"
                K.drop_undecided()           # the previous video defaults to deleted
                trigger_time, _, window = sh.pending
                folder = save_shot(sh.pending, args.out)
                replay = [cv2.imencode(".jpg", np.ascontiguousarray(f[2]),
                                       [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()
                          for f in window]
                metrics = shot_metrics(radar, trigger_time, args)
                # Every radar reading around the shot, as (milliseconds from the
                # trigger, mph). Printed and saved so the club/ball rule can be tuned.
                radar_log = []
                if radar is not None and radar.ok:
                    radar_log = [(round((t - trigger_time) * 1000), round(s, 1)) for t, s in
                                 radar.window(trigger_time - 0.6, time.monotonic())]
                    print("Radar readings (ms from trigger, mph):",
                          radar_log if radar_log else "none")
                if bridge is not None or ops is not None:
                    metrics["radar_pending"] = True
                save_metrics(folder, metrics, radar_log)
                with K.lock:
                    K.replay, K.folder, K.metrics = replay, folder, metrics
                    K.video = "pending" if folder else "none"
                    K.shot += 1
                    K.rev += 1
                if bridge is not None or ops is not None:
                    threading.Thread(target=add_radar_results,
                                     args=(bridge, ops, K.shot, trigger_time, folder, radar_log),
                                     daemon=True).start()
                shown = {k: v for k, v in metrics.items() if v is not None and k != "carry_estimated"}
                print(f"Shot {K.shot}: {shown if shown else 'no sensor readings'}")
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
                ball = detect_ball(model, gray, args, trk)
                K.state = update_ready(sh, args, gray, ball, trk, time.monotonic())
                ball = trk["box"]

            K.latest_gray = gray
            # Live picture for the Camera view, with a box round the ball.
            view = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            if args.search_area:
                a = [int(float(v)) for v in args.search_area.split(",")]
                cv2.rectangle(view, (a[0], a[1]), (a[2], a[3]), (255, 200, 0), 1)
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
        K.drop_undecided()
        K.quit = True
        sh.running = False
        if bridge is not None:
            bridge.stop()
        if ops is not None:
            ops.stop()
        if K.sim is not None:
            K.sim.stop()
        if browser is not None:
            browser.terminate()
        time.sleep(0.2)
        cam.stop()
        server.shutdown()


if __name__ == "__main__":
    main()
