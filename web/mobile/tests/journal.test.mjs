import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Journal, mergeLocal } from '../src/journal.ts';
import { piOrigin } from '../src/pi.ts';
import { normalizeSessionCsv } from '../../MODUS_Golf_Firebase_AI_Starter/app-core/shot.mjs';
import { sha256 } from '@noble/hashes/sha2.js';

const example=JSON.parse(readFileSync(new URL('../../MODUS_Golf_Firebase_AI_Starter/contracts/fixtures/demo_shots.json',import.meta.url),'utf8'))[0];
function memory() {const slots=new Map();return {slots,async read(key){return slots.get(key) ?? null;},async write(key,value){slots.set(key,value);}};}

test('cold local startup requires no account or network and starts empty',async () => {
  const data=await new Journal(memory()).load();assert.deepEqual(data.shots,[]);assert.equal(data.piOrigin,'http://10.42.0.1:8000');
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

test('34-column Pi snapshots persist and diagnostic enrichment updates one local revision',async()=>{
  const fixture=readFileSync(new URL('../../MODUS_Golf_Firebase_AI_Starter/contracts/fixtures/pi_csv_34_synthetic.csv',import.meta.url),'utf8');
  const context={deviceId:'pi_test',profileId:'golfer_a',filename:'session_20261119_120000.csv',hashBytes:sha256};
  const incoming=await normalizeSessionCsv(fixture,context);
  const port=memory(),journal=new Journal(port);await journal.load();
  await journal.commit(current=>({...current,shots:mergeLocal(current.shots,incoming)}));
  assert.deepEqual((await new Journal(port).load()).shots,incoming);
  const retry=mergeLocal(incoming,await normalizeSessionCsv(fixture,context));
  assert.equal(retry.length,2);assert.equal(retry[0].revision,1);
  const enriched=await normalizeSessionCsv(fixture.replace('calibrated, ""cluster""','calibrated, ""updated""'),context);
  const merged=mergeLocal(retry,enriched);
  assert.equal(merged.length,2);assert.equal(merged[0].revision,2);
  assert.equal(merged[0].source.csv_extra.club_speed_how,'calibrated, "updated"');
  await journal.commit(current=>({...current,shots:merged}));
  assert.deepEqual((await new Journal(port).load()).shots,merged);
});
