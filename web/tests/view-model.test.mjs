import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { filterShots, summary, displayMetric, converted, uniqueShots, validateCloudShot, sourceName, historyCsv, shotDate, selectedShot, flightPoints, directionWasApplied } from '../src/domain.ts';
import {CSV_EXTENDED_COLUMNS,normalizeSessionCsv} from '../MODUS_Golf_Firebase_AI_Starter/app-core/shot.mjs';
const fixtures = JSON.parse(readFileSync('MODUS_Golf_Firebase_AI_Starter/contracts/fixtures/demo_shots.json', 'utf8'));
const real = () => ({ ...structuredClone(fixtures[0]), record_kind: 'real', source: { ...fixtures[0].source, kind: 'pi_live' } });
test('250 records are all included in whole-filter statistics and random shot lookup', () => {
  const shots = Array.from({ length: 250 }, (_, i) => ({ ...real(), shot_id: `record_${i}`, sequence_number: i+1, carry_yards: i }));
  const all = filterShots(shots, { profileId: shots[0].profile_id });
  const stats = summary(all, shots[0].profile_id);
  assert.equal(all.length, 250); assert.equal(stats.shot_count, 250);
  assert.equal(stats.metrics.carry_yards.n, 250); assert.equal(stats.metrics.carry_yards.mean, 124.5);
  for (const i of [0, 249, 114, 23, 200, 125, 98, 180, 77, 42]) assert.equal(all.find(s => s.shot_id === `record_${i}`).carry_yards, i);
});
test('profile, club, session and source-date filters never reassign ownership', () => {
  const first = real(), other = { ...real(), shot_id: 'other', profile_id: 'other_golfer' };
  const result = filterShots([first,other], { profileId: first.profile_id, club: first.club, sessionId: first.session_id, date: '2026-10-22' });
  assert.equal(result.length, 1); assert.equal(other.profile_id, 'other_golfer');
  assert.equal(shotDate(first), '2026-10-22');
  assert.equal(filterShots([first], { profileId: first.profile_id, date: '2026-10-23' }).length, 0);
});
test('sample counts, missing values, sample SD, and synthetic exclusion are preserved', () => {
  const first = { ...real(), carry_yards: 100, club_speed_mph: null };
  const second = { ...real(), shot_id: 'two', carry_yards: 120, club_speed_mph: 90 };
  const synthetic = { ...real(), shot_id: 'synthetic', record_kind: 'synthetic', carry_yards: 1000 };
  const unknown = { ...real(), shot_id: 'unknown', record_kind: 'unknown', carry_yards: 1000 };
  const stats = summary([first,second,synthetic,unknown], first.profile_id);
  assert.equal(stats.shot_count, 2); assert.equal(stats.metrics.club_speed_mph.n, 1);
  assert.equal(stats.metrics.carry_yards.mean, 110); assert.ok(Math.abs(stats.metrics.carry_yards.sample_sd - Math.sqrt(200)) < 1e-9);
  assert.equal(stats.metrics.club_speed_mph.sample_sd, null);
});
test('units preserve zero angles and distinguish unavailable metrics', () => {
  assert.equal(displayMetric(0, 'horizontal_launch_angle_deg', 'metric'), '0.0');
  assert.equal(displayMetric(null, 'carry_yards', 'imperial'), '—');
  assert.equal(converted(100, 'carry_yards', 'metric'), 91.44);
  assert.equal(displayMetric(100, 'ball_speed_mph', 'metric'), '160.9');
});
test('new revisions upsert in place; stale revisions do not win; conflicting owners fail', () => {
  const first = real(), enriched = { ...first, revision: 2, carry_yards: 200 };
  assert.equal(uniqueShots([enriched,first]).length, 1);
  assert.equal(uniqueShots([enriched,first])[0].carry_yards, 200);
  assert.throws(() => uniqueShots([first,{ ...first, profile_id: 'different' }]), /immutable/);
});
test('cloud adapter rejects malformed fields before publishing a dataset', () => {
  const shot = real(); assert.equal(validateCloudShot({ ...shot, id: shot.shot_id }).shot_id, shot.shot_id);
  for (const invalid of [{ id: 'mismatch' }, { club_speed_mph: '99' }, { trajectory: [[1,2,NaN]] }, { source: { kind: 'pi_live', filename: 42 } }, { model_inputs: { spin_rpm: {} } }]) {
    assert.throws(() => validateCloudShot({ ...shot, ...invalid }), /contract/);
  }
});
test('CSV export includes stable identity and provenance, escapes quoted status, and keeps zero', () => {
  const shot = { ...real(), horizontal_launch_angle_deg: 0, source: { ...real().source, ti_radar: 'quality, "check"' } };
  const csv = historyCsv([shot]);
  assert.match(csv.split('\n')[0], /shot_id,session_id,device_id,profile_id,revision,record_kind/);
  assert.match(csv, /"quality, ""check"""/); assert.ok(csv.includes(',0,')); assert.ok(csv.includes(',real,final,pi_live,'));
  assert.equal(sourceName(fixtures[0]), 'Synthetic demo'); assert.equal(sourceName(shot), 'Pi record');
});

test('an earlier selection stays on its stable ID through new arrivals and enrichment', () => {
  const first = real(), newer = { ...real(), shot_id: 'newer', sequence_number: 2 };
  const enriched = { ...first, revision: 2, carry_yards: 121 };
  const rows = uniqueShots([first, newer, enriched]);
  assert.equal(selectedShot(rows, first.shot_id).carry_yards, 121);
  assert.equal(selectedShot(rows, null).shot_id, 'newer');
  assert.equal(selectedShot(rows, 'removed').shot_id, 'newer');
});

test('flight points require an eligible supplied path and never come from a CSV', () => {
  const shot = { ...real(), trajectory: [[0,0,0],[100,0,2]] };
  assert.deepEqual(flightPoints(shot), shot.trajectory);
  assert.equal(flightPoints({ ...shot, source: { kind: 'legacy_csv' } }), null);
  assert.equal(flightPoints({ ...shot, trajectory: [[0,0,0]] }), null);
  assert.equal(flightPoints({ ...shot, source: { kind: 'synthetic_demo' }, record_kind: 'real' }), null);
});

test('measured zero direction remains valid while an assumed direction is disclosed', () => {
  const shot = { ...real(), model_inputs: { ...real().model_inputs, horizontal_launch_angle_deg: 0 }, quality_flags: [] };
  assert.equal(directionWasApplied(shot), true);
  assert.equal(directionWasApplied({ ...shot, quality_flags: ['flight_direction_assumed'] }), false);
  assert.equal(directionWasApplied({ ...shot, model_inputs: { ...shot.model_inputs, horizontal_launch_angle_deg: null } }), false);
});

test('Firestore point maps decode losslessly without changing canonical modeled carry', () => {
  const shot = { ...real(), carry_yards: 112, trajectory: [{ forward_yards: 0, height_yards: 0, right_yards: 0 }, { forward_yards: 111.98, height_yards: 0, right_yards: -2 }] };
  const decoded = validateCloudShot(shot);
  assert.deepEqual(decoded.trajectory, [[0,0,0],[111.98,0,-2]]);
  assert.equal(decoded.carry_yards, 112);
  assert.equal(shot.trajectory[1].forward_yards, 111.98);
  for (const point of [{ forward_yards: 0, height_yards: 0 }, { forward_yards: 0, height_yards: 0, right_yards: Infinity }, { forward_yards: '0', height_yards: 0, right_yards: 0 }]) assert.throws(() => validateCloudShot({ ...shot, trajectory: [point] }), /contract/);
  assert.throws(() => validateCloudShot({ ...shot, source: { ...shot.source, apex_yards: '19' } }), /contract/);
});

test('extended Pi diagnostics validate and survive mixed-format history export',async()=>{
  const fixture=readFileSync('MODUS_Golf_Firebase_AI_Starter/contracts/fixtures/pi_csv_34_synthetic.csv','utf8');
  const shots=await normalizeSessionCsv(fixture,{deviceId:'pi_test',profileId:'golfer_a',filename:'session_20261119_120000.csv'});
  assert.deepEqual(validateCloudShot(shots[0]),shots[0]);
  const old=real();old.source.ti_radar='good';
  const exported=historyCsv([old,...shots]);
  const header=exported.split('\n')[0].split(',');
  assert.deepEqual(header.slice(0,34),CSV_EXTENDED_COLUMNS);assert.equal(header.length,46);
  const legacyRow=exported.split('\n')[1].split(',');
  assert.equal(legacyRow.length,46);assert.deepEqual(legacyRow.slice(14,34),Array(20).fill(''));
  assert.match(exported,/"calibrated, ""cluster"""/);
  assert.match(exported,/"check, ""held"""/);
  assert.equal(shots[1].club_speed_mph,null);
});

test('malformed extended provenance cannot enter the journal/cloud view',async()=>{
  const fixture=readFileSync('MODUS_Golf_Firebase_AI_Starter/contracts/fixtures/pi_csv_34_synthetic.csv','utf8');
  const [shot]=await normalizeSessionCsv(fixture,{deviceId:'pi_test',profileId:'golfer_a',filename:'session_20261119_120000.csv'});
  for(const extra of [null,[],{}, {...shot.source.csv_extra,unexpected:'x'}, {...shot.source.csv_extra,cam_frames:8}, {...shot.source.csv_extra,cam_quality:'x'.repeat(1001)}]) {
    assert.throws(()=>validateCloudShot({...shot,source:{...shot.source,csv_extra:extra}}),/contract/);
  }
  assert.throws(()=>validateCloudShot({...shot,source:{...shot.source,csv_format:'unknown'}}),/contract/);
});

