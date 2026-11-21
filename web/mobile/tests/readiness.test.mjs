import assert from 'node:assert/strict';
import {test} from 'node:test';
import {ballStatus,watchReadiness} from '../src/readiness.ts';

test('ball readiness follows kiosk state even when the previous shot had measurements', () => {
  for (const [state,label] of Object.entries({
    READY:'Ready', SWINGTEST:'Ready', SEARCHING:'Looking for Ball', BALL:'Looking for Ball',
    WAIT:'Get Set', CAPTURING:'Recording', MEASURING:'Measuring', CHECKING:'Checking',
    SLEEPING:'Asleep', WAKING:'Waking up', STARTING:'Starting', OTHER:'Status unavailable',
  })) {
    assert.equal(ballStatus(JSON.stringify({state,metrics:{carry:120}})), label);
  }
  assert.equal(ballStatus({ready:true}), 'Status unavailable');
});

test('stale readiness expires and late responses cannot revive it after disconnect', async t => {
  t.mock.timers.enable({apis:['setTimeout']});
  const labels=[];
  let finish;
  const stop=watchReadiness(() => new Promise(resolve => {finish=resolve;}), label => labels.push(label));
  finish('Ready');
  await Promise.resolve();
  t.mock.timers.tick(750);
  t.mock.timers.tick(2500);
  assert.deepEqual(labels,['Ready',null]);
  stop();
  finish('Ready');
  await Promise.resolve();
  t.mock.timers.tick(5000);
  assert.deepEqual(labels,['Ready',null]);
});

test('polling recovers after the monitor drops off Wi-Fi', async t => {
  t.mock.timers.enable({apis:['setTimeout']});
  const labels=[];
  let reads=0;
  const stop=watchReadiness(async () => {
    if (++reads === 1) throw Error('offline');
    return 'Looking for Ball';
  }, label => labels.push(label));
  await Promise.resolve();
  t.mock.timers.tick(2000);
  await Promise.resolve();
  stop();
  assert.deepEqual(labels,[null,'Looking for Ball']);
});
