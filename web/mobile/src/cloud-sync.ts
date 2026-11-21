import { useEffect, useRef, useState } from 'react';
import { accountToken } from './native-firebase';
import type { Journal, LocalState } from './journal';
import { belongsToAccount, pendingShots, payloadDigest } from './sync-queue';
import { sendShotBatch } from './upload-batch';
import { firebaseProjectId } from './firebase-project';

const deployment = `https://us-central1-${firebaseProjectId}.cloudfunctions.net/ingestLegacyShots`;
export const syncAvailable = import.meta.env.VITE_ENABLE_CLOUD_SYNC === 'true';

export function useCloudSync(
  journal: Journal, local: LocalState | null, uid: string | undefined, foreground: boolean,
  currentUid: () => string | null, setLocal: (data: LocalState) => void
) {
  const [status,setStatus]=useState('');
  const [retry,setRetry]=useState(0);
  const state=useRef(local);
  state.current=local;
  const callbacks=useRef({currentUid,setLocal});
  callbacks.current={currentUid,setLocal};
  const serial=useRef(Promise.resolve());

  useEffect(() => {
    setStatus('');
    if (!syncAvailable || !uid || !foreground) return;
    const controller=new AbortController();
    const active=() => !controller.signal.aborted && callbacks.current.currentUid() === uid;
    let timer:ReturnType<typeof setTimeout>;
    let failures=0;
    function schedule(delay: number) {
      if (active()) timer=setTimeout(() => {
        serial.current=serial.current.then(async () => { if (active()) await upload(); });
      },delay);
    }
    async function upload() {
      const data=state.current;
      const sync=data?.sync;
      const candidates=data && uid ? pendingShots(data,uid) : [];
      if (!sync || !candidates.length) {
        schedule(5000);
        return;
      }
      const first=candidates[0];
      const binding=sync.bindings[first.session_id];
      const sessionShots=candidates.filter(shot => shot.session_id === first.session_id);
      try {
        setStatus('Uploading saved shots…');
        const send=async (body: string, refresh: boolean) => {
          const token=await accountToken(binding.uid,refresh);
          if (!active()) throw new Error('Upload paused.');
          return fetch(deployment,{
            method:'POST',redirect:'error',headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},body,
            signal:AbortSignal.any([controller.signal,AbortSignal.timeout(25_000)])
          });
        };
        const {shots:batch,outcomes}=await sendShotBatch(sessionShots,sync.installationId,binding.profileId,async body => {
          const response=await send(body,false);
          return response.status === 401 && active() ? send(body,true) : response;
        });
        if (!active()) return;
        let applied=false;
        const saved=await journal.commit(current => {
          if (!active() || !current.sync || current.sync.installationId !== sync.installationId) return current;
          const next={...current.sync.outcomes};
          for (const shot of current.shots) {
            const receipt=outcomes.get(shot.shot_id);
            const currentBinding=current.sync.bindings[shot.session_id];
            if (!receipt || receipt.revision !== shot.revision || receipt.digest !== payloadDigest(shot) || !belongsToAccount(currentBinding,uid) ||
                currentBinding?.profileId !== binding.profileId) continue;
            next[shot.shot_id]=receipt;
            applied=true;
          }
          return applied ? {...current,sync:{...current.sync,outcomes:next}} : current;
        });
        if (applied) callbacks.current.setLocal(saved);
        if (!active()) return;
        failures=0;
        setStatus([...outcomes.values()].some(item => item.status === 'rejected') ?
          'Some shots need attention. They are still saved on this iPhone.' : 'Cloud receipts saved.');
        schedule(outcomes.size < batch.length ? 15_000 : 2500);
      } catch {
        if (!active()) return;
        setStatus('Upload waiting. Saved shots will retry while the app is open.');
        failures++;
        schedule(Math.min(120_000,5000*2**Math.min(failures-1,5))*(0.8+Math.random()*0.4));
      }
    }
    schedule(0);
    return () => {controller.abort();clearTimeout(timer);};
  },[journal,uid,foreground,retry]);
  return {status,retry:() => setRetry(value => value+1)};
}
