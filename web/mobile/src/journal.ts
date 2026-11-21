import { mergeRevision, type Shot } from '../../MODUS_Golf_Firebase_AI_Starter/app-core/shot.mjs';
import { validateCloudShot, type Units } from '../../src/domain.ts';
import type { SessionDetails, BagClub } from './PracticeDetails';
import { bindSession, belongsToAccount, type SyncState } from './sync-queue.ts';
import { sha256 } from '@noble/hashes/sha2.js';

export interface LocalState {
  version: 1; shots: Shot[]; piOrigin: string; deviceId: string; profileId: string;
  units?: Units; sync?: SyncState; monitors?: Record<string,string>;
  sessionDetails?: Record<string,SessionDetails>; bag?: BagClub[];
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
  if (data.units !== undefined && data.units !== 'imperial' && data.units !== 'metric') throw new Error('Invalid display units');
  if (data.monitors && Object.values(data.monitors).some(id => !/^[A-Za-z0-9_-]{1,120}$/.test(id))) throw new Error('Invalid monitor identity');
  for (const shot of data.shots) validateCloudShot(shot as unknown as Record<string,unknown>);
}

/** Two generations: a failed/torn write never overwrites the last valid slot. */
export class Journal {
  private generation = 0;
  private state = initial();
  private writes: Promise<void> = Promise.resolve();
  private loaded = false;
  private port: StoragePort;
  constructor(port: StoragePort) {this.port=port;}
  async load(): Promise<LocalState> {
    return this.enqueue(() => this.loadSaved());
  }
  private async loadSaved(): Promise<LocalState> {
    if (this.loaded) return structuredClone(this.state);
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
    this.loaded=true;
    return structuredClone(this.state);
  }
  commit(change: (current: LocalState) => LocalState): Promise<LocalState> {
    return this.enqueue(() => {
      this.requireLoaded();
      return this.save(change(structuredClone(this.state)));
    });
  }
  mergeCapture(incoming: Shot[], isCurrent: () => boolean,
    player?: {uid: string | null; profileId: string; confirmedFile: string | null}): Promise<LocalState | null> {
    return this.enqueue(async () => {
      this.requireLoaded();
      if (!isCurrent()) return null;
      const first = incoming[0];
      const binding = first && this.state.sync?.bindings[first.session_id];
      if (binding && player && (!belongsToAccount(binding, player.uid) || binding.profileId !== player.profileId)) {
        throw new Error('This monitor session is already linked. Select its golfer or start a fresh session on the monitor.');
      }
      const shots = mergeLocal(this.state.shots, incoming);
      if (player?.uid && player.profileId && !binding && first?.source.filename &&
          first.source.filename === player.confirmedFile && first.record_kind === 'real') {
        return this.save(bindSession({...this.state, shots}, first.session_id, {uid:player.uid, profileId:player.profileId}));
      }
      if (shots === this.state.shots) return null;
      return this.save({...this.state, shots});
    });
  }
  private enqueue<T>(work: () => Promise<T>): Promise<T> {
    const job = this.writes.then(work);
    this.writes = job.then(() => {},() => {});
    return job;
  }
  private requireLoaded() {
    if (!this.loaded) throw new Error('Saved practice must load successfully before changes can be saved. Your existing records have not been replaced.');
  }
  private async save(data: LocalState): Promise<LocalState> {
    validate(data);
    const envelope: Envelope = {version:1,generation:this.generation+1,digest:await digest(data),data};
    const slot = envelope.generation % 2 ? 'a' : 'b';
    const serialized = JSON.stringify(envelope);
    await this.port.write(slot,serialized);
    if (await this.port.read(slot) !== serialized) throw new Error('Local save was not verified. The previous saved generation was retained.');
    this.generation=envelope.generation;this.state=data;
    return structuredClone(data);
  }
}

export function mergeLocal(previous: Shot[], incoming: Shot[]): Shot[] {
  if (!incoming.length) return previous;
  const rows = new Map(previous.map(shot => [shot.shot_id,shot]));
  let changed = false;
  for (const item of incoming) {
    const old = rows.get(item.shot_id);
    if (old && ['session_id','device_id','profile_id','sequence_number'].some(key => old[key as keyof Shot] !== item[key as keyof Shot])) throw new Error('Local shot identity cannot be reassigned.');
    const candidate = {...item,revision:old?.revision ?? item.revision};
    if (old?.record_kind === 'synthetic' && item.record_kind !== 'synthetic') throw new Error('Synthetic shots cannot become physical shots.');
    // Reopening with the confirmation checkbox off must not revoke an earlier
    // explicit physical-shot confirmation for the same immutable source row.
    if (old?.record_kind === 'real' && candidate.record_kind === 'unknown') candidate.record_kind='real';
    if (old && canonical(candidate) === canonical(old)) continue;
    if (old) candidate.revision=old.revision+1;
    rows.set(item.shot_id,mergeRevision(old,candidate));
    changed = true;
  }
  return changed ? [...rows.values()] : previous;
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return '['+value.map(canonical).join(',')+']';
  if (value !== null && typeof value === 'object') return '{'+Object.keys(value).sort().map(key => JSON.stringify(key)+':'+canonical((value as Record<string,unknown>)[key])).join(',')+'}';
  return JSON.stringify(value);
}
