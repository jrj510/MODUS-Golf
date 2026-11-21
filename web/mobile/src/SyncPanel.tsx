import { useMemo, useState } from 'react';
import type { AccountUser, Profile } from './native-firebase';
import type { LocalState } from './journal';
import { syncOverview, rejectionMessage } from './sync-overview';
import { syncAvailable } from './cloud-sync';

export function SyncPanel({local,user,profiles,busy,status,retry,bind}: {
  local:LocalState; user:AccountUser; profiles:Profile[]; busy:boolean; status:string;
  retry:() => void; bind:(sessionId:string,profileId:string) => Promise<unknown>;
}) {
  const [sessionId,setSessionId]=useState('');
  const [profileId,setProfileId]=useState('');
  const {sessions,attention,pending,synced,rejected,unconfirmed,lastReceipt}=useMemo(() => syncOverview(local,user.uid),[local,user.uid]);
  const session=sessions.get(sessionId);
  const golfer=profiles.find(item => item.id === profileId);
  return <section className="panel">
    <h2>Sync local practice</h2>
    <p>{pending} waiting · {synced} synced · {rejected} need attention</p>
    <p>Shots stay saved on this iPhone. Linked shots upload automatically while the app is open and internet is available.</p>
    {lastReceipt && <p>Last confirmed upload {new Date(lastReceipt).toLocaleString()}</p>}
    {status && <p role="status">{status}</p>}
    {rejected > 0 && <details><summary>Review {rejected} shots needing attention</summary>
      <ul>{[...attention].map(([code,count]) => <li key={code}>{count} shots: {rejectionMessage(code)} <small>Reference: {code}</small></li>)}</ul>
      <p>These shots remain in local history and backups. Retrying unchanged measurements will not resolve a rejection. Keep a JSON backup from Monitor when investigating.</p>
    </details>}
    {unconfirmed > 0 && <p>{unconfirmed} monitor records are not ready to upload. Confirm physical shots in Monitor and wait for completed measurements.</p>}
    {!syncAvailable && <p>This build can link sessions. Upload will be available once the cloud service is enabled.</p>}
    {sessions.size > 0 ? <form onSubmit={event => {
      event.preventDefault();
      if (session && golfer) void bind(sessionId,profileId);
    }}>
      {profiles.length === 0 && <p>Add a golfer above before linking your session.</p>}
      <label>Confirmed monitor session<select value={sessionId} onChange={event => setSessionId(event.target.value)}>
        <option value="">Choose a session</option>
        {[...sessions].map(([id,label]) => <option key={id} value={id}>{label}</option>)}
      </select></label>
      <label>Cloud golfer<select value={profileId} onChange={event => setProfileId(event.target.value)}>
        <option value="">Choose a golfer</option>
        {profiles.map(item => <option key={item.id} value={item.id}>{item.display_name}</option>)}
      </select></label>
      <p>Linking assigns confirmed shots in this session, including later updates, to the selected golfer in {user.email ?? 'this account'}. A linked session cannot be moved to another account.</p>
      <button className="primary" disabled={busy || !session || !golfer}>Link session to {golfer?.display_name ?? 'golfer'}</button>
    </form> : <p>{synced || pending || rejected ? 'All eligible local sessions are linked to this account.' : 'Capture and confirm a physical session in Monitor to get started.'}</p>}
    {syncAvailable && pending > 0 && <button disabled={busy || status === 'Uploading saved shots…'} onClick={retry}>Retry upload</button>}
  </section>;
}
