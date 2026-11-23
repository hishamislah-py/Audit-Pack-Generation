/* S01 · Sign in. On a backend with authentication: username + password, checked by the server
   (POST /api/auth/login → HttpOnly session cookie). Without authentication (--insecure-no-auth, or the
   in-browser mock) it stays the simulated session: the reviewer identity comes from GET /api/app → reviewer
   (one analyst per server process, contract §1). Credentials are never stored in the browser. */
import React from 'react';
import { Button, Notice, Mark, Icon, Enum } from '../../ui/index.jsx';
import { useAppState } from '../hooks.js';
import '../format.js';


export default function LoginScreen({ onSignIn, app, appError, kind, store }) {
  const st = useAppState();
  const auth = st.auth || { checked: true, enabled: false };
  const [busy, setBusy] = React.useState(false);
  const [username, setUsername] = React.useState('');
  const [password, setPassword] = React.useState('');
  const [error, setError] = React.useState(null);
  const userRef = React.useRef(null);
  React.useEffect(() => { if (!app && store && store.loadApp) store.loadApp(); }, []);
  React.useEffect(() => { if (auth.checked && auth.enabled && userRef.current) userRef.current.focus(); }, [auth.checked, auth.enabled]);
  const r = (app && app.reviewer) || null;
  const signIn = async (e) => {
    if (e) e.preventDefault();
    if (busy || !onSignIn || !auth.checked) return;
    if (auth.enabled && (!username.trim() || !password)) { setError('Enter your username and password.'); return; }
    setBusy(true); setError(null);
    try {
      const res = await onSignIn(auth.enabled ? { username: username.trim(), password } : undefined);
      if (res && !res.ok && res.error) setError(res.error.message);
    } finally { setPassword(''); setBusy(false); }
  };
  if (auth.enabled) return <LoginFrame>
    <form className="rf-login__form" onSubmit={signIn} aria-labelledby="login-title" noValidate>
      <div><h2 id="login-title" className="rf-signin__title">Sign in</h2><p className="rf-signin__sub">Use your analyst account.</p></div>
      {error && <div role="alert"><Notice tone="danger" title="Sign-in failed" compact>{error}</Notice></div>}
      {appError && !error && <Notice tone="danger" title="The analyst identity could not be read" compact>{appError}</Notice>}
      <label className={'rf-field' + (error ? ' is-error' : '')}><span className="rf-signin__label">Email</span>
        <input ref={userRef} className="rf-input rf-input--lg" name="username" autoComplete="username" autoCapitalize="none" spellCheck={false}
          value={username} onChange={(e) => setUsername(e.target.value)} disabled={busy} required /></label>
      <label className={'rf-field' + (error ? ' is-error' : '')}><span className="rf-signin__label">Password</span>
        <input className="rf-input rf-input--lg" type="password" name="password" autoComplete="current-password"
          value={password} onChange={(e) => setPassword(e.target.value)} disabled={busy} required /></label>
      <Button type="submit" variant="primary" size="lg" block loading={busy}>{busy ? 'Signing in…' : 'Sign in'}</Button>
      <p className="rf-signin__note">You are signed out automatically after a period of inactivity.</p>
    </form>
  </LoginFrame>;
  if (!auth.checked) return <LoginFrame><div className="rf-login__form" aria-busy="true"><h2 id="login-title" className="page-title" style={{ margin: 0 }}>Sign in</h2><p className="rf-muted">Checking your session…</p></div></LoginFrame>;
  return <LoginFrame>{simulated()}</LoginFrame>;

  function simulated() {
    return <form className="rf-login__form" onSubmit={signIn} aria-labelledby="login-title">
        <div><h2 id="login-title" className="page-title" style={{ margin: 0 }}>Sign in</h2><p className="rf-muted" style={{ margin: '4px 0 0', fontSize: 13 }}>Internal access for safeguarding analysts.</p></div>
        {kind === 'mock' && <Notice tone="attention" title="Mock data service · no backend connected" compact>Synthetic demo data, simulated in this browser. Nothing is sent to the Ringfence backend.</Notice>}
        {kind !== 'mock' && <Notice tone="attention" title="Authentication is disabled on this server" compact>The server was started with <span className="rf-mono">--insecure-no-auth</span>. Use it only for local tests.</Notice>}
        {appError && <Notice tone="danger" title="The analyst identity could not be read" compact>{appError}</Notice>}
        <div className="rf-demo">
          <Icon name="user" />
          <div>
            <div className="rf-strong">Analyst for this server</div>
            {r ? <>
              <div><span className="rf-mono">{r.reviewer_id}</span>{r.name ? ' · ' + r.name : ''}</div>
              <div className="rf-muted" style={{ fontSize: 12 }}>{[r.role, r.kind].filter(Boolean).join(' · ')}</div>
            </> : <div className="rf-muted">{appError ? 'Not available. Sign in tries again.' : 'Reading identity from GET /api/app…'}</div>}
            {app && app.llm && <div className="rf-muted" style={{ fontSize: 12, marginTop: 4 }}>LLM mode <Enum>{app.llm.mode}</Enum> · {app.llm.label}</div>}
            {app && app.engine_configured === false && <div className="rf-muted" style={{ fontSize: 12, marginTop: 2 }}>The reconciliation engine is not configured on this server.</div>}
          </div>
        </div>
        <Button type="submit" variant="primary" size="lg" block loading={busy}>{busy ? 'Signing in…' : 'Sign in'}</Button>
        <p className="rf-help" style={{ margin: 0 }}>This is a simulated session. The reviewer identity comes from <span className="rf-mono">GET /api/app</span>, one analyst per server process.</p>
      </form>;
  }
}

function LoginFrame({ children }) {
  // One centred sign-in card (23 Nov 2026 owner request): no marketing panel, aligned on every screen size.
  return <div className="rf-signin">
    <div className="rf-signin__card">
      <div className="rf-signin__brand"><Mark size={30} /><div><div className="rf-signin__name">Ringfence</div><div className="rf-signin__tag">Safeguarding reconciliation</div></div></div>
      {children}
    </div>
    <div className="rf-signin__foot">Authorised users only · activity is recorded</div>
  </div>;
}
