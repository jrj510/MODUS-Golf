import { useEffect, useState } from 'react';
import { signOut, type User } from 'firebase/auth';
import { auth } from './firebase';
import { FirebaseRepository, type Profile } from './repository';
import { errorText } from './auth-ui';

export function Account({ user }: { user: User }) {
  const [repository] = useState(() => new FirebaseRepository(user.uid));
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [name, setName] = useState('');
  const [editing, setEditing] = useState<string | null>(null);
  useEffect(() => repository.watchProfiles(items => { setProfiles(items); setLoading(false); }, e => {
    setError(errorText(e)); setLoading(false);
  }), [repository]);
  async function run(action: () => Promise<void>) {
    setError(''); setBusy(true);
    try { await action(); } catch (e) { if (auth.currentUser?.uid === user.uid) setError(errorText(e)); }
    finally { setBusy(false); }
  }
  return <><section className="card"><p className="eyebrow">FIREBASE ACCOUNT</p><h1>Your space to improve.</h1>
    <p className="account-email">{user.email}</p><p>Each golfer profile is separate from your signed-in account and physical device.</p>
    <button disabled={busy} onClick={() => void run(async () => { await signOut(auth); })}>Sign out</button>
  </section><section className="card"><h2>Golfer profiles</h2>
    {loading ? <p role="status">Loading profiles…</p> : profiles.length === 0 ? <p>No profiles yet. Add your first golfer below.</p> : <ul>{profiles.map(profile => <li key={profile.id}><span>{profile.display_name}</span><button disabled={busy} onClick={() => { setEditing(profile.id); setName(profile.display_name); }}>Rename</button></li>)}</ul>}
    <form onSubmit={e => { e.preventDefault(); void run(async () => {
      if (editing) await repository.renameProfile(editing, name); else await repository.createProfile(name);
      setName(''); setEditing(null);
    }); }}><fieldset disabled={busy || loading}><label>{editing ? 'New name' : 'New golfer name'}<input required maxLength={80} value={name} onChange={e => setName(e.target.value)} /></label>
      <button className="primary">{busy ? 'Saving…' : editing ? 'Save name' : 'Add golfer'}</button>
      {editing && <button type="button" onClick={() => { setEditing(null); setName(''); }}>Cancel</button>}
    </fieldset></form>
    <small>Profile deletion and capture assignment require server-side reference checks.</small>
  </section>{error && <p className="card error" role="alert">{error}</p>}</>;
}
