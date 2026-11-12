#!/usr/bin/env python3
"""
Kiosk mode for the launch monitor.

The touchscreen shows a dashboard of shot numbers that is always on screen:
    Ball Speed, Club Speed, Smash Factor, Carry,
    Launch Angle, Launch Direction, Spin Rate, Club Path

Top left is the status indicator (Looking for Ball / Ready / Recording).
After a shot the numbers fill in and a "Shot Preview" button appears beside
the status. Tapping it opens the slow-motion replay with Save and Delete.

Hitting zone: open Camera and drag a box over where the ball is set down,
once (it is remembered). The camera then keeps watching that zone and finds
each ball put down in it by itself, then goes Ready once the ball is still.
Tapping a ball on the Camera view points it out if it is ever missed.

Nothing needs to be tapped between shots. The numbers and the replay stay
until the next shot replaces them. A replay that was neither saved nor
deleted is deleted when the next shot arrives, or when the kiosk exits.

Numbers that no connected sensor can measure yet are shown as "--".

Sleep (the moon button, top right): the camera and the TI radar stop and the
screen goes dark until it is tapped; waking takes a few seconds (the TI radar
is set up again, exactly as at start-up). With --sleep-minutes the kiosk also
goes to sleep by itself after that long Looking for Ball with no ball, no shot
and no taps on the screen. It never sleeps in the middle of a shot. The speed
radar stays on: switching its mode while running can break its trigger.
Ball finding, Ready and the shot triggers are not changed by any of this.

This file must sit in the same folder as shot_capture.py, which it reuses.

Run from a terminal, inside vision-env:
    python3 camera/kiosk.py
    python3 camera/kiosk.py --no-ball          (swing test, no ball needed)
    python3 camera/kiosk.py --no-browser       (no screen attached; view from the laptop)
"""

import argparse
import collections
import glob
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

from ballflight import club_defaults, shot_flight
from range_page import RANGE_PAGE
from shot_capture import (HEIGHT, KEEP_MARKER, STREAM, WIDTH, Shared, View, ZoneWatch, add_blob_args,
                          convert_area, count_training, fits_zoomed, save_training_frame, set_view,
                          sharpness, zoom_on,
                          add_exposure_args, add_tracking_args, camera_thread, detect_ball,
                          new_track, prune_shots, save_shot, set_frame_rate, shot_folder,
                          smooth_box, start_camera, update_ready, _ball_diff)

DEFAULT_MODEL = "~/openflight/models/golf_ball_yolo11n_new_256.onnx"
# Clubs for the Club button (same list and names as the start menu, launcher.py).
CLUBS = ["driver", "3w", "hybrid", "5i", "6i", "7i", "8i", "9i", "pw", "52", "56", "60"]
CLUB_LABEL = {"driver": "Driver", "3w": "3 Wood", "hybrid": "Hybrid", "5i": "5 Iron",
              "6i": "6 Iron", "7i": "7 Iron", "8i": "8 Iron", "9i": "9 Iron", "pw": "PW",
              "52": "52\u00b0", "56": "56\u00b0", "60": "60\u00b0"}
MENU_SETTINGS = os.path.expanduser("~/MODUS-Golf/shots/launcher.json")   # shared with launcher.py
REPLAY_FPS = 30
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")

PAGE = b"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
/* Same look as the start menu (launcher.py): dark cards, green for "on". */
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:#0b0f14;color:#eef3f7;
  font-family:system-ui,-apple-system,sans-serif;overflow:hidden;user-select:none;-webkit-user-select:none}
body{display:flex;flex-direction:column;padding:2vh 2.2vw;gap:1.8vh}
#top{display:flex;align-items:center;gap:.75vw;height:11vh;min-height:48px}
#brand{margin:0;font-size:4.4vh;font-weight:800;letter-spacing:.5px;white-space:nowrap}
#brand span{color:#2ecc71}
#status{display:flex;align-items:center;gap:1vw;background:#141b24;border:3px solid #141b24;
  border-radius:16px;padding:0 1.6vw;height:100%;font-size:3.8vh;font-weight:700;white-space:nowrap}
#dot{width:2.4vh;height:2.4vh;border-radius:50%;background:#8a97a5}
#shotno{color:#8a97a5;font-size:2.8vh;font-weight:600;margin-left:auto;white-space:nowrap}
button{background:#141b24;border:3px solid #141b24;border-radius:12px;color:#eef3f7;font:inherit;
  font-size:3vh;font-weight:700;padding:0 1.6vw;height:100%}
button:active{border-color:#2ecc71;background:#132519}
#pv{border-color:#2ecc71;background:#132519}
#quit{color:#8a97a5}
#top>button{padding:0 1.15vw}   /* a little tighter, so Sleep fits too on an 800x480 screen */
#sleepbtn{display:flex;align-items:center}
#sleepbtn svg{width:4.4vh;height:4.4vh;fill:#8a97a5}
.hide{display:none!important}
.view{flex:1;min-height:0}
#main{display:grid;grid-template-columns:repeat(4,1fr);grid-template-rows:1fr 1fr;gap:1.5vw}
.tile{background:#141b24;border:3px solid #141b24;border-radius:16px;display:flex;flex-direction:column;
  align-items:flex-start;justify-content:space-between;padding:1.8vh 1.4vw;min-width:0;
  transition:border-color .3s,background .3s}
.lbl{color:#2ecc71;font-size:3.6vh;font-weight:700}
.val{font-size:10.5vh;font-weight:800;line-height:1;font-variant-numeric:tabular-nums;align-self:center}
.val.none{color:#2f3b48}
.unit{color:#2ecc71;font-size:3.4vh;font-weight:700;min-height:4vh;align-self:flex-end}
.fresh{border-color:#2ecc71;background:#132519}
#preview,#camera{display:flex;flex-direction:column;align-items:center;gap:1.5vh}
#camera{position:relative}#live{touch-action:none}
#sel{position:absolute;display:none;border:2px dashed #2ecc71;pointer-events:none}
#preview img,#camera img{flex:1;min-height:0;max-width:100%;object-fit:contain;border-radius:16px;
  border:3px solid #141b24}
.bar{display:flex;align-items:center;gap:1.5vw;height:11vh;min-height:48px;width:100%;justify-content:center}
#keep{background:#2ecc71;border-color:#2ecc71;color:#06210f;font-weight:800}
#del{border-color:#c0392b;color:#ff8a80}
#vmsg{font-size:3vh;color:#8a97a5;font-weight:600}
.cmsg{font-size:2.4vh;color:#8a97a5;text-align:center}
#expo{font-size:2.2vh;color:#6f7c89}
#camwarn{color:#f0b429;font-size:2.4vh;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#clubbtn b{color:#2ecc71}
#clubs{display:flex;flex-direction:column;gap:2vh}
#clubs .grid{flex:1;display:grid;grid-template-columns:repeat(4,1fr);grid-template-rows:repeat(3,1fr);gap:1.5vw}
#clubs .club{height:auto;font-size:4.4vh;font-weight:800;border-radius:16px}
#clubs .club.on{border-color:#2ecc71;background:#132519;color:#2ecc71}
#clubs .head{display:flex;align-items:center;gap:1.5vw;height:9vh}
#clubs .head .lbl{flex:1}
</style></head><body>
<div id="top">
  <h1 id="brand">MODUS <span>Golf</span></h1>
  <div id="status"><span id="dot"></span><span id="stext">Starting</span></div>
  <button id="pv" class="hide" onclick="show('preview')">Shot Preview</button>
  <span id="camwarn"></span>
  <span id="shotno"></span>
  <button id="clubbtn" onclick="show('clubs')">Club <b id="clubname"></b></button>
  <button id="cam" onclick="show('camera')">Camera</button>
  <button id="rng" onclick="location.href='/range'">Range</button>
  <button id="sleepbtn" onclick="sleepUI.sleep()" title="Sleep"><svg viewBox="0 0 24 24"><path
    d="M20.5 14.6A8.6 8.6 0 0 1 9.4 3.5 8.6 8.6 0 1 0 20.5 14.6z"/></svg></button>
  <button id="quit" onclick="post('quit')">Menu</button>
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
<div id="clubs" class="view hide">
  <div class="head"><button onclick="show('main')">Back</button>
    <span class="lbl">Club: sets the typical launch and spin until launch angle is measured</span></div>
  <div class="grid" id="clubgrid"></div>
</div>
<div id="camera" class="view hide">
  <img id="live" draggable="false"><div id="sel"></div>
  <div class="bar"><button onclick="show('main')">Back</button>
    <button id="zoombtn" class="hide" onclick="zoomToggle()">Zoom in</button>
    <button id="trainbtn" onclick="saveTraining()">Save frame</button>
    <span class="cmsg">Drag a box over where the ball is set down (once). Each ball put down inside it
      is found by itself.<br>Tap a ball to point it out. <span id="focus"></span> <span id="expo"></span></span></div>
</div>
__SLEEP__
<script>
const TILES=[['ball_speed','Ball Speed','mph',1],['club_speed','Club Speed','mph',1],
  ['smash','Smash Factor','',2],['carry','Carry','yd',0],
  ['launch_angle','Launch Angle','deg',1],['launch_dir','Launch Direction','deg',1],
  ['spin','Spin Rate','rpm',0],['club_path','Club Path','deg',1]];
const STATUS={STARTING:['Starting','#8a97a5'],SEARCHING:['Looking for Ball','#f0b429'],
  BALL:['Looking for Ball','#f0b429'],READY:['Ready','#2ecc71'],
  CAPTURING:['Recording','#c77dff'],WAIT:['Get Set','#f0b429'],MEASURING:['Measuring','#4dabf7'],
  CHECKING:['Checking','#4dabf7'],SLEEPING:['Asleep','#5c6b7a'],WAKING:['Waking up','#8a97a5'],
  SWINGTEST:['Ready','#2ecc71']};
const $=id=>document.getElementById(id);
const main=$('main');
for(const [k,label,unit] of TILES){
  const t=document.createElement('div');t.className='tile';t.id='t_'+k;
  t.innerHTML='<div class="lbl">'+label+'</div><div class="val none" id="m_'+k+'">--</div>'+
              '<div class="unit" id="u_'+k+'">'+unit+'</div>';
  main.appendChild(t);
}
let view='main',shot=-1,rev=-1,video='none',club=null;
const CLUBS=__CLUBS__,CLUB_LABEL=__CLUB_LABEL__;
for(const c of CLUBS){const b=document.createElement('button');b.className='club';b.dataset.club=c;
  b.textContent=CLUB_LABEL[c]||c.toUpperCase();
  b.onclick=()=>{club=c;drawClub();fetch('/club?c='+encodeURIComponent(c),{method:'POST'});show('main');};
  $('clubgrid').appendChild(b);}
function drawClub(){
  $('clubname').textContent=club?(CLUB_LABEL[club]||club):'';
  document.querySelectorAll('#clubgrid .club').forEach(b=>b.classList.toggle('on',b.dataset.club===club));
}
function post(a){fetch('/'+a,{method:'POST'});}
// Live view: drag a box over the hitting area (the hitting zone) and the camera
// keeps looking for a ball set down anywhere inside it (remembered across
// restarts). A tap points out a ball; with no zone yet it also makes one round it.
let drag=null;
$('live').addEventListener('dragstart',e=>e.preventDefault());   // mouse: no image drag
function imgXY(e){
  const img=$('live'),r=img.getBoundingClientRect();
  const s=Math.min(r.width/img.naturalWidth,r.height/img.naturalHeight);
  const w=img.naturalWidth*s,h=img.naturalHeight*s;
  return [(e.clientX-r.left-(r.width-w)/2)/w,(e.clientY-r.top-(r.height-h)/2)/h];
}
const clip=v=>Math.min(Math.max(v,0),1).toFixed(4);
$('live').addEventListener('pointerdown',e=>{
  if(!$('live').naturalWidth)return;
  e.preventDefault();drag={x:e.clientX,y:e.clientY,p:imgXY(e)};
  try{$('live').setPointerCapture(e.pointerId);}catch(err){}
});
$('live').addEventListener('pointermove',e=>{
  if(!drag)return;
  const c=$('camera').getBoundingClientRect(),st=$('sel').style;
  st.display='block';
  st.left=(Math.min(drag.x,e.clientX)-c.left)+'px';st.top=(Math.min(drag.y,e.clientY)-c.top)+'px';
  st.width=Math.abs(e.clientX-drag.x)+'px';st.height=Math.abs(e.clientY-drag.y)+'px';
});
function endDrag(e){
  if(!drag)return;
  const a=drag.p,b=imgXY(e),moved=Math.hypot(e.clientX-drag.x,e.clientY-drag.y);
  drag=null;$('sel').style.display='none';
  if(moved<12){
    if(a[0]>=0&&a[0]<=1&&a[1]>=0&&a[1]<=1)
      fetch('/aim?x='+clip(a[0])+'&y='+clip(a[1]),{method:'POST'});
  }else{
    fetch('/zone?x0='+clip(Math.min(a[0],b[0]))+'&y0='+clip(Math.min(a[1],b[1]))+
          '&x1='+clip(Math.max(a[0],b[0]))+'&y1='+clip(Math.max(a[1],b[1])),{method:'POST'});
  }
}
$('live').addEventListener('pointerup',endDrag);
$('live').addEventListener('pointercancel',()=>{drag=null;$('sel').style.display='none';});
let zoomed=false;
function zoomToggle(){fetch('/view?zoom='+(zoomed?0:1),{method:'POST'});}
function saveTraining(){fetch('/train_frame',{method:'POST'});}
function show(v){
  view=v;
  for(const n of ['main','preview','camera','clubs'])$(n).classList.toggle('hide',n!=v);
  $('rep').src=(v=='preview')?'/replay.mjpg?'+shot+'_'+Date.now():'';
  $('live').src=(v=='camera')?'/stream.mjpg':'';
}
async function tick(){
  let next=250;
  try{
    const s=await (await fetch('/state')).json();
    sleepUI.view(s.state);
    if(s.state=='SLEEPING'){
      next=1000;                       // nothing changes while asleep
      if(view!='main')show('main');    // (closes the live camera stream)
    }
    const st=STATUS[s.state]||[s.state,'#fff'];
    $('stext').textContent=st[0];$('dot').style.background=st[1];$('status').style.borderColor=st[1];
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
    if(s.club&&s.club!==club){club=s.club;drawClub();}
    video=s.video;
    const has=(video=='pending'||video=='kept');
    $('pv').classList.toggle('hide',!has);
    $('keep').classList.toggle('hide',video!='pending');
    $('del').classList.toggle('hide',!has);
    $('vmsg').textContent=video=='kept'?'Saved':(video=='pending'?'Save this video?':'');
    if(view=='preview'&&!has)show('main');
    const c=s.camera;
    $('expo').textContent=c?('Exposure '+c.exposure_us+' us x'+c.gain+
      (c.median!=null?', ball area brightness '+c.median+(c.clipped_pct?' ('+c.clipped_pct+'% white)':''):'')+
      (c.message?'. '+c.message:'')):'';
    const vw=s.view||{};zoomed=!!vw.zoomed;
    $('zoombtn').classList.toggle('hide',!vw.can_zoom);
    $('zoombtn').textContent=zoomed?'Wide view':'Zoom in';
    const f=s.focus;
    $('focus').textContent=f?('Focus '+f.value+' (best '+f.best+', '+f.where+'). '):'';
    const tr=s.training;
    $('trainbtn').textContent='Save frame'+(tr?' ('+tr[0]+' ball / '+tr[1]+' empty)':'');
    $('camwarn').textContent=(c&&c.state=='limit')?(c.message.split(':')[0]):
      (s.zone===false?'No hitting zone yet: Camera, then drag a box over the mat':'');
    fails=0;
  }catch(e){
    // The kiosk stopped (Menu pressed): wait for the start menu, then go there.
    if(++fails>=3){waitForMenu();return;}
  }
  setTimeout(tick,next);
}
let fails=0;
async function waitForMenu(){
  $('stext').textContent='Back to menu...';$('dot').style.background='#9aa7b4';
  try{const r=await fetch('/ping',{cache:'no-store'});if(r.ok){location.href='/';return;}}catch(e){}
  setTimeout(waitForMenu,1000);
}
tick();
</script></body></html>"""

# Sleep screen, shared by the dashboard and the Range page: black over
# everything while asleep, and the tap that wakes it never reaches a button
# underneath. Any tap on the screen also puts off the automatic sleep.
SLEEP_SNIPPET = b"""<style>
#sleepov{position:fixed;inset:0;z-index:1000;background:#000;display:none;flex-direction:column;
  align-items:center;justify-content:center;gap:2vh;touch-action:none;user-select:none;-webkit-user-select:none}
#sleepov.on{display:flex}
#sleepov b{font:800 5vh system-ui,sans-serif;color:#2a343e}
#sleepov span{font:600 2.8vh system-ui,sans-serif;color:#1f272f}
#sleepov.lit b{color:#eef3f7}#sleepov.lit span{color:#8a97a5}
</style>
<div id="sleepov"><b id="sleept">Asleep</b><span id="sleeps">Tap anywhere to wake</span></div>
<script>
const sleepUI=(()=>{
  const ov=document.getElementById('sleepov');
  let going=false,state='';
  function say(a,b,lit){document.getElementById('sleept').textContent=a;
    document.getElementById('sleeps').textContent=b;ov.classList.toggle('lit',!!lit);}
  function view(st){
    state=st;
    if(st=='SLEEPING'){going=false;ov.classList.add('on');say('Asleep','Tap anywhere to wake');}
    else if(st=='WAKING'){ov.classList.add('on');say('Waking up','Starting the camera and radar',true);}
    else if(going)ov.classList.add('on');          // finishing the last shot first
    else ov.classList.remove('on');
  }
  ov.addEventListener('pointerdown',e=>{
    e.preventDefault();e.stopPropagation();
    if(state=='WAKING')return;
    if(going&&state!='SLEEPING'){         // changed your mind before it went to sleep
      going=false;fetch('/wake',{method:'POST'}).catch(()=>{});
      setTimeout(()=>view(state),400);return;
    }
    fetch('/wake',{method:'POST'}).catch(()=>{});
    say('Waking up','Starting the camera and radar',true);
  });
  ov.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();});
  let touched=0;
  document.addEventListener('pointerdown',()=>{
    const n=Date.now();
    if(n-touched>15000){touched=n;fetch('/touch',{method:'POST'}).catch(()=>{});}
  },true);
  function sleep(){
    going=true;ov.classList.add('on');say('Going to sleep','Tap to stay awake',true);
    fetch('/sleep',{method:'POST'}).catch(()=>{});
  }
  async function poll(){             // pages without their own /state loop (Range)
    let next=1000;
    try{const s=await (await fetch('/state',{cache:'no-store'})).json();
        view(s.state);if(s.state!='SLEEPING')next=500;}catch(e){}
    setTimeout(poll,next);
  }
  return {view,sleep,poll};
})();
</script>"""

PAGE = (PAGE.replace(b"__CLUBS__", json.dumps(CLUBS).encode())
            .replace(b"__CLUB_LABEL__", json.dumps(CLUB_LABEL).encode())
            .replace(b"__SLEEP__", SLEEP_SNIPPET))
_end = RANGE_PAGE.rfind(b"</body>")
RANGE_PAGE_SLEEP = (RANGE_PAGE[:_end] + SLEEP_SNIPPET + b"\n<script>sleepUI.poll()</script>"
                    + RANGE_PAGE[_end:]) if _end >= 0 else RANGE_PAGE

BACKLIGHT_SAVE = "/tmp/modus-backlight"   # read back by start_kiosk.sh if the kiosk stops while asleep


class Backlight:
    """The touchscreen's backlight, switched off while asleep (it is most of
    the screen's power; the touch panel keeps working, so a tap still wakes).
    Uses /sys/class/backlight. If that is missing or can't be written, the
    screen is only blacked out."""

    def __init__(self, root="/sys/class/backlight", save_file=BACKLIGHT_SAVE):
        self.root, self.save_file = root, save_file
        self.lock = threading.Lock()
        self.saved = None          # [(path, value)] to put back on waking
        self.warned = False

    @staticmethod
    def _write(path, value):
        try:
            with open(path, "w") as f:
                f.write(str(value))
            return True
        except PermissionError:
            # Not writable by this user: the Pi's own user can usually sudo.
            try:
                return subprocess.run(["sudo", "-n", "tee", path], input=str(value).encode(),
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      timeout=3).returncode == 0
            except (OSError, subprocess.SubprocessError):
                return False
        except OSError:
            return False

    def off(self):
        """Backlight off. True if it could be switched off."""
        with self.lock:
            if self.saved is not None:
                return True
            saved = []
            for dev in sorted(glob.glob(os.path.join(self.root, "*"))):
                level_path = os.path.join(dev, "brightness")
                try:
                    with open(level_path) as f:
                        level = int(f.read().strip())
                    with open(os.path.join(dev, "max_brightness")) as f:
                        top = int(f.read().strip())
                except (OSError, ValueError):
                    continue
                if self._write(level_path, 0):
                    saved.append((level_path, level if level > 0 else top))
                power = os.path.join(dev, "bl_power")
                if os.path.exists(power) and self._write(power, 4):   # 4 = powered down
                    saved.append((power, 0))
            if not saved:
                if not self.warned:
                    self.warned = True
                    print("Screen backlight can't be switched off here (nothing writable in "
                          f"{self.root}); the screen just goes black while asleep")
                return False
            self.saved = saved
            try:
                with open(self.save_file, "w") as f:
                    f.write("".join(f"{p} {v}\n" for p, v in saved))
            except OSError:
                pass
            return True

    def on(self):
        """Backlight back as it was."""
        with self.lock:
            if self.saved is None:
                return
            for path, value in reversed(self.saved):
                self._write(path, value)
            self.saved = None
            try:
                os.remove(self.save_file)
            except OSError:
                pass

    def restore_leftover(self):
        """A run that stopped while asleep left the backlight off: put it back."""
        try:
            with open(self.save_file) as f:
                rows = [line.split() for line in f if line.strip()]
        except OSError:
            return
        for row in reversed(rows):
            if len(row) == 2:
                self._write(row[0], row[1])
        try:
            os.remove(self.save_file)
        except OSError:
            pass
        print("Screen backlight turned back on (left off by the last run)")


def empty_metrics():
    return {"ball_speed": None, "club_speed": None, "smash": None, "carry": None,
            "carry_estimated": True, "launch_angle": None, "launch_dir": None,
            "spin": None, "club_path": None}


AREA_FILE = "search_area.txt"   # where the hitting zone is remembered
# Size of the hitting zone made round a tapped ball, in wide-view pixels. With
# the ball 5 ft 2 in from the camera it always sits in about the same spot, so
# the zone is kept small (about 5 ball widths across, 4 tall): other balls on
# a range mat, or marks on the floor, stay outside it and are never looked at.
TAP_ZONE = (80, 60)


def tap_zone(view):
    """TAP_ZONE in the given view's pixels: twice as many when zoomed in, so the
    zone covers the same patch of ground either way."""
    k = 2 // view.scale
    return TAP_ZONE[0] * k, TAP_ZONE[1] * k


def zone_around(x, y, size=TAP_ZONE):
    """A hitting zone of the given size centred on (x, y), kept inside the picture."""
    w, h = min(size[0], WIDTH), min(size[1], HEIGHT)
    x0 = int(min(max(x - w / 2, 0), WIDTH - w))
    y0 = int(min(max(y - h / 2, 0), HEIGHT - h))
    return x0, y0, x0 + w, y0 + h


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
        self.ops = None         # the radar bridges, so the Club button can update them
        self.bridge = None
        self.args = None
        self.reset_track = False
        self.history = []       # flights of the last shots, for the range view
        self.viewers = 0        # browsers watching the live camera stream
        self.radar_jobs = []    # threads still working out the last shot's numbers
        self.hint = None        # (x, y) of a tap on the live view, for the main loop
        self.view = View()      # which part of the sensor the picture shows (wide / zoomed)
        self.can_zoom = False   # full sensor mode running: zooming is possible
        self.want_view = None   # a view change asked for, applied by the main loop
        self.train_request = False
        self.training = None    # (ball, empty) training examples saved
        self.focus = None       # {"value", "best", "where"} while the Camera view is open
        self.sleep_request = False    # Sleep pressed: sleep at the next moment no shot is in hand
        self.wake_request = False     # the dark screen was tapped
        self.last_active = time.monotonic()   # last ball, shot or tap (for the automatic sleep)
        self.backlight = Backlight()

    def touch(self):
        """Something happened on the screen: put off the automatic sleep."""
        self.last_active = time.monotonic()

    def ask_sleep(self):
        """The Sleep button. The main loop sleeps once no shot is being handled."""
        if self.state in ("SLEEPING", "WAKING"):
            return
        self.wake_request = False
        self.sleep_request = True

    def ask_wake(self):
        """A tap on the dark screen (or on "Going to sleep", to stay awake)."""
        self.sleep_request = False
        self.touch()
        if self.state == "SLEEPING":
            self.wake_request = True
            self.backlight.on()      # light up at once; the sensors take a few seconds

    def test_shot(self, speed=None, launch=None):
        """A pretend shot, for trying the screens without hitting a ball."""
        import random
        club = getattr(self.args, "club", "52") if self.args else "52"
        speed = float(speed) if speed else random.uniform(55, 75)
        f = shot_flight(speed, club, launch_angle=float(launch) if launch else None,
                        direction=random.uniform(-4, 4))
        f["test"] = True
        with self.lock:
            self.shot += 1
            m = empty_metrics()
            m.update(ball_speed=round(speed, 1), carry=round(f["carry"]),
                     carry_estimated=True, flight=f, test=True)
            self.metrics = m
            self.history = (self.history + [dict(f, shot=self.shot, at=time.strftime("%H:%M:%S"))])[-30:]
            self.rev += 1
        print(f"Test shot {self.shot}: {speed:.1f} mph, carry {f['carry']:.0f} yd")

    def aim(self, fx, fy):
        """A tap on the live view (0-1 of the picture's width and height): "the
        ball is here". The ball found right there is taken at once. A tap
        inside the hitting zone leaves the zone as it is; with no zone yet, or
        a tap outside it, a zone is made round the tapped ball."""
        if self.args is None:
            return
        x, y = int(fx * WIDTH), int(fy * HEIGHT)
        area = [int(float(v)) for v in self.args.search_area.split(",")] \
            if self.args.search_area else None
        if not area or not (area[0] <= x <= area[2] and area[1] <= y <= area[3]):
            self._use_area(zone_around(x, y, tap_zone(self.view)), "made round the tapped ball")
        self.hint = (x, y)
        self.reset_track = True
        print(f"Tapped at ({x}, {y}): looking for the ball there")

    def set_zone(self, fx0, fy0, fx1, fy1):
        """Look for the ball anywhere inside a box dragged over the hitting area
        (0-1 of the picture's width and height). Remembered for the next start."""
        if self.args is None:
            return
        x0, x1 = sorted((int(fx0 * WIDTH), int(fx1 * WIDTH)))
        y0, y1 = sorted((int(fy0 * HEIGHT), int(fy1 * HEIGHT)))
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, WIDTH), min(y1, HEIGHT)
        if x1 - x0 < 40 or y1 - y0 < 24:
            print(f"Hitting zone too small ({x1 - x0}x{y1 - y0} px); ignored")
            return
        self._use_area((x0, y0, x1, y1), "drawn", kind="drawn")
        if self.can_zoom and not self.view.zoomed and self.args.zoom != "off":
            self.zoom_to_zone()

    def zoom_to_zone(self):
        """Ask for a zoomed view on the hitting zone, if it fits in one."""
        a = [int(float(v)) for v in self.args.search_area.split(",")] if self.args.search_area else None
        if a is None:          # no zone: zoom on the middle of the picture
            self.want_view = zoom_on(self.view.to_sensor(WIDTH / 2, HEIGHT / 2))
        elif fits_zoomed(a, self.view):
            self.want_view = zoom_on(self.view.to_sensor((a[0] + a[2]) / 2, (a[1] + a[3]) / 2))
        else:
            print("Hitting zone is too big to zoom in on (it must be under about half the "
                  "picture's width and height); staying wide")

    def set_club(self, club):
        """The Club button: change the club without leaving the kiosk. Used for
        the next shot's typical launch and spin, and passed to both radars."""
        if self.args is None or club not in CLUBS or club == self.args.club:
            return
        with self.lock:
            self.args.club = club
            self.rev += 1
        told = []
        for name, part in (("speed radar", self.ops), ("TI radar", self.bridge)):
            if part is not None and hasattr(part, "set_club"):
                try:
                    part.set_club(club)
                    told.append(name)
                except Exception as e:
                    print(f"Could not give the {name} the new club ({e})")
        print(f"[{time.strftime('%H:%M:%S')}] Club: {CLUB_LABEL.get(club, club)}"
              + (f" (also set on the {' and '.join(told)})" if told else ""))
        # Remembered for next time, so the start menu doesn't need to ask.
        try:
            with open(MENU_SETTINGS) as f:
                saved = json.load(f)
        except (OSError, ValueError):
            saved = {}
        saved["club"] = club
        try:
            os.makedirs(os.path.dirname(MENU_SETTINGS), exist_ok=True)
            with open(MENU_SETTINGS, "w") as f:
                json.dump(saved, f)
        except OSError:
            pass

    def set_zoom(self, on):
        """The Zoom in / Wide view button."""
        if self.args is None or not self.can_zoom:
            return
        if on and not self.view.zoomed:
            self.zoom_to_zone()
        elif not on and self.view.zoomed:
            self.want_view = View()

    def _use_area(self, area, how, kind="tap"):
        self.args.search_area = ",".join(str(int(v)) for v in area)
        self.zone_kind = kind
        self.reset_track = True
        self.save_zone()
        print(f"Hitting zone ({how}): {self.args.search_area}")

    def save_zone(self):
        """Remember the hitting zone, how it was made, and which view it is in."""
        if not self.args.search_area:
            return
        kind = getattr(self, "zone_kind", "tap")
        try:
            os.makedirs(self.args.out, exist_ok=True)
            with open(os.path.join(self.args.out, AREA_FILE), "w") as f:
                f.write(self.args.search_area + "\n" + kind + "\n" + self.view.tag + "\n")
        except OSError as e:
            print(f"Could not save the hitting zone: {e}")

    def decide(self, action):
        """Save or delete the latest shot's video."""
        with self.lock:
            if action == "keep" and self.video == "pending":
                self.video = "kept"
                try:                    # never pruned by --keep-shots
                    open(os.path.join(self.folder, KEEP_MARKER), "w").close()
                except (OSError, TypeError):
                    pass
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
                                   "metrics": K.metrics, "video": K.video,
                                   "camera": getattr(K, "camera", None),
                                   "zone": bool(K.args is not None and K.args.search_area),
                                   "view": {"zoomed": K.view.zoomed, "can_zoom": K.can_zoom},
                                   "focus": K.focus, "training": K.training,
                                   "club": K.args.club if K.args is not None else None}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            elif path == "/stream.mjpg":
                self._mjpeg_headers()
                K.viewers += 1              # the live picture is only drawn while watched
                try:
                    while not K.quit:
                        jpeg = STREAM.get()
                        if jpeg is not None:
                            self._send_jpeg(jpeg)
                finally:
                    K.viewers -= 1
            elif path in ("/range", "/range.html"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(RANGE_PAGE_SLEEP)
            elif path == "/ping":
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"kiosk")
            elif path == "/session.csv":
                p = getattr(K, "session_path", None)
                body = open(p, "rb").read() if p and os.path.exists(p) else \
                    (",".join(SESSION_COLUMNS) + "\n").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/csv")
                self.send_header("Content-Disposition",
                                 f'attachment; filename="{os.path.basename(p or "session.csv")}"')
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            elif path == "/history":
                with K.lock:
                    body = json.dumps({"rev": K.rev, "shots": K.history}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
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
        if action == "sleep":
            K.ask_sleep()
        elif action == "wake":
            K.ask_wake()
        elif action != "quit":
            K.touch()            # the screen is being used: not idle
        if action == "testshot":
            q = dict(p.split("=", 1) for p in self.path.split("?", 1)[-1].split("&") if "=" in p)
            K.test_shot(q.get("speed"), q.get("launch"))
        if action == "aim":
            q = dict(p.split("=", 1) for p in self.path.split("?", 1)[-1].split("&") if "=" in p)
            try:
                K.aim(float(q["x"]), float(q["y"]))
            except (KeyError, ValueError):
                pass
        if action == "zone":
            q = dict(p.split("=", 1) for p in self.path.split("?", 1)[-1].split("&") if "=" in p)
            try:
                K.set_zone(float(q["x0"]), float(q["y0"]), float(q["x1"]), float(q["y1"]))
            except (KeyError, ValueError):
                pass
        if action == "view":
            q = dict(p.split("=", 1) for p in self.path.split("?", 1)[-1].split("&") if "=" in p)
            K.set_zoom(q.get("zoom") == "1")
        if action == "club":
            q = dict(p.split("=", 1) for p in self.path.split("?", 1)[-1].split("&") if "=" in p)
            K.set_club(q.get("c", ""))
        if action == "train_frame":
            K.train_request = True
        if action == "quit":
            K.quit = True
            # Make sure the program really ends (camera or radar threads can
            # hang on shutdown), so the start menu can come back.
            t = threading.Timer(10.0, lambda: os._exit(0))
            t.daemon = True
            t.start()
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


SESSION_COLUMNS = ["shot", "time", "club", "ball_speed_mph", "club_speed_mph", "smash",
                   "launch_deg", "launch_measured", "spin_rpm_used", "carry_yd", "apex_yd",
                   "ti_radar", "ball_speed_raw_mph", "launch_dir_deg"]


def _session_path():
    """This run's shot log, one CSV per kiosk start, in logs/sessions/."""
    if getattr(K, "session_path", None) is None:
        os.makedirs(os.path.join("logs", "sessions"), exist_ok=True)
        K.session_path = os.path.join("logs", "sessions",
                                      time.strftime("session_%Y%m%d_%H%M%S.csv"))
    return K.session_path


def _log_session(shot, m, f, r):
    """Add one shot to the session CSV, to compare against another launch monitor."""
    try:
        path = _session_path()
        new = not os.path.exists(path)
        row = [shot, time.strftime("%H:%M:%S"), f.get("club"), m.get("ball_speed"),
               m.get("club_speed"), m.get("smash"), f.get("launch"),
               "no" if "launch" in f.get("assumed", []) else "yes", f.get("spin"),
               f.get("carry"), f.get("apex"),
               (r or {}).get("error") or (r or {}).get("quality") or "",
               m.get("ball_speed_raw"), m.get("launch_dir")]
        with open(path, "a") as out:
            if new:
                out.write(",".join(SESSION_COLUMNS) + "\n")
            out.write(",".join("" if v is None else str(v) for v in row) + "\n")
    except OSError as e:
        print(f"Could not write the session log: {e}")


def _publish(shot, o, r, final):
    """Show the radar numbers for this shot. Returns the metrics, or None if a
    newer shot has replaced it."""
    with K.lock:
        if K.shot != shot:
            return None
        m = dict(K.metrics)
        m["radar_pending"] = not final
        club = getattr(K.args, "club", "52") if K.args else "52"
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
            if r.get("launch_dir") is not None:
                m["launch_dir"] = round(r["launch_dir"], 1)
            if m.get("ball_speed") is None and r["ball_speed"] is not None:
                m["ball_speed"] = round(r["ball_speed"], 1)
        fix = getattr(K, "correct_speed", None)
        if fix is not None and o and o.get("ball_speed"):
            # The OPS reads the ball's speed along its line of sight, which is
            # low for a ball climbing away at the launch angle. Correct it with
            # the TI's angle, or the club's typical launch until that arrives
            # (as OpenFlight does). Always from the raw reading, so the second
            # pass with the TI angle replaces the first.
            raw = float(o["ball_speed"])
            launch = m.get("launch_angle")
            if launch is None:
                launch = club_defaults(club)[0]
            try:
                m["ball_speed"] = round(fix(raw, launch), 1)
                m["ball_speed_raw"] = round(raw, 1)
            except Exception as e:
                print(f"Shot {shot}: ball-speed correction failed ({type(e).__name__}: {e})")
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
        if m.get("ball_speed"):
            # Fly the ball: measured ball speed, plus the TI radar's launch angle
            # when there is one (otherwise the club's typical launch). Spin uses
            # the club's typical value: the speed radar's spin is experimental.
            f = shot_flight(m["ball_speed"], club, launch_angle=m.get("launch_angle"))
            m["carry"] = round(f["carry"])
            m["carry_estimated"] = "launch" in f["assumed"]
            m["flight"] = f
            if final and not any(h.get("shot") == shot for h in K.history):
                K.history = (K.history + [dict(f, shot=shot, at=time.strftime("%H:%M:%S"))])[-30:]
                _log_session(shot, m, f, r)
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
            "launch_angle": None, "launch_dir": None, "ball_speed": None, "quality": None,
            "error": "no speed-radar shot to guide the TI radar"}
        m = _publish(shot, o, r, final=True)
        if m is None:
            return
    save_metrics(folder if K.folder == folder else None, m, radar_log)
    if getattr(K, "sim", None) is not None and o:
        K.sim.send(o.get("shot"), r.get("launch_angle") if r else None,
                   ball_speed=m.get("ball_speed"), launch_dir=m.get("launch_dir"))

    if ops is not None and not o:
        print(f"Shot {shot}: speed radar gave no reading (no ball seen flying away from it)")
    if r and r["error"]:
        print(f"Shot {shot}: TI radar gave no angle ({r['error']})")
    shown = {x: m[x] for x in ("ball_speed", "ball_speed_raw", "club_speed", "smash",
                               "launch_angle", "launch_dir", "spin", "carry")
             if m.get(x) is not None}
    print(f"Shot {shot}: {shown if shown else 'no radar numbers'}")

def _write_flight(pending, folder, args):
    """Save a shot's ball-flight frames (no video) at low priority, then prune
    old shot folders."""
    try:
        os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 10)   # this thread only
    except (AttributeError, OSError):
        pass
    try:
        save_shot(pending, args.out, video=False, folder=folder)
        prune_shots(args.out, args.keep_shots)
    except Exception as e:
        print(f"Could not save the shot frames: {type(e).__name__}: {e}")


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
    p.add_argument("--checks-per-second", type=float, default=8.0,
                   help="ball checks a second while a ball is being confirmed")
    p.add_argument("--search-checks-per-second", type=float, default=4.0,
                   help="ball checks a second while no ball is in view (saves power)")
    p.add_argument("--ready-checks-per-second", type=float, default=2.0,
                   help="ball checks a second while READY; the motion trigger watches every frame anyway")
    p.add_argument("--still-pixels", type=float, default=12.0)
    p.add_argument("--still-seconds", type=float, default=1.0)
    p.add_argument("--hold-seconds", type=float, default=5.0,
                   help="how long to stay Ready when the ball is covered (club, feet, body over it)")
    p.add_argument("--rearm-pause", type=float, default=2.0,
                   help="after Ready is lost, stay Looking for Ball at least this long before arming again")
    p.add_argument("--recording", default="flight", choices=("flight", "full", "off"),
                   help="flight: keep just the ball leaving (0.03 s before to 0.15 s after impact), "
                        "saved quietly, no preview video (default, least power); full: 0.25 s + 0.5 s "
                        "with the slow-motion Shot Preview; off: save nothing")
    p.add_argument("--pre", type=float, default=None,
                   help="seconds kept from before the trigger (default: by --recording)")
    p.add_argument("--post", type=float, default=None,
                   help="seconds recorded after the trigger (default: by --recording)")
    p.add_argument("--keep-shots", type=int, default=30,
                   help="keep only the newest this many shot folders (Saved ones are never deleted; 0 = all)")
    p.add_argument("--idle-fps", type=float, default=60.0,
                   help="camera frame rate while no ball is READY (full --fps once READY); 0 = always full")
    p.add_argument("--verify-seconds", type=float, default=1.5,
                   help="after a camera trigger, watch the ball's spot this long: if the ball shows up "
                        "again (a club tapped down behind it) it was no shot. 0 = off")
    p.add_argument("--settle-seconds", type=float, default=8.0,
                   help="after a shot, pause ball finding while the radars work out the numbers, "
                        "up to this long (spreads out the power draw)")
    p.add_argument("--trigger", default="motion", help="motion, sound, or both: motion,sound")
    p.add_argument("--motion-threshold", type=float, default=25.0)
    p.add_argument("--bit-depth", type=int, default=8, choices=(8, 10),
                   help="sensor bit depth; 8 allows the fastest frame rates")
    p.add_argument("--exposure", type=int, default=0,
                   help="fix the exposure in microseconds (0 = automatic, see --exposure-mode)")
    p.add_argument("--gain", type=float, default=0.0, help="analogue gain with --exposure")
    p.add_argument("--out", default="shots", help="folder to save shots into")
    p.add_argument("--port", type=int, default=8000)
    add_blob_args(p)
    add_tracking_args(p)
    add_exposure_args(p)
    p.add_argument("--no-ball", action="store_true",
                   help="swing test: skip ball detection and record when a fast swing passes")
    p.add_argument("--swing-fraction", type=float, default=0.015,
                   help="share of the picture that must change in one frame to count as a swing")
    p.add_argument("--radar-port", default="/dev/ttyAMA0",
                   help="OPS243-A serial port (/dev/ttyAMA0 = Pi UART on the J3 header, /dev/ttyACM0 = USB)")
    p.add_argument("--ops-speed-mode", action="store_true",
                   help="read plain speed readings from the OPS243-A. Only for a radar NOT set up in "
                        "rolling-buffer mode; this sends it setup commands")
    p.add_argument("--ops", action="store_true",
                   help="use the OPS243-A in rolling-buffer mode through OpenFlight's code "
                        "(ball speed, club speed, spin)")
    p.add_argument("--trigger-out-gpio", type=int, default=0,
                   help="camera as the shot trigger: pulse this GPIO the moment the camera triggers. "
                        "Wire it to OPS J3-3 and to --gate-gpio (in place of the sound detector's GATE). 0 = off")
    p.add_argument("--ops-trigger", choices=("sound", "speed"), default="sound",
                   help="what starts a shot capture: sound = SEN-14262 GATE on OPS J3-3 and GPIO17; "
                        "speed = the OPS243-A's own speed trigger (no sound detector; ball must be 35+ mph)")
    p.add_argument("--ops-trigger-mph", type=float, default=60.0,
                   help="speed trigger: outbound speed that counts as a shot, mph (OpenFlight's default is 20)")
    p.add_argument("--ops-ksps", type=int, default=30, help="OPS243-A sample rate, thousands per second")
    p.add_argument("--ops-pre-trigger", type=int, default=None,
                   help="speed radar (sound trigger): how many of its 32 buffer blocks (~4.3 ms each) come "
                        "from before the trigger. With the camera as the trigger it fires ~4 frames after "
                        "the ball leaves, so the club coming in needs more history than OpenFlight's "
                        "default (made for a sound trigger at impact). Empty = OpenFlight's default")
    p.add_argument("--ops-power", type=int, default=None, choices=range(0, 8),
                   help="OPS243-A transmit power, 0 = strongest (OpenFlight uses 3)")
    p.add_argument("--iwr", action="store_true",
                   help="use the TI radar through OpenFlight's code for launch angle")
    p.add_argument("--openflight", default="~/openflight", help="where OpenFlight is installed")
    p.add_argument("--iwr-port", default="/dev/ttyUSB0")
    p.add_argument("--iwr-config", default="config/iwr6843_l3dump_wide_24f3ms_53bin_iq16.cfg")
    p.add_argument("--iwr-cal", default="config/iwr6843_calibration_reference.json",
                   help="TI radar calibration file (inside the OpenFlight folder)")
    # TI geometry. start_kiosk.sh passes the measured values; these defaults
    # match it so a hand-started kiosk uses the same numbers.
    p.add_argument("--iwr-tee-m", type=float, default=1.575,
                   help="slant distance, TI antenna centre to ball centre, m")
    p.add_argument("--iwr-net-m", type=float, default=4.6,
                   help="TI antenna centre to the net, m")
    p.add_argument("--iwr-tilt-deg", type=float, default=10.0,
                   help="TI antenna face tilt: degrees it leans back from vertical (boresight up)")
    p.add_argument("--iwr-radar-height-m", type=float, default=0.076,
                   help="TI antenna centre height above the ground under the ball, m")
    p.add_argument("--iwr-ball-height-m", type=float, default=0.021,
                   help="ball centre height above the same ground, m (0.021 = ball on the ground)")
    p.add_argument("--iwr-azimuth-offset-deg", type=float, default=0.0,
                   help="degrees the radars point right of the target line (left = negative)")
    p.add_argument("--no-speed-correction", action="store_true",
                   help="show the speed radar's raw ball speed (no launch-angle cosine correction)")
    p.add_argument("--iwr-save-dumps", action="store_true", help="also save the raw TI radar captures")
    p.add_argument("--gate-gpio", type=int, default=17,
                   help="GPIO number the sound sensor's GATE is wired to (17 = pin 11, 26 = pin 37)")
    p.add_argument("--club", default="52",
                   help="club being hit, for typical launch and spin: driver, 7i, pw, 52, sw ...")
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
    p.add_argument("--sleep-minutes", type=float, default=0.0,
                   help="go to sleep by itself after this many minutes of Looking for Ball with no ball, "
                        "no shot and no taps on the screen (camera and TI radar off, screen dark; tap "
                        "to wake). 0 = only with the Sleep button")
    p.add_argument("--sleep-screen", choices=("off", "black"), default="off",
                   help="while asleep: off = backlight off (saves the most); black = backlight left on "
                        "with the screen black (if the touchscreen doesn't respond with its backlight off)")
    args = p.parse_args()
    args.triggers = {t.strip() for t in args.trigger.split(",") if t.strip()}
    if args.pre is None:
        args.pre = 0.25 if args.recording == "full" else 0.03
    if args.post is None:
        args.post = 0.5 if args.recording == "full" else 0.15
    args.swing_test = args.no_ball
    if args.swing_test:
        args.triggers.discard("motion")  # there is no ball patch to watch
    # The hitting zone set last time wins over --search-area. A saved zone
    # made from a tap is resized to TAP_ZONE round its centre (older ones were
    # either just round one ball or much bigger). A box dragged by hand is
    # kept exactly as drawn.
    saved_view = View()            # the view the saved zone was drawn in
    try:
        with open(os.path.join(args.out, AREA_FILE)) as f:
            lines = f.read().split()
        if lines:
            a = [int(float(v)) for v in lines[0].split(",")]
            kind = lines[1] if len(lines) > 1 else "tap"
            saved_view = View.from_tag(lines[2] if len(lines) > 2 else "wide")
            size = tap_zone(saved_view)
            if kind != "drawn" and (a[2] - a[0], a[3] - a[1]) != size:
                a = zone_around((a[0] + a[2]) / 2, (a[1] + a[3]) / 2, size)
                print(f"Resized the saved tap zone to {size[0]}x{size[1]} px")
            args.search_area = ",".join(str(int(v)) for v in a)
            K.zone_kind = kind
            print(f"Using the hitting zone set last time: {args.search_area} ({saved_view.tag})")
    except (OSError, ValueError, IndexError):
        pass
    K.args = args
    K.backlight.restore_leftover()

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

    # Exposure is picked by measuring the area around the ball (see
    # ExposureControl in shot_capture.py); --exposure fixes it by hand.
    # With --sensor full the picture can zoom in 2x on the hitting zone (the
    # ball twice as wide). Start in the view the zone was saved in, or zoom on
    # it now (--zoom auto/on); the zone is converted to whichever view is used.
    view = View()
    if args.sensor == "full" and args.zoom != "off":
        if saved_view.zoomed:
            view = saved_view
        elif args.search_area:
            a = [int(float(v)) for v in args.search_area.split(",")]
            if fits_zoomed(a, saved_view) or args.zoom == "on":
                view = zoom_on(saved_view.to_sensor((a[0] + a[2]) / 2, (a[1] + a[3]) / 2))
        elif args.zoom == "on":
            view = zoom_on((640, 400))
    cam, ae = start_camera(args, view)
    K.camera = None
    K.can_zoom = bool(args.full_sensor)
    K.view = view if args.full_sensor else View()
    if args.search_area and K.view != saved_view:
        a = convert_area([int(float(v)) for v in args.search_area.split(",")], saved_view, K.view)
        args.search_area = ",".join(str(v) for v in a) if a else None
        if a:
            print(f"Hitting zone in this view ({K.view.tag}): {args.search_area}")
            K.save_zone()
        else:
            print("The saved hitting zone is outside this view: drag a new one")
    K.training = count_training(args.out)

    sh = Shared(maxlen=int(args.fps * (args.pre + args.post) * 1.3) + 20)
    cam_thread = threading.Thread(target=camera_thread, args=(cam, sh, args), daemon=True)
    cam_thread.start()

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
    def start_ti():
        """The TI radar (launch angle), through OpenFlight. Also used on waking up."""
        try:
            from iwr_bridge import IWRBridge
            # OpenFlight's monitor owns the sound trigger pin; each sound trigger is passed on to
            # the camera so it can capture the shot too.
            return IWRBridge(args, on_trigger=lambda: sh.trigger("sound"), ops=ops)
        except Exception as e:
            print(f"TI radar not available ({type(e).__name__}: {e}); continuing without it")
            return None

    def stop_ti(b):
        """Stop the TI radar (going to sleep): unhook it from the speed radar, then
        stop its firmware and free its port and trigger pin."""
        if ops is not None:
            for hooks, fn in ((getattr(ops, "listeners", None), getattr(b, "_on_ops_shot", None)),
                              (getattr(ops, "trigger_listeners", None), getattr(b, "_software_trigger", None))):
                if hooks is not None and fn is not None:
                    while fn in hooks:
                        hooks.remove(fn)
        b.stop()

    bridge = start_ti() if args.iwr else None
    K.ops, K.bridge = ops, bridge       # so the Club button can update both radars
    # Ball-speed cosine correction: on whenever the TI radar is running, as in
    # OpenFlight. The raw reading is kept in the session log.
    K.correct_speed = None
    if bridge is not None and ops is not None and not args.no_speed_correction:
        from iwr_bridge import ops_speed_corrector
        K.correct_speed = ops_speed_corrector(args)
        if K.correct_speed is not None:
            print("Ball speed: corrected for launch angle (raw OPS reading kept in the log)")
    if args.trigger_out_gpio:
        # The camera replaces the sound detector: when it sees the ball leave
        # (motion trigger) it sends the same 3.3 V pulse the detector's GATE did,
        # into OPS J3-3 (HOST_INT) and GPIO17, so both radars capture exactly as
        # with the sound trigger. Made after the radars, which pick the Pi 5 pin
        # factory first.
        try:
            try:
                from openflight.gpio_factory import ensure_lgpio_pin_factory
                ensure_lgpio_pin_factory()
            except Exception:
                pass
            from gpiozero import DigitalOutputDevice    # (plain OutputDevice has no blink())
            trig_out = DigitalOutputDevice(args.trigger_out_gpio, active_high=True, initial_value=False)

            def fire(source):
                if source != "sound":        # "sound" = our own pulse coming back on --gate-gpio
                    print(f"[{time.strftime('%H:%M:%S')}] Camera trigger ({source}): "
                          f"pulse on GPIO{args.trigger_out_gpio} to both radars")
                    trig_out.blink(on_time=0.05, off_time=0.05, n=1, background=True)
            sh.on_fire = fire
            print(f"Camera is the shot trigger: pulses GPIO{args.trigger_out_gpio} "
                  f"(wired to OPS J3-3 and GPIO{args.gate_gpio})")
        except Exception as e:
            print(f"Trigger output not available ({type(e).__name__}: {e}); radars get no trigger")
    if "sound" in args.triggers and bridge is None:
        try:
            from gpiozero import DigitalInputDevice
            gate = DigitalInputDevice(args.gate_gpio, pull_up=False)
            gate.when_activated = lambda: sh.trigger("sound")
            print(f"Sound trigger on GPIO{args.gate_gpio}")
        except Exception as e:
            print(f"Sound trigger not available ({e}); continuing without it")

    ball, trk, drawn = None, new_track(), None
    # Notices a ball being set down in the hitting zone (see ZoneWatch).
    zone = None if args.swing_test else ZoneWatch(args)
    rearm_at = time.monotonic() + 2.0
    settle_until = 0.0          # after a shot: let the radars work before looking again
    # Lower frame rate while no ball is READY (only with a fixed/ladder exposure:
    # libcamera's auto exposure would change brightness with the frame rate).
    idle_fps = args.idle_fps if (0 < args.idle_fps < args.fps and not args.swing_test
                                 and (ae is not None or args.exposure > 0)) else 0
    fps_now = args.fps
    rates = {"SEARCHING": args.search_checks_per_second, "BALL": args.checks_per_second,
             "READY": args.ready_checks_per_second, "MEASURING": 4.0, "CHECKING": 20.0}
    verify = None               # a camera trigger being checked: is the ball really gone?
    K.state = "SEARCHING"
    view_settle_until = 0.0     # frames from before a zoom change are still arriving
    focus_best, focus_where = None, None

    # Sleep: camera and TI radar off, screen dark, until the screen is tapped.
    # The speed radar is left running in its rolling-buffer mode (OpenFlight:
    # changing its mode at runtime can break its trigger until it is power-cycled).
    sleep_after = args.sleep_minutes * 60.0
    asleep_since = 0.0

    def camera_controls_now():
        """Everything the camera was running with, to start it again with on waking."""
        us = int(1_000_000 / fps_now)
        c = {"FrameDurationLimits": (us, us)}
        if ae is not None:
            c.update(ae.controls())
        elif args.exposure > 0:
            c["ExposureTime"] = min(args.exposure, int(1_000_000 / args.fps) - 100)
            if args.gain > 0:
                c["AnalogueGain"] = args.gain
        elif args.gain > 0:
            c["AnalogueGain"] = args.gain
        if getattr(args, "full_sensor", False):
            c["ScalerCrop"] = K.view.crop()
        return c

    def fall_asleep(reason):
        nonlocal bridge, asleep_since, ball, drawn
        K.sleep_request = False
        K.wake_request = False
        K.state = "SLEEPING"
        asleep_since = time.monotonic()
        dark = K.backlight.off() if args.sleep_screen == "off" else False
        with sh.lock:                             # forget the ball; nothing is armed
            sh.armed = False
            sh.roi = sh.roi_ref = None
        trk.update(new_track())
        ball, drawn = None, None
        sh.running = False                        # the camera thread ends after this frame
        cam_thread.join(timeout=3.0)
        camera_off = not cam_thread.is_alive()
        if camera_off:
            try:
                cam.stop()
            except Exception as e:
                print(f"Could not stop the camera ({type(e).__name__}: {e})")
        ti = "off" if bridge is not None else "not running"
        if bridge is not None:
            try:
                stop_ti(bridge)
            except Exception as e:
                print(f"TI radar stop: {type(e).__name__}: {e}")
            bridge = K.bridge = None
        print(f"[{time.strftime('%H:%M:%S')}] Asleep ({reason}): camera "
              f"{'off' if camera_off else 'still running (did not stop)'}, TI radar {ti}, screen "
              f"{'backlight off' if dark else 'black'}. Tap the screen to wake.")

    def wake_up():
        nonlocal bridge, cam_thread, zone, view_settle_until
        K.wake_request = False
        K.state = "WAKING"
        K.backlight.on()
        K.touch()
        print(f"[{time.strftime('%H:%M:%S')}] Waking up after "
              f"{(time.monotonic() - asleep_since) / 60:.1f} min asleep")
        t0 = time.monotonic()
        sh.frames.clear()
        sh.latest = None                          # no old picture is looked at again
        if cam_thread.is_alive():
            sh.running = True                     # it never stopped
        else:
            try:
                cam.set_controls(camera_controls_now())   # applied as it starts
                cam.start()
            except Exception as e:
                print(f"Camera did not start again ({type(e).__name__}: {e})")
            sh.running = True
            cam_thread = threading.Thread(target=camera_thread, args=(cam, sh, args), daemon=True)
            cam_thread.start()
        if args.iwr and bridge is None:
            bridge = K.bridge = start_ti()        # set up again exactly as at start-up
        if zone is not None:
            # As at start-up: a fresh picture of the empty zone (the box may
            # have been carried somewhere else), taken once things are still.
            zone = ZoneWatch(args)
        view_settle_until = time.monotonic() + 0.5
        K.reset_track = True
        K.touch()
        K.state = "SEARCHING"
        print(f"[{time.strftime('%H:%M:%S')}] Awake in {time.monotonic() - t0:.1f} s: camera on, "
              f"TI radar {'on' if bridge is not None else 'off'}")

    if sleep_after > 0:
        print(f"Sleep: by itself after {args.sleep_minutes:g} min with no ball, no shot and no taps "
              f"(or with the Sleep button)")
    K.touch()                   # the idle time counts from now, not from loading the model
    try:
        while not K.quit:
            loop_start = time.monotonic()
            if K.state == "SLEEPING":
                if K.wake_request:
                    wake_up()
                else:
                    time.sleep(0.1)
                continue
            if K.state != "SEARCHING" or K.viewers > 0:
                K.last_active = loop_start        # a ball, a shot, or the Camera view open
            if K.sleep_request or (sleep_after > 0 and K.state == "SEARCHING"
                                   and loop_start - K.last_active >= sleep_after):
                # Never in the middle of a shot: wait until it is saved and measured.
                if sh.trigger_time is None and sh.pending is None and verify is None \
                        and not any(j.is_alive() for j in K.radar_jobs):
                    fall_asleep("Sleep button" if K.sleep_request else
                                f"nothing for {args.sleep_minutes:g} min")
                    continue
            want, K.want_view = K.want_view, None
            if want is not None and want != K.view and K.can_zoom \
                    and sh.trigger_time is None and sh.pending is None:
                # Zoom in on the hitting zone, or back out to the wide view.
                try:
                    set_view(cam, want)
                except Exception as e:
                    print(f"Could not change the view ({e}); staying {K.view.tag}")
                else:
                    old, K.view = K.view, want
                    if args.search_area:
                        a = convert_area([int(float(v)) for v in args.search_area.split(",")], old, want)
                        args.search_area = ",".join(str(v) for v in a) if a else None
                        K.save_zone()
                    print(f"View: {want.tag}" + (f", hitting zone {args.search_area}"
                                                 if args.search_area else ", no hitting zone in view"))
                    K.reset_track = True
                    K.hint = None
                    if zone is not None:
                        zone.ball_d = None            # the ball is a different size now
                    view_settle_until = time.monotonic() + 0.4
                    focus_best = None
            if K.reset_track:             # the zone was drawn, or a ball tapped
                K.reset_track = False
                trk.update(new_track())
                hint, K.hint = K.hint, None
                trk["hint"] = (hint[0], hint[1], 6) if hint else None
                sh.armed = False
                sh.roi = sh.roi_ref = None
                if ae is not None:
                    ae.next_check = max(view_settle_until, time.monotonic())  # re-meter on the (new) zone

            # A trigger fired. The radars were pulsed at once (their recordings
            # are short), but whether it was a shot is decided here: a club
            # tapped down behind the ball covers its spot exactly like a shot
            # does. If the ball's spot looks like the ball again within
            # --verify-seconds, it was no shot: back to Ready with nothing
            # counted. The radar numbers take longer than this to arrive anyway,
            # so a real shot loses nothing by the wait.
            if sh.pending is not None and verify is None and args.verify_seconds > 0 \
                    and not args.swing_test and sh.roi is not None and sh.ball_ref is not None:
                verify = {"until": time.monotonic() + args.verify_seconds, "back": 0, "peak": 0.0}
            if verify is not None:
                d = _ball_diff(sh, sh.latest)      # against the ball as it looked when armed
                if d is not None:
                    verify["peak"] = max(verify["peak"], d)
                verify["back"] = verify["back"] + 1 if (d is not None and d <= args.motion_threshold * 0.5) else 0
                if verify["back"] >= 3:               # ball seen in its spot on 3 checks in a row
                    print(f"[{time.strftime('%H:%M:%S')}] No shot: the ball is still there "
                          f"(its spot changed by up to {verify['peak']:.1f}, now {d:.1f}); back to Ready")
                    with sh.lock:
                        sh.pending = None
                        sh.roi_ref = sh.ball_ref.copy()   # motion trigger back on the ball's own picture
                        sh.armed = True               # same ball
                    verify = None
                    K.state = "READY"
                    continue
                if time.monotonic() < verify["until"]:
                    K.state = "CHECKING"
                    time.sleep(1.0 / rates["CHECKING"])
                    continue
                verify = None                         # the ball didn't come back: a shot

            # A shot was captured: save it, work out the numbers, and carry on.
            if sh.pending is not None:
                K.state = "CAPTURING"
                K.drop_undecided()           # the previous video defaults to deleted
                trigger_time, _, window = sh.pending
                folder, replay = None, []
                if args.recording == "full":
                    # Frames, a preview video and the replay: the heaviest option.
                    folder = save_shot(sh.pending, args.out)
                    replay = [cv2.imencode(".jpg", np.ascontiguousarray(f[2]),
                                           [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()
                              for f in window]
                elif args.recording == "flight" and window:
                    # Just the ball leaving, as raw frames: no video, no JPEGs,
                    # written by a background thread so nothing else waits.
                    folder = shot_folder(args.out)
                    threading.Thread(target=_write_flight, args=(sh.pending, folder, args),
                                     daemon=True).start()
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
                    K.video = "pending" if (folder and replay) else "none"
                    K.shot += 1
                    K.rev += 1
                if bridge is not None or ops is not None:
                    job = threading.Thread(target=add_radar_results,
                                           args=(bridge, ops, K.shot, trigger_time, folder, radar_log),
                                           daemon=True)
                    job.start()
                    K.radar_jobs = [j for j in K.radar_jobs if j.is_alive()] + [job]
                    settle_until = time.monotonic() + args.settle_seconds
                shown = {k: v for k, v in metrics.items() if v is not None and k != "carry_estimated"}
                print(f"Shot {K.shot}: {shown if shown else 'no sensor readings'} "
                      f"(camera running at {sh.camera_fps:.0f} fps)")
                with sh.lock:
                    sh.pending = None
                    sh.roi = sh.roi_ref = None
                if zone is not None:              # retake the empty zone once the ball has gone
                    zone.shot_taken(trk.get("box"), time.monotonic())
                ball, trk = None, new_track()
                rearm_at = time.monotonic() + 2.0
                K.state = "SEARCHING"
                continue

            gray = sh.latest
            if gray is None:
                time.sleep(0.01)
                continue

            # Exposure: never changed while a shot is being recorded, nor while
            # the ball is READY (the motion trigger compares against a fixed
            # picture of it). In the swing test a change briefly disarms, so the
            # brightness step itself can't look like a swing.
            if ae is not None:
                busy = sh.trigger_time is not None or sh.pending is not None
                hold = busy or (sh.armed and not args.swing_test)
                if ae.update(gray, time.monotonic(), hold=hold) and args.swing_test:
                    sh.armed = False
                    rearm_at = time.monotonic() + 0.5
                K.camera = ae.summary(sh.exposure)

            now = time.monotonic()
            if zone is not None and sh.trigger_time is None and now >= view_settle_until:
                following = trk.get("box") is not None and trk["center"] is not None
                zone.update(gray, now, protect=trk["box"] if following else None,
                            allow_new=ae is None or ae.state in ("ok", "limit"))
            measuring = (now < settle_until and not args.swing_test
                         and any(j.is_alive() for j in K.radar_jobs))
            if sh.trigger_time is not None:
                K.state = "CAPTURING"
            elif measuring:
                # The radars are still working out the last shot (the TI radar's
                # processing is the heaviest moment for the battery). Don't run
                # the ball finder on top of it; the next ball is being set down.
                K.state = "MEASURING"
            elif now < view_settle_until:
                K.state = "SEARCHING"         # the picture is still switching views
            elif args.swing_test:
                # No ball needed: arm shortly after start-up or the last shot.
                if not sh.armed and time.monotonic() >= rearm_at:
                    sh.armed = True
                K.state = "SWINGTEST" if sh.armed else "WAIT"
            else:
                ball = detect_ball(model, gray, args, trk, zone)
                was = K.state
                K.state = update_ready(sh, args, gray, ball, trk, time.monotonic())
                ball = trk["box"] if K.state in ("BALL", "READY") else None
                if K.state == "READY" and was != "READY":
                    b = trk["box"]
                    if zone is not None:          # set-down spots must be about this size
                        zone.ball_d = ((b[2] - b[0]) + (b[3] - b[1])) / 2.0
                    # Logged so a box on the wrong spot can be traced to its finder.
                    print(f"[{time.strftime('%H:%M:%S')}] READY on {trk['box']} "
                          f"(found by {trk.get('found_by') or trk.get('source')}; now {trk.get('source')}), "
                          f"exposure {sh.exposure[0]} us x{sh.exposure[1]}")

            # Full frame rate only while READY or recording; slower otherwise.
            if idle_fps:
                want = args.fps if (sh.armed or sh.trigger_time is not None
                                    or sh.pending is not None) else idle_fps
                if want != fps_now:
                    try:
                        set_frame_rate(cam, want)
                        fps_now = want
                    except Exception as e:
                        print(f"Could not change the frame rate ({e}); staying at full speed")
                        idle_fps = 0

            if K.train_request:
                # "Save frame" on the Camera view: training pictures for the
                # ball model. With the box on a ball: that ball; with no ball
                # found: the hitting zone as "no ball here".
                K.train_request = False
                box = trk["box"] if K.state in ("BALL", "READY") and trk.get("box") else None
                if box is None and not args.search_area:
                    print("Save frame: draw a hitting zone first (or wait for the box on the ball)")
                else:
                    try:
                        n = save_training_frame(gray, args, box, args.out)
                        K.training = count_training(args.out)
                        print(f"Saved {n} training example(s) ({'ball' if box else 'no ball'}); "
                              f"{K.training[0]} ball / {K.training[1]} empty so far")
                    except OSError as e:
                        print(f"Could not save the training frame: {e}")

            if K.viewers > 0 and now >= view_settle_until:
                # Focus meter for turning the lens: sharpness round the ball
                # (or of the hitting zone while no ball is boxed).
                b = trk.get("box") if K.state in ("BALL", "READY") else None
                if b is not None:
                    d = max(b[2] - b[0], b[3] - b[1])
                    region, where = (b[0] - d, b[1] - d, b[2] + d, b[3] + d), "ball"
                elif args.search_area:
                    region, where = [int(float(v)) for v in args.search_area.split(",")], "zone"
                else:
                    region, where = (WIDTH // 4, HEIGHT // 4, 3 * WIDTH // 4, 3 * HEIGHT // 4), "middle"
                value = sharpness(gray, region)
                if where != focus_where:
                    focus_best, focus_where = None, where
                if value is not None:
                    focus_best = value if focus_best is None else max(focus_best, value)
                    K.focus = {"value": value, "best": focus_best, "where": where}
            else:
                K.focus = None

            K.latest_gray = gray
            # Live picture for the Camera view, with a box round the ball (eased
            # so it doesn't flicker; it still jumps if the ball really moves).
            # Only drawn while someone has the Camera view open.
            drawn = smooth_box(drawn, ball)
            if K.viewers <= 0:
                spare = 1.0 / rates.get(K.state, args.checks_per_second) - (time.monotonic() - loop_start)
                if spare > 0:
                    time.sleep(spare)
                continue
            view = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            if args.search_area:                          # the hitting zone, in yellow
                a = [int(float(v)) for v in args.search_area.split(",")]
                cv2.rectangle(view, (a[0], a[1]), (a[2], a[3]), (0, 210, 255), 1)
                cv2.putText(view, "hitting zone" + (" (zoomed 2x)" if K.view.zoomed else ""),
                            (a[0] + 3, a[1] + 12), cv2.FONT_HERSHEY_SIMPLEX,
                            0.4, (0, 210, 255), 1, cv2.LINE_AA)
            if zone is not None and K.state == "SEARCHING":
                for b, _ in zone.placed:                  # something just set down: being checked
                    cv2.circle(view, ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2),
                               max((b[2] - b[0]) // 2 + 4, 6), (0, 140, 255), 1)
            if trk.get("hint"):                           # where the screen was tapped
                hx, hy = trk["hint"][:2]
                cv2.drawMarker(view, (int(hx), int(hy)), (255, 0, 255), cv2.MARKER_CROSS, 14, 1)
            if drawn and K.state in ("BALL", "READY"):
                color = (0, 255, 0) if K.state == "READY" else (0, 200, 255)
                cv2.rectangle(view, (drawn[0], drawn[1]), (drawn[2], drawn[3]), color, 2)
                # Which finder placed the box: "model 0.72" or "spot finder".
                cv2.putText(view, str(trk.get("source") or ""), (drawn[0], max(drawn[1] - 5, 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)
            ok, jpeg = cv2.imencode(".jpg", view, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if ok:
                STREAM.put(jpeg.tobytes())

            spare = 1.0 / rates.get(K.state, args.checks_per_second) - (time.monotonic() - loop_start)
            if spare > 0:
                time.sleep(spare)
    except KeyboardInterrupt:
        pass
    finally:
        print("\nStopping.")
        K.drop_undecided()
        K.quit = True
        K.backlight.on()
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
