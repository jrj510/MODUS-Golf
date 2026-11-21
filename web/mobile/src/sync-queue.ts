import { sha256 } from '@noble/hashes/sha2.js';
import { canonicalJson } from '../../MODUS_Golf_Firebase_AI_Starter/app-core/sync-wire.mjs';
import type { Shot } from '../../src/domain';
import type { LocalState } from './journal';
import { firebaseProjectId, legacyBindingsProjectId } from './firebase-project.ts';

export type Binding = {uid:string; profileId:string; projectId?:string};
// Existing journals predate the owner's project correction. Never reinterpret
// their unqualified UIDs as accounts in a different Firebase project.
export function bindingProject(binding: Binding) {return binding.projectId ?? legacyBindingsProjectId;}
export function belongsToAccount(binding: Binding | undefined, uid: string | null | undefined) {
  return !!binding && binding.uid === uid && bindingProject(binding) === firebaseProjectId;
}
export type Outcome = {
  revision:number; digest:string; status:'accepted'|'rejected'; code:string;
  checkedCsv34?:boolean; cloudShotId?:string; cloudSessionId?:string; receivedAt:string;
};
export type SyncState = {
  installationId:string;
  bindings:Record<string,Binding>;
  outcomes:Record<string,Outcome>;
};

export function eligible(shot: Shot) {
  return shot.source.kind === 'legacy_csv' && shot.record_kind === 'real' && shot.processing_state === 'final';
}
export function payloadDigest(shot: Shot) {
  return Array.from(sha256(new TextEncoder().encode(canonicalJson(shot))),byte => byte.toString(16).padStart(2,'0')).join('');
}
function installationId() {
  const bytes=crypto.getRandomValues(new Uint8Array(16));
  bytes[6]=(bytes[6]&15)|64;
  bytes[8]=(bytes[8]&63)|128;
  const hex=Array.from(bytes,byte => byte.toString(16).padStart(2,'0')).join('');
  return [hex.slice(0,8),hex.slice(8,12),hex.slice(12,16),hex.slice(16,20),hex.slice(20)].join('-');
}
export function bindSession(state: LocalState, sessionId: string, binding: Pick<Binding,'uid'|'profileId'>): LocalState {
  if (!state.shots.some(shot => shot.session_id === sessionId && eligible(shot))) throw new Error('Confirm physical shots before linking this session.');
  const sync=state.sync ?? {installationId:installationId(),bindings:{},outcomes:{}};
  if (Object.hasOwn(sync.bindings,sessionId)) throw new Error('This session is already linked.');
  return {...state,sync:{...sync,bindings:{...sync.bindings,[sessionId]:{...binding,projectId:firebaseProjectId}}}};
}
export function pendingShots(state: LocalState, uid: string) {
  return state.shots.filter(shot => eligible(shot) && belongsToAccount(state.sync?.bindings[shot.session_id],uid) &&
    !currentOutcome(state,shot));
}
export function currentOutcome(state: LocalState, shot: Shot) {
  const outcome=state.sync?.outcomes[shot.shot_id];
  // Receipts from the original validator predate extended monitor CSV support.
  if (shot.source.csv_format === 'modus_csv_34' && outcome?.status === 'rejected' &&
      outcome.code === 'invalid_shot' && !outcome.checkedCsv34) return undefined;
  return outcome?.revision === shot.revision && outcome.digest === payloadDigest(shot) ? outcome : undefined;
}
export function acceptReceipt(shot: Shot, receipt: unknown): Outcome | null {
  if (!receipt || typeof receipt !== 'object') return null;
  const value=receipt as Record<string,unknown>;
  const digest=payloadDigest(shot);
  if (value.shotId !== shot.shot_id || value.revision !== shot.revision || value.digest !== digest ||
      typeof value.code !== 'string' || value.code.length > 64) return null;
  const receivedAt=new Date().toISOString();
  if (value.status === 'rejected') return {
    revision:shot.revision,digest,status:'rejected',code:value.code,receivedAt,
    ...(shot.source.csv_format === 'modus_csv_34' && value.code === 'invalid_shot' ? {checkedCsv34:true} : {})
  };
  if (value.status !== 'accepted' || typeof value.cloudShotId !== 'string' || typeof value.cloudSessionId !== 'string' ||
      !/^shot_[a-f0-9]{64}$/.test(value.cloudShotId) || !/^session_[a-f0-9]{64}$/.test(value.cloudSessionId)) return null;
  return {revision:shot.revision,digest,status:'accepted',code:value.code,cloudShotId:value.cloudShotId,cloudSessionId:value.cloudSessionId,receivedAt};
}
