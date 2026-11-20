import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {CSV_COLUMNS,CSV_EXTRA_COLUMNS,CSV_EXTENDED_COLUMNS,parseSessionCsv,normalizeSessionCsv} from './shot.mjs';

const contract=JSON.parse(await readFile(new URL('../contracts/pi-csv-34.json',import.meta.url),'utf8'));
const fixture=(await readFile(new URL('../contracts/fixtures/pi_csv_34_synthetic.csv',import.meta.url),'utf8')).replaceAll('\r\n','\n');
const context={deviceId:'pi_test',profileId:'golfer_a',filename:'session_20261119_120000.csv'};
const quote=value=>/[",\r\n]/.test(value)?'"'+value.replaceAll('"','""')+'"':value;
const csv=(columns,rows)=>columns.join(',')+'\n'+rows.map(row=>columns.map(key=>quote(row[key])).join(',')).join('\n')+'\n';

test('extended contract matches the verified current Pi header and parses its 34 fields',()=>{
  assert.equal(contract.columns.length,34);assert.deepEqual(CSV_EXTENDED_COLUMNS,contract.columns);
  assert.equal(CSV_COLUMNS.length,14);assert.equal(CSV_EXTRA_COLUMNS.length,20);
  assert.deepEqual(fixture.split('\n')[0].split(','),contract.columns);
  const rows=parseSessionCsv(fixture);assert.equal(rows.length,2);
  assert.equal(Object.keys(rows[0]).length,34);assert.equal(rows[0].club_speed_how,'calibrated, "cluster"');
});

test('34-column normalization preserves all diagnostics without promoting rejected/check metrics',async()=>{
  const rows=parseSessionCsv(fixture),shots=await normalizeSessionCsv(fixture,context);
  for(let i=0;i<shots.length;i++) {
    assert.equal(shots[i].source.csv_format,'modus_csv_34');
    assert.deepEqual(shots[i].source.csv_extra,Object.fromEntries(CSV_EXTRA_COLUMNS.map(key=>[key,rows[i][key]])));
    assert.equal(shots[i].spin_rpm,null);assert.equal(shots[i].club_path_deg,null);
    assert.equal(shots[i].trajectory,null);assert.equal(shots[i].timestamp,null);assert.equal(shots[i].record_kind,'unknown');
  }
  assert.equal(shots[0].horizontal_launch_angle_deg,0);
  assert.equal(shots[1].club_speed_mph,null);assert.equal(shots[1].smash_factor,null);
  assert.equal(shots[1].source.csv_extra.club_speed_hidden_mph,'80');
  assert.equal(shots[1].vertical_launch_angle_deg,null);
  assert.equal(shots[1].source.csv_extra.cam_launch_deg,'12.5');
  assert.equal(shots[1].model_inputs.vertical_launch_angle_deg,17);
  assert.equal(shots[1].model_inputs.spin_rpm,7000);
  assert.equal(shots[1].source.ti_radar,'check, "held"');
});

test('known headers can be reordered without shifting metrics or changing identity/content hashes',async()=>{
  const rows=parseSessionCsv(fixture);
  for(const columns of [CSV_COLUMNS,CSV_EXTENDED_COLUMNS]) {
    const original=await normalizeSessionCsv(csv(columns,rows),context);
    const reordered=await normalizeSessionCsv(csv([...columns].reverse(),rows),context);
    assert.deepEqual(reordered,original);
  }
});

test('adding diagnostics preserves legacy shot/session IDs and retains legacy data shape',async()=>{
  const rows=parseSessionCsv(fixture);
  const old=await normalizeSessionCsv(csv(CSV_COLUMNS,rows),context);
  const current=await normalizeSessionCsv(fixture,context);
  assert.equal(current[0].shot_id,old[0].shot_id);assert.equal(current[0].session_id,old[0].session_id);
  assert.notEqual(current[0].source.row_sha256,old[0].source.row_sha256);
  assert.equal('csv_format' in old[0].source,false);assert.equal('csv_extra' in old[0].source,false);
});

test('changing only a diagnostic changes row hash but keeps immutable source identities',async()=>{
  const rows=parseSessionCsv(fixture),[before]=await normalizeSessionCsv(fixture,context);
  rows[0].cam_quality='fair';
  const [after]=await normalizeSessionCsv(csv(CSV_EXTENDED_COLUMNS,rows),context);
  assert.equal(after.shot_id,before.shot_id);assert.equal(after.session_id,before.session_id);
  assert.notEqual(after.source.row_sha256,before.source.row_sha256);
});

test('missing, unexpected, duplicate and truncated columns are rejected instead of discarded',()=>{
  const rows=parseSessionCsv(fixture);
  assert.throws(()=>parseSessionCsv(csv(CSV_EXTENDED_COLUMNS.slice(0,-1),rows)),/header.*33 columns/);
  assert.throws(()=>parseSessionCsv(csv([...CSV_EXTENDED_COLUMNS,'unexpected'],rows.map(row=>({...row,unexpected:'value'})))),/header/);
  const duplicate=[...CSV_EXTENDED_COLUMNS];duplicate[33]=duplicate[0];
  assert.throws(()=>parseSessionCsv(csv(duplicate,rows)),/duplicate column/);
  const renamed=[...CSV_EXTENDED_COLUMNS];renamed[0]='wrong_shot';
  assert.throws(()=>parseSessionCsv(csv(renamed,rows.map(row=>({...row,wrong_shot:row.shot})))),/header/);
  const shortRow=CSV_EXTENDED_COLUMNS.slice(0,-1).map(key=>quote(rows[0][key])).join(',');
  assert.throws(()=>parseSessionCsv(CSV_EXTENDED_COLUMNS.join(',')+'\n'+shortRow+'\n'),/wrong column count/);
  assert.throws(()=>parseSessionCsv(fixture.trimEnd()),/incomplete/);
});

test('extended CSV preserves CRLF/quoted fields and bounds raw diagnostic text',async()=>{
  assert.deepEqual(parseSessionCsv(fixture.replaceAll('\n','\r\n')),parseSessionCsv(fixture));
  const rows=parseSessionCsv(fixture);rows[0].club_speed_how='x'.repeat(1001);
  await assert.rejects(()=>normalizeSessionCsv(csv(CSV_EXTENDED_COLUMNS,rows),context),/diagnostic text/);
});
