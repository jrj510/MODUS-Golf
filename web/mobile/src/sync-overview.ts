import type { LocalState } from './journal';
import { belongsToAccount, currentOutcome, eligible } from './sync-queue.ts';

export function syncOverview(local:LocalState,uid:string) {
  const sessions=new Map<string,string>();
  const attention=new Map<string,number>();
  let pending=0,synced=0,rejected=0,unconfirmed=0,lastReceipt='';
  for(const shot of local.shots) {
    const binding=local.sync?.bindings[shot.session_id];
    if(binding && !belongsToAccount(binding,uid)) continue;
    if(shot.source.kind !== 'legacy_csv' || shot.record_kind === 'synthetic') continue;
    if(!eligible(shot)) {unconfirmed++;continue;}
    if(!binding) {
      sessions.set(shot.session_id,local.sessionDetails?.[shot.session_id]?.name || shot.source.filename || 'Local practice');
      continue;
    }
    const outcome=currentOutcome(local,shot);
    if(!outcome) {pending++;continue;}
    if(outcome.status === 'accepted') {
      synced++;
      if(outcome.receivedAt > lastReceipt) lastReceipt=outcome.receivedAt;
    } else {
      rejected++;
      attention.set(outcome.code,(attention.get(outcome.code) ?? 0)+1);
    }
  }
  return {sessions,attention,pending,synced,rejected,unconfirmed,lastReceipt};
}

export function rejectionMessage(code:string) {
  const messages:Record<string,string>={
    invalid_shot:'The cloud could not validate these measurements.',
    revision_conflict:'A different measurement already uses the same shot revision.',
    stale_revision:'The cloud already has a newer version of these measurements.',
    deleted:'These shots were previously deleted from the cloud.',
    ownership_conflict:'This session is already assigned to a different cloud account or golfer.',
    profile_missing:'The linked golfer is missing from the cloud account.',
  };
  return messages[code] ?? 'The cloud did not accept these measurements.';
}
