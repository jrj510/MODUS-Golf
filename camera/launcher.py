#!/usr/bin/env python3
"""
MODUS-Golf start menu.

Shown on the Pi's screen (and on any phone on the MODUS WiFi) before the kiosk
starts. Pick how shots are detected and which club is being hit, press Start,
and this prints the choice for start_kiosk.sh, which then starts the kiosk. The
kiosk's Menu button brings you back here.

    python3 camera/launcher.py [--open-browser]

Prints one line when Start is pressed, for example "outside,7i" or "inside,driver".
Modes (both use the camera + sound trigger and the slow-motion shot preview):
       outside = Outside Golf: slower camera so a battery pack lasts and doesn't cut out;
       inside  = Inside Golf: fastest camera, needs a wall outlet.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SETTINGS = os.path.expanduser("~/MODUS-Golf/shots/launcher.json")
MODES = ("outside", "inside")
CLUBS = ["driver", "3w", "hybrid", "5i", "6i", "7i", "8i", "9i", "pw", "52", "56", "60"]
CLUB_LABEL = {"driver": "Driver", "3w": "3 Wood", "hybrid": "Hybrid", "5i": "5 Iron",
              "6i": "6 Iron", "7i": "7 Iron", "8i": "8 Iron", "9i": "9 Iron", "pw": "PW",
              "52": "52°", "56": "56°", "60": "60°"}

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MODUS Golf</title>
<style>
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:#0b0f14;color:#eef3f7;
  font-family:system-ui,-apple-system,sans-serif;user-select:none;-webkit-user-select:none}
body{display:flex;flex-direction:column;padding:2.5vh 3vw;gap:2.2vh}
h1{margin:0;font-size:5.5vh;letter-spacing:.5px}
h1 span{color:#2ecc71}
.lbl{color:#8a97a5;font-size:2.8vh;margin-bottom:1vh;font-weight:600}
.row{display:grid;gap:1.5vw}
.modes{grid-template-columns:1fr 1fr}
.mode{background:#141b24;border:3px solid #141b24;border-radius:16px;padding:2vh 2vw;color:#eef3f7;
  text-align:left;font:inherit}
.mode b{display:block;font-size:3.6vh;margin-bottom:.6vh}
.mode small{color:#8a97a5;font-size:2.3vh;line-height:1.3}
.mode.on{border-color:#2ecc71;background:#132519}
.clubs{grid-template-columns:repeat(6,1fr)}
.club{background:#141b24;border:3px solid #141b24;border-radius:12px;color:#eef3f7;font:inherit;
  font-size:3vh;font-weight:700;padding:1.6vh 0}
.club.on{border-color:#2ecc71;background:#132519}
#start{margin-top:auto;background:#2ecc71;color:#06210f;border:0;border-radius:16px;font:inherit;
  font-size:4.6vh;font-weight:800;padding:2.4vh}
#start:disabled{background:#2a3a30;color:#7c8a80}
#hint{color:#6f7c89;font-size:2.1vh;text-align:center}
#msg{color:#f0b429;font-size:2.4vh;text-align:center;min-height:2.6vh}
</style></head><body>
<h1>MODUS <span>Golf</span></h1>
<div>
  <div class="lbl">Where are you playing?</div>
  <div class="row modes">
    <button class="mode" data-mode="outside"><b>Outside Golf</b>
      <small>Runs on the battery pack. Slower camera and no shot replay to save power.</small></button>
    <button class="mode" data-mode="inside"><b>Inside Golf</b>
      <small>Fastest camera. Plug into a wall outlet (won't work on the battery).</small></button>
  </div>
</div>
<div>
  <div class="lbl">Club (sets typical launch and spin until launch angle is measured)</div>
  <div class="row clubs" id="clubs"></div>
</div>
<div id="msg"></div>
<button id="start">Start</button>
<div id="hint">Phone: join WiFi <b>MODUS</b>, open <b>10.42.0.1:8000</b></div>
<script>
const CLUBS=__CLUBS__, LABEL=__LABELS__;
let mode=__MODE__, club=__CLUB__;
const $=id=>document.getElementById(id);
for(const c of CLUBS){const b=document.createElement('button');b.className='club';b.dataset.club=c;
  b.textContent=LABEL[c]||c.toUpperCase();$('clubs').appendChild(b);}
function draw(){
  document.querySelectorAll('.mode').forEach(b=>b.classList.toggle('on',b.dataset.mode===mode));
  document.querySelectorAll('.club').forEach(b=>b.classList.toggle('on',b.dataset.club===club));
}
document.querySelectorAll('.mode').forEach(b=>b.onclick=()=>{mode=b.dataset.mode;draw();});
document.querySelectorAll('.club').forEach(b=>b.onclick=()=>{club=b.dataset.club;draw();});
$('start').onclick=async()=>{
  $('start').disabled=true;$('start').textContent='Starting...';
  $('msg').textContent='Getting the camera and radars ready (about 20 seconds)';
  try{await fetch('/start?mode='+mode+'&club='+encodeURIComponent(club),{method:'POST'});}catch(e){}
  waitForKiosk();
};
async function waitForKiosk(){
  try{const r=await fetch('/state',{cache:'no-store'});if(r.ok){location.href='/';return;}}catch(e){}
  setTimeout(waitForKiosk,1000);
}
draw();
__NOTE__
</script></body></html>"""


def load_settings():
    try:
        with open(SETTINGS) as f:
            s = json.load(f)
    except (OSError, ValueError):
        s = {}
    mode = s.get("mode")
    if mode not in MODES:
        mode = "outside"                               # older saved choice
    club = s.get("club") if s.get("club") in CLUBS else "52"
    return mode, club


def save_settings(mode, club):
    try:
        os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
        with open(SETTINGS, "w") as f:
            json.dump({"mode": mode, "club": club}, f)
    except OSError:
        pass


def session_env():
    """Environment for opening a window on the Pi's own screen, even when this
    was started over SSH: borrow the display settings from a program that is
    already running on the desktop."""
    env = dict(os.environ)
    if "WAYLAND_DISPLAY" in env or "DISPLAY" in env:
        return env
    uid = os.getuid()
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            if os.stat(f"/proc/{pid}").st_uid != uid:
                continue
            with open(f"/proc/{pid}/environ", "rb") as f:
                items = dict(p.split(b"=", 1) for p in f.read().split(b"\0") if b"=" in p)
        except OSError:
            continue
        if b"WAYLAND_DISPLAY" in items or b"DISPLAY" in items:
            for key in (b"WAYLAND_DISPLAY", b"DISPLAY", b"XDG_RUNTIME_DIR"):
                if key in items:
                    env[key.decode()] = items[key].decode()
            return env
    env["WAYLAND_DISPLAY"] = "wayland-0"
    return env


def open_browser(url):
    exe = shutil.which("chromium") or shutil.which("chromium-browser")
    if exe is None:
        print("Chromium not found; open the menu from a browser yourself.", file=sys.stderr)
        return
    profile = os.path.expanduser("~/.config/modus-kiosk")
    subprocess.Popen([exe, "--kiosk", "--noerrdialogs", "--disable-infobars", "--no-first-run",
                      "--password-store=basic", f"--user-data-dir={profile}", url],
                     env=session_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)   # keeps running after this menu closes


def main():
    p = argparse.ArgumentParser(description="MODUS-Golf start menu")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--open-browser", action="store_true", help="open the full-screen browser")
    p.add_argument("--note", default="", help="message to show, e.g. after a crash")
    args = p.parse_args()

    mode, club = load_settings()
    note = (f"document.getElementById('msg').textContent={json.dumps(args.note)};"
            if args.note else "")
    page = (PAGE.replace("__CLUBS__", json.dumps(CLUBS))
                .replace("__LABELS__", json.dumps(CLUB_LABEL))
                .replace("__MODE__", json.dumps(mode)).replace("__CLUB__", json.dumps(club))
                .replace("__NOTE__", note)).encode()
    choice = {}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/ping":
                body, kind = b"menu", "text/plain"
            elif path == "/":
                body, kind = page, "text/html"
            else:
                self.send_response(404)      # e.g. /state: the kiosk isn't running yet
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            path, _, query = self.path.partition("?")
            q = dict(x.split("=", 1) for x in query.split("&") if "=" in x)
            if path == "/start":
                m = q.get("mode") if q.get("mode") in MODES else "outside"
                c = q.get("club") if q.get("club") in CLUBS else "52"
                choice.update(mode=m, club=c)
                done.set()
            self.send_response(204)
            self.end_headers()

        def log_message(self, *a):
            pass

    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if args.open_browser:
        open_browser(f"http://localhost:{args.port}/")
    print(f"Menu ready at http://localhost:{args.port}/", file=sys.stderr)
    done.wait()
    server.shutdown()
    server.server_close()
    save_settings(choice["mode"], choice["club"])
    print(f"{choice['mode']},{choice['club']}")


if __name__ == "__main__":
    main()
