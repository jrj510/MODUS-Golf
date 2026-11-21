import { useState, type ReactNode } from 'react';
import { metricKeys, metricLabels, unitFor, displayMetric, clubName, sourceName, shotTime, flightPoints, directionWasApplied, type Shot, type Units, type Metric } from './domain';
export function Icon({ name }: { name: string }) {
  const paths: Record<string, ReactNode> = {
    practice: <><path d="M5 20V4m0 0c5-4 9 4 14 0v9c-5 4-9-4-14 0"/><path d="M2 21h8"/></>,
    sessions: <><rect x="4" y="4" width="16" height="17" rx="3"/><path d="M8 2v4m8-4v4M4 10h16m-12 4h3m2 0h3m-8 3h3"/></>,
    bag: <><path d="M7 9h11l-1 12H8L7 9Zm3 0V3l5-1v3l-5 1m5 3V5l5-1v3l-5 1"/><path d="M7 12H4v6h4"/></>,
    settings: <><circle cx="12" cy="12" r="4"/><path d="m10 2 4 0 1 3 3 2 3 0 1 4-2 2-1 3 1 3-3 2-3-1-3 0-2 1-3-3 0-3-2-2 1-4 3-1 2-3Z"/></>,
    arrow: <path d="M5 12h14m-5-5 5 5-5 5"/>,
    cloud: <path d="M5 18a5 5 0 1 1 1-10 7 7 0 0 1 13 2 4 4 0 0 1 0 8H5Z"/>,
  };
  return <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">{paths[name] ?? paths.arrow}</svg>;
}
export function Empty({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <div className="empty"><div className="empty-icon"><Icon name="practice"/></div><h3>{title}</h3><p>{children}</p>{action}</div>;
}
export function MetricCards({ shot, units, primary = false }: { shot?: Shot; units: Units; primary?: boolean }) {
  const keys: Metric[] = primary ? ['carry_yards', 'ball_speed_mph', 'vertical_launch_angle_deg'] : metricKeys;
  return <div className={`metric-grid ${primary ? 'primary-metrics' : ''}`}>{keys.map(key => <article className={`metric-card ${key === 'carry_yards' ? 'carry' : ''}`} key={key}>
    <span>{metricLabels[key]}</span><div><strong>{displayMetric(shot?.[key], key, units)}</strong><small>{unitFor(key, units)}</small></div>
    <p>{key === 'carry_yards' ? 'Estimated · Pi flight model' : key === 'vertical_launch_angle_deg' && shot?.vertical_launch_angle_deg == null ? 'Measured angle unavailable' : shot?.[key] == null ? 'Not available' : key === 'smash_factor' ? 'Calculated · same-shot ratio' : 'Reported shot metric'}</p>
  </article>)}</div>;
}
export function MoreMetrics({ shot, units }: { shot?: Shot; units: Units }) {
  const spin = shot?.spin_rpm ?? shot?.model_inputs.spin_rpm;
  const number = (value: number | null | undefined, digits = 1) => value == null || !Number.isFinite(value) ? '—' : value.toFixed(digits);
  return <details className="more-metrics"><summary>More metrics <span>Club speed · smash · direction · spin · club path · apex</span></summary><div className="secondary-metrics">
    {(['club_speed_mph','smash_factor','horizontal_launch_angle_deg'] as Metric[]).map(key => <div key={key}><span>{metricLabels[key]}</span><strong>{displayMetric(shot?.[key],key,units)} <small>{unitFor(key,units)}</small></strong><p>{key === 'smash_factor' ? 'Calculated ratio' : 'Reported value'}</p></div>)}
    <div><span>Spin rate</span><strong>{number(spin,0)} <small>rpm</small></strong><p>{shot?.spin_rpm != null ? 'Experimental · not a validated spin measurement' : 'Estimated model input · not measured'}</p></div>
    <div><span>Club path</span><strong>{number(shot?.club_path_deg)} <small>°</small></strong><p>{shot?.club_path_deg == null ? 'Unavailable · not inferred from launch direction' : 'Experimental · reported value'}</p></div>
    <div><span>Apex</span><strong>{number(shot?.source.apex_yards == null ? null : shot.source.apex_yards * (units === 'metric' ? .9144 : 1))} <small>{unitFor('carry_yards',units)}</small></strong><p>Estimated · supplied model result</p></div>
  </div></details>;
}
export function Trajectory({ shot, shots = [], units = 'imperial' }: { shot?: Shot; shots?: Shot[]; units?: Units }) {
  const [view, setView] = useState<'range' | 'side'>('range');
  const points = flightPoints(shot);
  if (!shot || !points) return <div className="trajectory-placeholder"><Icon name="practice"/><div><h3>No trajectory supplied for this shot</h3><p>CSV exports contain metrics only. A Pi-computed path will appear here when your backend supplies it.</p></div></div>;
  const others = shots.filter(item => item.shot_id !== shot.shot_id && item.session_id === shot.session_id && item.club === shot.club && flightPoints(item)).slice(-30);
  const all = [shot,...others];
  const allPoints = all.flatMap(item => flightPoints(item)!);
  const forward = Math.max(25, ...allPoints.map(p => p[0])) * 1.12;
  const height = Math.max(5, ...allPoints.map(p => p[1])) * 1.2;
  const lateral = Math.max(20, ...allPoints.map(p => Math.abs(p[2]))) * 1.15;
  const factor = units === 'metric' ? .9144 : 1;
  const distanceUnit = units === 'metric' ? 'm' : 'yd';
  const rangePath = (item: Shot) => flightPoints(item)!.map(p => `${200 + (directionWasApplied(item) ? p[2] : 0) / lateral * 145},${330 - p[0] / forward * 290}`).join(' ');
  const sidePath = (item: Shot) => flightPoints(item)!.map(p => `${45+p[0]/forward*400},${225-p[1]/height*180}`).join(' ');
  const end = points.at(-1)!;
  const title = shot.record_kind === 'synthetic' ? 'Synthetic Pi-model fixture' : 'Pi-computed flight';
  return <div className="flight-display"><div className="flight-caption"><span>{title} · estimated</span><small>{directionWasApplied(shot) ? 'Model uses supplied launch direction' : 'Direction assumed · overhead is distance-only'}</small></div>
    <div className="plot-tabs" role="group" aria-label="Flight view"><button aria-pressed={view === 'range'} onClick={() => setView('range')}>Range</button><button aria-pressed={view === 'side'} onClick={() => setView('side')}>Side view</button></div>
    <div className="flight-plots" data-view={view}><div className="range-plot"><h3>Range <small>Modeled landing positions</small></h3><svg viewBox="0 0 400 365" role="img" aria-label="Estimated overhead range from supplied trajectory points">
      {[1,2,3,4].map(i => <g key={i}><path d={`M25 ${330-i*290/4}H375`} className="plot-grid"/><text x="28" y={325-i*290/4}>{(forward*i/4*factor).toFixed(0)} {distanceUnit}</text></g>)}<path d="M200 35V335" className="target-line"/>
      {others.map(item => <polyline key={item.shot_id} points={rangePath(item)} className="older-flight"/>)}<polyline points={rangePath(shot)} className="selected-flight"/>
      <circle cx={200+(directionWasApplied(shot) ? end[2] : 0)/lateral*145} cy={330-end[0]/forward*290} r="6" className="landing-marker"/>
      <text x="200" y="355" textAnchor="middle">{directionWasApplied(shot) ? 'LEFT ← LATERAL POSITION → RIGHT' : 'DISTANCE ONLY · NOT MEASURED DISPERSION'}</text></svg></div>
    <div className="side-plot"><h3>Side profile <small>{distanceUnit} forward / height</small></h3><svg viewBox="0 0 480 265" role="img" aria-label="Estimated side profile from supplied Pi trajectory points">
      {[1,2,3].map(i => <g key={i}><path d={`M45 ${225-i*180/3}H455`} className="plot-grid"/><text x="5" y={229-i*180/3}>{(height*i/3*factor).toFixed(0)}</text></g>)}<path d="M45 225H455" className="target-line"/>
      {others.map(item => <polyline key={item.shot_id} points={sidePath(item)} className="older-flight"/>)}<polyline points={sidePath(shot)} className="selected-flight"/>
      {[1,2,3,4].map(i => <text key={i} x={45+i*400/4} y="250" textAnchor="middle">{(forward*i/4*factor).toFixed(0)} {distanceUnit}</text>)}</svg>
      <div className="flight-readout"><strong>{displayMetric(shot.carry_yards,'carry_yards',units)} <small>{distanceUnit} carry · modeled</small></strong><span>{shot.quality_flags.includes('launch_assumed') ? 'Launch assumed' : 'Reported launch'} · spin {shot.spin_rpm == null ? 'assumed' : 'experimental'}</span></div></div></div>
    <small>Yellow: selected shot. Muted: same-session, same-club paths. Modeled flight is not an observed camera track; launch direction alone does not establish draw/fade or measured dispersion.</small></div>;
}
export function ShotList({ shots, units, onSelect, totalCount = shots.length, selectedId }: { shots: Shot[]; units: Units; onSelect: (shot: Shot) => void; totalCount?: number; selectedId?: string | null }) {
  const [page, setPage] = useState(1);
  const shown = [...shots].reverse().slice(0, page * 25);
  return <><div className="table-scroll"><table><thead><tr><th>Shot / club</th><th>Carry <small>{units === 'metric' ? 'm' : 'yd'} · modeled</small></th><th>Ball speed <small>{units === 'metric' ? 'km/h' : 'mph'}</small></th><th>Source</th><th>Details</th></tr></thead><tbody>{shown.map(shot => <tr key={shot.shot_id} className={selectedId === shot.shot_id ? "selected-row" : undefined}><td><strong>{clubName(shot.club)}</strong><small>#{shot.sequence_number} · {shotTime(shot)}</small></td><td>{displayMetric(shot.carry_yards, 'carry_yards', units)}</td><td>{displayMetric(shot.ball_speed_mph, 'ball_speed_mph', units)}</td><td><span className="tag">{sourceName(shot)}</span><small>{shot.record_kind === 'unknown' ? 'Unconfirmed · excluded from stats' : shot.processing_state}</small></td><td><button className="icon-button" aria-label={`Open shot ${shot.sequence_number} ${clubName(shot.club)}`} onClick={() => onSelect(shot)}><Icon name="arrow"/></button></td></tr>)}</tbody></table></div>{shown.length < shots.length && <button className="load-more" onClick={() => setPage(page + 1)}>Show 25 more · {shots.length - shown.length} remaining</button>}<small>Showing {shown.length} of {totalCount} records. Statistics include all eligible records in this filter, across every display page.</small></>;
}
export function download(name: string, content: string, type = 'application/json') {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement('a'); a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

