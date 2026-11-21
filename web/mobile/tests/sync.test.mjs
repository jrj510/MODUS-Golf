import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Journal } from '../src/journal.ts';
import { acceptReceipt, bindSession, belongsToAccount, payloadDigest, pendingShots } from '../src/sync-queue.ts';
import { firebaseProjectId, legacyBindingsProjectId } from '../src/firebase-project.ts';
import { syncOverview } from '../src/sync-overview.ts';
import { sendShotBatch } from '../src/upload-batch.ts';
import { normalizeSessionCsv } from '../../MODUS_Golf_Firebase_AI_Starter/app-core/shot.mjs';

const filename='session_20261022_192000.csv';
const csv=readFileSync(new URL('../../MODUS_Golf_Firebase_AI_Starter/contracts/fixtures/'+filename,import.meta.url),'utf8');
const [shot,other]=await normalizeSessionCsv(csv,{filename,deviceId:'modus_pi_local',profileId:'phone_local_golfer',confirmedReal:true});

function confirmBatch(body) {
  const receipts=JSON.parse(body).shots.map(item => ({
    status:'accepted', code:'write', shotId:item.shot_id, revision:item.revision, digest:payloadDigest(item),
    cloudShotId:'shot_'+'a'.repeat(64), cloudSessionId:'session_'+'b'.repeat(64)
  }));
  return Response.json({version:1,receipts});
}

test('larger extended sessions drain in byte-limited batches with exact receipts', async () => {
  const csv34=readFileSync(new URL('../../MODUS_Golf_Firebase_AI_Starter/contracts/fixtures/pi_csv_34_synthetic.csv',import.meta.url),'utf8');
  const [sample]=await normalizeSessionCsv(csv34,{filename,deviceId:'pi',profileId:'golfer',confirmedReal:true});
  const diagnostics=Object.fromEntries(Object.keys(sample.source.csv_extra).map(key => [key,'球'.repeat(160)]));
  const remaining=Array.from({length:21},(_,index) => ({
    ...sample, shot_id:'shot_'+index, source:{...sample.source,csv_extra:diagnostics}
  }));
  const uploaded=[];
  while (remaining.length) {
    const {shots,outcomes}=await sendShotBatch(remaining,'installation','golfer',async body => {
      assert.ok(Buffer.byteLength(body,'utf8')<=96_000);
      assert.ok(JSON.parse(body).shots.length<=20);
      return confirmBatch(body);
    });
    assert.deepEqual([...outcomes.keys()],shots.map(item => item.shot_id));
    assert.ok([...outcomes.values()].every(result => result.status==='accepted'));
    uploaded.push(...shots);
    remaining.splice(0,shots.length);
  }
  assert.equal(new Set(uploaded.map(item => item.shot_id)).size,21);
});

test('a server size rejection splits the batch and isolates a single oversized shot', async () => {
  const attempts=[];
  const smaller=await sendShotBatch([shot,other],'installation','golfer',async body => {
    attempts.push(JSON.parse(body).shots.length);
    return attempts.length===1 ? new Response(null,{status:413}) : confirmBatch(body);
  });
  assert.deepEqual(attempts,[2,1]);
  assert.equal(smaller.outcomes.get(shot.shot_id).status,'accepted');
  const rejected=await sendShotBatch([shot],'installation','golfer',async () => new Response(null,{status:413}));
  const local=bindSession({shots:[shot,other]},shot.session_id,{uid:'owner',profileId:'golfer'});
  local.sync.outcomes[shot.shot_id]=rejected.outcomes.get(shot.shot_id);
  assert.equal(syncOverview(local,'owner').attention.get('upload_too_large'),1);
  assert.deepEqual(pendingShots(local,'owner'),[other]);
  const oversized={...shot,source:{...shot.source,ti_radar:'x'.repeat(96_000)}};
  const blocked=await sendShotBatch([oversized],'installation','golfer',async () => assert.fail('oversized request sent'));
  assert.equal(blocked.outcomes.get(shot.shot_id).code,'upload_too_large');
  await assert.rejects(sendShotBatch([shot],'installation','golfer',async () => new Response(null,{status:503})));
});

test('linked outbox survives reopening and remains private to the intended account',async () => {
  const slots=new Map();
  const port={async read(slot){return slots.get(slot) ?? null;},async write(slot,value){slots.set(slot,value);}};
  const journal=new Journal(port);
  await journal.load();
  const synthetic={...other,record_kind:'synthetic'};
  const binding={uid:'account_a',profileId:'golfer'};
  await journal.commit(state => bindSession({...state,shots:[shot,synthetic]},shot.session_id,binding));
  const local=await new Journal(port).load();
  assert.deepEqual(pendingShots(local,'account_a'),[shot]);
  assert.deepEqual(pendingShots(local,'account_b'),[]);
  assert.throws(() => bindSession(local,shot.session_id,{...binding,uid:'account_b'}),/already linked/);
  assert.throws(() => bindSession({...local,shots:[synthetic]},synthetic.session_id,binding),/Confirm physical/);
});

test('only the matching committed revision and digest can clear a pending shot', () => {
  const receipt={
    status:'accepted',code:'write',shotId:shot.shot_id,revision:shot.revision,digest:payloadDigest(shot),
    cloudShotId:'shot_'+'a'.repeat(64),cloudSessionId:'session_'+'b'.repeat(64)
  };
  assert.equal(acceptReceipt({...shot,revision:2},receipt),null);
  assert.equal(acceptReceipt({...shot,carry_yards:101},receipt),null);
  assert.equal(acceptReceipt(shot,{...receipt,cloudShotId:undefined}),null);
  assert.equal(acceptReceipt(shot,receipt)?.status,'accepted');
});

test('sync overview reports receipts, pending changes and rejections without exposing another account',async () => {
  const empty=await new Journal({async read(){return null;},async write(){}}).load();
  let local=bindSession({...empty,shots:[shot,other]},shot.session_id,{uid:'owner',profileId:'golfer'});
  const receipt={status:'accepted',code:'write',shotId:shot.shot_id,revision:shot.revision,digest:payloadDigest(shot),cloudShotId:'shot_'+'a'.repeat(64),cloudSessionId:'session_'+'b'.repeat(64)};
  local.sync.outcomes[shot.shot_id]=acceptReceipt(shot,receipt);
  local.sync.outcomes[other.shot_id]=acceptReceipt(other,{...receipt,shotId:other.shot_id,revision:other.revision,digest:payloadDigest(other),status:'rejected',code:'invalid_shot'});
  assert.equal(syncOverview(local,'owner').synced,1);
  assert.equal(syncOverview(local,'owner').rejected,1);
  assert.equal(syncOverview(local,'owner').attention.get('invalid_shot'),1);
  assert.equal(pendingShots(local,'owner').length,0);
  assert.equal(syncOverview(local,'stranger').synced,0);
  assert.equal(syncOverview(local,'stranger').rejected,0);
  local.shots=[{...shot,carry_yards:(shot.carry_yards ?? 0)+1},other];
  assert.equal(syncOverview(local,'owner').synced,0);
  assert.equal(syncOverview(local,'owner').pending,1);
  assert.equal(pendingShots(local,'owner').length,1);
});

test('unlinked sessions and unfinished records are distinguished from upload failures',async () => {
  const empty=await new Journal({async read(){return null;},async write(){}}).load();
  const local={...empty,shots:[shot,{...other,record_kind:'unknown'},{...other,record_kind:'synthetic'}]};
  const overview=syncOverview(local,'owner');
  assert.equal(overview.sessions.size,1);
  assert.equal(overview.unconfirmed,1);
  assert.equal(overview.pending,0);
  assert.equal(overview.rejected,0);
});

test('project-qualified links preserve original journals and isolate the incorrect-account project',async () => {
  const empty=await new Journal({async read(){return null;},async write(){}}).load();
  const linked=bindSession({...empty,shots:[shot]},shot.session_id,{uid:'same_uid',profileId:'golfer'});
  assert.equal(linked.sync.bindings[shot.session_id].projectId,firebaseProjectId);
  assert.equal(legacyBindingsProjectId,firebaseProjectId);
  assert.equal(belongsToAccount({uid:'same_uid',profileId:'golfer'},'same_uid'),true);
  for (const projectId of ['modus-golf']) {
    const binding={uid:'same_uid',profileId:'golfer',...(projectId ? {projectId} : {})};
    const old={...linked,sync:{...linked.sync,bindings:{[shot.session_id]:binding}}};
    assert.equal(belongsToAccount(binding,'same_uid'),false);
    assert.deepEqual(pendingShots(old,'same_uid'),[]);
    assert.throws(() => bindSession(old,shot.session_id,{uid:'same_uid',profileId:'golfer'}),/already linked/);
  }
});

test('an extended CSV rejected by the original validator gets one fresh attempt', async () => {
  const csv34=readFileSync(new URL('../../MODUS_Golf_Firebase_AI_Starter/contracts/fixtures/pi_csv_34_synthetic.csv',import.meta.url),'utf8');
  const [extended]=await normalizeSessionCsv(csv34,{filename,deviceId:'modus_pi_local',profileId:'phone_local_golfer',confirmedReal:true});
  const local=bindSession({shots:[extended]},extended.session_id,{uid:'account',profileId:'golfer'});
  const receipt={shotId:extended.shot_id,revision:extended.revision,digest:payloadDigest(extended),status:'rejected',code:'invalid_shot'};
  local.sync.outcomes[extended.shot_id]={...receipt,receivedAt:'2026-11-19T12:00:00Z'};
  assert.deepEqual(pendingShots(local,'account'),[extended]);
  assert.deepEqual(pendingShots(local,'different'),[]);
  local.sync.outcomes[extended.shot_id]=acceptReceipt(extended,receipt);
  assert.deepEqual(pendingShots(local,'account'),[]);
});
