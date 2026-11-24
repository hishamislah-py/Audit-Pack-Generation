/* ==========================================================================
   Ringfence backend adapter · implements every DataService method with the
   endpoint, body and headers in RINGFENCE_FRONTEND_API_CONTRACT.md.
   - Base URL: same origin `/api` (proxy it in development; the server sends
     no CORS headers and its CSP is default-src 'self').
   - Every POST sends `X-Smartparser-Client: webapp` (else 403 FORBIDDEN).
   - Errors are always { error, message }: rejected unchanged with `status`.
   ========================================================================== */
import { assertDataService } from './dataService.js';

export function createHttpService(config) {
  const cfg = Object.assign({ baseUrl: '', fetch: window.fetch.bind(window) }, config || {});
  const enc = encodeURIComponent;
  // Called when any request (other than /api/auth/*) answers 401 UNAUTHENTICATED: the session expired or was revoked.
  let onUnauthenticated = null;

  async function request(method, path, body, accept) {
    const headers = { Accept: accept || 'application/json' };
    if (method === 'POST') { headers['Content-Type'] = 'application/json'; headers['X-Smartparser-Client'] = 'webapp'; }
    let res;
    try {
      res = await cfg.fetch(cfg.baseUrl + path, { method, headers, body: method === 'POST' ? JSON.stringify(body || {}) : undefined, credentials: 'same-origin' });
    } catch (e) {
      throw { status: 0, error: 'NETWORK', message: 'The Ringfence server could not be reached.' };
    }
    const type = res.headers.get('Content-Type') || '';
    if (!res.ok) {
      let payload = null;
      try { payload = await res.json(); } catch (e) { /* not JSON */ }
      if (res.status === 401 && payload && payload.error === 'UNAUTHENTICATED' && path.indexOf('/api/auth/') !== 0 && onUnauthenticated) onUnauthenticated();
      throw { status: res.status, error: (payload && payload.error) || 'HTTP_' + res.status, message: (payload && payload.message) || 'The request failed (' + res.status + ').' };
    }
    if (type.indexOf('application/json') > -1) return res.json();
    return res.text();
  }
  const get = (p, accept) => request('GET', p, null, accept);
  const post = (p, b) => request('POST', p, b);
  const cl = (ref) => '/api/cases/' + enc(ref) + '/closure';
  const qs = (o) => { const s = Object.keys(o || {}).filter((k) => o[k] != null && o[k] !== '').map((k) => enc(k) + '=' + enc(o[k])).join('&'); return s ? '?' + s : ''; };

  const service = {
    kind: 'http',
    label: 'Ringfence backend',
    // Sign-in (server-side session in an HttpOnly cookie; the browser never sees the token).
    getSession: () => get('/api/auth/session'),
    login: (username, password) => post('/api/auth/login', { username, password }),
    logout: () => post('/api/auth/logout', {}),
    setUnauthenticatedHandler: (fn) => { onUnauthenticated = fn; },
    getApp: () => get('/api/app'),
    listCases: (q) => get('/api/cases' + qs({ status: q && q.status, assigned: q && q.assigned })),
    registerCase: (body) => post('/api/cases', body),
    detectPeriod: (body) => post('/api/cases/detect-period', body),
    getCase: (ref) => get('/api/cases/' + enc(ref)),
    claimCase: (ref, body) => post('/api/cases/' + enc(ref) + '/claim', body || {}),
    startCase: (ref, body) => post('/api/cases/' + enc(ref) + '/start', body),
    deferCase: (ref, body) => post('/api/cases/' + enc(ref) + '/defer', body),
    deleteCase: (ref) => post('/api/cases/' + enc(ref) + '/delete', { confirm: true }),
    resumeCase: (ref, body) => post('/api/cases/' + enc(ref) + '/resume', body),
    retryCase: (ref, body) => post('/api/cases/' + enc(ref) + '/retry', Object.assign({ confirm: true }, body)),
    validateCase: (ref) => post('/api/cases/' + enc(ref) + '/validate', {}),
    stageFile: (body) => post('/api/staging', body),
    submitEvidence: (ref, body) => post('/api/cases/' + enc(ref) + '/evidence', body),
    activateCase: (ref, body) => post('/api/cases/' + enc(ref) + '/activate', body),
    reconcileCase: (ref, body) => post('/api/cases/' + enc(ref) + '/reconcile', body),
    getRun: (ref, runId) => get('/api/cases/' + enc(ref) + '/runs/' + enc(runId)),
    getReview: (ref, vid) => get('/api/cases/' + enc(ref) + '/review/' + enc(vid)),
    postDecision: (ref, vid, body) => post('/api/cases/' + enc(ref) + '/review/' + enc(vid) + '/decision', body),
    confirmReview: (ref, vid, body) => post('/api/cases/' + enc(ref) + '/review/' + enc(vid) + '/confirm', body),
    rejectReview: (ref, vid, body) => post('/api/cases/' + enc(ref) + '/review/' + enc(vid) + '/reject', body),
    getActivity: (ref) => get('/api/cases/' + enc(ref) + '/activity'),
    listCustomers: () => get('/api/customers'),
    getCustomer: (id) => get('/api/customers/' + enc(id)),
    getFileVersion: (pid, vid) => get('/api/packages/' + enc(pid) + '/versions/' + enc(vid)),
    getVersionColumns: (pid, vid) => get('/api/packages/' + enc(pid) + '/versions/' + enc(vid) + '/columns'),
    getVersionPreview: (pid, vid) => get('/api/packages/' + enc(pid) + '/versions/' + enc(vid) + '/preview', 'text/csv'),
    getPackageHistory: (pid) => get('/api/packages/' + enc(pid) + '/history'),
    getSnapshot: (pid, sid) => get('/api/packages/' + enc(pid) + '/snapshots/' + enc(sid)),
    getJob: (jobId) => get('/api/jobs/' + enc(jobId)),
    // GET /api/runs/{id} exists only for a completed run (results.summary): mark it COMPLETED and expose
    // executed_at as finished_at for the screen. No other field is changed.
    getReconRun: (runId) => get('/api/runs/' + enc(runId)).then((r) => Object.assign({ state: 'COMPLETED', finished_at: r.executed_at }, r)),
    getControls: (runId, q) => get('/api/runs/' + enc(runId) + '/controls' + qs(q)),
    getReport: (runId) => get('/api/runs/' + enc(runId) + '/report', 'text/markdown'),
    getException: (runId, excId) => get('/api/runs/' + enc(runId) + '/exceptions/' + enc(excId)),
    listDemoScenarios: () => get('/api/demo/scenarios'),
    loadDemoScenario: (sid) => post('/api/demo/scenarios/' + enc(sid) + '/load', {}),
    getDemoVerification: (sid, ref) => get('/api/demo/scenarios/' + enc(sid) + '/verification' + qs({ case_ref: ref })),
    // Closure (impl_20261120 CONTRACT.md). Mutation bodies always carry expected_revision (the closure revision).
    getClosure: (ref) => get(cl(ref)),
    getClosurePack: (ref) => get(cl(ref) + '/pack'),
    getAiConfiguration: () => get('/api/ai/configuration'),
    getClosureException: (ref, exc) => get(cl(ref) + '/exceptions/' + enc(exc)),
    startInvestigation: (ref, exc, body) => post(cl(ref) + '/exceptions/' + enc(exc) + '/investigations', body),
    getInvestigation: (ref, inv) => get(cl(ref) + '/investigations/' + enc(inv)),
    decideInvestigation: (ref, inv, body) => post(cl(ref) + '/investigations/' + enc(inv) + '/decision', body),
    getExceptionHistory: (ref, exc) => get(cl(ref) + '/exceptions/' + enc(exc) + '/history'),
    openClosingReview: (ref, body) => post(cl(ref) + '/review', body),
    setClosingSelections: (ref, body) => post(cl(ref) + '/review/selections', body),
    requestClosingPreview: (ref, body) => post(cl(ref) + '/review/preview', body),
    decideClosingReview: (ref, body) => post(cl(ref) + '/review/decision', body),
    getFinalPack: (ref) => get(cl(ref) + '/final-pack'),
    getClosureHistory: (ref) => get(cl(ref) + '/history')
  };
  return assertDataService(service);
}
