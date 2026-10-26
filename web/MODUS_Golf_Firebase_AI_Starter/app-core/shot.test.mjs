import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {CSV_COLUMNS,parseSessionCsv,normalizeSessionCsv,mergeRevision,summarizeShots} from './shot.mjs';

const header=CSV_COLUMNS.join(',')+'\n';
const line='1,23:59:59,7i,120,,1.4,0,yes,7000,170,25,good,119,0\n';
const context={deviceId:'pi_test',profileId:'golfer_a',filename:'session_20261022_235900.csv',timezone:'America/Chicago'};
const normalize=(csv=header+line,c={})=>normalizeSessionCsv(csv,{...context,...c});

test('empty cells are null and zero-degree measurements survive',async()=>{
  const [s]=await normalize();assert.equal(s.club_speed_mph,null);
  assert.equal(s.vertical_launch_angle_deg,0);assert.equal(s.horizontal_launch_angle_deg,0);
});
test('CSV model spin never becomes measured spin',async()=>{
  const [s]=await normalize();assert.equal(s.spin_rpm,null);assert.equal(s.model_inputs.spin_rpm,7000);
  assert.equal(s.model_inputs.horizontal_launch_angle_deg,0);assert.equal(s.carry_kind,'model');
});
test('assumed vertical angle stays out of measured VLA',async()=>{
  const [s]=await normalize(header+line.replace(',0,yes,',',16.5,no,'));
  assert.equal(s.vertical_launch_angle_deg,null);assert.equal(s.model_inputs.vertical_launch_angle_deg,16.5);
});
test('local log time is preserved without invented UTC/impact timing',async()=>{
  const [s]=await normalize();assert.equal(s.timestamp,null);assert.equal(s.source.local_log_time,'23:59:59');
  assert.equal(s.source.timezone,'America/Chicago');assert.ok(s.quality_flags.includes('no_impact_timestamp'));
});
test('imports are unknown until confirmed as real',async()=>{
  const [s]=await normalize();assert.equal(s.record_kind,'unknown');
  assert.equal(summarizeShots([s],{profileId:'golfer_a'}).shot_count,0);
});
test('stable source IDs and content hashes identify retries and changed rows',async()=>{
  const [a]=await normalize(),[b]=await normalize(),[c]=await normalize(header+line.replace(',120,',',121,'));
  assert.equal(a.shot_id,b.shot_id);assert.equal(a.session_id,b.session_id);
  assert.equal(a.shot_id,c.shot_id);assert.notEqual(a.source.row_sha256,c.source.row_sha256);
});
test('different devices cannot collide on same source filename',async()=>{
  const [a]=await normalize(),[b]=await normalize(header+line,{deviceId:'pi_other'});
  assert.notEqual(a.shot_id,b.shot_id);assert.notEqual(a.session_id,b.session_id);
});
test('duplicate row sequence is rejected',async()=>{
  await assert.rejects(()=>normalize(header+line+line),/Duplicate/);
});
test('partial snapshots and wrong headers are rejected',()=>{
  assert.throws(()=>parseSessionCsv(header+line.trimEnd()),/incomplete/);
  assert.throws(()=>parseSessionCsv('shot,time\n1,12:00:00\n'),/header/);
});
test('quoted CSV fields and CRLF are parsed',()=>{
  const csv=(header+line.replace(',good,',',"good, reported",')).replaceAll('\n','\r\n');
  assert.equal(parseSessionCsv(csv)[0].ti_radar,'good, reported');
});
test('malformed CSV and non-finite numeric inputs are rejected',async()=>{
  assert.throws(()=>parseSessionCsv(header+line.replace(',good,',',"good"x,')),/Malformed/);
  await assert.rejects(()=>normalize(header+line.replace(',120,',',NaN,')),/ball speed/);
  await assert.rejects(()=>normalize(header+line.replace(',120,',',Infinity,')),/ball speed/);
  await assert.rejects(()=>normalize(header+line.replace(',120,',',0x78,')),/ball speed/);
});
test('invalid dates, local clock values and timezone names are rejected',async()=>{
  await assert.rejects(()=>normalize(header+line,{filename:'session_20260230_120000.csv'}),/filename date/);
  await assert.rejects(()=>normalize(header+line.replace('23:59:59','25:00:00')),/log time/);
  await assert.rejects(()=>normalize(header+line,{timezone:'Not/A_Timezone'}),/timezone/);
});
test('whole CSV is rejected when a later row is invalid',async()=>{
  const bad=line.replace(/^1,/,'2,').replace(',120,',',900,');
  await assert.rejects(()=>normalize(header+line+bad),/ball speed/);
});
test('oversized radar status text is rejected before import',async()=>{
  await assert.rejects(()=>normalize(header+line.replace(',good,',','+'x'.repeat(1001)+',')),/status text/);
});
test('stale revisions do not overwrite final enrichment',async()=>{
  const [a]=await normalize();const b={...a,revision:2,club_speed_mph:85};
  assert.equal(mergeRevision(b,a),b);assert.equal(mergeRevision(a,b),b);
});
test('same revision conflicts and cross-profile reassignment are rejected',async()=>{
  const [a]=await normalize();assert.equal(mergeRevision(a,{...a}),a);
  assert.throws(()=>mergeRevision(a,{...a,carry_yards:999}),/Conflicting/);
  assert.throws(()=>mergeRevision(a,{...a,revision:2,profile_id:'golfer_b'}),/immutable/);
});
test('statistics use per-metric samples and sample standard deviation',async()=>{
  const [a]=await normalize(header+line,{confirmedReal:true});
  const b={...a,shot_id:'other',sequence_number:2,ball_speed_mph:124,club_speed_mph:88};
  const s=summarizeShots([a,b],{profileId:'golfer_a'});
  assert.equal(s.shot_count,2);assert.equal(s.metrics.club_speed_mph.n,1);
  assert.equal(s.metrics.club_speed_mph.sample_sd,null);assert.equal(s.metrics.ball_speed_mph.mean,122);
  assert.ok(Math.abs(s.metrics.ball_speed_mph.sample_sd-Math.sqrt(8))<1e-10);
  assert.equal('spin_rpm' in s.metrics,false);
});
test('profile, club and processing filters isolate statistics',async()=>{
  const [a]=await normalize(header+line,{confirmedReal:true});
  const b={...a,shot_id:'other',profile_id:'golfer_b'},c={...a,shot_id:'pending',processing_state:'processing'};
  assert.equal(summarizeShots([a,b,c],{profileId:'golfer_a'}).shot_count,1);
  assert.equal(summarizeShots([a],{profileId:'golfer_a',club:'driver'}).shot_count,0);
});
test('synthetic data is excluded unless demo explicitly opts in',async()=>{
  const [a]=await normalize();const s={...a,record_kind:'synthetic'};
  assert.equal(summarizeShots([s],{profileId:'golfer_a'}).shot_count,0);
  const demo=summarizeShots([s],{profileId:'golfer_a',allowSynthetic:true});
  assert.equal(demo.shot_count,1);assert.equal(demo.includes_synthetic,true);
});
test('replayed revisions count as one shot and use newest values',async()=>{
  const [a]=await normalize(header+line,{confirmedReal:true});
  const b={...a,revision:2,ball_speed_mph:124};
  const s=summarizeShots([b,a,b],{profileId:'golfer_a'});
  assert.equal(s.shot_count,1);assert.equal(s.metrics.ball_speed_mph.mean,124);
});

test('packaged demo records match the CSV normalizer and remain synthetic',async()=>{
  const fixture=async name=>readFile(new URL('../contracts/fixtures/'+name,import.meta.url),'utf8');
  const csv=await fixture('session_20261022_192000.csv');
  const expected=(await normalizeSessionCsv(csv,{
    deviceId:'demo_pi',profileId:'demo_golfer_a',filename:'session_20261022_192000.csv',timezone:null
  })).map(s=>({...s,record_kind:'synthetic',quality_flags:[...s.quality_flags,'synthetic_fixture'],
    source:{...s.source,kind:'synthetic_demo'}}));
  const actual=JSON.parse(await fixture('demo_shots.json'));
  assert.deepEqual(actual,expected);assert.equal(actual.length,12);
  assert.equal(summarizeShots(actual,{profileId:'demo_golfer_a'}).shot_count,0);
  const demo=summarizeShots(actual,{profileId:'demo_golfer_a',allowSynthetic:true});
  assert.equal(demo.shot_count,12);assert.equal(demo.metrics.club_speed_mph.n,11);
  assert.equal(demo.metrics.vertical_launch_angle_deg.n,11);
  const profiles=JSON.parse(await fixture('demo_profiles.json'));
  const sessions=JSON.parse(await fixture('demo_sessions.json'));
  assert.ok(profiles.some(p=>p.profile_id===actual[0].profile_id));
  assert.equal(sessions[0].session_id,actual[0].session_id);
  assert.equal(sessions[0].record_kind,'synthetic');
});

test('demo API fixtures contain model paths and identify removed sound hardware',async()=>{
  const fixture=async name=>JSON.parse(await readFile(new URL('../contracts/fixtures/'+name,import.meta.url),'utf8'));
  const history=await fixture('pi_history.json'),state=await fixture('pi_state.json');
  assert.equal(history.shots.length,12);assert.equal(state.metrics.flight.test,true);
  for(const flight of history.shots){
    assert.equal(flight.test,true);assert.ok(flight.path.length>1);
    for(const point of flight.path){assert.equal(point.length,3);assert.ok(point.every(Number.isFinite));}
  }
  const hardware=await fixture('known_hardware.json');
  assert.equal(hardware.fixture_only,true);
  assert.equal(hardware.trigger_source,'camera');
  assert.equal(hardware.sound_sensor.status,'temporarily_removed');
});
