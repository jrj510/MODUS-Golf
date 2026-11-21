import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {decodeHistoryPage,historyPageSize} from '../src/cloud-history.ts';

const [shot]=JSON.parse(readFileSync(new URL('../../MODUS_Golf_Firebase_AI_Starter/contracts/fixtures/demo_shots.json',import.meta.url),'utf8'));
const snapshot=index => ({id:'shot_'+index,path:'users/owner/shots/shot_'+index,
  data:{...shot,shot_id:'shot_'+index,sequence_number:index+1},metadata:{fromCache:false}});

test('cloud pages are bounded and advance beyond invalid rows without discarding good records',() => {
  const rows=Array.from({length:historyPageSize+1},(_,i) => snapshot(i));
  rows[historyPageSize-1].data={invalid:true};
  const page=decodeHistoryPage(rows);
  assert.equal(page.items.length,historyPageSize-1);
  assert.equal(page.skipped,1);
  assert.equal(page.nextCursor,rows[historyPageSize-1].path);
  assert.equal(page.cached,false);
  assert.ok(!page.items.some(item => item.shot_id === rows[historyPageSize].id));
  assert.equal(decodeHistoryPage(rows.slice(0,2)).nextCursor,null);
});

test('empty and cached cloud pages cannot claim complete server history',() => {
  assert.equal(decodeHistoryPage([]).cached,true);
  const row=snapshot(0);
  row.metadata.fromCache=true;
  assert.equal(decodeHistoryPage([row]).cached,true);
});
