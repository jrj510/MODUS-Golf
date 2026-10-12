"""The driving-range view served by kiosk.py at /range.

Open http://<the Pi's address>:8000/range on a phone or laptop on the same
network. It shows each shot's flight from above and from the side, with the
numbers, and keeps the last shots on the range so you can see your spread.
The ball flight is calculated on the Pi (ballflight.py); this page only draws.
"""

RANGE_PAGE = b"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>MODUS Range</title>
<style>
:root{--bg:#0d1a12;--panel:#13241a;--line:#2a4a35;--text:#eef5f0;--dim:#8fa89a;
  --grass:#1d3a26;--grass2:#21422b;--tracer:#ffd23f;--old:#cfe8d6;--ready:#2ecc71;--wait:#f0b429}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--text);
  font-family:system-ui,-apple-system,sans-serif;-webkit-user-select:none;user-select:none}
body{display:flex;flex-direction:column;min-height:100vh;
  padding:max(8px,env(safe-area-inset-top)) 12px max(10px,env(safe-area-inset-bottom))}
#top{display:flex;align-items:center;gap:10px;margin-bottom:8px}
#title{font-weight:800;letter-spacing:.5px;font-size:18px}
#state{display:flex;align-items:center;gap:6px;background:var(--panel);border-radius:999px;
  padding:5px 12px;font-size:14px;font-weight:600}
#dot{width:10px;height:10px;border-radius:50%;background:var(--dim)}
#top .sp{flex:1}
#top a,#top button{color:var(--text);background:var(--panel);border:0;border-radius:10px;
  padding:7px 11px;font-size:13px;text-decoration:none;font-weight:600;white-space:nowrap}
#state{white-space:nowrap}
@media (max-width:520px){#title{display:none}#top{gap:6px}}
#stats{display:grid;grid-template-columns:1.4fr 1fr 1fr;gap:8px;margin-bottom:8px}
.st{background:var(--panel);border-radius:12px;padding:8px 10px;min-width:0}
.st .l{color:var(--dim);font-size:12px}
.st .v{font-size:24px;font-weight:800;font-variant-numeric:tabular-nums;line-height:1.15}
.st .u{color:var(--dim);font-size:12px;font-weight:600;margin-left:2px}
.st.big{grid-row:span 2;display:flex;flex-direction:column;justify-content:center}
.st.big .v{font-size:48px}
.est{color:var(--wait)}
#views{flex:1;display:flex;flex-direction:column;gap:8px;min-height:0}
canvas{width:100%;display:block;border-radius:12px;background:var(--grass)}
#top-view{flex:1;min-height:260px}
#side-view{height:120px}
#note{color:var(--dim);font-size:12px;text-align:center;margin-top:6px;min-height:15px}
@media (min-width:800px) and (orientation:landscape){
  body{height:100vh}
  #views{flex-direction:row}
  #top-view{width:auto;flex:1;min-width:0;min-height:0}
  #side-view{width:auto;flex:1.4;min-width:0;height:auto}
}
</style></head><body>
<div id="top">
  <span id="title">MODUS Range</span>
  <span id="state"><span id="dot"></span><span id="stext">Connecting</span></span>
  <span class="sp"></span>
  <button id="test">Test shot</button>
  <button id="clear">Clear</button>
  <a href="/">Back</a>
</div>
<div id="stats">
  <div class="st big"><div class="l">Carry</div><div><span class="v" id="carry">--</span><span class="u">yd</span></div></div>
  <div class="st"><div class="l">Ball Speed</div><div><span class="v" id="speed">--</span><span class="u">mph</span></div></div>
  <div class="st"><div class="l">Launch</div><div><span class="v" id="launch">--</span><span class="u">&deg;</span></div></div>
  <div class="st"><div class="l">Apex</div><div><span class="v" id="apex">--</span><span class="u">yd</span></div></div>
  <div class="st"><div class="l">Club</div><div><span class="v" id="club">--</span></div></div>
</div>
<div id="views">
  <canvas id="top-view"></canvas>
  <canvas id="side-view"></canvas>
</div>
<div id="note"></div>
<script>
const $=id=>document.getElementById(id);
const STATES={READY:['Ready','var(--ready)'],SWINGTEST:['Ready','var(--ready)'],
  SEARCHING:['Looking for ball','var(--wait)'],BALL:['Looking for ball','var(--wait)'],
  CAPTURING:['Recording','#c77dff'],WAIT:['Get set','var(--wait)'],STARTING:['Starting','var(--dim)']};
let shots=[],rev=-1,hidden=0,anim=null,lastShot=null;

function fit(c){
  const r=c.getBoundingClientRect(),d=window.devicePixelRatio||1;
  if(c.width!==Math.round(r.width*d)||c.height!==Math.round(r.height*d)){
    c.width=Math.round(r.width*d);c.height=Math.round(r.height*d);}
  const g=c.getContext('2d');g.setTransform(d,0,0,d,0,0);g.clearRect(0,0,r.width,r.height);return [g,r.width,r.height];
}
function maxDist(list){
  let m=60;for(const s of list)m=Math.max(m,s.carry*1.15,s.path[s.path.length-1][0]*1.1);
  const steps=[60,100,150,200,250,300,350];for(const s of steps)if(m<=s)return s;return 350;
}
function drawTop(list,cur,frac){
  const [g,W,H]=fit($('top-view'));const D=maxDist(list.concat(cur?[cur]:[]));
  const pad=18,y0=H-pad,sc=(H-2*pad)/D,cx=W/2;
  const X=z=>cx+z*sc,Y=x=>y0-x*sc;
  // mown stripes and yardage lines
  const step=D<=100?10:25;
  for(let d=0,i=0;d<D;d+=step,i++){g.fillStyle=i%2?'#1b3624':'#20402a';g.fillRect(0,Y(d+step),W,step*sc);}
  g.font='600 11px system-ui';g.textAlign='left';
  for(let d=step;d<=D;d+=step){
    g.strokeStyle='rgba(255,255,255,.10)';g.lineWidth=1;g.beginPath();g.moveTo(0,Y(d));g.lineTo(W,Y(d));g.stroke();
    if(d%(step*2)===0||step===25){g.fillStyle='rgba(255,255,255,.55)';g.fillText(d+' yd',6,Y(d)-3);}
  }
  g.strokeStyle='rgba(255,255,255,.25)';g.setLineDash([4,6]);g.beginPath();g.moveTo(cx,y0);g.lineTo(cx,pad);g.stroke();g.setLineDash([]);
  // tee box
  g.fillStyle='rgba(255,255,255,.18)';g.fillRect(cx-14,y0-4,28,8);
  // earlier shots: landing spots and faint paths
  for(const s of list){if(s===cur)continue;
    g.strokeStyle='rgba(207,232,214,.18)';g.lineWidth=1.5;g.beginPath();
    s.path.forEach((p,i)=>i?g.lineTo(X(p[2]),Y(p[0])):g.moveTo(X(p[2]),Y(p[0])));g.stroke();
    const e=s.path[s.path.length-1];g.fillStyle='rgba(207,232,214,.55)';
    g.beginPath();g.arc(X(e[2]),Y(e[0]),3.5,0,7);g.fill();}
  if(cur){const n=Math.max(2,Math.round(cur.path.length*frac));
    g.strokeStyle='#ffd23f';g.lineWidth=3;g.lineCap='round';g.beginPath();
    for(let i=0;i<n;i++){const p=cur.path[i];i?g.lineTo(X(p[2]),Y(p[0])):g.moveTo(X(p[2]),Y(p[0]));}g.stroke();
    const p=cur.path[n-1];g.fillStyle='#fff';g.beginPath();g.arc(X(p[2]),Y(p[0]),frac>=1?6:4.5,0,7);g.fill();
    if(frac>=1){g.strokeStyle='#ffd23f';g.lineWidth=2;g.beginPath();g.arc(X(p[2]),Y(p[0]),11,0,7);g.stroke();
      g.fillStyle='#fff';g.font='800 13px system-ui';g.textAlign='center';
      g.fillText(Math.round(cur.carry)+' yd',X(p[2]),Y(p[0])-16);}}
}
function drawSide(list,cur,frac){
  const [g,W,H]=fit($('side-view'));const all=list.concat(cur?[cur]:[]);
  const D=maxDist(all);let A=10;for(const s of all)A=Math.max(A,s.apex*1.2);
  const padL=8,padB=14,padT=10,sx=(W-2*padL)/D,sy=(H-padB-padT)/A,s0=Math.min(sx,sy*3);
  const X=x=>padL+x*sx,Y=y=>H-padB-y*sy;
  g.fillStyle='#173020';g.fillRect(0,H-padB,W,padB);
  g.fillStyle='rgba(255,255,255,.45)';g.font='600 10px system-ui';g.textAlign='right';
  g.fillText('height',W-8,padT+8);
  for(const s of list){if(s===cur)continue;g.strokeStyle='rgba(207,232,214,.2)';g.lineWidth=1.5;g.beginPath();
    s.path.forEach((p,i)=>i?g.lineTo(X(p[0]),Y(p[1])):g.moveTo(X(p[0]),Y(p[1])));g.stroke();}
  if(cur){const n=Math.max(2,Math.round(cur.path.length*frac));
    g.strokeStyle='#ffd23f';g.lineWidth=3;g.lineCap='round';g.beginPath();
    for(let i=0;i<n;i++){const p=cur.path[i];i?g.lineTo(X(p[0]),Y(p[1])):g.moveTo(X(p[0]),Y(p[1]));}g.stroke();
    const p=cur.path[n-1];g.fillStyle='#fff';g.beginPath();g.arc(X(p[0]),Y(p[1]),4,0,7);g.fill();}
}
function draw(frac){
  const list=shots.slice(hidden);const cur=lastShot&&list.includes(lastShot)?lastShot:null;
  drawTop(list,cur,frac);drawSide(list,cur,frac);
}
function showStats(s){
  const set=(id,v,est)=>{$(id).textContent=v;$(id).classList.toggle('est',!!est);};
  if(!s){for(const id of ['carry','speed','launch','apex','club'])set(id,'--');$('note').textContent='';return;}
  const a=s.assumed||[];
  set('carry',Math.round(s.carry),a.includes('launch'));set('speed',s.ball_speed.toFixed(1));
  set('launch',s.launch.toFixed(1),a.includes('launch'));set('apex',s.apex.toFixed(0));
  set('club',s.club.toUpperCase());
  $('note').textContent=a.includes('launch')?'Launch angle not measured yet: using the club\\'s typical launch (shown in yellow).':'';
}
function play(s){
  lastShot=s;showStats(s);if(anim)cancelAnimationFrame(anim);
  const dur=Math.min(2600,Math.max(900,s.time*450)),t0=performance.now();
  const step=t=>{const f=Math.min(1,(t-t0)/dur);draw(f);if(f<1)anim=requestAnimationFrame(step);else anim=null;};
  anim=requestAnimationFrame(step);
}
async function poll(){
  try{
    const st=await (await fetch('/state',{cache:'no-store'})).json();
    const v=STATES[st.state]||[st.state,'var(--dim)'];$('stext').textContent=v[0];$('dot').style.background=v[1];
    if(st.rev!==rev){rev=st.rev;
      const h=await (await fetch('/history',{cache:'no-store'})).json();
      const before=shots.length?shots[shots.length-1].shot:null;shots=h.shots||[];
      if(hidden>shots.length)hidden=0;
      const last=shots[shots.length-1];
      if(last&&last.shot!==before)play(last);else if(!anim)draw(1);
    }
  }catch(e){$('stext').textContent='Not connected';$('dot').style.background='#e5484d';}
  setTimeout(poll,600);
}
$('test').onclick=()=>fetch('/testshot',{method:'POST'});
$('clear').onclick=()=>{hidden=shots.length;lastShot=null;showStats(null);draw(1);};
window.addEventListener('resize',()=>{if(!anim)draw(1);});
draw(1);poll();
</script></body></html>"""
