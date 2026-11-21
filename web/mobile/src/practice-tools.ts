import { converted, type Shot, type Units } from '../../src/domain.ts';
import { describeSet } from './practice-trends.ts';

export type TargetRound = {
  distance: number; tolerance: number; units: Units;
  sessionId: string | null; after: number; through?: number;
};
export function lastSequence(shots: Shot[]) {
  return shots.reduce((max, shot) => Math.max(max, shot.sequence_number), 0);
}
export function scoreTarget(round: TargetRound, shots: Shot[], demo: boolean) {
  let short = 0, within = 0, long = 0, missing = 0, unconfirmed = 0;
  for (const shot of shots) {
    if (shot.session_id !== round.sessionId || shot.sequence_number <= round.after ||
        shot.sequence_number > (round.through ?? Infinity)) continue;
    if (shot.record_kind !== (demo ? 'synthetic' : 'real') || shot.processing_state !== 'final') {
      unconfirmed++;
      continue;
    }
    if (shot.carry_yards === null || !Number.isFinite(shot.carry_yards)) { missing++; continue; }
    const carry = converted(shot.carry_yards, 'carry_yards', round.units);
    if (carry < round.distance - round.tolerance - 1e-8) short++;
    else if (carry > round.distance + round.tolerance + 1e-8) long++;
    else within++;
  }
  return {short, within, long, missing, unconfirmed, scored:short + within + long};
}
export function yardageRows(shots: Shot[]) {
  const clubs = new Map<string, Shot[]>();
  for (const shot of shots) {
    const rows = clubs.get(shot.club);
    if (rows) rows.push(shot);
    else clubs.set(shot.club, [shot]);
  }
  return [...clubs].map(([club, rows]) => ({club, ...describeSet(rows).carry}))
    .sort((a,b) => (b.range?.median ?? -Infinity) - (a.range?.median ?? -Infinity) || a.club.localeCompare(b.club));
}
export function overlappingClubs(rows: ReturnType<typeof yardageRows>) {
  const pairs: [string,string][] = [];
  rows.forEach((a,i) => {
    if (!a.range) return;
    for (const b of rows.slice(i+1)) {
      if (b.range && a.range.low <= b.range.high && b.range.low <= a.range.high) pairs.push([a.club,b.club]);
    }
  });
  return pairs;
}
