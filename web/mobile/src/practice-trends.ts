import { summary, uniqueShots, type Metric, type Shot } from '../../src/domain.ts';
import { belongsToAccount, type Binding } from './sync-queue.ts';

export const minimumSamples = 5;
export const startBandDegrees = 2;
export type TrendSource = 'cloud' | 'pi' | 'demo';

// Unlinked sessions may be shared by several golfers using the same phone.
export function trendGroups(shots: Shot[], source: TrendSource, profileId: string, uid?: string,
  bindings: Record<string, Binding> = {}) {
  const groups = new Map<string, Shot[]>();
  const scoped = shots.filter(shot => shot.profile_id === profileId);
  for (const shot of uniqueShots(scoped)) {
    if (shot.processing_state !== 'final') continue;
    if (shot.record_kind !== (source === 'demo' ? 'synthetic' : 'real')) continue;
    if (source === 'cloud' && !uid) continue;
    let key = profileId;
    if (source === 'pi') {
      if (shot.source.kind !== 'legacy_csv') continue;
      const binding = bindings[shot.session_id];
      if (binding && !belongsToAccount(binding, uid)) continue;
      key = binding ? 'golfer/' + binding.profileId : 'session/' + shot.session_id;
    }
    const rows = groups.get(key);
    if (rows) rows.push(shot);
    else groups.set(key, [shot]);
  }
  return groups;
}

function distribution(values: number[]) {
  values.sort((a, b) => a - b);
  const quantile = (p: number) => {
    const i = p * (values.length - 1);
    const low = Math.floor(i);
    return values[low] + (values[Math.ceil(i)] - values[low]) * (i - low);
  };
  if (values.length < minimumSamples) return {count: values.length, range: null};
  const low = quantile(0.25);
  const high = quantile(0.75);
  return {count: values.length, range: {low, high, median: quantile(0.5), width: high - low}};
}

export function describeSet(shots: Shot[]) {
  const readings = (key: 'horizontal_launch_angle_deg' | 'ball_speed_mph' | 'carry_yards') =>
    shots.map(shot => shot[key]).filter((n): n is number => n !== null && Number.isFinite(n));
  const angles = readings('horizontal_launch_angle_deg');
  const left = angles.filter(n => n < -startBandDegrees).length;
  const right = angles.filter(n => n > startBandDegrees).length;
  const center = angles.length - left - right;
  return {
    size: shots.length,
    direction: {count: angles.length, left, right, center},
    speed: distribution(readings('ball_speed_mph')),
    carry: distribution(readings('carry_yards'))
  };
}

function sessionTime(shots: Shot[]) {
  const first = shots[0];
  const filename = first.source.filename?.match(/^session_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})\.csv$/);
  if (filename) {
    const [,y,m,d,h,min,s] = filename;
    return {clock: first.device_id, time: y+'-'+m+'-'+d+'T'+h+':'+min+':'+s};
  }
  let earliest = Infinity;
  for (const shot of shots) if (shot.timestamp) earliest = Math.min(earliest, Date.parse(shot.timestamp));
  return Number.isFinite(earliest) ? {clock: 'UTC/', time: new Date(earliest).toISOString()} : {clock: '', time: ''};
}

export function clubSessions(shots: Shot[], club: string) {
  const sets = new Map<string, Shot[]>();
  for (const shot of shots) {
    if (shot.club !== club) continue;
    const rows = sets.get(shot.session_id);
    if (rows) rows.push(shot);
    else sets.set(shot.session_id, [shot]);
  }
  return [...sets].map(([id, rows]) => ({id, ...sessionTime(rows), stats: describeSet(rows),
    averages: summary(rows, rows[0].profile_id, rows[0].record_kind === 'synthetic').metrics}))
    .sort((a, b) => b.time.localeCompare(a.time) || a.id.localeCompare(b.id));
}

export function previousSet(sets: ReturnType<typeof clubSessions>, current: (typeof sets)[number]) {
  return sets.find(set => set.clock === current.clock && set.time && set.time < current.time);
}

export function averageChange(metric: Metric, selected: number | null, baseline: number | null) {
  if (selected === null || baseline === null) return null;
  const delta = selected - baseline;
  const percent = metric.endsWith('_deg') || baseline === 0 ? null : 100 * delta / baseline;
  return {delta, percent};
}
