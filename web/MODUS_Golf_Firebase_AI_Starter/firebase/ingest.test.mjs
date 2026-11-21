import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { normalizeSessionCsv } from '../app-core/shot.mjs';
import { decideRevision, prepareShot, shotDigest, validBatch } from './ingest-core.mjs';

const filename='session_20261022_192000.csv';
const csv=readFileSync(new URL('../contracts/fixtures/'+filename,import.meta.url),'utf8');
const [shot]=await normalizeSessionCsv(csv,{filename,deviceId:'modus_pi_local',profileId:'phone_local_golfer',confirmedReal:true});
const installationId='af1ccf87-ea2d-442d-b848-41742455bc19';

test('legacy validation preserves source facts and rejects spoofed or ineligible data',async () => {
  const valid={version:1,installationId,profileId:'golfer',shots:[shot]};
  assert.equal(validBatch(valid),true);
  assert.equal(validBatch({...valid,uid:'victim'}),false);
  assert.equal(validBatch({...valid,shots:Array(21).fill(shot)}),false);
  const prepared=await prepareShot(shot,installationId,'golfer');
  assert.equal(prepared.record.profile_id,'golfer');
  assert.equal(prepared.record.original_shot_id,shot.shot_id);
  assert.ok(prepared.record.quality_flags.includes('sensor_values_unverified'));
  assert.equal(prepared.record.horizontal_launch_angle_deg,shot.horizontal_launch_angle_deg);
  for (const invalid of [{record_kind:'synthetic'},{record_kind:'unknown'},{shot_id:'spoofed'},
    {ball_speed_mph:251},{trajectory:[[0,0,0]]},{owner_uid:'victim'},{processing_state:'processing'}]) {
    assert.equal(await prepareShot({...shot,...invalid},installationId,'golfer'),null);
  }
});

test('canonical IDs are stable within an installation and revisions cannot roll back',async () => {
  const first=await prepareShot(shot,installationId,'golfer');
  const replay=await prepareShot(Object.fromEntries(Object.entries(shot).reverse()),installationId,'golfer');
  const changed=await prepareShot({...shot,carry_yards:100},installationId,'golfer');
  const later=await prepareShot({...shot,carry_yards:100,revision:2},installationId,'golfer');
  assert.equal(first.digest,replay.digest);
  assert.equal(first.cloudShotId,later.cloudShotId);
  assert.equal(decideRevision(first.record,replay.record),'replay');
  assert.equal(decideRevision(first.record,changed.record),'revision_conflict');
  assert.equal(decideRevision(first.record,later.record),'write');
  assert.equal(decideRevision(later.record,first.record),'stale_revision');
  assert.equal(decideRevision({...first.record,deleted_at:true},later.record),'deleted');
  assert.equal(decideRevision(first.record,{...later.record,profile_id:'other'}),'ownership_conflict');
});

test('emulator verifies login, account ownership, idempotent commit and direct write denial',
  {skip:!process.env.FIRESTORE_EMULATOR_HOST || !process.env.FIREBASE_AUTH_EMULATOR_HOST},async () => {
    const {initializeApp}=await import('firebase-admin/app');
    const {getFirestore}=await import('firebase-admin/firestore');
    const projectId='demo-modus-golf';
    const db=getFirestore(initializeApp({projectId}));
    const auth='http://'+process.env.FIREBASE_AUTH_EMULATOR_HOST;
    const endpoint='http://127.0.0.1:5001/'+projectId+'/us-central1/ingestLegacyShots';
    async function account() {
      const result=await fetch(auth+'/identitytoolkit.googleapis.com/v1/accounts:signUp?key=demo',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({email:crypto.randomUUID()+'@example.invalid',password:'test-only-password',returnSecureToken:true})
      });
      assert.equal(result.status,200);
      const user=await result.json();
      await db.doc('users/'+user.localId+'/profiles/golfer').set({display_name:'Test golfer'});
      return user;
    }
    const a=await account(), b=await account();
    const batch={version:1,installationId:crypto.randomUUID(),profileId:'golfer',shots:[shot]};
    function send(token,body=batch) {
      return fetch(endpoint,{
        method:'POST',headers:{'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})},
        body:JSON.stringify(body)
      });
    }
    async function receipt(token,body=batch) {
      const response=await send(token,body);
      assert.equal(response.status,200);
      return (await response.json()).receipts[0];
    }
    assert.equal((await send(null)).status,401);
    assert.equal((await send(a.idToken,{...batch,uid:b.localId})).status,400);
    const first=await receipt(a.idToken);
    assert.equal(first.status,'accepted');
    assert.equal(first.code,'write');
    assert.deepEqual(await receipt(a.idToken),{...first,code:'replay'});
    assert.equal((await receipt(b.idToken)).code,'ownership_conflict');
    assert.equal((await receipt(a.idToken,{...batch,profileId:'unknown'})).code,'profile_missing');
    const shotPath='users/'+a.localId+'/shots/'+first.cloudShotId;
    const record=await db.doc(shotPath).get();
    assert.equal(record.get('profile_id'),'golfer');
    assert.equal(record.get('original_shot_id'),shot.shot_id);
    assert.equal((await db.collection('users/'+a.localId+'/shots').get()).size,1);
    const firestore='http://'+process.env.FIRESTORE_EMULATOR_HOST+'/v1/projects/'+projectId+'/databases/(default)/documents/';
    const ownerHeaders={Authorization:'Bearer '+a.idToken,'Content-Type':'application/json'};
    assert.equal((await fetch(firestore+shotPath,{headers:ownerHeaders})).status,200);
    assert.equal((await fetch(firestore+shotPath,{headers:{Authorization:'Bearer '+b.idToken}})).status,403);
    assert.equal((await fetch(firestore+shotPath,{method:'PATCH',headers:ownerHeaders,body:JSON.stringify({fields:{}})})).status,403);
    // Exercise the phone's bounded, default document-order pagination against
    // the actual rules with an authenticated client (never production data).
    const seed=db.batch();
    for (let i=0;i<205;i++) {
      const id='page_'+String(i).padStart(3,'0');
      seed.set(db.doc(`users/${a.localId}/shots/${id}`),{...record.data(),shot_id:id});
    }
    await seed.commit();
    const seen=new Set();
    let cursor;
    let pages=0;
    while (true) {
      const structuredQuery={from:[{collectionId:'shots'}],limit:101,orderBy:[{field:{fieldPath:'__name__'},direction:'ASCENDING'}],
        ...(cursor ? {startAt:{values:[{referenceValue:cursor}],before:false}} : {})};
      const result=await fetch(firestore+'users/'+a.localId+':runQuery',{
        method:'POST',headers:ownerHeaders,body:JSON.stringify({structuredQuery})
      });
      const payload=await result.json();
      assert.equal(result.status,200,JSON.stringify(payload));
      const documents=payload.filter(item => item.document).map(item => item.document);
      assert.ok(documents.length <= 101);
      for (const document of documents.slice(0,100)) {
        assert.equal(seen.has(document.name),false,'A page repeated a document');
        seen.add(document.name);
      }
      pages++;
      if (documents.length <= 100) break;
      cursor=documents[99].name;
    }
    assert.equal(pages,3);
    assert.equal(seen.size,206);
    const denied=await fetch(firestore+'users/'+a.localId+':runQuery',{
      method:'POST',headers:{Authorization:'Bearer '+b.idToken,'Content-Type':'application/json'},
      body:JSON.stringify({structuredQuery:{from:[{collectionId:'shots'}],limit:101}})
    });
    assert.equal(denied.status,403);
    const extendedBatch={...batch,installationId:crypto.randomUUID(),shots:[await extendedFixtureShot()]};
    const extended=await receipt(a.idToken,extendedBatch);
    assert.equal(extended.status,'accepted');
    assert.equal(extended.digest,shotDigest(extendedBatch.shots[0]));
    const stored=await db.doc('users/'+a.localId+'/shots/'+extended.cloudShotId).get();
    assert.deepEqual(stored.get('source.csv_extra'),extendedBatch.shots[0].source.csv_extra);
    assert.deepEqual(await receipt(a.idToken,extendedBatch),{...extended,code:'replay'});
  });

async function extendedFixtureShot() {
  const extended=readFileSync(new URL('../contracts/fixtures/pi_csv_34_synthetic.csv',import.meta.url),'utf8');
  const [sample]=await normalizeSessionCsv(extended,{filename,deviceId:'modus_pi_local',profileId:'phone_local_golfer',confirmedReal:true});
  return sample;
}

test('34-column monitor import preserves diagnostics and rejects unexpected diagnostic fields', async () => {
  const sample=await extendedFixtureShot();
  const prepared=await prepareShot(sample,installationId,'golfer');
  assert.deepEqual(prepared.record.source.csv_extra,sample.source.csv_extra);
  assert.equal(prepared.digest,shotDigest(sample));
  const bad=structuredClone(sample);
  bad.source.csv_extra.unexpected='test';
  assert.equal(await prepareShot(bad,installationId,'golfer'),null);
});
