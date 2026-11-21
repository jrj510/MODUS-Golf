import assert from 'node:assert/strict';
import {test} from 'node:test';
import {commandConfirmed, commandPath, monitorState} from '../src/monitor-remote.ts';

const sample={state:'READY',shot:2,rev:7,metrics:{},club:'7i',light:'day',view:{can_zoom:true,zoomed:false}};

test('remote controls require kiosk telemetry and display support is explicitly advertised', () => {
  assert.equal(monitorState({state:'unavailable'}),null);
  assert.equal(monitorState({state:'READY'}).kiosk,false);
  const state=monitorState(JSON.stringify(sample));
  assert.equal(state.kiosk,true);
  assert.equal(state.screenControl,false);
  assert.equal(monitorState({...sample,view:{can_zoom:false},club:'unknown'}).zoom,null);
  assert.equal(monitorState({...sample,club:'unknown'}).club,null);
});

test('monitor commands use kiosk settings and require the requested value on readback', () => {
  const state=monitorState(sample);
  for (const [command,path,confirmed] of [
    [{kind:'club',value:'7i'},'/club?c=7i',true],
    [{kind:'club',value:'8i'},'/club?c=8i',false],
    [{kind:'light',value:'night'},'/light?mode=night',false],
    [{kind:'zoom',value:true},'/view?zoom=1',false],
    [{kind:'sleep'},'/sleep',false], [{kind:'wake'},'/wake',true]
  ]) {
    assert.equal(commandPath(command),path);
    assert.equal(commandConfirmed(state,command,''),confirmed);
  }
  const asleep=monitorState({...sample,state:'SLEEPING'});
  assert.equal(commandConfirmed(asleep,{kind:'sleep'},''),true);
  assert.equal(commandConfirmed(asleep,{kind:'wake'},''),false);
  assert.equal(commandConfirmed(monitorState({...sample,state:'WAKING'}),{kind:'wake'},''),false);
});

test('a physical display change is confirmed only by the matching kiosk receipt', () => {
  const state=monitorState({...sample,display:{version:1,applied:'d100'}});
  const command={kind:'screen',value:'range'};
  assert.equal(commandPath(command),'/display/range');
  assert.equal(state.screenControl,true);
  assert.equal(commandConfirmed(state,command,'d101'),false);
  assert.equal(commandConfirmed(state,command,'d100'),true);
});
