import { useState } from 'react';
import { clubName, displayMetric, unitFor, type Shot, type Units } from '../../src/domain';
import { minimumSamples, trendGroups, type TrendSource } from './practice-trends';
import { overlappingClubs, scoreTarget, yardageRows, type TargetRound } from './practice-tools';
import type { LocalState } from './journal';
import type { Profile } from './native-firebase';

export function TargetPractice({round, shots, units, demo, available, start, finish}: {
  round: TargetRound | null; shots: Shot[]; units: Units; demo: boolean; available: boolean;
  start:(distance:number,tolerance:number) => void; finish:() => void;
}) {
  const unit = unitFor('carry_yards', round?.units ?? units);
  const score = round && scoreTarget(round, shots, demo);
  return <section className="panel"><h2>Target-distance practice</h2>
    {round && score && <div aria-live="polite">
      <p className="trend-reading">{score.within} of {score.scored} within {round.distance - round.tolerance}–{round.distance + round.tolerance} {unit}</p>
      <p>{score.short} short · {score.long} long{score.missing > 0 && ' · '+score.missing+' missing carry'}
        {score.unconfirmed > 0 && ' · '+score.unconfirmed+' awaiting confirmation or final measurements'}</p>
      <small>{round.through === undefined ? 'In progress' : 'Finished'} · Modeled carry</small>
    </div>}
    {round && round.through === undefined ? <button onClick={finish}>Finish target practice</button> :
      <form key={units} onSubmit={event => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        const distance = Number(form.get('distance')), tolerance = Number(form.get('tolerance'));
        if (distance > 0 && tolerance > 0 && tolerance < distance) start(distance,tolerance);
        else { const input = event.currentTarget.elements.namedItem('tolerance') as HTMLInputElement;
          input.setCustomValidity('Choose a tolerance smaller than the target distance.'); input.reportValidity(); }
      }}>
        <div className="filters"><label>Target ({unitFor('carry_yards',units)})<input name="distance" type="number" inputMode="decimal" step="0.1" min="0.1" required defaultValue="100" onChange={e => (e.currentTarget.form!.elements.namedItem('tolerance') as HTMLInputElement).setCustomValidity('')}/></label>
          <label>Tolerance (± {unitFor('carry_yards',units)})<input name="tolerance" type="number" inputMode="decimal" min="0.1" step="0.1" required defaultValue="5" onChange={e => e.currentTarget.setCustomValidity('')}/></label></div>
        <button disabled={!available}>{round ? 'Start another target' : 'Start target practice'}</button>
        <p>{available ? demo ? 'Add demo shots to score this target.' : 'Counts new shots with any club in this session. Confirm physical shots in Practice setup to score them.' : 'Connect to the monitor and wait for its first read, or select synthetic test shots to try a target.'}</p>
      </form>}
  </section>;
}

export function YardageCard({shots, source, profileId, uid, local, profiles, units, names}: {
  shots:Shot[]; source:TrendSource; profileId:string; uid?:string; local:LocalState | null;
  profiles:Profile[]; units:Units; names:Record<string,string>;
}) {
  const groups = trendGroups(shots,source,profileId,uid,local?.sync?.bindings);
  const [choice,setChoice] = useState('');
  const selected = groups.has(choice) ? choice : [...groups.keys()].at(-1) ?? '';
  const rows = yardageRows(groups.get(selected) ?? []);
  const overlaps = overlappingClubs(rows);
  const name = (club:string) => names[club] ?? clubName(club);
  const fmt = (v:number) => displayMetric(v,'carry_yards',units);
  const unit = unitFor('carry_yards',units);
  return <section className="panel"><h2>Club yardage card</h2>
    {source === 'pi' && groups.size > 0 && <label>Golfer or session<select value={selected} onChange={e => setChoice(e.target.value)}>
      {[...groups].map(([key,group]) => <option key={key} value={key}>{key.startsWith('golfer/') ?
        profiles.find(p => p.id === key.slice(7))?.display_name ?? 'Linked golfer · '+key.slice(-6) :
        'Unlinked · '+(local?.sessionDetails?.[group[0].session_id]?.name || group[0].source.filename || key.slice(-6))}</option>)}</select></label>}
    <p>Typical modeled carry and middle 50% range. Each club needs {minimumSamples} carry readings.</p>
    {rows.length > 0 ? <div className="table-scroll"><table><thead><tr><th>Club</th><th>Typical ({unit})</th><th>Range ({unit})</th><th>Readings</th></tr></thead>
      <tbody>{rows.map(r => <tr key={r.club}><th scope="row">{name(r.club)}</th><td>{r.range ? fmt(r.range.median) : '—'}</td>
        <td>{r.range ? fmt(r.range.low)+'–'+fmt(r.range.high) : '—'}</td><td>{r.count}</td></tr>)}</tbody></table></div> : <p>No eligible shots in this view yet.</p>}
    {overlaps.length > 0 && <><h3>Clubs to test side by side</h3><p>Their typical carry ranges overlap.</p>
      <ul>{overlaps.map(([a,b]) => <li key={JSON.stringify([a,b])}>{name(a)} and {name(b)}</li>)}</ul></>}
  </section>;
}
