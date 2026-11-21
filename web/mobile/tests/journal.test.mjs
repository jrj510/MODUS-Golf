import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Journal, mergeLocal } from '../src/journal.ts';
import { decodePiSnapshot, piOrigin } from '../src/pi.ts';
import { CSV_COLUMNS, normalizeSessionCsv } from '../../MODUS_Golf_Firebase_AI_Starter/app-core/shot.mjs';
import { sha256 } from '@noble/hashes/sha2.js';

const example=JSON.parse(readFileSync(new URL('../../MODUS_Golf_Firebase_AI_Starter/contracts/fixtures/demo_shots.json',import.meta.url),'utf8'))[0];
function memory() {const slots=new Map();return {slots,async read(key){return slots.get(key) ?? null;},async write(key,value){slots.set(key,value);}};}

test('cold local startup requires no account or network and starts empty',async () => {
  const data=await new Journal(memory()).load();assert.deepEqual(data.shots,[]);assert.equal(data.piOrigin,'http://10.42.0.1:8000');
});
test('writes before load or after failed recovery cannot replace stored practice',async () => {
  const port=memory(),journal=new Journal(port);
  await assert.rejects(journal.commit(state => ({...state,shots:[example]})),/must load successfully/);
  assert.equal(port.slots.size,0);
  port.slots.set('a','damaged');
  await assert.rejects(journal.load(),/damaged/);
  await assert.rejects(journal.mergeCapture([example],() => true),/must load successfully/);
  assert.deepEqual([...port.slots],[['a','damaged']]);
});
test('loading and subsequent writes serialize without resetting existing records',async () => {
  const port=memory(),first=new Journal(port);await first.load();
  await first.commit(state => ({...state,shots:[example]}));
  const reopened=new Journal(port);
  const loading=reopened.load();
  const saving=reopened.commit(state => ({...state,units:'metric'}));
  await loading;
  assert.equal((await saving).shots.length,1);
  assert.equal((await reopened.load()).units,'metric');
});
test('250 saved records survive a fresh journal instance with exact values',async () => {
  const port=memory(), journal=new Journal(port);await journal.load();
  const shots=Array.from({length:250},(_,i) => ({...structuredClone(example),shot_id:`local_${i}`,sequence_number:i+1,carry_yards:i}));
  await journal.commit(current => ({...current,shots}));
  const reopened=await new Journal(port).load();assert.deepEqual(reopened.shots,shots);
});
test('concurrent saves serialize without losing already committed shots',async () => {
  const port=memory(), journal=new Journal(port);await journal.load();
  await Promise.all(Array.from({length:10},(_,i) => journal.commit(current => ({...current,shots:[...current.shots,{...structuredClone(example),shot_id:`burst_${i}`}]}))));
  assert.equal((await new Journal(port).load()).shots.length,10);
});
test('a torn newer write is rejected and the previous complete generation recovers',async () => {
  const port=memory(), journal=new Journal(port);await journal.load();
  await journal.commit(current => ({...current,shots:[example]}));
  port.write=async (key,value) => {port.slots.set(key,value.slice(0,25));};
  await assert.rejects(journal.commit(current => ({...current,shots:[]})),/not verified/);
  assert.deepEqual((await new Journal(port).load()).shots,[example]);
});
test('corrupt data never silently resets to an empty practice',async () => {
  const port=memory();port.slots.set('a','{}');port.slots.set('b','broken');
  await assert.rejects(new Journal(port).load(),/damaged/);
});
test('digest detects well-formed JSON that was modified after saving',async () => {
  const port=memory(), journal=new Journal(port);await journal.load();await journal.commit(current => ({...current,shots:[example]}));
  const value=JSON.parse(port.slots.get('a'));value.data.shots[0].carry_yards=499;port.slots.set('a',JSON.stringify(value));
  await assert.rejects(new Journal(port).load(),/damaged/);
});
test('retries, key order and late enrichment retain one immutable local identity',() => {
  const reordered=Object.fromEntries(Object.entries(example).reverse());
  const retry=mergeLocal([example],[reordered]);assert.equal(retry.length,1);assert.equal(retry[0].revision,1);
  const changed=mergeLocal(retry,[{...reordered,carry_yards:123}]);assert.equal(changed[0].revision,2);
  assert.equal(mergeLocal(changed,[{...reordered,carry_yards:123}])[0].revision,2);
  assert.throws(() => mergeLocal(changed,[{...example,profile_id:'different'}]),/reassigned/);
});
test('portable mobile hashing matches the web contract even without Web Crypto',async () => {
  const csv=readFileSync(new URL('../../MODUS_Golf_Firebase_AI_Starter/contracts/fixtures/session_20261022_192000.csv',import.meta.url),'utf8');
  const context={deviceId:'local_device',profileId:'local_golfer',filename:'session_20261022_192000.csv'};
  const standard=await normalizeSessionCsv(csv,context);
  const descriptor=Object.getOwnPropertyDescriptor(globalThis,'crypto');
  try {
    Object.defineProperty(globalThis,'crypto',{value:undefined,configurable:true});
    const portable=await normalizeSessionCsv(csv,{...context,hashBytes:sha256});assert.deepEqual(portable,standard);
    const journal=new Journal(memory());await journal.load();await journal.commit(current => ({...current,shots:portable}));
  } finally {Object.defineProperty(globalThis,'crypto',descriptor);}
});
test('Pi connection accepts only configured local origins without credentials',() => {
  assert.equal(piOrigin('http://10.42.0.1:8000'),'http://10.42.0.1:8000');
  for (const address of ['https://example.com','http://user:password@10.42.0.1:8000','http://10.42.0.1:8000/path','http://10.42.0.1:8000/?token=value']) assert.throws(() => piOrigin(address));
});

test('reopening a confirmed session does not silently downgrade physical records',() => {
  const real={...structuredClone(example),record_kind:'real',source:{...example.source,kind:'legacy_csv'}};
  const reopened=mergeLocal([real],[{...real,record_kind:'unknown'}]);
  assert.equal(reopened[0].record_kind,'real');assert.equal(reopened[0].revision,real.revision);
  assert.throws(() => mergeLocal([example],[{...example,record_kind:'real'}]),/Synthetic/);
});

test('the Pi header-only placeholder waits for a shot; it cannot identify records', async () => {
  const state = {deviceId:'local_device', profileId:'local_golfer'};
  const disposition = 'attachment; filename="session.csv"';
  assert.deepEqual(await decodePiSnapshot(CSV_COLUMNS.join(',')+'\n',disposition,state,null),{filename:null,shots:[]});
  const csv = readFileSync(new URL('../../MODUS_Golf_Firebase_AI_Starter/contracts/fixtures/session_20261022_192000.csv',import.meta.url),'utf8');
  await assert.rejects(decodePiSnapshot(csv,disposition,state,null),/original session CSV filename/);
  const snapshot = await decodePiSnapshot(csv,'attachment; filename="session_20261022_192000.csv"',state,'session_20261021_192000.csv');
  assert.ok(snapshot.shots.length);
  assert.ok(snapshot.shots.every(shot => shot.record_kind === 'unknown'));
});

test('large journals skip writes for identical and canceled monitor snapshots', async t => {
  const port = memory();
  const journal = new Journal(port);
  await journal.load();
  const shots = Array.from({length:10_000},(_,i) => ({...example,shot_id:`large_${i}`,sequence_number:i+1}));
  await journal.commit(current => ({...current,units:'metric',shots}));
  const start = performance.now();
  const reopened = new Journal(port);
  const data = await reopened.load();
  const loadMs = performance.now()-start;
  assert.equal(data.shots.length,10_000);
  assert.equal(data.units,'metric');
  port.write = async () => assert.fail('A stale or identical snapshot must not write the journal');
  const retryStart = performance.now();
  for (let poll=0; poll<5; poll++) assert.equal(await reopened.mergeCapture(shots.slice(-100),() => true),null);
  assert.equal(await reopened.mergeCapture([{...example,shot_id:'stale'}],() => false),null);
  t.diagnostic(`In-memory journal: 10,000-shot reopen ${loadMs.toFixed(1)} ms, five unchanged 100-shot polls ${(performance.now()-retryStart).toFixed(1)} ms`);
});

test('34-column monitor response survives capture, relaunch, retry and diagnostic enrichment', async () => {
  const csv = readFileSync(new URL('../../MODUS_Golf_Firebase_AI_Starter/contracts/fixtures/pi_csv_34_synthetic.csv', import.meta.url), 'utf8');
  const port = memory();
  let journal = new Journal(port);
  const state = await journal.load();
  const capture = async text => {
    const snapshot = await decodePiSnapshot(text, 'attachment; filename="session_20261119_120000.csv"', state, null);
    return journal.mergeCapture(snapshot.shots, () => true);
  };
  const placeholder = await decodePiSnapshot(csv.split('\n')[0]+'\n', 'attachment; filename="session.csv"', state, null);
  assert.deepEqual(placeholder, {filename:null, shots:[]});
  const first = await capture(csv);
  assert.equal(first.shots.length, 2);
  assert.equal(first.shots[0].record_kind, 'unknown');
  journal = new Journal(port);
  assert.deepEqual((await journal.load()).shots, first.shots);
  assert.equal(await capture(csv), null);
  const updated = await capture(csv.replace('calibrated, ""cluster""', 'calibrated, ""updated""'));
  assert.equal(updated.shots.length, 2);
  assert.equal(updated.shots[0].shot_id, first.shots[0].shot_id);
  assert.equal(updated.shots[0].revision, 2);
  assert.equal(updated.shots[0].source.csv_extra.club_speed_how, 'calibrated, "updated"');
  assert.deepEqual((await new Journal(port).load()).shots, updated.shots);
});
