/* S01 · Sign in. On a backend with authentication: username + password, checked by the server
   (POST /api/auth/login → HttpOnly session cookie). Without authentication (--insecure-no-auth, or the
   in-browser mock) it stays the simulated session: the reviewer identity comes from GET /api/app → reviewer
   (one analyst per server process, contract §1). Credentials are never stored in the browser. */
import React from 'react';
import { Button, Notice, Mark, Icon, Enum } from '../../ui/index.jsx';
import { useAppState } from '../hooks.js';
import '../format.js';

const JOURNEY = [['01', 'Received', 'Customer ZIP attached to its case'], ['02', 'Parsed', 'Smart Parser classifies and maps evidence'], ['03', 'Reviewed', 'You decide what the parser could not'], ['04', 'Validated', 'PV-01 to PV-09 pass'], ['05', 'Activated', 'Package sealed as a snapshot'], ['06', 'Completed', 'UC-042 reconciliation reports the outcome']];

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
      <div><h2 id="login-title" className="page-title" style={{ margin: 0 }}>Sign in</h2><p className="rf-muted" style={{ margin: '4px 0 0', fontSize: 13 }}>Internal access for safeguarding analysts.</p></div>
      {error && <div role="alert"><Notice tone="danger" title="Sign-in failed" compact>{error}</Notice></div>}
      {appError && !error && <Notice tone="danger" title="The analyst identity could not be read" compact>{appError}</Notice>}
      <label className={'rf-field' + (error ? ' is-error' : '')}><span className="rf-strong">Username</span>
        <input ref={userRef} className="rf-input rf-input--lg" name="username" autoComplete="username" autoCapitalize="none" spellCheck={false}
          value={username} onChange={(e) => setUsername(e.target.value)} disabled={busy} required /></label>
      <label className={'rf-field' + (error ? ' is-error' : '')}><span className="rf-strong">Password</span>
        <input className="rf-input rf-input--lg" type="password" name="password" autoComplete="current-password"
          value={password} onChange={(e) => setPassword(e.target.value)} disabled={busy} required /></label>
      <Button type="submit" variant="primary" size="lg" block loading={busy}>{busy ? 'Signing in…' : 'Sign in'}</Button>
      <p className="rf-help" style={{ margin: 0 }}>Your session is kept by the server and ends when you sign out or after a period of inactivity. Use synthetic evidence only.</p>
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
        <p className="rf-help" style={{ margin: 0 }}>This is a simulated session. The reviewer identity comes from <span className="rf-mono">GET /api/app</span>, one analyst per server process. Use synthetic evidence only.</p>
      </form>;
  }
}

function LoginFrame({ children }) {
  return <div className="rf-login">
    <section className="rf-login__brand">
      <div className="rf-row" style={{ gap: 10 }}><Mark size={28} /><span style={{ fontSize: 18, fontWeight: 600 }}>Ringfence</span></div>
      <h1 className="display" style={{ margin: '64px 0 0', maxWidth: 440 }}>Safeguarding evidence, on the record.</h1>
      <p className="rf-login__lede">Process customer evidence, decide what needs a person, seal the package and run the UC-042 reconciliation. Defer a case at any point and resume where you left off. Every step is traceable to its source.</p>
      <ol className="rf-login__journey">{JOURNEY.map((s) => <li key={s[0]}><span className="rf-mono">{s[0]}</span><div>{s[1]}<small>{s[2]}</small></div></li>)}</ol>
      <div className="rf-login__foot">Moorwand safeguarding operations · UC-042 proof of concept · synthetic data only</div>
    </section>
    <section className="rf-login__formwrap">{children}</section>
  </div>;
}
