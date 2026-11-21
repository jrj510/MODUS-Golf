import { useMemo, useState } from 'react';
import { clubName, displayMetric, metricKeys, metricLabels, unitFor, type Shot, type Units } from '../../src/domain';
import { averageChange, clubSessions, minimumSamples, previousSet, startBandDegrees, trendGroups, type TrendSource } from './practice-trends';
import type { LocalState } from './journal';

type Props = {
  shots: Shot[]; source: TrendSource; profileId: string; uid?: string; local: LocalState | null;
  profiles: {id: string; display_name: string}[]; units: Units; initialClub: string; initialSession?: string; clubLabels: Record<string, string>;
};
type Session = ReturnType<typeof clubSessions>[number];

function sessionName(session: Session) {
  return session.time ? session.time.slice(0,19).replace('T',' · ') + (session.clock === 'UTC/' ? ' UTC' : '') :
    'Undated session · ' + session.id.slice(-6);
}

function SessionAverages({current, baseline, units}: {current: Session; baseline?: Session; units: Units}) {
  return <section className="panel"><h2>Session averages</h2>
    <p>Each average uses the available readings for that metric. Small samples can move the average substantially.</p>
    <div className="table-scroll"><table className="session-averages">
      <thead><tr><th>Metric</th>{baseline && <th>Baseline</th>}<th>Selected</th>{baseline && <th>Change</th>}</tr></thead>
      <tbody>{metricKeys.map(key => {
        const value = current.averages[key];
        const prior = baseline?.averages[key];
        const diff = averageChange(key, value.mean, prior?.mean ?? null);
        let change = '—';
        if (diff) {
          if (key.endsWith('_deg')) {
            change = Math.abs(diff.delta) < 0.05 ? '≈ 0°' : (diff.delta > 0 ? '+' : '−') + Math.abs(diff.delta).toFixed(1) + '°';
          } else if (diff.percent !== null) {
            const magnitude = Math.abs(diff.percent);
            change = magnitude < 1e-10 ? '0%' : (diff.percent > 0 ? 'Up ' : 'Down ') + (magnitude < 0.1 ? '<0.1' : magnitude.toFixed(1)) + '%';
          } else change = 'Zero baseline';
        }
        return <tr key={key}><th scope="row">{metricLabels[key]}<small>{unitFor(key,units)}</small></th>
          {prior && <td>{displayMetric(prior.mean,key,units)}<small>n={prior.n}</small></td>}
          <td>{displayMetric(value.mean,key,units)}<small>n={value.n}</small></td>
          {baseline && <td>{change}</td>}</tr>;
      })}</tbody>
    </table></div>
    {baseline && <small>Percent change uses the baseline average. Launch changes are in degrees. Positive horizontal change means farther right.</small>}
  </section>;
}

function Consistency({metric, current, previous, units}: {
  metric: 'ball_speed_mph' | 'carry_yards'; current: Session; previous?: Session; units: Units;
}) {
  const speed = metric === 'ball_speed_mph';
  const key = speed ? 'speed' : 'carry';
  const {count, range} = current.stats[key];
  const prior = previous?.stats[key];
  const fmt = (n: number) => displayMetric(n, metric, units);
  const unit = unitFor(metric, units);
  return <section className="panel">
    <h2>{speed ? 'Ball speed' : 'Modeled carry'}</h2>
    {range ? <>
      <p className="trend-reading">{fmt(range.median)} <small>{unit} median</small></p>
      <p>Middle 50% of {count} shots with {speed ? 'speed' : 'carry'} data fell between <strong>{fmt(range.low)} and {fmt(range.high)} {unit}</strong>.</p>
      {prior?.range && <p>Middle-half spread went from {fmt(prior.range.width)} {unit} ({prior.count} shots) to {fmt(range.width)} {unit} ({count} shots). A smaller spread means more consistent {speed ? 'speed' : 'modeled distance'}.</p>}
    </> : <p>{count} of {minimumSamples} readings needed for a typical range.</p>}
  </section>;
}

export function PracticeTrends({shots, source, profileId, uid, local, profiles, units, initialClub, initialSession = '', clubLabels}: Props) {
  const groups = useMemo(() => trendGroups(shots, source, profileId, uid, local?.sync?.bindings),
    [shots, source, profileId, uid, local?.sync?.bindings]);
  const initialRows = [...groups].find(([,rows]) => rows.some(s => s.session_id === initialSession));
  const [groupChoice, chooseGroup] = useState(initialRows?.[0] ?? '');
  const [clubChoice, chooseClub] = useState(initialClub || initialRows?.[1].find(s => s.session_id === initialSession)?.club || '');
  const [sessionChoice, chooseSession] = useState(initialSession);
  const [baselineChoice, chooseBaseline] = useState('');
  const [goalChoice, chooseGoal] = useState('');
  const group = groups.has(groupChoice) ? groupChoice : [...groups.keys()].at(-1) ?? '';
  const rows = groups.get(group);
  const clubs = [...new Set(rows?.map(shot => shot.club))].sort();
  const club = clubs.includes(clubChoice) ? clubChoice : clubs[0];
  const sets = useMemo(() => rows && club ? clubSessions(rows, club) : [], [rows, club]);
  const current = sets.find(set => set.id === sessionChoice) ?? sets[0];
  const alternatives = sets.filter(set => set.id !== current?.id);
  const prior = alternatives.find(set => set.id === baselineChoice) ?? (current && previousSet(sets, current));
  const label = (set: Session) => {
    const name = source === 'pi' && local?.sessionDetails?.[set.id]?.name;
    return (name ? name + ' · ' : '') + sessionName(set);
  };
  function groupLabel(key: string) {
    if (key.startsWith('golfer/')) {
      const id = key.slice(7);
      return profiles.find(item => item.id === id)?.display_name ?? 'Linked golfer · ' + id.slice(-6);
    }
    const id = key.slice(8);
    return 'Unlinked · ' + (local?.sessionDetails?.[id]?.name || groups.get(key)?.[0].source.filename || id.slice(-6));
  }
  if (!current) return <section className="panel"><h2>Start a practice set</h2>
    <p>{source === 'pi' ? 'Confirm a physical session in Monitor, then hit five shots with one club at the same target.' :
      source === 'demo' ? 'Add sample shots in Practice to explore the feedback.' : 'Choose a golfer and a history page with confirmed shots.'}</p></section>;
  const d = current.stats.direction;
  const old = prior?.stats.direction;
  const hasDirection = d.count >= minimumSamples;
  const side = d.right > d.count / 2 ? 'right' : d.left > d.count / 2 ? 'left' : '';
  const distance = current.stats.carry.range;
  const speed = current.stats.speed.range;
  const band = '±' + startBandDegrees + '°';
  const goal = goalChoice || (hasDirection ? 'line' : distance ? 'carry' : speed ? 'speed' : 'line');
  let drill = 'Hit five shots with this club at one target to establish a baseline.';
  if (goal === 'line' && hasDirection) {
    drill = 'Pick a spot on your target line a few feet ahead of the ball. Hit five shots toward it and count how many start within ' + band + '.';
    if (side) drill = 'Most measured starts were ' + side + ' of the band. Align the monitor and clubface with one target. Hit five stock shots and count how many start within ' + band + '.';
    if (d.center === d.count) drill = 'All measured shots started inside the band. Change targets, realign the monitor and try to keep five more starts inside ' + band + '.';
  } else if (goal === 'carry' && distance) {
    drill = 'Aim for a modeled carry of ' + displayMetric(distance.median, 'carry_yards', units) + ' ' + unitFor('carry_yards', units) + '. Hit five shots and compare the middle-half carry spread with this set.';
  } else if (goal === 'speed' && speed) {
    drill = 'Hit five stock swings at a comfortable pace. Compare the new ball-speed spread with this set at a similar median speed.';
  }
  return <>
    <div className="filters">
      {source === 'pi' && <label>Golfer or unlinked session<select value={group} onChange={e => {chooseGroup(e.target.value); chooseSession(''); chooseBaseline('');}}>
        {[...groups.keys()].map(key => <option key={key} value={key}>{groupLabel(key)}</option>)}</select></label>}
      <label>Club<select value={club} onChange={e => {chooseClub(e.target.value); chooseSession(''); chooseBaseline('');}}>
        {clubs.map(c => <option key={c} value={c}>{clubLabels[c] ?? clubName(c)}</option>)}</select></label>
      <label>Selected session<select value={current.id} onChange={e => {chooseSession(e.target.value); chooseBaseline('');}}>
        {sets.map(s => <option key={s.id} value={s.id}>{label(s)} · {s.stats.size} shots</option>)}</select></label>
      {alternatives.length > 0 && <label>Compare with<select value={prior?.id ?? ''} onChange={e => chooseBaseline(e.target.value)}>
        {!prior && <option value="">Choose a baseline session</option>}
        {alternatives.map(set => <option key={set.id} value={set.id}>{label(set)} · {set.stats.size} shots</option>)}
      </select></label>}
    </div>
    {!alternatives.length && <p>A second session with this club will enable percentage comparisons.</p>}
    <SessionAverages current={current} baseline={prior} units={units}/>
    {source === 'pi' && group.startsWith('session/') && <p>Link sessions to the same golfer in Account to compare them over time.</p>}
    <section className="panel trend-focus"><h2>Next practice set</h2>
      <label>Practice focus<select value={goal} onChange={e => chooseGoal(e.target.value)}>
        <option value="line">Start on line</option><option value="speed">Repeat ball speed</option><option value="carry">Control carry distance</option>
      </select></label><p>{drill}</p></section>
    <section className="panel"><h2>Start direction</h2>
      {hasDirection ? <>
        <p className="trend-reading">{side ? (side === 'right' ? d.right : d.left) + ' of ' + d.count + ' started ' + side : d.center + ' of ' + d.count + ' inside the band'}</p>
        <p>{d.left} left · {d.center} within {band} · {d.right} right</p>
        {old && old.count >= minimumSamples && <p>Inside the band went from {old.center}/{old.count} ({Math.round(100 * old.center / old.count)}%) to {d.center}/{d.count} ({Math.round(100 * d.center / d.count)}%).</p>}
        <small>Measured at launch relative to monitor aim. Use the same alignment to compare sessions. The ball can curve after launch.</small>
      </> : <p>{d.count} of {minimumSamples} measured launch directions needed to show a pattern.</p>}
    </section>
    <Consistency metric="ball_speed_mph" current={current} previous={prior} units={units}/>
    <Consistency metric="carry_yards" current={current} previous={prior} units={units}/>
  </>;
}
