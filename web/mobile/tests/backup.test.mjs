import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Journal } from '../src/journal.ts';
import { createBackup, readBackup, restoreBackup } from '../src/backup.ts';
import { bindSession } from '../src/sync-queue.ts';
import { normalizeSessionCsv } from '../../MODUS_Golf_Firebase_AI_Starter/app-core/shot.mjs';

test('backup restores without duplicates and rejects other account or installation links',async () => {
  const filename='session_20261022_192000.csv';
  const csv=readFileSync(new URL('../../MODUS_Golf_Firebase_AI_Starter/contracts/fixtures/'+filename,import.meta.url),'utf8');
  const empty=await new Journal({async read(){return null;},async write(){}}).load();
  const [shot]=await normalizeSessionCsv(csv,{filename,deviceId:empty.deviceId,profileId:empty.profileId,confirmedReal:true});
  const linked=bindSession({...empty,shots:[shot]},shot.session_id,{uid:'owner',profileId:'golfer'});
  const text=createBackup(linked,[shot]);
  const backup=await readBackup(new File([text],'backup.json'));
  assert.throws(() => restoreBackup(empty,backup,'other'),/owns this backup/);
  assert.throws(() => restoreBackup({...linked,sync:{...linked.sync,installationId:crypto.randomUUID()}},backup,'owner'),/different installation/);
  const restored=restoreBackup(empty,backup,'owner');
  assert.deepEqual(restored.shots,[shot]);
  assert.deepEqual(restoreBackup(restored,backup,'owner'),restored);
  const legacy=JSON.parse(text);
  delete legacy.local.sync.bindings[shot.session_id].projectId;
  const originalProject=await readBackup(new File([JSON.stringify(legacy)],'original-project.json'));
  assert.deepEqual(restoreBackup(empty,originalProject,'owner').shots,[shot]);
  legacy.local.sync.bindings[shot.session_id].projectId='modus-golf';
  const wrongProject=await readBackup(new File([JSON.stringify(legacy)],'wrong-project.json'));
  assert.throws(() => restoreBackup(empty,wrongProject,'owner'),/Firebase project/);
});

test('backup recovers practice settings and notes while keeping newer local preferences',async () => {
  const filename='session_20261022_192000.csv';
  const csv=readFileSync(new URL('../../MODUS_Golf_Firebase_AI_Starter/contracts/fixtures/'+filename,import.meta.url),'utf8');
  const empty=await new Journal({async read(){return null;},async write(){}}).load();
  const [shot]=await normalizeSessionCsv(csv,{filename,deviceId:'custom_monitor',profileId:empty.profileId,confirmedReal:true});
  const original={...empty,shots:[shot],deviceId:'custom_monitor',units:'metric',
    bag:[{id:'club_1',name:'Practice iron',monitorLabel:'7i',archived:false}],
    sessionDetails:{[shot.session_id]:{name:'Monday practice',notes:'Work on launch'}},
    monitors:{[empty.piOrigin]:'custom_monitor'}
  };
  const read=async value => readBackup(new File([JSON.stringify(value)],'backup.json'));
  const exported=JSON.parse(createBackup(original,[shot]));
  const backup=await read(exported);
  const restored=restoreBackup(empty,backup,null);
  assert.deepEqual(restored.shots,[shot]);
  assert.equal(restored.units,'metric');
  assert.equal(restored.deviceId,'custom_monitor');
  assert.deepEqual(restored.bag,original.bag);
  assert.deepEqual(restored.sessionDetails,original.sessionDetails);
  assert.deepEqual(restored.monitors,original.monitors);
  const current={...restored,units:'imperial',bag:[{...restored.bag[0],name:'Updated iron'}],
    sessionDetails:{[shot.session_id]:{name:'Renamed',notes:'Latest notes'}}};
  assert.deepEqual(restoreBackup(current,backup,null),current);
  const wrongMonitor={...current,monitors:{[empty.piOrigin]:'different_monitor'}};
  assert.throws(() => restoreBackup(wrongMonitor,backup,null),/monitor identity/);
  await assert.rejects(read({...exported,local:{...exported.local,units:'invalid'}}),/display units/);
  await assert.rejects(read({...exported,local:{...exported.local,bag:[{...original.bag[0],name:'a'.repeat(61)}]}}),/club inventory/);
  await assert.rejects(read({...exported,local:{...exported.local,piOrigin:'https://example.com'}}),/private-network/);
  await assert.rejects(read({...exported,local:{...exported.local,sessionDetails:{unexported:{name:'Private',notes:''}}}}),/session details/);
});
