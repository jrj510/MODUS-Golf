import { useState, type FormEvent } from 'react';

import { createUserWithEmailAndPassword, signInWithEmailAndPassword, signInWithPopup,
  sendPasswordResetEmail } from 'firebase/auth';
import { auth, googleProvider } from './firebase';
import './style.css';

export function errorText(error: unknown) {
  const code = (error as { code?: string })?.code;
  const messages: Record<string, string> = {
    'auth/invalid-credential': 'Email or password was not accepted.',
    'auth/email-already-in-use': 'This email already has an account. Sign in or reset your password.',
    'auth/weak-password': 'Choose a stronger password with at least 8 characters.',
    'auth/invalid-email': 'Enter a valid email address.',
    'auth/popup-blocked': 'Allow popups for this site, then try Google sign-in again.',
    'auth/popup-closed-by-user': 'Google sign-in was closed. You can try again.',
    'auth/account-exists-with-different-credential': 'Sign in with your existing email/password account first.',
    'auth/unauthorized-domain': 'This app domain needs to be authorized in Firebase Authentication settings.',
    'auth/too-many-requests': 'Too many attempts. Please wait before trying again.',
    'auth/network-request-failed': 'Could not reach Firebase. Check your connection and try again.',
    'permission-denied': 'Firestore access was denied. Check your account and deployed security rules.',
  };
  return code ? (messages[code] ?? `Firebase returned ${code}. Please try again.`)
    : error instanceof Error ? error.message : 'Something went wrong. Please try again.';
}

export function Login({ onDemo }: { onDemo: () => void }) {
  const [mode, setMode] = useState<'signin' | 'signup'>('signin');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [email, setEmail] = useState('');
  async function run(action: () => Promise<unknown>) {
    setError(''); setNotice(''); setBusy(true);
    try { await action(); } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const password = String(data.get('password'));
    void run(() => mode === 'signin' ? signInWithEmailAndPassword(auth, email, password)
      : createUserWithEmailAndPassword(auth, email, password));
  }
  return <section className="card login"><p className="eyebrow">YOUR PRACTICE, TOGETHER</p>
    <h1>{mode === 'signin' ? 'Welcome back.' : 'Make room for progress.'}</h1>
    <p>Sign in to manage your golfer profiles and access your cloud records.</p>
    <form onSubmit={submit}><fieldset disabled={busy}>
      <label>Email<input name="email" type="email" autoComplete="email" required value={email} onChange={e => setEmail(e.target.value)} /></label>
      <label>Password<input name="password" type="password" required minLength={mode === 'signup' ? 8 : undefined} autoComplete={mode === 'signin' ? 'current-password' : 'new-password'} /></label>
      {mode === 'signup' && <small>Use at least 8 characters. Firebase also enforces the project’s password policy.</small>}
      <button className="primary" type="submit">{busy ? 'Please wait…' : mode === 'signin' ? 'Sign in' : 'Create account'}</button>
      <button type="button" onClick={() => void run(() => signInWithPopup(auth, googleProvider))}>Continue with Google</button>
      <button className="text" type="button" onClick={() => { setMode(mode === 'signin' ? 'signup' : 'signin'); setError(''); }}>{mode === 'signin' ? 'New here? Create an account' : 'Already registered? Sign in'}</button>
      <button className="text" type="button" onClick={() => void run(async () => {
        if (!email.trim()) throw new Error('Enter your email address first.');
        await sendPasswordResetEmail(auth, email);
        setNotice('If this email has an account, a password reset email will arrive shortly.');
      })}>Reset password</button>
    </fieldset></form>
    {error && <p className="error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    <div className="demo-entry"><button type="button" onClick={onDemo}>Explore the demo</button><small>Synthetic shots. No account or hardware connection required.</small></div>
  </section>;
}

