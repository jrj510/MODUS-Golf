// Framework-independent MODUS app starter. No Pi I/O or Firebase side effects.
export const CSV_COLUMNS = Object.freeze(['shot','time','club','ball_speed_mph',
  'club_speed_mph','smash','launch_deg','launch_measured','spin_rpm_used',
  'carry_yd','apex_yd','ti_radar','ball_speed_raw_mph','launch_dir_deg']);

function identity(value, label) {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_-]{1,120}$/.test(value))
    throw new Error(`Invalid ${label}; use an explicit opaque ID, not a display name`);
  return value;
}
function number(value, label, min, max) {
  if (value === null || value === undefined || String(value).trim() === '') return null;
  const text = String(value).trim();
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(text))
    throw new Error(`Invalid ${label}`);
  const n = Number(text);
  if (!Number.isFinite(n) || n < min || n > max) throw new Error(`Invalid ${label}`);
  return n;
}
function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value !== null && typeof value === 'object')
    return '{' + Object.keys(value).sort().map(k => JSON.stringify(k)+':'+canonical(value[k])).join(',') + '}';
  return JSON.stringify(value);
}
export async function stableId(prefix, parts, hashBytes) {
  if (!hashBytes && !globalThis.crypto?.subtle) throw new Error('Web Crypto requires HTTPS/localhost or Node 20+');
  const bytes = new TextEncoder().encode(JSON.stringify([prefix, ...parts]));
  const digest = hashBytes ? await hashBytes(bytes) : await globalThis.crypto.subtle.digest('SHA-256', bytes);
  return prefix + '_' + Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2,'0')).join('');
}

export function parseSessionCsv(text) {
  if (typeof text !== 'string' || new TextEncoder().encode(text).length > 1048576)
    throw new Error('CSV must be text no larger than 1 MiB');
  text = text.replace(/^\uFEFF/, '');
  if (!text.endsWith('\n')) throw new Error('CSV is incomplete; download a complete newline-terminated snapshot');
  const rows=[]; let row=[], field='', quoted=false, closed=false;
  const finishField=()=>{row.push(field);field='';closed=false;};
  for (let i=0;i<text.length;i++) {
    const c=text[i];
    if (quoted) {
      if(c==='"') { if(text[i+1]==='"'){field+='"';i++;} else {quoted=false;closed=true;} }
      else field+=c;
    } else if(c===',') finishField();
    else if(c==='\r' && text[i+1]==='\n') continue;
    else if(c==='\n') {finishField();rows.push(row);row=[];}
    else if(c==='"' && field==='' && !closed) quoted=true;
    else {if(closed || c==='"')throw new Error('Malformed CSV quoting');field+=c;}
  }
  if(quoted)throw new Error('Unclosed CSV quote');
  const header=rows.shift();
  if(!header || header.length!==CSV_COLUMNS.length || header.some((x,i)=>x!==CSV_COLUMNS[i]))
    throw new Error('CSV header does not match the current MODUS kiosk');
  if(rows.length>10000)throw new Error('CSV has too many rows');
  return rows.map((values,index)=>{
    if(values.length!==header.length)throw new Error(`CSV row ${index+2} has the wrong column count`);
    return Object.fromEntries(header.map((key,i)=>[key,values[i]]));
  });
}

function checkFilename(filename) {
  const match=/^session_(20\d{2})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})\.csv$/.exec(filename);
  if(!match)throw new Error('Keep the original session_YYYYMMDD_HHMMSS.csv filename');
  const [y,m,d,h,n,s]=match.slice(1).map(Number);
  const date=new Date(Date.UTC(y,m-1,d,h,n,s));
  if(date.getUTCFullYear()!==y || date.getUTCMonth()!==m-1 || date.getUTCDate()!==d ||
     date.getUTCHours()!==h || date.getUTCMinutes()!==n || date.getUTCSeconds()!==s)
    throw new Error('Invalid session filename date/time');
}

export async function normalizeSessionCsv(text, context) {
  const {deviceId,profileId,filename,timezone=null,confirmedReal=false}=context;
  identity(deviceId,'device ID');identity(profileId,'golfer profile ID');checkFilename(filename);
  if(typeof confirmedReal!=='boolean')throw new Error('Real-shot confirmation must be explicit');
  if(timezone!==null) {
    if(typeof timezone!=='string' || timezone.length>100)throw new Error('Invalid timezone');
    try {new Intl.DateTimeFormat('en-US',{timeZone:timezone});} catch {throw new Error('Invalid timezone');}
  }
  const rows=parseSessionCsv(text), seen=new Set();
  // Validate the entire snapshot before returning any records to a writer.
  const parsed=rows.map(row=>{
    if(!/^[1-9]\d*$/.test(row.shot) || !Number.isSafeInteger(Number(row.shot)))throw new Error('Invalid shot number');
    if(seen.has(row.shot))throw new Error('Duplicate shot number in CSV');seen.add(row.shot);
    if(!/^(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d$/.test(row.time))throw new Error('Invalid local log time');
    if(!['yes','no'].includes(row.launch_measured))throw new Error('Invalid launch_measured flag');
    if(!/^[A-Za-z0-9 -]{1,24}$/.test(row.club))throw new Error('Invalid club label');
    if(row.ti_radar.length>1000)throw new Error('Radar status text exceeds the contract limit');
    return {row,
      ball:number(row.ball_speed_mph,'ball speed',0,250),
      club:number(row.club_speed_mph,'club speed',0,200),
      smash:number(row.smash,'smash factor',0,2),
      launch:number(row.launch_deg,'vertical angle',-30,90),
      hla:number(row.launch_dir_deg,'horizontal angle',-90,90),
      spin:number(row.spin_rpm_used,'model spin',0,30000),
      carry:number(row.carry_yd,'modeled carry',0,500),
      apex:number(row.apex_yd,'modeled apex',0,300),
      raw:number(row.ball_speed_raw_mph,'raw radar speed',0,250)};
  });
  const id=(prefix,parts)=>stableId(prefix,parts,context.hashBytes);
  const sessionId=await id('session',[deviceId,filename]);
  return Promise.all(parsed.map(async x=>({
    schema_version:1,
    shot_id:await id('shot',[deviceId,filename,x.row.shot]),
    session_id:sessionId,device_id:deviceId,profile_id:profileId,
    sequence_number:Number(x.row.shot),revision:1,timestamp:null,
    club:x.row.club.toLowerCase(),record_kind:confirmedReal?'real':'unknown',processing_state:'final',
    ball_speed_mph:x.ball,club_speed_mph:x.club,smash_factor:x.smash,
    vertical_launch_angle_deg:x.row.launch_measured==='yes'?x.launch:null,
    horizontal_launch_angle_deg:x.hla,carry_yards:x.carry,carry_kind:'model',
    spin_rpm:null,club_path_deg:null,trajectory:null,
    model_inputs:{vertical_launch_angle_deg:x.launch,spin_rpm:x.spin,horizontal_launch_angle_deg:0},
    quality_flags:['legacy_csv','sensor_values_unverified','spin_assumed','flight_direction_assumed',
      'no_impact_timestamp',...(x.row.launch_measured==='no'?['launch_assumed']:[])],
    source:{kind:'legacy_csv',filename,local_log_time:x.row.time,timezone,
      row_sha256:await id('row',CSV_COLUMNS.map(k=>x.row[k])),
      ti_radar:x.row.ti_radar,ball_speed_raw_mph:x.raw,apex_yards:x.apex}
  })));
}

export function mergeRevision(previous, incoming) {
  if(!incoming || typeof incoming.shot_id!=='string' || !Number.isInteger(incoming.revision) || incoming.revision<1)
    throw new Error('Invalid shot identity/revision');
  if(!previous)return incoming;
  for(const key of ['shot_id','session_id','profile_id','device_id'])
    if(previous[key]!==incoming[key])throw new Error('Shot identity and ownership are immutable');
  if(incoming.revision<previous.revision)return previous;
  if(incoming.revision===previous.revision) {
    if(canonical(previous)!==canonical(incoming))throw new Error('Conflicting payload at the same revision');
    return previous;
  }
  return incoming;
}

function metricSummary(values) {
  const xs=values.filter(x=>typeof x==='number'&&Number.isFinite(x));
  const n=xs.length;if(!n)return {n:0,mean:null,min:null,max:null,sample_sd:null};
  const mean=xs.reduce((a,b)=>a+b,0)/n;
  return {n,mean,min:Math.min(...xs),max:Math.max(...xs),
    sample_sd:n<2?null:Math.sqrt(xs.reduce((a,b)=>a+(b-mean)**2,0)/(n-1))};
}
export function summarizeShots(shots,{profileId,club=null,sessionId=null,allowSynthetic=false}) {
  identity(profileId,'golfer profile ID');
  const unique=new Map();
  for(const shot of shots)unique.set(shot.shot_id,mergeRevision(unique.get(shot.shot_id),shot));
  const included=[...unique.values()].filter(s=>s.profile_id===profileId &&
    (!club || s.club===club) && (!sessionId || s.session_id===sessionId) && s.processing_state==='final' &&
    (s.record_kind==='real' || (allowSynthetic && s.record_kind==='synthetic')));
  const metrics={};
  for(const key of ['ball_speed_mph','club_speed_mph','smash_factor',
    'vertical_launch_angle_deg','horizontal_launch_angle_deg','carry_yards'])
    metrics[key]=metricSummary(included.map(s=>s[key]));
  return {shot_count:included.length,metrics,carry_kind:'model',
    statistics_source:'app',includes_synthetic:included.some(s=>s.record_kind==='synthetic')};
}
