/* Ringfence analyst app · store (framework-agnostic)
   Holds the route, the simulated reviewer session (S01), toasts and a query cache.
   React binds to it in hooks.js. All data comes from the data service (mockService or
   httpService); screens render the backend payloads as returned and never derive
   lifecycle rules (contract §2, design handoff §5). */

export const TABS = ['overview', 'evidence', 'parser', 'review', 'package', 'recon', 'closing', 'activity'];

export function parseRoute(hash) {
  const h = String(hash || '').replace(/^#?\/?/, '');
  const [path, qs] = h.split('?');
  const p = path.split('/').filter(Boolean).map(decodeURIComponent);
  const query = Object.fromEntries(new URLSearchParams(qs || ''));
  if (!p.length || p[0] === 'queue') return { view: 'queue', query };
  if (p[0] === 'login') return { view: 'login', query };
  if (p[0] === 'register') return { view: 'register', query };
  if (p[0] === 'completed') return { view: 'completed', query };
  if (p[0] === 'demo') return { view: 'demo', query };
  if (p[0] === 'customers') return p[1] ? { view: 'customer', id: p[1], query } : { view: 'customers', query };
  if (p[0] === 'cases' && p[1]) return { view: 'case', ref: p[1], tab: TABS.includes(p[2]) ? p[2] : 'overview', sub: p[3] || null, id: p[4] || null, query };
  return { view: 'queue', query };
}

export function normaliseError(e) {
  if (e && typeof e === 'object' && 'error' in e) return { status: e.status || 0, error: e.error, message: e.message || e.error };
  return { status: 0, error: 'CLIENT', message: String((e && e.message) || e) };
}

export function createStore(service, options) {
  const opt = Object.assign({ routing: 'hash', start: 'login' }, options || {});
  const svc = service;
  // Contract §5 intervals for the backend; the in-browser mock polls faster (no server load).
  // closure: audit pack / AI investigation / preview / final-pack jobs (3–5 s while a job runs).
  const POLL = svc.kind === 'mock' ? { case: 1000, recon: 1000, queue: 5000, closure: 4000 } : { case: 3000, recon: 5000, queue: 30000, closure: 4000 };
  const subs = new Set(), queries = new Map(), mounted = new Map(), tokens = new Map();
  let toastSeq = 0;
  const hasHash = opt.routing === 'hash' && typeof location !== 'undefined' && location.hash.length > 2;
  let state = { route: parseRoute(hasHash ? location.hash : '#/' + opt.start), app: null, appError: null, signedIn: false, toasts: [], menuOpen: false };

  const emit = () => subs.forEach((f) => f());
  const set = (patch) => { state = Object.assign({}, state, patch); emit(); };
  const EMPTY = Object.freeze({ data: undefined, error: null, loading: false, at: 0 });
  const getQuery = (key) => queries.get(key) || EMPTY;
  const putQuery = (key, patch) => { queries.set(key, Object.assign({}, getQuery(key), patch)); emit(); };

  function fetchKey(key) {
    const m = mounted.get(key);
    if (!m) return Promise.resolve();
    const tok = (tokens.get(key) || 0) + 1; tokens.set(key, tok);
    putQuery(key, { loading: true });
    return Promise.resolve().then(() => m.fetcher(svc)).then((data) => {
      if (tokens.get(key) !== tok) return;
      const prev = getQuery(key).data;
      putQuery(key, { data, error: null, loading: false, at: Date.now() });
      related(key, prev, data);
    }, (err) => { if (tokens.get(key) === tok) putQuery(key, { error: normaliseError(err), loading: false }); });
  }
  // A case moved to a new revision: refetch every mounted query that belongs to it, and the queue.
  function related(key, prev, data) {
    if (!key.startsWith('case:') || !prev || !data || prev.revision === data.revision) return;
    const ref = key.slice(5);
    mounted.forEach((m, k) => { if (k !== key && (k.includes(ref) || k.startsWith('queue') || k.startsWith('customer'))) fetchKey(k); });
  }
  function mountQuery(key, fetcher) {
    const m = mounted.get(key);
    if (m) { m.count++; m.fetcher = fetcher; } else mounted.set(key, { fetcher, count: 1 });
    fetchKey(key);
    return () => { const x = mounted.get(key); if (x && --x.count <= 0) mounted.delete(key); };
  }
  const refetch = (key) => fetchKey(key);
  const invalidate = (match) => Promise.all([...mounted.keys()].filter((k) => !match || k.includes(match)).map(fetchKey));
  function adopt(result) {
    const det = result && result.case_ref && result.actions ? result : result && result.case && result.case.case_ref ? result.case : null;
    if (det) { const key = 'case:' + det.case_ref; const prev = getQuery(key).data; putQuery(key, { data: det, error: null, at: Date.now() }); related(key, prev, det); }
  }

  /* Mutations: never throw to the caller; refetch after every mutation (contract §5). */
  async function mutate(fn, o) {
    o = o || {};
    try {
      const r = await fn(svc);
      adopt(r);
      if (o.key && r) putQuery(o.key, { data: r, error: null, at: Date.now() });
      if (o.success) toast('success', typeof o.success === 'function' ? o.success(r) : o.success);
      await invalidate(); // resolve after the refetch so the next action sends the new revision
      return { ok: true, data: r };
    } catch (e) {
      const err = normaliseError(e);
      if (err.error === 'CASE_CHANGED' || err.error === 'CLOSURE_CHANGED') { toast('attention', err.message); invalidate(); }
      else if (!o.inline) toast('danger', err.message);
      return { ok: false, error: err };
    }
  }

  function toast(tone, text) {
    const id = ++toastSeq;
    set({ toasts: state.toasts.concat([{ id, tone, text }]).slice(-4) });
    setTimeout(() => dismiss(id), tone === 'danger' ? 8000 : 4500);
    return id;
  }
  const dismiss = (id) => { if (state.toasts.some((t) => t.id === id)) set({ toasts: state.toasts.filter((t) => t.id !== id) }); };

  function nav(path) {
    const h = '#/' + String(path).replace(/^#?\/?/, '');
    if (opt.routing === 'hash') { if (location.hash !== h) location.hash = h; else set({ route: parseRoute(h), menuOpen: false }); }
    else set({ route: parseRoute(h), menuOpen: false });
  }
  if (opt.routing === 'hash' && typeof window !== 'undefined') window.addEventListener('hashchange', () => set({ route: parseRoute(location.hash), menuOpen: false }));

  /* S01 sign-in. With the backend (httpService) the server checks the username and password and keeps the
     session itself (HttpOnly cookie, GET /api/auth/session restores it after a refresh). When the server runs
     without authentication (--insecure-no-auth) or with the in-browser mock, S01 stays the simulated session:
     the identity comes from GET /api/app (contract §1). No credential is held in this store. */
  const hasAuth = typeof svc.getSession === 'function' && typeof svc.login === 'function';
  state.auth = { checked: !hasAuth, enabled: false, user: null };
  const setAuth = (patch) => set({ auth: Object.assign({}, state.auth, patch) });
  const afterSignIn = () => { if (state.route.view === 'login') nav(state.route.query.next || 'queue'); };
  const sessionReady = !hasAuth ? Promise.resolve() : svc.getSession().then((s) => {
    setAuth({ checked: true, enabled: !!s.auth_enabled, user: s.user || null });
    if (s.auth_enabled && s.authenticated) return fetchApp().then((app) => { if (app) { set({ signedIn: true }); afterSignIn(); } });
    return null;
  }, (e) => { setAuth({ checked: true }); set({ appError: normaliseError(e).message }); });
  if (hasAuth && svc.setUnauthenticatedHandler) svc.setUnauthenticatedHandler(() => {
    if (!state.signedIn) return;
    endSession();
    toast('attention', 'Your session has ended. Sign in again.');
  });

  function fetchApp() {
    return svc.getApp().then((app) => { set({ app, appError: null }); return app; }, (e) => { set({ appError: normaliseError(e).message }); return null; });
  }
  function loadApp() {
    // Before sign-in on an authenticated server /api/app is protected: wait for the session check, never call it signed out.
    return sessionReady.then(() => (state.auth.enabled && !state.signedIn ? state.app : fetchApp()));
  }
  function signIn(creds) {
    if (state.auth.enabled) {
      const c = creds || {};
      return svc.login(c.username || '', c.password || '').then((s) => {
        setAuth({ user: s.user || null });
        return fetchApp().then((app) => { if (app) { set({ signedIn: true }); afterSignIn(); } return { ok: !!app }; });
      }, (e) => ({ ok: false, error: normaliseError(e) }));
    }
    return (state.app ? Promise.resolve(state.app) : loadApp()).then((app) => {
      if (!app) return { ok: false };
      set({ signedIn: true });
      afterSignIn();
      return { ok: true };
    });
  }
  function endSession() {
    queries.clear(); // no case data from the ended session stays in memory
    set({ signedIn: false, menuOpen: false, app: state.auth.enabled ? null : state.app, auth: Object.assign({}, state.auth, { user: null }) });
    nav('login');
  }
  function signOut() {
    const done = () => endSession();
    return state.auth.enabled && svc.logout ? svc.logout().then(done, done) : Promise.resolve(done());
  }

  return {
    svc, kind: svc.kind, POLL,
    subscribe: (f) => { subs.add(f); return () => subs.delete(f); },
    getState: () => state,
    getQuery, mountQuery, refetch, invalidate, mutate, toast, dismiss, nav, loadApp, signIn, signOut,
    setMenu: (open) => set({ menuOpen: open }),
    casePoll: (c) => (!c ? null : c.current_run && c.current_run.status === 'PROCESSING' || (c.progress && c.progress.current_operation) || c.deferring ? POLL.case : c.progress && c.progress.reconciliation && c.progress.reconciliation.state === 'RUNNING' ? POLL.recon : null)
  };
}
