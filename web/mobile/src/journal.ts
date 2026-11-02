import { mergeRevision, type Shot } from '../../MODUS_Golf_Firebase_AI_Starter/app-core/shot.mjs';
import { validateCloudShot } from '../../src/domain.ts';
import { sha256 } from '@noble/hashes/sha2.js';

export interface LocalState {
  version: 1; shots: Shot[]; piOrigin: string; deviceId: string; profileId: string;
}
export interface StoragePort {read(slot: string): Promise<string | null>; write(slot: string, value: string): Promise<void>}
type Envelope = {version:1;generation:number;digest:string;data:LocalState};
const initial = (): LocalState => ({version:1,shots:[],piOrigin:'http://10.42.0.1:8000',deviceId:'modus_pi_local',profileId:'phone_local_golfer'});
async function digest(value: LocalState) {
  const hash = sha256(new TextEncoder().encode(JSON.stringify(value)));
  return Array.from(new Uint8Array(hash),byte => byte.toString(16).padStart(2,'0')).join('');
}
function validate(data: LocalState) {
  if (!data || data.version !== 1 || !Array.isArray(data.shots) || typeof data.piOrigin !== 'string' ||
      !/^[A-Za-z0-9_-]{1,120}$/.test(data.deviceId) || !/^[A-Za-z0-9_-]{1,120}$/.test(data.profileId)) throw new Error('Invalid local journal');
  for (const shot of data.shots) validateCloudShot(shot as unknown as Record<string,unknown>);
}

/** Two generations: a failed/torn write never overwrites the last valid slot. */
export class Journal {
  private generation = 0;
  private state = initial();
  private writes: Promise<void> = Promise.resolve();
  private port: StoragePort;
  constructor(port: StoragePort) {this.port=port;}
  async load(): Promise<LocalState> {
    const texts = await Promise.all(['a','b'].map(slot => this.port.read(slot)));
    const candidates: Envelope[] = [];
    for (const text of texts) {
      if (text === null) continue;
      try {
        const value = JSON.parse(text) as Envelope;
        if (value.version !== 1 || !Number.isSafeInteger(value.generation) || value.generation < 1) continue;
        validate(value.data);
        if (value.digest === await digest(value.data)) candidates.push(value);
      } catch { /* Recover using the other fully validated generation. */ }
    }
    candidates.sort((a,b) => b.generation-a.generation);
    if (!candidates.length && texts.some(text => text !== null)) throw new Error('Local storage is damaged. Keep the app data and recover a backup before continuing.');
    if (candidates[0]) {this.generation=candidates[0].generation;this.state=candidates[0].data;}
    return structuredClone(this.state);
  }
  commit(change: (current: LocalState) => LocalState): Promise<LocalState> {
    const job = this.writes.then(async () => {
      const data = change(structuredClone(this.state)); validate(data);
      const envelope: Envelope = {version:1,generation:this.generation+1,digest:await digest(data),data};
      const slot = envelope.generation % 2 ? 'a' : 'b';
      const serialized = JSON.stringify(envelope);
      await this.port.write(slot,serialized);
      if (await this.port.read(slot) !== serialized) throw new Error('Local save was not verified. The previous saved generation was retained.');
      this.generation=envelope.generation;this.state=data;
      return structuredClone(data);
    });
    this.writes = job.then(() => {},() => {});
    return job;
  }
}

export function mergeLocal(previous: Shot[], incoming: Shot[]): Shot[] {
  const rows = new Map(previous.map(shot => [shot.shot_id,shot]));
  for (const item of incoming) {
    const old = rows.get(item.shot_id);
    if (old && ['session_id','device_id','profile_id','sequence_number'].some(key => old[key as keyof Shot] !== item[key as keyof Shot])) throw new Error('Local shot identity cannot be reassigned.');
    const candidate = {...item,revision:old?.revision ?? item.revision};
    if (old?.record_kind === 'synthetic' && item.record_kind !== 'synthetic') throw new Error('Synthetic shots cannot become physical shots.');
    // Reopening with the confirmation checkbox off must not revoke an earlier
    // explicit physical-shot confirmation for the same immutable source row.
    if (old?.record_kind === 'real' && candidate.record_kind === 'unknown') candidate.record_kind='real';
    if (old && canonical(candidate) !== canonical(old)) candidate.revision=old.revision+1;
    rows.set(item.shot_id,mergeRevision(old,candidate));
  }
  return [...rows.values()];
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return '['+value.map(canonical).join(',')+']';
  if (value !== null && typeof value === 'object') return '{'+Object.keys(value).sort().map(key => JSON.stringify(key)+':'+canonical((value as Record<string,unknown>)[key])).join(',')+'}';
  return JSON.stringify(value);
}
