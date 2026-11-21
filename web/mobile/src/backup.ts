import { validateCloudShot, type Shot } from '../../src/domain.ts';
import { mergeRevision } from '../../MODUS_Golf_Firebase_AI_Starter/app-core/shot.mjs';
import type { LocalState } from './journal';
import { bindingProject, belongsToAccount, type Binding } from './sync-queue.ts';
import { piOrigin } from './pi.ts';
import type { BagClub, SessionDetails } from './PracticeDetails';
import type { Units } from '../../src/domain';

const opaqueId=/^[A-Za-z0-9_-]{1,120}$/;
const uuid=/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/;
type Backup = {
  shots:Shot[]; installationId?:string; bindings:Record<string,Binding>;
  units?:Units; bag:BagClub[]; sessionDetails:Record<string,SessionDetails>;
  piOrigin:string; deviceId:string; monitors:Record<string,string>;
};

function dictionary(value:unknown): value is Record<string,unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}
function checkClubLabels(clubs:BagClub[]) {
  const labels=clubs.filter(club => !club.archived && club.monitorLabel).map(club => club.monitorLabel);
  if (new Set(labels).size !== labels.length) throw new Error('Conflicting active club labels. Edit the matching clubs before restoring this backup.');
}

export function createBackup(local: LocalState, visible: Shot[]) {
  const sessionIds=new Set(visible.map(shot => shot.session_id));
  const bindings=Object.fromEntries(Object.entries(local.sync?.bindings ?? {}).filter(([id]) => sessionIds.has(id)));
  const sync=local.sync && Object.keys(bindings).length ? {installationId:local.sync.installationId,bindings,outcomes:{}} : undefined;
  return JSON.stringify({requires_owner_binding:true,local:{
    ...local,shots:visible,sync,
    sessionDetails:Object.fromEntries(Object.entries(local.sessionDetails ?? {}).filter(([id]) => sessionIds.has(id)))
  }},null,2);
}

export async function readBackup(file: File): Promise<Backup> {
  if (file.size > 32*1024*1024) throw new Error('Choose a MODUS backup smaller than 32 MB.');
  const parsed=JSON.parse(await file.text());
  const local=parsed?.local;
  if (parsed?.requires_owner_binding !== true || local?.version !== 1 || !Array.isArray(local.shots) || local.shots.length > 20_000) {
    throw new Error('Choose a MODUS Golf local JSON backup with up to 20,000 shots.');
  }
  const seen=new Set<string>();
  const shots:Shot[]=local.shots.map((input: Record<string,unknown>) => {
    const shot=validateCloudShot(input);
    if (!opaqueId.test(shot.shot_id) || !opaqueId.test(shot.session_id) || !opaqueId.test(shot.device_id) || seen.has(shot.shot_id)) {
      throw new Error('The backup contains invalid or duplicate shot identifiers.');
    }
    seen.add(shot.shot_id);
    return shot;
  });
  const sessions=new Set(shots.map(shot => shot.session_id));
  if (local.units !== undefined && local.units !== 'imperial' && local.units !== 'metric') throw new Error('Invalid backup display units.');
  const sessionDetails:Record<string,SessionDetails>=Object.create(null);
  if (local.sessionDetails !== undefined) {
    if (!dictionary(local.sessionDetails)) throw new Error('Invalid backup session details.');
    for (const [id,detail] of Object.entries(local.sessionDetails)) {
      if (!sessions.has(id) || !dictionary(detail) || typeof detail.name !== 'string' || detail.name.length > 80 ||
          typeof detail.notes !== 'string' || detail.notes.length > 1000) throw new Error('Invalid backup session details.');
      sessionDetails[id]={name:detail.name,notes:detail.notes};
    }
  }
  const bag:BagClub[]=[];
  if (local.bag !== undefined) {
    if (!Array.isArray(local.bag) || local.bag.length > 200) throw new Error('Invalid backup club inventory.');
    const clubIds=new Set<string>();
    for (const club of local.bag) {
      if (!dictionary(club) || typeof club.id !== 'string' || !opaqueId.test(club.id) || clubIds.has(club.id) ||
          typeof club.name !== 'string' || !club.name.trim() || club.name.length > 60 ||
          typeof club.monitorLabel !== 'string' || club.monitorLabel.length > 120 || typeof club.archived !== 'boolean') {
        throw new Error('Invalid backup club inventory.');
      }
      clubIds.add(club.id);
      bag.push({id:club.id,name:club.name,monitorLabel:club.monitorLabel,archived:club.archived});
    }
    checkClubLabels(bag);
  }
  if (typeof local.piOrigin !== 'string' || typeof local.deviceId !== 'string' || !opaqueId.test(local.deviceId)) throw new Error('Invalid backup monitor settings.');
  const origin=piOrigin(local.piOrigin);
  const monitors:Record<string,string>=Object.create(null);
  if (local.monitors !== undefined) {
    if (!dictionary(local.monitors) || Object.keys(local.monitors).length > 100) throw new Error('Invalid backup monitor settings.');
    for (const [address,id] of Object.entries(local.monitors)) {
      if (piOrigin(address) !== address || typeof id !== 'string' || !opaqueId.test(id)) throw new Error('Invalid backup monitor settings.');
      monitors[address]=id;
    }
  }
  if (monitors[origin] && monitors[origin] !== local.deviceId) throw new Error('Conflicting backup monitor identity.');
  monitors[origin]=local.deviceId;
  const bindings:Record<string,Binding>=Object.create(null);
  const sync=local.sync;
  if (sync !== undefined) {
    if (typeof sync?.installationId !== 'string' || !uuid.test(sync.installationId) ||
        !sync.bindings || typeof sync.bindings !== 'object' || Array.isArray(sync.bindings)) throw new Error('Invalid backup account links.');
    for (const [sessionId,value] of Object.entries(sync.bindings)) {
      const item=value as Binding | null;
      if (!sessions.has(sessionId) || !item || typeof item.uid !== 'string' || !item.uid || item.uid.length > 128 ||
          typeof item.profileId !== 'string' || !opaqueId.test(item.profileId) ||
          (item.projectId !== undefined && (typeof item.projectId !== 'string' || !/^[a-z][a-z0-9-]{4,28}[a-z0-9]$/.test(item.projectId)))) throw new Error('Invalid backup account links.');
      bindings[sessionId]={uid:item.uid,profileId:item.profileId,projectId:bindingProject(item)};
    }
  }
  return {shots,bindings,installationId:sync?.installationId,units:local.units,bag,sessionDetails,piOrigin:origin,deviceId:local.deviceId,monitors};
}

export function restoreBackup(current: LocalState, backup: Backup, uid: string | null): LocalState {
  const linked=Object.entries(backup.bindings);
  if (linked.some(([,binding]) => !belongsToAccount(binding,uid))) throw new Error('Sign in to the account and Firebase project that owns this backup.');
  if (linked.length && current.sync && current.sync.installationId !== backup.installationId) {
    throw new Error('This backup was linked on a different installation. Restore it on an installation without linked sessions.');
  }
  const rows=new Map(current.shots.map(shot => [shot.shot_id,shot]));
  const sessions=new Set(current.shots.map(shot => shot.session_id));
  for (const shot of backup.shots) {
    if (shot.profile_id !== current.profileId) throw new Error('This backup has a different local golfer.');
    const known=current.sync?.bindings[shot.session_id];
    const incoming=backup.bindings[shot.session_id];
    if (known && (!incoming || known.uid !== incoming.uid || known.profileId !== incoming.profileId || bindingProject(known) !== bindingProject(incoming))) {
      throw new Error('The backup conflicts with a linked session on this iPhone.');
    }
    if (incoming && !known && sessions.has(shot.session_id)) {
      throw new Error('Restore linked sessions into an installation without existing copies of those sessions.');
    }
    const prior=rows.get(shot.shot_id);
    if (prior && (prior.record_kind === 'synthetic') !== (shot.record_kind === 'synthetic')) throw new Error('Conflicting synthetic shot identity.');
    rows.set(shot.shot_id,mergeRevision(prior,shot));
  }
  const sync=linked.length ? {
    installationId:backup.installationId!,
    bindings:{...current.sync?.bindings,...backup.bindings},
    outcomes:current.sync?.outcomes ?? {}
  } : current.sync;
  const clubs=new Map(backup.bag.map(club => [club.id,club]));
  for (const club of current.bag ?? []) clubs.set(club.id,club);
  const bag=[...clubs.values()];
  checkClubLabels(bag);
  // A new installation can recover the monitor identity used by the backup.
  // On an established installation, a conflict must not change future shot IDs.
  const knownMonitors=current.monitors ?? (current.shots.length ? {[current.piOrigin]:current.deviceId} : {});
  for (const [address,id] of Object.entries(backup.monitors)) {
    if (knownMonitors[address] && knownMonitors[address] !== id) throw new Error('The backup conflicts with a saved monitor identity on this iPhone.');
  }
  const useBackupMonitor=!current.shots.length && !current.monitors;
  return {...current,shots:[...rows.values()],sync,
    units:current.units ?? backup.units,
    bag,
    sessionDetails:{...backup.sessionDetails,...current.sessionDetails},
    monitors:{...backup.monitors,...knownMonitors},
    ...(useBackupMonitor ? {piOrigin:backup.piOrigin,deviceId:backup.deviceId} : {})
  };
}
