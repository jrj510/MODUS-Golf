import assert from 'node:assert/strict';
import {test} from 'node:test';
import {averageChange, clubSessions, describeSet, previousSet, trendGroups} from '../src/practice-trends.ts';
import {displayMetric} from '../../src/domain.ts';
import fixtures from '../../MODUS_Golf_Firebase_AI_Starter/contracts/fixtures/demo_shots.json' with {type:'json'};

function shot(id, overrides = {}) {
  return {...fixtures[0], shot_id:id, record_kind:'real', profile_id:'local', session_id:'first',
    source:{...fixtures[0].source,kind:'legacy_csv'}, ...overrides};
}
test('phone trends isolate linked golfers, projects, accounts and each unlinked session', () => {
  const bindings = {a:{uid:'owner',profileId:'alice'}, b:{uid:'owner',profileId:'bob'},
    c:{uid:'other',profileId:'alice'}, d:{uid:'owner',profileId:'alice',projectId:'separate'}};
  const shots = ['a','b','c','d','e','f'].map(id => shot(id,{session_id:id}));
  const groups = trendGroups(shots,'pi','local','owner',bindings);
  assert.deepEqual([...groups.keys()],['golfer/alice','golfer/bob','session/e','session/f']);
  assert.deepEqual([...trendGroups(shots,'pi','local',undefined,bindings).keys()],['session/e','session/f']);
});
test('use only the final eligible revision and selected golfer and source', () => {
  const a = shot('a');
  const data = [a, {...a, revision:2, processing_state:'failed'}, shot('b'), shot('b'),
    shot('c',{profile_id:'guest'}),shot('d',{record_kind:'synthetic'}),shot('e',{record_kind:'unknown'})];
  assert.deepEqual(trendGroups(data,'cloud','local','owner').get('local').map(s => s.shot_id),['b']);
  assert.equal(trendGroups(data,'cloud','local').size,0);
  assert.deepEqual(trendGroups(data,'demo','local').get('local').map(s => s.shot_id),['d']);
});
test('measured zero and band edges count, missing direction never inherits the model default', () => {
  const rows = [null, -3, -2, 0, 2, 3].map((angle,i) => shot(String(i), {
    horizontal_launch_angle_deg:angle, ball_speed_mph:[50,51,52,53,150,null][i], carry_yards:i < 4 ? 100 : null
  }));
  const {direction,speed,carry} = describeSet(rows);
  assert.deepEqual(direction,{count:5,left:1,right:1,center:3});
  assert.deepEqual(speed,{count:5,range:{low:51,median:52,high:53,width:2}});
  assert.equal(displayMetric(speed.range.median,'ball_speed_mph','metric'),'83.7');
  assert.deepEqual(carry,{count:4,range:null});
});
test('compare only the same club in an earlier dated set on a comparable clock', () => {
  const set = (id, filename, extra={}) => shot(id,{session_id:id,source:{kind:'legacy_csv',filename},...extra});
  const sets = clubSessions([set('older','session_20261101_095000.csv'), set('undated',undefined),
    set('latest','session_20261101_141000.csv'),set('other','session_20261101_135000.csv',{club:'7i'}),
    set('different_clock','session_20261101_130000.csv',{device_id:'second_monitor'})], 'driver');
  assert.equal(sets[0].id,'latest');
  assert.equal(previousSet(sets,sets[0]).id,'older');
  assert.equal(previousSet(sets,sets.at(-1)),undefined);
});

test('session percentage uses the baseline mean, with independent reading counts', () => {
  const shots = [shot('a',{ball_speed_mph:100}),shot('b',{ball_speed_mph:null}),
    shot('c',{session_id:'second',ball_speed_mph:108}),shot('d',{session_id:'second',ball_speed_mph:112})];
  const sets = clubSessions(shots,'driver');
  const a = sets.find(s=>s.id==='first').averages.ball_speed_mph;
  const b = sets.find(s=>s.id==='second').averages.ball_speed_mph;
  assert.deepEqual([a.n,a.mean,b.n,b.mean],[1,100,2,110]);
  assert.deepEqual(averageChange('ball_speed_mph',b.mean,a.mean),{delta:10,percent:10});
  assert.equal(averageChange('carry_yards',90,120).percent,-25);
  assert.equal(averageChange('smash_factor',1.4,1.4).percent,0);
});
test('angle changes remain meaningful across zero and missing baselines have no percentage', () => {
  assert.deepEqual(averageChange('horizontal_launch_angle_deg',2,-3),{delta:5,percent:null});
  assert.deepEqual(averageChange('carry_yards',30,0),{delta:30,percent:null});
  assert.equal(averageChange('ball_speed_mph',null,10),null);
});
