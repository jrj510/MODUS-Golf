import assert from 'node:assert/strict';
import {test} from 'node:test';
import fixtures from '../../MODUS_Golf_Firebase_AI_Starter/contracts/fixtures/demo_shots.json' with {type:'json'};
import {lastSequence, overlappingClubs, scoreTarget, yardageRows} from '../src/practice-tools.ts';
import {shotCue} from '../src/spoken-cues.ts';
import {Journal} from '../src/journal.ts';
import {pendingShots} from '../src/sync-queue.ts';

function shot(n,carry,extra={}) {
  return {...fixtures[0],shot_id:'shot_'+n,sequence_number:n,record_kind:'real',carry_yards:carry,
    source:{...fixtures[0].source,kind:'legacy_csv'},...extra};
}
test('target window skips warmup, other sessions and post-finish shots, including boundary carries', () => {
  const rows = [0,88,90,100,110,111,null,0,0,0,0].map((v,i) => shot(i+1,v));
  rows[7].record_kind='unknown';
  rows[8].session_id='other';
  rows[9].processing_state='processing';
  const round={sessionId:rows[0].session_id,after:1,through:10,distance:100,tolerance:10,units:'imperial'};
  assert.equal(lastSequence(rows),11);
  assert.deepEqual(scoreTarget(round,rows,false),{short:1,within:3,long:1,missing:1,unconfirmed:2,scored:5});
  const metric={...round,units:'metric',distance:100,tolerance:5};
  assert.equal(scoreTarget(metric,[shot(2,95/0.9144),shot(3,105/0.9144)],false).within,2);
  const demo=shot(2,100,{record_kind:'synthetic'});
  assert.equal(scoreTarget(round,[demo],true).within,1);
  assert.equal(scoreTarget(round,[demo],false).scored,0);
});
test('yardage card excludes missing carry, gates small samples, and finds overlapping ranges', () => {
  const make=(club,values) => values.map((v,i) => shot(i+1,v,{club}));
  const rows=yardageRows([...make('7i',[125,130,135,140,165,null]),
    ...make('8i',[119,125,129,133,139]), ...make('pw',[75,80,83,86,90]), ...make('6i',[140])]);
  assert.deepEqual(rows.map(r => r.club),['7i','8i','pw','6i']);
  assert.deepEqual(rows[0],{club:'7i',count:5,range:{low:130,high:140,median:135,width:10}});
  assert.equal(rows.at(-1).range,null);
  assert.deepEqual(overlappingClubs(rows),[['7i','8i']]);
});
test('confirmation links only the named file and player, keeps retries idempotent and blocks conflicting players', async () => {
  const slots=new Map();
  const journal=new Journal({async read(k){return slots.get(k) ?? null;}, async write(k,v){slots.set(k,v);}});
  await journal.load();
  const first=shot(1,100), guest={uid:null,profileId:'',confirmedFile:first.source.filename};
  const alice={uid:'account',profileId:'alice',confirmedFile:first.source.filename};
  assert.equal((await journal.mergeCapture([first],()=>true,guest)).sync,undefined);
  assert.equal(await journal.mergeCapture([first],()=>true,{...alice,confirmedFile:'other.csv'}),null);
  assert.equal(await journal.mergeCapture([first],()=>false,alice),null);
  const linked=await journal.mergeCapture([first],()=>true,alice);
  assert.equal(linked.sync.bindings[first.session_id].profileId,'alice');
  assert.equal(pendingShots(linked,'account').length,1);
  assert.equal(await journal.mergeCapture([first],()=>true,alice),null);
  for (const player of [guest,{...alice,profileId:'bob'},{...alice,uid:'different'}]) {
    await assert.rejects(journal.mergeCapture([shot(2,110)],()=>true,player),/already linked/);
  }
  const second=await journal.mergeCapture([shot(2,111)],()=>true,alice);
  assert.equal(second.shots.length,2);
  assert.equal(second.shots[1].carry_yards,111);
});
test('spoken results use display units and only announce confirmed final shots', () => {
  assert.equal(shotCue(shot(1,100),'metric'),'Modeled carry, 91 meters.');
  assert.equal(shotCue(shot(1,null,{ball_speed_mph:100}),'imperial'),'Ball speed, 100 miles per hour.');
  assert.equal(shotCue(shot(1,null,{ball_speed_mph:null}),'imperial'),'Shot recorded.');
  assert.equal(shotCue(shot(1,100,{record_kind:'unknown'}),'imperial'),'');
});
