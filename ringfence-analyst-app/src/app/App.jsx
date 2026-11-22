/* Ringfence analyst application (UC-042 Moorwand Safeguarding).
   <App store={createStore(dataService)} /> — the same component runs in the Vite app (main.jsx)
   and in the design-system card (card-entry.jsx). */
import React from 'react';
import { StoreContext, useAppState, useStoreApi, useQuery } from './hooks.js';
import { AppShell, Icon } from '../ui/index.jsx';
import { analystOf, fmtPeriod } from './format.js';
import LoginScreen from './screens/Login.jsx';
import QueueScreen from './screens/Queue.jsx';
import CustomersScreen from './screens/Customers.jsx';
import CustomerScreen from './screens/Customer.jsx';
import RegisterScreen from './screens/Register.jsx';
import CaseWorkspace from './CaseWorkspace.jsx';

export default function App({ store }) {
  return <StoreContext.Provider value={store}><Root /></StoreContext.Provider>;
}

function Root() {
  const st = useAppState();
  const store = useStoreApi();
  React.useEffect(() => { if (!st.app) store.loadApp(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  if (!st.signedIn) return <div className={'rf-app' + (store.kind === 'mock' ? ' rf-app--mock' : '')}><LoginScreen onSignIn={store.signIn} app={st.app} appError={st.appError} kind={store.kind} store={store} /><ServiceBar /><Toasts /></div>;
  return <Shell st={st} store={store} />;
}

function Shell({ st, store }) {
  const r = st.route;
  const q = useQuery('queue', (svc) => svc.listCases(), { poll: store.POLL.queue, focus: true });
  const ac = q.data && q.data.active_case;
  const props = { route: r, app: st.app, nav: store.nav, store };
  let body;
  if (r.view === 'customers') body = <CustomersScreen {...props} />;
  else if (r.view === 'customer') body = <CustomerScreen key={r.id} {...props} />;
  else if (r.view === 'register') body = <RegisterScreen {...props} />;
  else if (r.view === 'demo') body = <QueueScreen {...props} focusDemo />; // old #/demo link: the queue's Demo scenarios section
  else if (r.view === 'case') body = <CaseWorkspace key={r.ref} {...props} />;
  else body = <QueueScreen {...props} />;
  return <div className={store.kind === 'mock' ? 'rf-app--mock' : undefined}><AppShell analyst={analystOf(st.app)} active={r.view === 'customers' || r.view === 'customer' ? 'customers' : 'queue'} demo={!!(st.app && st.app.demo_scenarios)}
    activeCase={ac ? { ref: ac.case_ref, customer: ac.customer_name, period: fmtPeriod(ac.reporting_period) } : null}
    onNav={store.nav} menuOpen={st.menuOpen} onMenu={() => store.setMenu(!st.menuOpen)} onSignOut={store.signOut}
    overlay={<><ServiceBar /><Toasts /></>}>{body}</AppShell></div>;
}

const TOAST_ICON = { success: 'check', danger: 'alert', attention: 'alert', info: 'info' };
function Toasts() {
  const st = useAppState();
  const store = useStoreApi();
  return <div className="rf-toasts" aria-live="polite">{st.toasts.map((t) => <div key={t.id} className={'rf-toast rf-toast--' + t.tone} role={t.tone === 'danger' ? 'alert' : 'status'}>
    <Icon name={TOAST_ICON[t.tone] || 'info'} size={14} /><span className="rf-toast__text">{t.text}</span>
    <button type="button" className="rf-toast__close" aria-label="Dismiss" onClick={() => store.dismiss(t.id)}><Icon name="x" size={12} /></button></div>)}</div>;
}

/* Identifies the data service in use. The mock is labelled everywhere it is active. */
function ServiceBar() {
  const store = useStoreApi();
  const [open, setOpen] = React.useState(false);
  const [f, setF] = React.useState({ run: false, recon: false, fast: false });
  if (store.kind !== 'mock') return <div className="rf-svcbar rf-svcbar--http" role="note"><Icon name="shield" size={12} /><span>Backend · Ringfence server via <span className="rf-mono">/api</span></span></div>;
  const m = store.svc.mock;
  const flip = (k, fn) => (e) => { const v = e.target.checked; setF(Object.assign({}, f, { [k]: v })); fn(v); };
  return <div className="rf-svcbar" role="note">
    <b>MOCK DATA SERVICE</b><span>In-browser simulation · synthetic data · no backend connected · processing simulated with timers</span>
    <button type="button" className="rf-svcbar__btn" aria-expanded={open} onClick={() => setOpen(!open)}>Simulate…</button>
    {open && <div className="rf-svcbar__menu" role="group" aria-label="Mock controls">
      <label><input type="checkbox" checked={f.run} onChange={flip('run', m.setFailNextRun)} /> Fail the next Smart Parser run</label>
      <label><input type="checkbox" checked={f.recon} onChange={flip('recon', m.setFailNextRecon)} /> Fail the next reconciliation</label>
      <label><input type="checkbox" checked={f.fast} onChange={flip('fast', (v) => m.setSpeed(v ? 4 : 1))} /> Fast processing (×4)</label>
      <button type="button" className="rf-svcbar__btn" onClick={() => { m.reset(); setF({ run: false, recon: false, fast: false }); m.setSpeed(1); store.invalidate(); store.nav('queue'); store.toast('info', 'Mock demo data reset'); setOpen(false); }}>Reset demo data</button>
    </div>}
  </div>;
}
