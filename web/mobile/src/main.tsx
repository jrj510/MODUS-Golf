import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Capacitor } from '@capacitor/core';
import { App as NativeApp } from '@capacitor/app';
import { Icon, MetricCards, MoreMetrics, Trajectory, ShotList, Empty } from '../../src/components';
import { Bag } from '../../src/bag';
import { clubName, filterShots, historyCsv, selectedShot, displayMetric, shotDate, type Shot, type Units } from '../../src/domain';
import fixtures from '../../MODUS_Golf_Firebase_AI_Starter/contracts/fixtures/demo_shots.json';
import history from '../../MODUS_Golf_Firebase_AI_Starter/contracts/fixtures/pi_history.json';
import { Journal, type LocalState } from './journal';
import { storagePort } from './storage';
import { readPi, selectMonitor } from './pi';
import { observeAccount, observeHistory, signInEmail, signInGoogle, signOut, resetPassword, createProfile, type AccountUser, type Profile } from './native-firebase';
import '../../src/style.css';
import './style.css';
import './appearance.css';
import { useAppearance, type Appearance } from './appearance';
import { useCloudSync } from './cloud-sync';
import { bindSession, belongsToAccount } from './sync-queue';
import { SyncPanel } from './SyncPanel';
import { createBackup, readBackup, restoreBackup } from './backup';
import { shareFile } from './share-file';
import { ClubInventory, SessionEditor, GolferForm } from './PracticeDetails';

import { TargetPractice, YardageCard } from './DistancePractice';
import { lastSequence, type TargetRound } from './practice-tools';
import { shotCue, speakCue, speechAvailable, stopSpeaking } from './spoken-cues';
import { PracticeTrends } from './PracticeTrends';
import { BallReadiness } from './BallReadiness';

type Tab='trends'|'practice'|'sessions'|'bag'|'connection'|'account';
type Source='pi'|'demo'|'cloud';
const navigation=[{id:'practice',name:'Practice',icon:'practice'},{id:'sessions',name:'History',icon:'sessions'},{id:'bag',name:'Bag',icon:'bag'},{id:'connection',name:'Monitor',icon:'settings'},{id:'account',name:'Account',icon:'cloud'}] as const;
const native=Capacitor.isNativePlatform();
function errorText(error:unknown) {return error instanceof Error ? error.message : 'The action could not be completed.';}

function MobileApp() {
  const {appearance,chooseAppearance,storageMessage}=useAppearance();
  const [journal]=useState(() => new Journal(storagePort()));
  const [local,setLocal]=useState<LocalState | null>(null);
  const [tab,setTab]=useState<Tab>('practice');
  const [source,setSource]=useState<Source>('pi');
  const [club,setClub]=useState('');
  const [selection,setSelection]=useState<string | null>(null);
  const [session,setSession]=useState('');
  const units=local?.units ?? 'imperial';
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [backup,setBackup]=useState<Awaited<ReturnType<typeof readBackup>> | null>(null);
  const [connected,setConnected]=useState(false);
  const [practicePlayer,setPracticePlayer]=useState('');
  const [round,setRound]=useState<TargetRound | null>(null);
  const [demoRound,setDemoRound]=useState<TargetRound | null>(null);
  const [voice,setVoice]=useState(false);
  const [voiceError,setVoiceError]=useState('');
  const cursor=useRef<{sessionId:string | null; sequence:number} | null>(null);
  const [capture,setCapture]=useState(false);
  const [confirmedFilename,setConfirmedFilename]=useState<string | null>(null);
  const [sessionFilename,setSessionFilename]=useState<string | null>(null);
  const [lastRead,setLastRead]=useState<Date | null>(null);
  const [lastSaved,setLastSaved]=useState<Date | null>(null);
  const pollInFlight=useRef(Promise.resolve());
  const [piStatus,setPiStatus]=useState('Not connected');
  const [piAddress,setPiAddress]=useState('http://10.42.0.1:8000');
  const [user,setUser]=useState<AccountUser | null>(null);
  const [cloudShots,setCloudShots]=useState<Shot[]>([]);
  const [profiles,setProfiles]=useState<Profile[]>([]);
  const [profile,setProfile]=useState('');
  const [cached,setCached]=useState(true);
  const [skippedCloudShots,setSkippedCloudShots]=useState(0);
  const [cloudCursors,setCloudCursors]=useState<string[]>([]);
  const [loadedCloudCursors,setLoadedCloudCursors]=useState<string[]>([]);
  const [nextCloudCursor,setNextCloudCursor]=useState<string | null>(null);
  const [cloudLoading,setCloudLoading]=useState(false);
  const [cloudRefresh,setCloudRefresh]=useState(0);
  const [busy,setBusy]=useState(false);
  const busyRef=useRef(false);
  const localRef=useRef(local);localRef.current=local;
  const accountRef=useRef<string | null>(null);
  const voiceActive=voice && capture && connected && (tab === 'connection' || (tab === 'practice' && source === 'pi'));
  const canSpeak=useRef(false);canSpeak.current=voiceActive;
  const failVoice=useCallback(() => {setVoice(false);setVoiceError('Speech unavailable. Check the iPhone voice and audio settings, then try again.');},[]);
  const readyCue=useCallback(() => {if (canSpeak.current) speakCue('Ready.',failVoice);},[failVoice]);
  useEffect(() => {if (!voiceActive) stopSpeaking();return stopSpeaking;},[voiceActive]);
  const sync=useCloudSync(journal,local,user?.uid,capture,() => accountRef.current,setLocal);
  const visibleLocal=useMemo(() => local?.shots.filter(shot => {
    const binding=local.sync?.bindings[shot.session_id];
    return !binding || belongsToAccount(binding,user?.uid);
  }) ?? [],[local,user?.uid]);
  useEffect(() => {void journal.load().then(data => {setLocal(data);setPiAddress(data.piOrigin);}).catch(error => setError(errorText(error)));},[journal]);
  useEffect(() => {window.scrollTo({top:0});},[tab]);
  useEffect(() => {setSelection(null);setClub('');setSession('');},[source,profile]);
  useEffect(() => {
    if (!native) return;let active=true;let stop:(() => void) | undefined;
    void observeAccount(current => {
      if (!active) return;
      if (accountRef.current !== (current?.uid ?? null)) {setPracticePlayer('');setConfirmedFilename(null);setRound(null);setDemoRound(null);cursor.current=null;stopSpeaking();setCloudShots([]);setCloudCursors([]);setLoadedCloudCursors([]);setNextCloudCursor(null);setBackup(null);setSkippedCloudShots(0);setProfiles([]);setProfile('');setSource(value => value === 'cloud' ? 'pi' : value);}
      accountRef.current=current?.uid ?? null;setUser(current);
    }).then(cleanup => {if (active) stop=cleanup;else cleanup();}).catch(() => {/* Firebase is optional for starting local practice. Account actions report configuration errors. */});
    return () => {active=false;stop?.();};
  },[]);
  useEffect(() => {
    if (!user) return;let active=true;let stop:(() => void) | undefined;const uid=user.uid;
    setCloudLoading(true);
    void observeHistory(uid,(items,fromCache,skipped,nextCursor) => {if (active && accountRef.current === uid) {setCloudShots(items);setCached(fromCache);setSkippedCloudShots(skipped);setLoadedCloudCursors(cloudCursors);setNextCloudCursor(nextCursor);setCloudLoading(false);}},items => {if (active && accountRef.current === uid) setProfiles(items);},failure => {if (active && accountRef.current === uid) {setCloudLoading(false);setCached(true);setError(failure.message);}},cloudCursors.at(-1))
      .then(cleanup => {if (active) stop=cleanup;else cleanup();}).catch(failure => {if (active && accountRef.current === uid) {setCloudLoading(false);setError(errorText(failure));}});
    return () => {active=false;stop?.();};
  },[user?.uid,cloudCursors,cloudRefresh]);
  useEffect(() => {if (!profiles.some(item => item.id === profile)) setProfile(profiles[0]?.id ?? '');},[profiles,profile]);
  useEffect(() => {
    if (!native) return;let active=true;let listener:{remove:() => Promise<void>} | undefined;
    void NativeApp.addListener('appStateChange',event => {if (active) {if (!event.isActive) {cursor.current=null;canSpeak.current=false;stopSpeaking();}setCapture(event.isActive);}}).then(value => {if (active) listener=value;else void value.remove();});
    setCapture(true);return () => {active=false;void listener?.remove();};
  },[]);
  useEffect(() => {
    const state=localRef.current;
    if (!connected || !capture || !state) return;
    let active=true;
    let next: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const snapshot=await readPi(state!,confirmedFilename);
        if (!active) return;
        setSessionFilename(snapshot.filename);
        const uid = user?.uid ?? null;
        const current = () => active && accountRef.current === uid;
        const saved=await journal.mergeCapture(snapshot.shots, current,
          {uid, profileId:practicePlayer, confirmedFile:confirmedFilename});
        if (!current()) return;
        const sessionId=snapshot.shots[0]?.session_id ?? null;
        const sequence=lastSequence(snapshot.shots);
        const previous=cursor.current;
        cursor.current={sessionId,sequence:previous?.sessionId === sessionId ? Math.max(sequence,previous.sequence) : sequence};
        setLastRead(new Date());
        if (sessionId) {
          const known=lastSequence((localRef.current?.shots ?? []).filter(s => s.session_id === sessionId));
          setRound(r => {
            if (!r || r.through !== undefined || r.sessionId === sessionId) return r;
            if (r.sessionId) return {...r,through:lastSequence((localRef.current?.shots ?? []).filter(s => s.session_id === r.sessionId))};
            return {...r,sessionId,after:known};
          });
          if (canSpeak.current && previous && (previous.sessionId === sessionId || previous.sessionId === null) &&
              sequence > previous.sequence && sequence > known) {
            const newest=snapshot.shots.find(s => s.sequence_number === sequence);
            if (newest) speakCue(shotCue(newest,localRef.current?.units ?? 'imperial'),failVoice);
          }
        }
        if (saved) {
          setLocal(saved);
          setLastSaved(new Date());
        }
        if (!active) return;
        if (!snapshot.shots.length) setPiStatus('Monitor reached · waiting for the first shot');
        else setPiStatus(saved ? 'New measurements saved on this iPhone' : 'Monitor reached · shots up to date');
      } catch (failure) {
        if (active) {
          cursor.current=null;setLastRead(null);
          setPiStatus(errorText(failure));
        }
      } finally {
        if (active) next=setTimeout(schedule,5000);
      }
    }
    function schedule() {
      pollInFlight.current=pollInFlight.current.then(async () => {
        if (active) await poll();
      });
    }
    schedule();
    return () => {active=false;clearTimeout(next);};
  },[connected,capture,confirmedFilename,journal,practicePlayer,user?.uid,failVoice]);
  const base=useMemo(() => source === 'cloud' ? cloudShots : visibleLocal.filter(shot => source === 'demo' ? shot.record_kind === 'synthetic' : shot.source.kind === 'legacy_csv'),[source,cloudShots,visibleLocal]);
  const activeProfile=source === 'cloud' ? profile : local?.profileId ?? '';
  const sessions=useMemo(() => {
    const items=new Map<string,{label:string; count:number}>();
    for (const shot of base) {
      if (shot.profile_id !== activeProfile) continue;
      const item=items.get(shot.session_id);
      if (item) item.count++;
      else items.set(shot.session_id,{label:(source !== 'cloud' && local?.sessionDetails?.[shot.session_id]?.name) || shot.source.filename || (source === 'demo' ? 'Synthetic practice' : shotDate(shot) || 'Undated session'),count:1});
    }
    return [...items.entries()].reverse();
  },[activeProfile,base,source,local?.sessionDetails]);
  const filtered=useMemo(() => activeProfile ? filterShots(base,{profileId:activeProfile,club,sessionId:session}) : [],[base,activeProfile,club,session]);
  const practiceShots=useMemo(() => {
    if (source !== 'pi' || selection) return filtered;
    return filtered.filter(s => {
      const binding=local?.sync?.bindings[s.session_id];
      return binding ? binding.profileId === practicePlayer : !practicePlayer || (connected &&
        s.device_id === local?.deviceId && s.source.filename === sessionFilename);
    });
  },[filtered,source,selection,practicePlayer,local?.sync,local?.deviceId,connected,sessionFilename]);
  const shot=selectedShot(practiceShots,selection);
  const clubs=[...new Set(base.map(item => item.club))];
  const clubLabels=Object.fromEntries((local?.bag ?? []).filter(club => !club.archived && club.monitorLabel).map(club => [club.monitorLabel,club.name]));
  async function action(work:() => Promise<unknown>):Promise<boolean> {
    if (busyRef.current) return false;
    busyRef.current=true;setBusy(true);setError('');setNotice('');
    try {await work();return true;}
    catch(failure) {setError(errorText(failure));return false;}
    finally {busyRef.current=false;setBusy(false);}
  }
  function changeCloudPage(cursors:string[]) {setCloudLoading(true);setSelection(null);setSession('');setCloudCursors(cursors);}
  async function connectMonitor(address:string) {
    const saved = await journal.commit(current => selectMonitor(current,address));
    setLocal(saved);
    localRef.current = saved;
    setPiAddress(saved.piOrigin);
    cursor.current=null;setLastRead(null);
    setLastSaved(null);
    setSource('pi');
    setPiStatus('Connecting to monitor…');
    setConnected(true);
  }
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
  const selectedGolfer=profiles.find(p => p.id === practicePlayer);
  function changePlayer(id:string) {
    setPracticePlayer(id);setSelection(null);setSession('');setConfirmedFilename(null);setRound(null);cursor.current=null;setLastRead(null);stopSpeaking();
  }
  function endRound(demo = false) {
    const update = demo ? setDemoRound : setRound;
    update(r => r && r.through === undefined ? {...r,through:lastSequence(visibleLocal.filter(s => s.session_id === r.sessionId))} : r);
  }
  const practiceSetup=<section className="panel"><h2>Practice setup</h2>
    <label>Playing as<select value={practicePlayer} onChange={e => changePlayer(e.target.value)}>
      <option value="">Guest · local practice</option>{profiles.map(p => <option key={p.id} value={p.id}>{p.display_name}</option>)}
    </select></label>
    {practicePlayer && <button onClick={() => changePlayer('')}>Play as guest</button>}
    {user && !profiles.length && <button onClick={() => setTab('account')}>Manage golfer profiles</button>}
    {!user && <small>Guest practice works offline. Your saved account golfers appear here when signed in.</small>}
    {sessionFilename && connected && <label className="checkbox"><input type="checkbox"
      disabled={!!practicePlayer && !selectedGolfer} checked={confirmedFilename === sessionFilename}
      onChange={e => setConfirmedFilename(e.target.checked ? sessionFilename : null)}/>
      {selectedGolfer ? 'Confirm physical shots and link all shots in '+sessionFilename+' to '+selectedGolfer.display_name+' for automatic upload.'
        : 'Confirm physical shots for '+sessionFilename+'.'}</label>}
    {selectedGolfer && <p>Use a fresh monitor session when switching golfers. Confirm the session here once its file appears.</p>}
    {connected && !lastRead && <small role="status">{piStatus}</small>}
    <label className="checkbox"><input type="checkbox" checked={voice} disabled={!speechAvailable()} onChange={e => {
      setVoiceError('');setVoice(e.target.checked);
      if (e.target.checked) speakCue('Spoken cues on.',failVoice); else stopSpeaking();
    }}/>Speak ready and new shot results</label>
    {voiceError && <small role="status">{voiceError}</small>}{!speechAvailable() && <small>Speech is unavailable on this device.</small>}
  </section>;
  return <div className="workspace mobile-workspace"><header className="phone-header"><a href="#" onClick={() => setTab('practice')}>MODUS <b>Golf</b></a><span>{native ? 'Installed app · local practice' : 'Browser preview · local storage'}</span></header>
    <main><div className="page-heading"><h1>{navigation.find(item => item.id === tab)?.name ?? 'Practice trends'}</h1></div>
    {(tab === 'connection' || (tab === 'practice' && source === 'pi')) && <BallReadiness
      origin={local?.piOrigin ?? piAddress} connected={connected} foreground={capture}
      onPractice={tab === 'practice'} canConnect={native && !!local && !busy}
      connect={() => local && void action(() => connectMonitor(local.piOrigin))}
      onReady={readyCue} settings={() => setTab('connection')}/>}
    {!native && <div className="source-banner"><strong>Browser preview</strong><span>This previews the iPhone UI and browser storage. Native Google sign-in and direct Pi transport require the installed iOS build.</span></div>}
    {error && <div className="error" role="alert">{error}<button className="text" onClick={() => setError('')}>Dismiss</button></div>}{notice && <div className="source-banner neutral" role="status">{notice}</div>}
    {source === 'cloud' && skippedCloudShots > 0 && <p role="status">{skippedCloudShots} cloud records could not be read. History and statistics show the valid records only.</p>}
    {source === 'cloud' && ['practice','sessions','bag','trends'].includes(tab) && <section className="panel" aria-label="Cloud history pages">
      <p>Cloud history · page {loadedCloudCursors.length+1}. Statistics, filters and exports use the loaded page, up to 100 records.</p>
      <p>{cached ? 'Cached results may be incomplete. Reconnect and refresh to check for more history.' : 'Refresh to include newly uploaded records.'}</p>
      {cloudLoading && <p role="status">Loading cloud history…</p>}
      <div className="button-row">
        <button disabled={cloudLoading || !loadedCloudCursors.length} onClick={() => changeCloudPage(loadedCloudCursors.slice(0,-1))}>Previous page</button>
        <button disabled={cloudLoading || !nextCloudCursor} onClick={() => nextCloudCursor && changeCloudPage([...loadedCloudCursors,nextCloudCursor])}>Next page</button>
        <button disabled={cloudLoading} onClick={() => {changeCloudPage([]);setCloudRefresh(value => value+1);}}>Refresh history</button>
      </div>
    </section>}
    {!local && <p role="status">{error ? 'Local storage needs attention. Records have not been replaced with an empty dataset.' : 'Opening saved local practice…'}</p>}
    {['practice','sessions','bag','trends'].includes(tab) && <><div className="filters"><label>Data source<select aria-label="Data source" value={source} onChange={event => setSource(event.target.value as Source)}><option value="pi">Local Pi shots</option><option value="demo">Synthetic test shots</option><option value="cloud" disabled={!user}>My cloud history</option></select></label>{tab !== 'trends' && <label>Filter by club<select value={club} onChange={event => {setClub(event.target.value);setSelection(null);}}><option value="">All clubs</option>{clubs.map(item => <option key={item} value={item}>{clubLabels[item] ?? clubName(item)}</option>)}</select></label>}{source === 'cloud' && <label>Golfer<select value={profile} onChange={event => setProfile(event.target.value)}>{profiles.map(item => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></label>}</div>
      <div className="source-banner neutral"><strong>{source === 'demo' ? 'Synthetic test records' : source === 'cloud' ? 'Private cloud history' : 'Local capture history'}</strong><span>{source === 'demo' ? 'Never uploaded. Saved here for offline testing.' : source === 'cloud' ? 'Scoped to the signed-in account.' : 'Confirm a physical session in Monitor to include its shots in statistics.'}</span></div></>}
    {tab === 'trends' && <PracticeTrends key={JSON.stringify([source,user?.uid,activeProfile])} shots={base} source={source}
      profileId={activeProfile} uid={user?.uid} local={local} profiles={profiles} units={units} initialClub={club} initialSession={session} clubLabels={clubLabels}/>}
    {tab === 'practice' && <>{source === 'pi' && practiceSetup}
      {source !== 'cloud' && <TargetPractice round={source === 'demo' ? demoRound : round} units={units} demo={source === 'demo'} shots={visibleLocal}
        available={!!local && (source === 'demo' || (!!cursor.current && capture && connected && !!lastRead))}
        finish={() => endRound(source === 'demo')} start={(distance,tolerance) => {
          const baseline=source === 'demo' ? {sessionId:'synthetic_phone_session',sequence:lastSequence(visibleLocal.filter(s => s.record_kind === 'synthetic'))} : cursor.current;
          if (baseline) (source === 'demo' ? setDemoRound : setRound)({distance,tolerance,units,sessionId:baseline.sessionId,after:baseline.sequence});
        }}/>}
      {source === 'demo' && <button disabled={!local || busy} onClick={() => void addSynthetic()}>Add demo shot</button>}
      {shot && <><div className="section-title"><h2>{selection ? 'Selected saved shot' : source === 'cloud' ? 'Latest shot on this page' : 'Latest saved shot'}</h2><span className="tag">{source === 'demo' ? 'SYNTHETIC' : source === 'cloud' ? 'CLOUD' : 'LOCAL CSV'}</span></div><MetricCards shot={shot} units={units} primary/><MoreMetrics shot={shot} units={units}/>
      {practiceShots.length > 0 && <div className="recent-selector"><div className="section-title"><h2>Review a shot</h2><button className="text" onClick={() => setSelection(null)}>Follow latest</button></div><div className="shot-chips" role="group" aria-label="Recent shots">{practiceShots.slice(-8).reverse().map(item => <button key={item.shot_id} aria-pressed={item.shot_id === shot?.shot_id} className={item.shot_id === shot?.shot_id ? 'selected' : ''} onClick={() => setSelection(item.shot_id)}><span>#{item.sequence_number} · {clubLabels[item.club] ?? clubName(item.club)}</span><strong>{displayMetric(item.carry_yards,'carry_yards',units)} <small>{units === 'metric' ? 'm' : 'yd'}</small></strong></button>)}</div></div>}
      <button onClick={() => setTab('trends')}>View practice trends</button>
      <section className="panel"><h2>Flight views</h2><Trajectory shot={shot} shots={practiceShots} units={units}/></section></>}
      {!practiceShots.length && <Empty title={source === 'cloud' ? cloudLoading ? 'Loading your history' : 'No cloud shots in this view' : club ? 'No shots for this club' : 'No saved shots in this view'}>{source === 'cloud' ? 'Check your golfer and club filters. Confirm and link a monitor session in Account to upload saved shots.' : club ? 'Choose All clubs to see the rest of your saved practice.' : source === 'demo' ? 'Add a sample shot to explore its metrics and flight.' : 'Join MODUS Wi-Fi and connect the monitor to capture shots.'}</Empty>}
      </>}
    {tab === 'sessions' && <><label>Practice session<select value={session} onChange={event => {setSession(event.target.value);setSelection(null);}}><option value="">All sessions</option>{sessions.map(([id,item]) => <option key={id} value={id}>{item.label} · {item.count} shots</option>)}</select></label>{source !== 'cloud' && session && sessions.some(([id]) => id === session) &&
      <SessionEditor key={session} details={local?.sessionDetails?.[session]} busy={busy} save={details => void action(async () => {
        const uid=accountRef.current;
        const saved=await journal.commit(current => {
          const binding=current.sync?.bindings[session];
          if (binding && (!belongsToAccount(binding,uid) || accountRef.current !== uid)) throw new Error('Sign in to edit this session.');
          return {...current,sessionDetails:{...current.sessionDetails,[session]:details}};
        });
        setLocal(saved);setNotice('Session details saved.');
      })}/>}<button disabled={!filtered.some(s => s.processing_state === 'final' && s.record_kind === (source === 'demo' ? 'synthetic' : 'real'))} onClick={() => setTab('trends')}>Compare session averages</button>
      <section className="panel"><div className="panel-heading"><h2>Saved shots · {filtered.length}</h2><button disabled={!filtered.length || busy} onClick={() => void action(() => shareFile('modus-phone-history.csv',historyCsv(filtered),'text/csv'))}>Export CSV</button></div><ShotList shots={filtered} units={units} selectedId={shot?.shot_id} onSelect={item => {setSelection(item.shot_id);setTab('practice');}}/></section><button onClick={() => setTab('bag')}>My Bag statistics</button></>}
    {tab === 'bag' && <><button onClick={() => setTab('trends')}>View practice trends</button>
      <YardageCard shots={club ? base.filter(s => s.club === club) : base} source={source} profileId={activeProfile} uid={user?.uid} local={local}
        profiles={profiles} units={units} names={clubLabels}/>{local && <ClubInventory clubs={local.bag ?? []} reported={[...new Set(visibleLocal.filter(item => item.record_kind !== 'synthetic').map(item => item.club))]} busy={busy} save={club => action(async () => {
      const saved=await journal.commit(current => {
        const bag=current.bag ?? [];
        const id=club.id || 'club_'+Date.now().toString(36);
        if (!club.archived && club.monitorLabel && bag.some(item => item.id !== id && !item.archived && item.monitorLabel === club.monitorLabel)) {
          throw new Error('That monitor label already matches an active club.');
        }
        const updated={...club,id};
        return {...current,bag:club.id ? bag.map(item => item.id === id ? updated : item) : [...bag,updated]};
      });
      setLocal(saved);setNotice('Club saved.');
    })}/>}<Bag shots={filtered} profileId={activeProfile || 'phone_local_golfer'} demo={source === 'demo'} units={units} clubLabels={clubLabels}/></>}
    {tab === 'connection' && <><section className="panel"><h2>Connect to your monitor</h2><p>Power on your monitor, join MODUS in iPhone Settings → Wi-Fi, then return here. Allow Local Network access when iOS asks. Saved shots remain available after you leave MODUS Wi-Fi.</p><label>Pi address<input type="url" value={piAddress} disabled={connected} onChange={event => setPiAddress(event.target.value)}/></label><div className="button-row"><button className="primary" disabled={!native || !local || busy} onClick={() => void action(async () => {
      if (connected) {
        endRound();cursor.current=null;setLastRead(null);setConnected(false);setConfirmedFilename(null);setSessionFilename(null);
        setPiStatus('Disconnected · local history retained');
      } else await connectMonitor(piAddress);
    })}>{connected ? 'Disconnect monitor' : 'Connect monitor'}</button>{connected && <button onClick={() => {setSource('pi');setTab('practice');}}>View practice</button>}</div><p role="status">{connected && !capture ? 'Phone capture paused' : piStatus}</p>{lastRead && <p>Last successful read: {lastRead.toLocaleTimeString()}</p>}{lastSaved && <p>Last saved measurements: {lastSaved.toLocaleTimeString()}</p>}</section>
      {practiceSetup}<section className="panel"><h2>Saved locally</h2><p>{visibleLocal.length} records available on this iPhone.</p><button disabled={!local || busy} onClick={() => {
        if (local) void action(() => shareFile('modus-phone-local-backup.json',createBackup(local,visibleLocal),'application/json'));
      }}>Export local JSON backup</button>
      {connected && <p>Disconnect the monitor before restoring a backup.</p>}
      <label>Choose a backup to restore<input type="file" accept=".json,application/json" disabled={!local || busy || connected} onChange={event => {
        const file=event.target.files?.[0];
        event.target.value='';
        setBackup(null);
        const uid=accountRef.current;
        if (file) void action(async () => {
          const preview=await readBackup(file);
          if (uid === accountRef.current) setBackup(preview);
        });
      }}/></label>
      {backup && <div><p>{backup.shots.length} shots and {backup.bag.length} clubs in this backup. Restore also recovers session notes and monitor settings. Existing names, clubs and display preferences are kept; matching shots keep their latest revision.</p>
        <button disabled={busy || connected} onClick={() => void action(async () => {
          const uid=accountRef.current;
          const saved=await journal.commit(current => {
            if (uid !== accountRef.current) throw new Error('The signed-in account changed.');
            return restoreBackup(current,backup,uid);
          });
          setLocal(saved);setPiAddress(saved.piOrigin);setBackup(null);setNotice('Backup merged on this iPhone.');
        })}>Restore backup</button><button disabled={busy} onClick={() => setBackup(null)}>Cancel restore</button></div>}
      <label>Display units<select value={units} disabled={!local || busy} onChange={event => {
        const units=event.target.value as Units;
        void action(async () => setLocal(await journal.commit(current => ({...current,units}))));
      }}><option value="imperial">Imperial · mph / yards</option><option value="metric">Metric · km/h / meters</option></select></label></section><section className="panel"><h2>Demo practice</h2><p>Save a synthetic shot to try practice without the monitor.</p><button disabled={!local || busy} onClick={() => void addSynthetic()}>Add synthetic test shot</button></section></>}
    {tab === 'account' && <><section className="panel"><label>Appearance<select value={appearance}
      onChange={event => chooseAppearance(event.target.value as Appearance)}>
      <option value="classic">MODUS default</option><option value="light">Light</option><option value="dark">Dark</option>
    </select></label>{storageMessage && <p role="status">{storageMessage}</p>}</section><section className="panel"><h2>{user ? 'Your account' : 'Sign in when online'}</h2><p>Offline practice works without signing in. New account creation and Google sign-in require internet.</p>{user ? <><p>{user.email}</p><button disabled={busy} onClick={() => void action(signOut)}>Sign out</button><button onClick={() => {setSource('cloud');setTab('sessions');}}>View my cloud history</button></> : <AccountForm busy={busy} run={action} notify={setNotice}/>}</section>{user && <section className="panel"><h2>Golfer profiles</h2><ul>{profiles.map(item => <li key={item.id}>{item.display_name}</li>)}</ul><GolferForm key={user.uid} busy={busy} save={name => action(async () => {await createProfile(user.uid,name);setNotice('Golfer saved. You can now link a practice session below.');})}/><small>History filters do not change the ownership of local captures. Pairing is a separate action.</small></section>}{user && local && <SyncPanel key={user.uid} local={local} user={user} profiles={profiles} busy={busy} status={sync.status} retry={sync.retry} bind={(sessionId,profileId) => action(async () => {
      const uid=user.uid;
      const saved=await journal.commit(current => {
        if (accountRef.current !== uid) throw new Error('The signed-in account changed.');
        return bindSession(current,sessionId,{uid,profileId});
      });
      setLocal(saved);
      setNotice('Practice session linked.');
      sync.retry();
    })}/>}</>}
    <footer className="workspace-footer"><span>MODUS GOLF</span><span>{source === 'cloud' ? 'Private cloud history' : 'Local practice · saved on this device'}</span></footer></main>
    <nav className="bottom-nav" aria-label="App navigation">{navigation.map(item => <button key={item.id} className={(tab === item.id || (tab === 'trends' && item.id === 'bag')) ? 'active' : ''} aria-current={tab === item.id ? 'page' : undefined} onClick={() => setTab(item.id)}><Icon name={item.icon}/>{item.name}</button>)}</nav>
  </div>;
}
function AccountForm({busy,run,notify}:{busy:boolean;run:(action:() => Promise<unknown>) => Promise<boolean>;notify:(message:string) => void}) {
  const [create,setCreate]=useState(false);const [email,setEmail]=useState('');
  return <form onSubmit={event => {event.preventDefault();const password=String(new FormData(event.currentTarget).get('password'));void run(() => signInEmail(email.trim(),password,create));}}><fieldset disabled={busy}><label>Email<input name="email" type="email" autoComplete="email" required value={email} onChange={event => setEmail(event.target.value)}/></label><label>Password<input name="password" type="password" required minLength={create ? 8 : undefined} autoComplete={create ? 'new-password' : 'current-password'}/></label><button className="primary">{busy ? 'Please wait…' : create ? 'Create account' : 'Sign in'}</button><button type="button" onClick={() => void run(signInGoogle)}>Continue with Google</button><button type="button" onClick={() => setCreate(!create)}>{create ? 'Already registered? Sign in' : 'Create a new account'}</button><button type="button" onClick={() => void run(async () => {if (!email.trim()) throw new Error('Enter your email first.');await resetPassword(email.trim());notify('If an eligible account uses this email, password reset instructions have been sent. Check your inbox and spam folder.');})}>Reset password</button></fieldset></form>;
}
createRoot(document.getElementById('root')!).render(<MobileApp/>);
