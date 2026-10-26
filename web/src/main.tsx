import { Component, lazy, Suspense, useEffect, useRef, useState, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { onAuthStateChanged, type User } from 'firebase/auth';
import { auth } from './firebase';
import { Login } from './auth-ui';
const Workspace = lazy(() => import('./workspace').then(module => ({default:module.Workspace})));
import './style.css';
class WorkspaceBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    return this.state.failed ? <div className="auth-page"><section className="card login"><h1>Workspace could not load.</h1><p>Check your connection and reload the app.</p><button className="primary" onClick={() => location.reload()}>Reload app</button></section></div> : this.props.children;
  }
}
function App() {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [explore, setExplore] = useState(false);
  const previous = useRef<string | null>(null);
  useEffect(() => onAuthStateChanged(auth, current => {
    if (previous.current !== (current?.uid ?? null)) setExplore(false);
    previous.current = current?.uid ?? null;
    setUser(current); setReady(true);
  }), []);
  if (!ready) return <div className="auth-page"><p role="status">Connecting to your Firebase account…</p></div>;
  const active = user && auth.currentUser?.uid === user.uid ? user : null;
  if (active || explore) return <WorkspaceBoundary><Suspense fallback={<div className="auth-page"><p role="status">Loading your practice workspace…</p></div>}><Workspace key={active?.uid ?? 'guest'} user={active} onSignIn={() => setExplore(false)}/></Suspense></WorkspaceBoundary>;
  return <div className="auth-page"><a className="auth-brand" href="/">MODUS <span>GOLF</span></a><Login onDemo={() => setExplore(true)}/><p className="auth-note">Your shot processing stays on the launch monitor.<br/>Your history, ready when you are.</p></div>;
}
createRoot(document.getElementById('root')!).render(<App/>);
