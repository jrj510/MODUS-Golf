import { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Capacitor } from '@capacitor/core';
import { App as NativeApp } from '@capacitor/app';
import { Icon, MetricCards, MoreMetrics, Trajectory, ShotList, Empty, download } from '../../src/components';
import { Bag } from '../../src/bag';
import { clubName, filterShots, historyCsv, selectedShot, displayMetric, type Shot, type Units } from '../../src/domain';
import fixtures from '../../MODUS_Golf_Firebase_AI_Starter/contracts/fixtures/demo_shots.json';
import history from '../../MODUS_Golf_Firebase_AI_Starter/contracts/fixtures/pi_history.json';
import { Journal, mergeLocal, type LocalState } from './journal';
import { storagePort } from './storage';
import { piOrigin, readPi } from './pi';
import { observeAccount, observeHistory, signInEmail, signInGoogle, signOut, resetPassword, createProfile, type AccountUser, type Profile } from './native-firebase';
import '../../src/style.css';
import './style.css';

type Tab='practice'|'sessions'|'bag'|'connection'|'account';
type Source='pi'|'demo'|'cloud';
const navigation=[{id:'practice',name:'Practice',icon:'practice'},{id:'sessions',name:'History',icon:'sessions'},{id:'connection',name:'Connection',icon:'settings'},{id:'account',name:'Account',icon:'cloud'}] as const;
const native=Capacitor.isNativePlatform();
function errorText(error:unknown) {return error instanceof Error ? error.message : 'The action could not be completed.';}

function MobileApp() {
  const [journal]=useState(() => new Journal(storagePort()));
  const [local,setLocal]=useState<LocalState | null>(null);
  const [tab,setTab]=useState<Tab>('practice');
  const [source,setSource]=useState<Source>('pi');
  const [club,setClub]=useState('');
  const [selection,setSelection]=useState<string | null>(null);
  const [units,setUnits]=useState<Units>('imperial');
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [connected,setConnected]=useState(false);
  const [capture,setCapture]=useState(false);
  const [confirmed,setConfirmed]=useState(false);
  const [piStatus,setPiStatus]=useState('Not connected');
  const [piAddress,setPiAddress]=useState('http://10.42.0.1:8000');
  const [user,setUser]=useState<AccountUser | null>(null);
  const [cloudShots,setCloudShots]=useState<Shot[]>([]);
  const [profiles,setProfiles]=useState<Profile[]>([]);
  const [profile,setProfile]=useState('');
  const [cached,setCached]=useState(true);
  const [busy,setBusy]=useState(false);
  const localRef=useRef(local);localRef.current=local;
  const accountRef=useRef<string | null>(null);
  useEffect(() => {void journal.load().then(data => {setLocal(data);setPiAddress(data.piOrigin);}).catch(error => setError(errorText(error)));},[journal]);
  useEffect(() => {window.scrollTo({top:0});},[tab]);
  useEffect(() => {setSelection(null);setClub('');},[source,profile]);
  useEffect(() => {
    if (!native) return;let active=true;let stop:(() => void) | undefined;
    void observeAccount(current => {
      if (!active) return;
      if (accountRef.current !== (current?.uid ?? null)) {setCloudShots([]);setProfiles([]);setProfile('');setSource(value => value === 'cloud' ? 'pi' : value);}
      accountRef.current=current?.uid ?? null;setUser(current);
    }).then(cleanup => {if (active) stop=cleanup;else cleanup();}).catch(() => {/* Firebase is optional for starting local practice. Account actions report configuration errors. */});
    return () => {active=false;stop?.();};
  },[]);
  useEffect(() => {
    if (!user) return;let active=true;let stop:(() => void) | undefined;const uid=user.uid;
    void observeHistory(uid,(items,fromCache) => {if (active && accountRef.current === uid) {setCloudShots(items);setCached(fromCache);}},items => {if (active && accountRef.current === uid) setProfiles(items);},failure => {if (active && accountRef.current === uid) {setCloudShots([]);setError(failure.message);}})
      .then(cleanup => {if (active) stop=cleanup;else cleanup();}).catch(failure => {if (active) setError(errorText(failure));});
    return () => {active=false;stop?.();};
  },[user?.uid]);
  useEffect(() => {if (!profiles.some(item => item.id === profile)) setProfile(profiles[0]?.id ?? '');},[profiles,profile]);
  useEffect(() => {
    if (!native) return;let active=true;let listener:{remove:() => Promise<void>} | undefined;
    void NativeApp.addListener('appStateChange',event => {if (active) setCapture(event.isActive);}).then(value => {if (active) listener=value;else void value.remove();});
    setCapture(true);return () => {active=false;void listener?.remove();};
  },[]);
  useEffect(() => {
    if (!connected || !capture || !localRef.current) return;let active=true;let next:ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const shots=await readPi(localRef.current!,confirmed);
        if (!active) return;
        const saved=await journal.commit(current => ({...current,shots:mergeLocal(current.shots,shots)}));
        if (active) {setLocal(saved);setPiStatus('CSV read · saved on this device');}
      } catch(failure) {if (active) setPiStatus(errorText(failure));}
      finally {if (active) next=setTimeout(poll,5000);}
    }
    void poll();return () => {active=false;clearTimeout(next);};
  },[connected,capture,confirmed,journal]);
  const base=source === 'cloud' ? cloudShots : local?.shots.filter(shot => source === 'demo' ? shot.record_kind === 'synthetic' : shot.source.kind === 'legacy_csv') ?? [];
  const activeProfile=source === 'cloud' ? profile : local?.profileId ?? '';
  const filtered=useMemo(() => activeProfile ? filterShots(base,{profileId:activeProfile,club}) : [],[base,activeProfile,club]);
  const shot=selectedShot(filtered,selection);
  const clubs=[...new Set(base.map(item => item.club))];
  const awaiting=local?.shots.filter(item => item.record_kind === 'real').length ?? 0;
  async function action(work:() => Promise<unknown>) {setBusy(true);setError('');setNotice('');try {await work();}catch(failure){setError(errorText(failure));}finally{setBusy(false);}}
  async function addSynthetic() {
    await action(async () => {
      const saved=await journal.commit(current => {
        const sequence=current.shots.filter(item => item.record_kind === 'synthetic').length+1;
        const item=structuredClone(fixtures[(sequence-1)%fixtures.length]) as Shot;
        const model=history.shots.find(path => path.shot === item.sequence_number && path.carry === item.carry_yards);
        item.shot_id=`synthetic_phone_${sequence}`;item.session_id='synthetic_phone_session';item.profile_id=current.profileId;item.device_id=current.deviceId;item.sequence_number=sequence;
        item.timestamp=new Date().toISOString();item.trajectory=model?.path as [number,number,number][] ?? null;
        return {...current,shots:[...current.shots,item]};
      });setLocal(saved);setSource('demo');setNotice('Synthetic shot saved locally. It will not upload to Firebase.');
    });
  }
  return <div className="workspace mobile-workspace"><header className="phone-header"><a href="#" onClick={() => setTab('practice')}>MODUS <b>Golf</b></a><span>{native ? 'Installed app · local practice' : 'Browser preview · local storage'}</span></header>
    <main><div className="page-heading"><div><p className="eyebrow">MODUS GOLF / {source === 'cloud' ? 'FIREBASE HISTORY' : 'ON THIS DEVICE'}</p><h1>{tab === 'sessions' ? 'History' : tab === 'bag' ? 'My Bag' : tab[0].toUpperCase()+tab.slice(1)}</h1><p>{source === 'cloud' ? cached ? 'Cached cloud records may be available offline.' : 'Firebase records received.' : 'Open practice and saved shots without internet.'}</p></div></div>
    {!native && <div className="source-banner"><strong>Browser preview</strong><span>This previews the iPhone UI and browser storage. Native Google sign-in and direct Pi transport require the installed iOS build.</span></div>}
    {error && <div className="error" role="alert">{error}<button className="text" onClick={() => setError('')}>Dismiss</button></div>}{notice && <div className="source-banner neutral" role="status">{notice}</div>}
    {!local && <p role="status">{error ? 'Local storage needs attention. Records have not been replaced with an empty dataset.' : 'Opening saved local practice…'}</p>}
    {['practice','sessions','bag'].includes(tab) && <><div className="filters"><label>Data source<select aria-label="Data source" value={source} onChange={event => setSource(event.target.value as Source)}><option value="pi">Local Pi shots</option><option value="demo">Synthetic test shots</option><option value="cloud" disabled={!user}>My Firebase history</option></select></label><label>Club<select value={club} onChange={event => {setClub(event.target.value);setSelection(null);}}><option value="">All clubs</option>{clubs.map(item => <option key={item} value={item}>{clubName(item)}</option>)}</select></label>{source === 'cloud' && <label>Golfer<select value={profile} onChange={event => setProfile(event.target.value)}>{profiles.map(item => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></label>}</div>
      <div className="source-banner neutral"><strong>{source === 'demo' ? 'Synthetic test records' : source === 'cloud' ? 'Private Firebase history' : 'Local capture history'}</strong><span>{source === 'demo' ? 'Never uploaded. Saved here for offline testing.' : source === 'cloud' ? 'Scoped to the signed-in account.' : 'Unconfirmed shots stay out of statistics. Cloud upload awaits pairing and the ingest service.'}</span></div></>}
    {tab === 'practice' && <><div className="section-title"><h2>{selection ? 'Selected saved shot' : 'Latest saved shot'}</h2><span className="tag">{source === 'demo' ? 'SYNTHETIC' : source === 'cloud' ? 'CLOUD' : 'LOCAL CSV'}</span></div><MetricCards shot={shot} units={units} primary/><MoreMetrics shot={shot} units={units}/>
      {filtered.length > 0 && <div className="recent-selector"><div className="section-title"><h2>Review a shot</h2><button className="text" onClick={() => setSelection(null)}>Follow latest</button></div><div className="shot-chips" role="group" aria-label="Recent shots">{filtered.slice(-8).reverse().map(item => <button key={item.shot_id} aria-pressed={item.shot_id === shot?.shot_id} className={item.shot_id === shot?.shot_id ? 'selected' : ''} onClick={() => setSelection(item.shot_id)}><span>#{item.sequence_number} · {clubName(item.club)}</span><strong>{displayMetric(item.carry_yards,'carry_yards',units)} <small>{units === 'metric' ? 'm' : 'yd'}</small></strong></button>)}</div></div>}
      <section className="panel"><h2>Flight views</h2><Trajectory shot={shot} shots={filtered} units={units}/></section>
      {!filtered.length && <Empty title="Your offline practice is ready">Connect to MODUS Wi-Fi to copy Pi shots, or add an explicitly synthetic test shot to try saving and reopening.</Empty>}
      <div className="button-row"><button disabled={!local || busy} onClick={() => void addSynthetic()}>Add synthetic test shot</button><button onClick={() => setTab('connection')}>Connect to Pi</button></div></>}
    {tab === 'sessions' && <><section className="panel"><div className="panel-heading"><h2>Saved shots · {filtered.length}</h2><button disabled={!filtered.length} onClick={() => download('modus-phone-history.csv',historyCsv(filtered),'text/csv')}>Export CSV</button></div><ShotList shots={filtered} units={units} selectedId={shot?.shot_id} onSelect={item => {setSelection(item.shot_id);setTab('practice');}}/></section><button onClick={() => setTab('bag')}>My Bag statistics</button></>}
    {tab === 'bag' && <Bag shots={filtered} profileId={activeProfile || 'phone_local_golfer'} demo={source === 'demo'} units={units}/>}
    {tab === 'connection' && <><section className="panel"><h2>Connect to your monitor</h2><p>The MODUS hotspot needs no internet. Wi-Fi is only needed while copying new Pi measurements; saved shots stay available afterward.</p><label>Pi address<input type="url" value={piAddress} disabled={connected} onChange={event => setPiAddress(event.target.value)}/></label><label className="checkbox"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)}/>I confirm this session contains physical shots, not the Pi's test-shot generator.</label><div className="button-row"><button className="primary" disabled={!native || !local || busy} onClick={() => void action(async () => {
      if (connected) {setConnected(false);setPiStatus('Disconnected · local history retained');return;}
      const origin=piOrigin(piAddress);const saved=await journal.commit(current => ({...current,piOrigin:origin}));setLocal(saved);localRef.current=saved;setSource('pi');setConnected(true);
    })}>{connected ? 'Disconnect Pi' : 'Start local connection'}</button></div><p role="status">{piStatus}</p><small>Reads only the existing /session.csv endpoint, at most once every five seconds in the foreground. No app hosting or new processing service runs on the Pi.</small></section>
      <section className="panel"><h2>Saved locally</h2><p>{local?.shots.length ?? 0} total records · {awaiting} confirmed physical records awaiting cloud pairing.</p><p>No upload acknowledgement exists yet. Pairing and the authenticated ingest service remain required before these records can reach Firebase.</p><button disabled={!local} onClick={() => download('modus-phone-local-backup.json',JSON.stringify({requires_owner_binding:true,local},null,2))}>Export local JSON backup</button><label>Display units<select value={units} onChange={event => setUnits(event.target.value as Units)}><option value="imperial">Imperial · mph / yards</option><option value="metric">Metric · km/h / meters</option></select></label></section></>}
    {tab === 'account' && <><section className="panel"><h2>{user ? 'Firebase account' : 'Sign in when online'}</h2><p>Offline practice works without signing in. New account creation and Google sign-in require internet.</p>{user ? <><p>{user.email}</p><button disabled={busy} onClick={() => void action(signOut)}>Sign out</button><button onClick={() => {setSource('cloud');setTab('sessions');}}>View my cloud history</button></> : <AccountForm busy={busy} run={action}/>}</section>{user && <section className="panel"><h2>Golfer profiles</h2><ul>{profiles.map(item => <li key={item.id}>{item.display_name}</li>)}</ul><form onSubmit={event => {event.preventDefault();const name=String(new FormData(event.currentTarget).get('name'));void action(() => createProfile(user.uid,name));}}><label>New golfer name<input name="name" maxLength={80} required/></label><button disabled={busy}>Add golfer</button></form><small>History filters do not change the ownership of local captures. Pairing is a separate action.</small></section>}</>}
    <footer className="workspace-footer"><span>MODUS GOLF · IPHONE APP SOURCE</span><span>{source === 'cloud' ? 'Firebase Authentication + Firestore' : 'Local persistence · cloud upload pending integration'}</span></footer></main>
    <nav className="bottom-nav" aria-label="App navigation">{navigation.map(item => <button key={item.id} className={tab === item.id || tab === 'bag' && item.id === 'sessions' ? 'active' : ''} onClick={() => setTab(item.id)}><Icon name={item.icon}/>{item.name}</button>)}</nav>
  </div>;
}
function AccountForm({busy,run}:{busy:boolean;run:(action:() => Promise<unknown>) => Promise<void>}) {
  const [create,setCreate]=useState(false);const [email,setEmail]=useState('');
  return <form onSubmit={event => {event.preventDefault();const password=String(new FormData(event.currentTarget).get('password'));void run(() => signInEmail(email,password,create));}}><fieldset disabled={busy}><label>Email<input name="email" type="email" autoComplete="email" required value={email} onChange={event => setEmail(event.target.value)}/></label><label>Password<input name="password" type="password" required minLength={create ? 8 : undefined} autoComplete={create ? 'new-password' : 'current-password'}/></label><button className="primary">{busy ? 'Please wait…' : create ? 'Create account' : 'Sign in'}</button><button type="button" onClick={() => void run(signInGoogle)}>Continue with Google</button><button type="button" onClick={() => setCreate(!create)}>{create ? 'Already registered? Sign in' : 'Create a new account'}</button><button type="button" onClick={() => void run(async () => {if (!email.trim()) throw new Error('Enter your email first.');await resetPassword(email);})}>Reset password</button></fieldset></form>;
}
createRoot(document.getElementById('root')!).render(<MobileApp/>);
