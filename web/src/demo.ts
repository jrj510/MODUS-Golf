import shots from '../MODUS_Golf_Firebase_AI_Starter/contracts/fixtures/demo_shots.json';
import profiles from '../MODUS_Golf_Firebase_AI_Starter/contracts/fixtures/demo_profiles.json';
import history from '../MODUS_Golf_Firebase_AI_Starter/contracts/fixtures/pi_history.json';
import { type Shot } from './domain';
export class DemoRepository {
  readonly shots: Shot[] = (() => {
    const current = (structuredClone(shots) as Shot[]).map(shot => {
      const fixture = history.shots.find(item => item.shot === shot.sequence_number && item.carry === shot.carry_yards);
      return { ...shot, trajectory: fixture ? structuredClone(fixture.path) as [number, number, number][] : null };
    });
    // A second explicitly synthetic session exercises like-for-like comparison.
    // It is never passed to Firebase or presented as hardware measurements.
    const comparison = current.map(shot => ({ ...structuredClone(shot),
      shot_id: `demo_prior_${shot.shot_id.slice(5)}`, session_id: 'demo_previous_session',
      carry_yards: shot.carry_yards == null ? null : Math.max(0, shot.carry_yards - 8), trajectory: null,
      source: { ...shot.source, filename: 'session_20261015_192000.csv', row_sha256: undefined, apex_yards: null },
      quality_flags: [...shot.quality_flags, 'synthetic_comparison_fixture'],
    }));
    return [...comparison, ...current];
  })();
  readonly profiles = profiles.map(profile => ({ id: profile.profile_id, display_name: profile.display_name }));
}
export class LocalPiRepository {
  readonly supported = false;
  readonly message = 'Use the Pi’s separate local range page. An authenticated live transport is not connected yet.';
}
