import { mergeRevision, summarizeShots, CSV_COLUMNS, CSV_EXTRA_COLUMNS, CSV_EXTENDED_COLUMNS, type Shot } from '../MODUS_Golf_Firebase_AI_Starter/app-core/shot.mjs';
export type { Shot };
export type Units = 'imperial' | 'metric';
export type Metric = 'ball_speed_mph' | 'club_speed_mph' | 'smash_factor' | 'vertical_launch_angle_deg' | 'horizontal_launch_angle_deg' | 'carry_yards';
export const metricLabels: Record<Metric, string> = { ball_speed_mph: 'Ball speed', club_speed_mph: 'Club speed', smash_factor: 'Smash factor', vertical_launch_angle_deg: 'Vertical launch', horizontal_launch_angle_deg: 'Horizontal launch', carry_yards: 'Modeled carry' };
export const metricKeys = Object.keys(metricLabels) as Metric[];
export function unitFor(key: Metric, units: Units) {
  return key.endsWith('_mph') ? units === 'metric' ? 'km/h' : 'mph' : key === 'carry_yards' ? units === 'metric' ? 'm' : 'yd' : key.endsWith('_deg') ? '°' : 'ratio';
}
export function converted(value: number, key: Metric, units: Units) {
  return units === 'imperial' ? value : key.endsWith('_mph') ? value * 1.609344 : key === 'carry_yards' ? value * 0.9144 : value;
}
export function displayMetric(value: number | null | undefined, key: Metric, units: Units) {
  return value == null || !Number.isFinite(value) ? '—' : converted(value, key, units).toFixed(key === 'smash_factor' ? 2 : 1);
}
export function selectedShot(shots: Shot[], selectedId: string | null): Shot | undefined {
  return (selectedId ? shots.find(shot => shot.shot_id === selectedId) : undefined) ?? shots.at(-1);
}
export function flightPoints(shot?: Shot): [number, number, number][] | null {
  if (!shot || !shot.trajectory || shot.trajectory.length < 2) return null;
  if (shot.source.kind !== 'pi_live' && !(shot.source.kind === 'synthetic_demo' && shot.record_kind === 'synthetic')) return null;
  return shot.trajectory;
}
export function directionWasApplied(shot: Shot) {
  return !shot.quality_flags.includes('flight_direction_assumed') && shot.model_inputs.horizontal_launch_angle_deg !== null;
}
export function clubName(club: string) {
  return club === 'driver' ? 'Driver' : /^\d+i$/.test(club) ? `${club.slice(0, -1)} iron` : /^\d+$/.test(club) ? `${club}° wedge` : club.toUpperCase();
}
export function sourceName(shot: Shot) {
  return shot.record_kind === 'synthetic' ? 'Synthetic demo' : shot.source.kind === 'legacy_csv' ? 'Imported CSV' : shot.source.kind === 'pi_live' ? 'Pi record' : 'Unconfirmed source';
}
export function shotDate(shot: Shot): string {
  if (shot.timestamp) return shot.timestamp.slice(0, 10);
  const match = shot.source.filename?.match(/^session_(\d{4})(\d{2})(\d{2})_/);
  return match ? `${match[1]}-${match[2]}-${match[3]}` : '';
}
export function shotTime(shot: Shot) {
  return shot.timestamp ? new Date(shot.timestamp).toLocaleString() : `${shotDate(shot) || 'Date unknown'} ${shot.source.local_log_time ?? ''} (local log)`;
}
export function uniqueShots(shots: Shot[]): Shot[] {
  const rows = new Map<string, Shot>();
  for (const shot of shots) rows.set(shot.shot_id, mergeRevision(rows.get(shot.shot_id), shot));
  return [...rows.values()].sort((a, b) => {
    const first = `${a.timestamp ?? `${shotDate(a)}T${a.source.local_log_time ?? ''}`}|${a.session_id}`;
    const second = `${b.timestamp ?? `${shotDate(b)}T${b.source.local_log_time ?? ''}`}|${b.session_id}`;
    return first.localeCompare(second) || a.sequence_number - b.sequence_number;
  });
}
export function filterShots(shots: Shot[], filters: { profileId: string; club?: string; sessionId?: string; date?: string }) {
  return uniqueShots(shots).filter(shot => shot.profile_id === filters.profileId && (!filters.club || shot.club === filters.club) &&
    (!filters.sessionId || shot.session_id === filters.sessionId) && (!filters.date || shotDate(shot) === filters.date));
}
export function summary(shots: Shot[], profileId: string, allowSynthetic = false) {
  return summarizeShots(shots, { profileId, allowSynthetic });
}
export function sessionLabel(shots: Shot[], id: string) {
  const first = shots.find(shot => shot.session_id === id);
  return first ? `${shotDate(first) || 'Undated'} · ${first.source.filename?.slice(17, 23) || id.slice(-6)}` : id.slice(-8);
}
export function historyCsv(shots: Shot[]) {
  const quote = (value: unknown) => { const text = value == null ? '' : String(value); return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text; };
  // CSV preserves the kiosk contract and its model-vs-measured distinctions.
  const extended=shots.some(shot=>shot.source.csv_format==='modus_csv_34');
  const rows = shots.map(s => [s.sequence_number, s.source.local_log_time ?? '', s.club,
    s.ball_speed_mph, s.club_speed_mph, s.smash_factor,
    s.vertical_launch_angle_deg ?? s.model_inputs.vertical_launch_angle_deg,
    s.vertical_launch_angle_deg == null ? 'no' : 'yes', s.model_inputs.spin_rpm,
    s.carry_yards, s.source.apex_yards ?? null, s.source.ti_radar ?? '',
    s.source.ball_speed_raw_mph ?? null, s.horizontal_launch_angle_deg,
    ...(extended?CSV_EXTRA_COLUMNS.map(key=>s.source.csv_extra?.[key] ?? ''):[]),
    s.shot_id, s.session_id, s.device_id, s.profile_id, s.revision, s.record_kind,
    s.processing_state, s.source.kind, s.source.filename ?? '', s.source.timezone ?? '',
    s.timestamp, s.quality_flags.join(';')]);
  const provenance = ['shot_id','session_id','device_id','profile_id','revision','record_kind','processing_state','source_kind','source_filename','source_timezone','timestamp_utc','quality_flags'];
  return [[...(extended?CSV_EXTENDED_COLUMNS:CSV_COLUMNS), ...provenance].join(','), ...rows.map(row => row.map(quote).join(','))].join('\n') + '\n';
}
export function validateCloudShot(record: Record<string, unknown>): Shot {
  const fail = () => { throw new Error('A cloud shot does not match the MODUS shot contract. No partial dataset was shown.'); };
  // Standard Firestore cannot persist an array directly inside an array.
  // Its storage format uses named point maps; the Pi/API contract stays tuples.
  if (Array.isArray(record.trajectory)) {
    record = { ...record, trajectory: record.trajectory.map(point => {
      if (Array.isArray(point)) return point;
      if (!point || typeof point !== 'object' || Object.keys(point).sort().join(',') !== 'forward_yards,height_yards,right_yards') return fail();
      return [point.forward_yards, point.height_yards, point.right_yards];
    }) };
  }
  if (record.schema_version !== 1 || record.carry_kind !== 'model') fail();
  for (const key of ['shot_id', 'session_id', 'device_id', 'profile_id', 'club']) if (typeof record[key] !== 'string' || !record[key]) fail();
  if (record.id && record.id !== record.shot_id) fail();
  if (!Number.isInteger(record.revision) || Number(record.revision) < 1 || !Number.isInteger(record.sequence_number) || Number(record.sequence_number) < 1) fail();
  if (!['real', 'unknown', 'synthetic'].includes(String(record.record_kind)) || !['final', 'processing', 'failed'].includes(String(record.processing_state))) fail();
  for (const key of [...metricKeys, 'spin_rpm', 'club_path_deg']) if (record[key] !== null && (typeof record[key] !== 'number' || !Number.isFinite(record[key]))) fail();
  if (record.timestamp !== null && (typeof record.timestamp !== 'string' || !Number.isFinite(Date.parse(record.timestamp)))) fail();
  if (!record.source || typeof record.source !== 'object' || !['legacy_csv', 'pi_live', 'synthetic_demo'].includes(String((record.source as Record<string, unknown>).kind))) fail();
  if (!Array.isArray(record.quality_flags) || record.quality_flags.some(flag => typeof flag !== 'string')) fail();
  if (!record.model_inputs || typeof record.model_inputs !== 'object') fail();
  for (const value of ['vertical_launch_angle_deg','horizontal_launch_angle_deg','spin_rpm']) {
    const item = (record.model_inputs as Record<string, unknown>)[value];
    if (item !== null && (typeof item !== 'number' || !Number.isFinite(item))) fail();
  }
  const source = record.source as Record<string, unknown>;
  if(source.csv_format!==undefined || source.csv_extra!==undefined) {
    if(source.csv_format!=='modus_csv_34' || !source.csv_extra || typeof source.csv_extra!=='object' || Array.isArray(source.csv_extra)) fail();
    const extra=source.csv_extra as Record<string,unknown>;
    if(Object.keys(extra).length!==CSV_EXTRA_COLUMNS.length || CSV_EXTRA_COLUMNS.some(key=>
      !Object.hasOwn(extra,key) || typeof extra[key]!=='string' || (extra[key] as string).length>1000)) fail();
  }
  for (const key of ['filename','local_log_time','ti_radar']) if (source[key] !== undefined && typeof source[key] !== 'string') fail();
  if (source.timezone !== undefined && source.timezone !== null && typeof source.timezone !== 'string') fail();
  for (const key of ['apex_yards','ball_speed_raw_mph']) if (source[key] !== undefined && source[key] !== null && (typeof source[key] !== 'number' || !Number.isFinite(source[key]))) fail();
  if (String(record.profile_id).length > 120 || !/^[A-Za-z0-9_-]+$/.test(String(record.profile_id))) fail();
  if (record.trajectory !== null && (!Array.isArray(record.trajectory) || record.trajectory.length > 1000 || record.trajectory.some(p => !Array.isArray(p) || p.length !== 3 || p.some(v => typeof v !== 'number' || !Number.isFinite(v))))) fail();
  return record as unknown as Shot;
}
