import { useEffect, useMemo, useState } from 'react';
import { signOut, type User } from 'firebase/auth';
import { auth } from './firebase';
import { Account } from './account';
import { DemoRepository, LocalPiRepository } from './demo';
import { FirebaseRepository, type Profile } from './repository';
import { filterShots, summary, clubName, unitFor, displayMetric, sessionLabel, historyCsv, sourceName, selectedShot, type Shot, type Units } from './domain';
import { Icon, Empty, MetricCards, MoreMetrics, CarryTrend, Trajectory, ShotDetail, ShotList, download } from './components';
import { ImportPreview } from './import-preview';
import { Bag } from './bag';
type Tab = 'practice' | 'sessions' | 'bag' | 'settings';
type Source = 'demo' | 'cloud' | 'import';
const tabs: { id: Tab; name: string; description: string }[] = [
  { id: 'practice', name: 'Practice', description: 'A clearer picture of every shot.' },
  { id: 'sessions', name: 'Sessions', description: 'Your range time, remembered.' },
  { id: 'bag', name: 'My Bag', description: 'Know your numbers. Find your gaps.' },
  { id: 'settings', name: 'Settings', description: 'Your golfers, preferences, and connection.' },
];
function startingUnits(): Units { try { return localStorage.getItem('modus-units') === 'metric' ? 'metric' : 'imperial'; } catch { return 'imperial'; } }
function initialTab(): Tab { const hash = location.hash.slice(1); return tabs.some(tab => tab.id === hash) ? hash as Tab : 'practice'; }
export function Workspace({ user, onSignIn }: { user: User | null; onSignIn: () => void }) {
  const [demo] = useState(() => new DemoRepository());
  const [tab, setTab] = useState<Tab>(initialTab);
  const [source, setSource] = useState<Source>(user ? 'cloud' : 'demo');
  const [demoProfiles, setDemoProfiles] = useState<Profile[]>(demo.profiles);
  const [cloudProfiles, setCloudProfiles] = useState<Profile[]>([]);
  const [cloudShots, setCloudShots] = useState<Shot[]>([]);
  const [imported, setImported] = useState<{ shots: Shot[]; profiles: Profile[] }>({ shots: [], profiles: [] });
  const [profileId, setProfileId] = useState(user ? '' : demo.profiles[0]?.id ?? '');
  const [club, setClub] = useState('');
  const [session, setSession] = useState('');
  const [date, setDate] = useState('');
  const [detailId, setDetailId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [units, setUnits] = useState<Units>(startingUnits);
  const [showImport, setShowImport] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [serverTime, setServerTime] = useState<Date | null>(null);
  const [fromCache, setFromCache] = useState(false);
  const [retry, setRetry] = useState(0);
  const profiles = source === 'cloud' ? cloudProfiles : source === 'demo' ? demoProfiles : imported.profiles;
  const shots = source === 'cloud' ? cloudShots : source === 'demo' ? demo.shots : imported.shots;
  useEffect(() => { try { localStorage.setItem('modus-units', units); } catch { /* Optional display preference, never private records. */ } }, [units]);
  useEffect(() => { const change = () => setTab(initialTab()); addEventListener('hashchange', change); return () => removeEventListener('hashchange', change); }, []);
  useEffect(() => { window.scrollTo({ top: 0 }); }, [tab]);
  useEffect(() => { if (detailId) document.querySelector('.shot-detail')?.scrollIntoView({ block: 'start' }); }, [detailId]);
  useEffect(() => {
    setDetailId(null); setSelectedId(null); setClub(''); setSession(''); setDate(''); setShowImport(false); setError('');
    setCloudShots([]); setCloudProfiles([]); setServerTime(null); setFromCache(false);
    if (source !== 'cloud' || !user) { setLoading(false); return; }
    let active = true; setLoading(true);
    const repository = new FirebaseRepository(user.uid);
    const failure = (e: Error) => { if (active) { setCloudShots([]); setError(e.message); setLoading(false); } };
    const stopProfiles = repository.watchProfiles(items => { if (active) setCloudProfiles(items); }, failure);
    const stopShots = repository.watchShots((items, cached) => {
      if (!active) return;
      setCloudShots(items); setFromCache(cached); setLoading(cached);
      if (!cached) { setServerTime(new Date()); setError(''); }
    }, failure);
    return () => { active = false; stopProfiles(); stopShots(); };
  }, [source, user?.uid, retry]);
  useEffect(() => { if (!profiles.some(profile => profile.id === profileId)) setProfileId(profiles[0]?.id ?? ''); }, [profiles, profileId]);
  useEffect(() => { setClub(''); setSession(''); setDate(''); setDetailId(null); setSelectedId(null); }, [profileId]);
  useEffect(() => { setSelectedId(null); }, [club, session, date]);
  const profileShots = useMemo(() => profileId ? filterShots(shots, { profileId }) : [], [shots, profileId]);
  const filtered = useMemo(() => profileId ? filterShots(shots, { profileId, club, sessionId: session, date }) : [], [shots, profileId, club, session, date]);
  const latest = selectedShot(filtered, selectedId);
  const newest = filtered.at(-1);
  const newerCount = selectedId && latest ? Math.max(0, filtered.length - 1 - filtered.findIndex(shot => shot.shot_id === latest.shot_id)) : 0;
  const detail = detailId ? shots.find(shot => shot.shot_id === detailId && shot.profile_id === profileId) : undefined;
  const selectedProfile = profiles.find(profile => profile.id === profileId);
  const clubs = [...new Set(profileShots.map(shot => shot.club))];
  const sessions = [...new Set(profileShots.map(shot => shot.session_id))];
  const info = tabs.find(item => item.id === tab)!;
  const stats = profileId ? summary(filtered, profileId, source === 'demo') : null;
  const open = (id: Tab) => { setTab(id); location.hash = id; setDetailId(null); };
  const status = source === 'demo' ? 'Synthetic demo · no device connected' : source === 'import' ? 'Local preview · not uploaded' : error ? 'Cloud connection needs attention' : loading ? 'Connecting to Firestore…' : 'Cloud history · updates automatically';
  const filterControls = <div className="filters"><label>Golfer<select aria-label="History golfer" value={profileId} onChange={e => setProfileId(e.target.value)}><option value="" disabled>{profiles.length ? 'Select golfer' : 'No golfer profiles'}</option>{profiles.map(profile => <option value={profile.id} key={profile.id}>{profile.display_name}</option>)}</select></label>
    <label>Club<select value={club} onChange={e => { setClub(e.target.value); setSelectedId(null); }}><option value="">All clubs</option>{clubs.map(c => <option key={c} value={c}>{clubName(c)}</option>)}</select></label>
    <label>Session<select value={session} onChange={e => { setSession(e.target.value); setSelectedId(null); }}><option value="">All sessions</option>{sessions.map(id => <option value={id} key={id}>{sessionLabel(profileShots, id)}</option>)}</select></label>
    {tab === 'sessions' && <label>UTC / source date<input type="date" value={date} onChange={e => setDate(e.target.value)}/></label>}
    <small className="filter-hint">History filters only. Capture ownership is unchanged.</small></div>;
  return <div className="app-shell"><a className="skip-link" href="#main-content">Skip to content</a><aside className="sidebar"><a className="brand" href="#practice" onClick={() => open('practice')}><span className="brand-symbol"><Icon name="practice"/></span><span>MODUS <b>Golf</b><small>LAUNCH MONITOR</small></span></a><p className="sidebar-label">YOUR PRACTICE</p><nav aria-label="Main navigation">{tabs.map(item => <button className={tab === item.id ? 'active' : ''} aria-current={tab === item.id ? 'page' : undefined} onClick={() => open(item.id)} key={item.id}><Icon name={item.id}/><span>{item.name}</span></button>)}</nav><div className="sidebar-note"><Icon name="cloud"/><p>Built around your game.</p><small>Accounts and history in the cloud. Shot processing on the Pi.</small></div><div className="sidebar-user"><span className="avatar">{(user?.email ?? 'D').slice(0,1).toUpperCase()}</span><div><strong>{user ? 'Your account' : 'Demo workspace'}</strong><small>{user?.email ?? 'Explore without signing in'}</small></div></div></aside>
  <div className="workspace"><div className="mobile-brand">MODUS <span>Golf</span></div><div className="topbar"><span className={`connection ${source}`}><span/>{status}</span><label className="source-select">Data source<select value={source} aria-label="Data source" onChange={e => setSource(e.target.value as Source)}><option value="cloud" disabled={!user}>My Firebase account</option><option value="demo">Synthetic demo</option>{imported.shots.length > 0 && <option value="import">Local CSV preview</option>}</select></label></div>
  <main id="main-content"><div className="page-heading"><div><p className="eyebrow">MODUS GOLF / {source === 'demo' ? 'DEMO WORKSPACE' : source === 'import' ? 'LOCAL PREVIEW' : 'YOUR WORKSPACE'}</p><h1>{info.name}</h1><p>{info.description}</p></div><div className="button-row"><button onClick={() => { setTab('sessions'); location.hash = 'sessions'; setShowImport(!showImport); }}>Preview CSV</button>{!user && <button className="primary" onClick={onSignIn}>Sign in</button>}</div></div>
    {source === 'demo' && <div className="source-banner"><strong>Demo mode</strong><span>Every shot is synthetic. Explore the workflow; nothing here is uploaded to Firebase.</span></div>}{source === 'import' && <div className="source-banner"><strong>Local CSV preview</strong><span>Records are held in this tab only. This is not a cloud import or a live connection.</span></div>}
    {error && <div className="error" role="alert"><strong>Could not load your cloud data.</strong><p>{error}</p><button onClick={() => setRetry(retry+1)}>Retry connection</button></div>}{source === 'cloud' && loading && <p role="status">{fromCache ? 'Waiting for a server-confirmed snapshot. Any displayed records are cached in memory.' : 'Loading your account’s complete shot history…'}</p>}
    {tab !== 'settings' && filterControls}
    {showImport && <ImportPreview profiles={profiles} onClose={() => setShowImport(false)} onUse={(records, profile) => { setImported({ shots: records, profiles: [profile] }); setSource('import'); setProfileId(profile.id); setTab('sessions'); location.hash = 'sessions'; setShowImport(false); }}/>} 
    {detail && <ShotDetail shot={detail} units={units} onClose={() => setDetailId(null)}/>}
    {tab === 'practice' && <><section className="practice-intro"><div><span className="pill">{source === 'demo' ? 'DEMO PLAYBACK' : 'SAVED SHOT HISTORY'}</span><h2>{selectedProfile ? `${selectedProfile.display_name}’s practice` : 'Your next practice starts here.'}</h2><p>{latest ? `Shot ${latest.sequence_number} · ${clubName(latest.club)} · ${latest.processing_state}` : 'Add a golfer profile in Settings, or choose the synthetic demo to explore.'}</p></div><div className="shot-counter"><strong>{filtered.length}</strong><span>records in view</span></div></section>
      <div className="section-title"><h2>{selectedId == null ? 'Latest saved shot' : 'Selected saved shot'}</h2>{latest && <span className="tag">{sourceName(latest)}</span>}</div><MetricCards shot={latest} units={units} primary/><MoreMetrics shot={latest} units={units}/>
      {filtered.length > 0 && <div className="recent-selector"><div className="section-title"><h2>Review a shot</h2><button className="text" onClick={() => setSelectedId(null)}>{newerCount > 0 ? `${newerCount} newer saved shots · View latest` : 'Follow latest'}</button></div><div className="shot-chips" role="group" aria-label="Recent shot selection">{filtered.slice(-8).reverse().map(shot => <button key={shot.shot_id} className={latest?.shot_id === shot.shot_id ? 'selected' : ''} aria-pressed={latest?.shot_id === shot.shot_id} onClick={() => setSelectedId(shot.shot_id)}><span>#{shot.sequence_number} · {clubName(shot.club)}</span><strong>{displayMetric(shot.carry_yards,'carry_yards',units)} <small>{unitFor('carry_yards',units)}</small></strong></button>)}</div><small>Selection changes this view only. {newest && selectedId && newest.shot_id !== selectedId ? 'An earlier shot stays selected when new records arrive.' : 'Latest follows incoming backend records.'}</small></div>}
      <div className="practice-bottom"><section className="panel flight-panel"><div className="panel-heading"><h2>Flight views</h2><span className="tag subtle">PI COMPUTED</span></div><Trajectory shot={latest} shots={filtered} units={units}/></section><section className="panel session-summary"><p className="eyebrow">IN THIS VIEW</p><h2>Make every session count.</h2><dl><div><dt>Eligible shots</dt><dd>{stats?.shot_count ?? 0}</dd></div><div><dt>Mean modeled carry</dt><dd>{displayMetric(stats?.metrics.carry_yards.mean, 'carry_yards', units)} <small>{unitFor('carry_yards', units)}</small></dd></div><div><dt>Golfer profiles</dt><dd>{profiles.length}</dd></div></dl><button onClick={() => open('bag')}>Explore My Bag <Icon name="arrow"/></button><small>App-computed from all eligible records in this filter.</small></section></div>
      {source === 'demo' && filtered.length > 0 && <div className="demo-controls"><div><strong>Walk through the demo</strong><small>Manual playback of synthetic fixtures. No live sensor states are simulated.</small></div><button onClick={() => setSelectedId(filtered[0]?.shot_id ?? null)}>First shot</button><button onClick={() => setSelectedId(current => filtered[Math.min((current ? filtered.findIndex(shot => shot.shot_id === current) : -1) + 1, filtered.length - 1)]?.shot_id ?? null)}>Next demo shot</button><button onClick={() => setSelectedId(null)}>Latest</button></div>}
      {!latest && !loading && <Empty title="No saved shots yet" action={<button onClick={() => { setTab('sessions'); setShowImport(true); }}>Preview a Pi CSV</button>}>Your launch monitor’s future uploader will add real records here. You can explore a local CSV preview now.</Empty>}
      <section className="panel"><div className="panel-heading"><h2>Recent shots</h2><button className="text" onClick={() => open('sessions')}>View all sessions <Icon name="arrow"/></button></div>{filtered.length ? <ShotList key={`${source}-${profileId}-${club}-${session}-${date}`} shots={filtered.slice(-5)} totalCount={filtered.length} units={units} selectedId={latest?.shot_id} onSelect={shot => { setSelectedId(shot.shot_id); window.scrollTo({top:0}); }}/> : <p>Your latest records will appear here.</p>}</section></>}
    {tab === 'sessions' && <><div className="overview-grid"><SummaryCard label="Records in view" value={String(filtered.length)} note="Every display page included"/><SummaryCard label="Eligible for statistics" value={String(stats?.shot_count ?? 0)} note={source === 'demo' ? 'Synthetic fixtures explicitly included' : 'Real, final records only'}/><SummaryCard label="Sessions in view" value={String(new Set(filtered.map(shot => shot.session_id)).size)} note="Grouped by stable session ID"/></div><section className="panel"><div className="panel-heading"><div><h2>Shot history</h2><p>Open any saved shot to inspect its metrics and source.</p></div><button disabled={!filtered.length} onClick={() => download('modus-history-export.csv', historyCsv(filtered), 'text/csv')}>Export CSV</button></div>{filtered.length ? <ShotList key={`${source}-${profileId}-${club}-${session}-${date}`} shots={filtered} units={units} onSelect={shot => setDetailId(shot.shot_id)}/> : <Empty title={loading ? 'Loading history…' : 'No shots match this view'}>Try another golfer or filter, or preview a session CSV. Cloud uploads require the ingestion service.</Empty>}</section><section className="panel"><div className="panel-heading"><h2>Modeled carry over time</h2><span className="tag">APP-COMPUTED</span></div><CarryTrend shots={filtered.filter(shot => shot.record_kind === 'real' || source === 'demo' && shot.record_kind === 'synthetic')} units={units}/></section></>}
    {tab === 'bag' && <Bag shots={filtered} profileId={profileId} demo={source === 'demo'} units={units}/>}
    {tab === 'settings' && <><section className="panel"><div className="panel-heading"><h2>Display preferences</h2><Icon name="settings"/></div><label>Units<select value={units} onChange={e => setUnits(e.target.value as Units)}><option value="imperial">Imperial · mph / yards</option><option value="metric">Metric · km/h / meters</option></select></label><small>Only this display preference is saved on this browser. Private shot records are not persisted.</small></section>
      {user && source === 'cloud' ? <Account user={user}/> : <section className="panel"><h2>{source === 'demo' ? 'Demo golfer profiles' : 'Preview attribution'}</h2>{source === 'demo' ? <LocalProfiles profiles={demoProfiles} onChange={setDemoProfiles}/> : <p>{selectedProfile?.display_name ?? 'No golfer selected'} · Attribution is fixed in the normalized records.</p>}{!user && <button className="primary" onClick={onSignIn}>Sign in to your Firebase account</button>}{user && <p>Signed in as {user.email}. Switch the data source to My Firebase account to manage real golfer profiles.</p>}</section>}
      <section className="panel"><h2>Launch monitor connection</h2><p className="device-state"><span/>Capture state not reported</p><p>{new LocalPiRepository().message}</p><div className="instructions"><strong>Local access on the MODUS Wi-Fi</strong><ol><li>Join the launch monitor’s Wi-Fi hotspot.</li><li>The supplied setup guide uses <code>http://10.42.0.1:8000/range</code>. Confirm the address if your Pi configuration differs.</li><li>Open the Pi range page in a separate browser tab and download <code>/session.csv</code> for preview here.</li></ol><a className="local-link" href="http://10.42.0.1:8000/range" target="_blank" rel="noreferrer">Open documented Pi range page ↗</a><small>Local-network navigation only. No Wi-Fi or SSH credentials are stored here.</small></div><p>The hosted app does not connect directly to the Pi’s private HTTP endpoints. Automatic upload needs device pairing, a durable Pi queue, and an authenticated ingestion backend.</p><dl className="provenance"><dt>Cloud snapshot</dt><dd>{source !== 'cloud' ? 'Not using cloud data' : serverTime ? `${serverTime.toLocaleString()}${fromCache ? ' · cached snapshot; awaiting server' : ' · confirmed by Firestore'}` : 'No server-confirmed snapshot yet'}</dd><dt>Pending uploads</dt><dd>Unavailable — no upload service connected</dd><dt>Sound detector</dt><dd>Temporarily unavailable; camera triggering is the current configuration. This is not a live health reading.</dd><dt>Battery / sensor health</dt><dd>No telemetry supplied</dd></dl></section><section className="panel"><h2>About this build</h2><p>Designed for readable shot feedback, history recall, session comparison and private golfer profiles. The PDR/MSDR accuracy and latency figures are design targets; this interface does not certify measurement accuracy or impact-to-phone latency.</p><p>Spin and club path remain experimental/unavailable. Statistics are computed in this app; a cloud analytics service is future work.</p>{user && <button onClick={() => void signOut(auth).catch(e => setError(e.message))}>Sign out of Firebase</button>}</section></>}
    <footer className="workspace-footer"><span>MODUS GOLF · PRACTICE WITH PURPOSE</span><span>{source === 'cloud' ? serverTime ? `Cloud snapshot ${serverTime.toLocaleTimeString()}` : 'Awaiting cloud snapshot' : source === 'demo' ? 'Synthetic demo — never uploaded' : 'Local preview — held in this tab'}</span></footer>
  </main></div><nav className="bottom-nav" aria-label="Mobile navigation">{tabs.map(item => <button key={item.id} className={tab === item.id ? 'active' : ''} aria-current={tab === item.id ? 'page' : undefined} onClick={() => open(item.id)}><Icon name={item.id}/><span>{item.name}</span></button>)}</nav></div>;
}
function SummaryCard({ label, value, note }: { label: string; value: string; note: string }) { return <article className="summary-card"><span>{label}</span><strong>{value}</strong><small>{note}</small></article>; }
function LocalProfiles({ profiles, onChange }: { profiles: Profile[]; onChange: (profiles: Profile[]) => void }) {
  const [name, setName] = useState(''); const [editing, setEditing] = useState<string | null>(null);
  return <><p>Editable in memory for this demo only. These are not Firebase accounts.</p><ul className="profile-list">{profiles.map(profile => <li key={profile.id}><span>{profile.display_name}</span><button onClick={() => { setName(profile.display_name); setEditing(profile.id); }}>Rename</button></li>)}</ul><form onSubmit={e => { e.preventDefault(); if (!name.trim()) return; onChange(editing ? profiles.map(profile => profile.id === editing ? { ...profile, display_name: name.trim() } : profile) : [...profiles, { id: `demo_${crypto.randomUUID()}`, display_name: name.trim() }]); setName(''); setEditing(null); }}><label>Demo golfer name<input value={name} required maxLength={80} onChange={e => setName(e.target.value)}/></label><div className="button-row"><button className="primary">{editing ? 'Save demo name' : 'Add demo golfer'}</button>{editing && <button type="button" onClick={() => { setName(''); setEditing(null); }}>Cancel</button>}</div></form></>;
}


