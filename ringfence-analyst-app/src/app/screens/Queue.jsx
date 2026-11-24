/* S02 · Work queue. Renders GET /api/cases as returned: items in the backend's order (never re-sorted),
   counts and active_case for all cases whatever the filter (contract §3.2). Opening a case never starts it. */
import React from 'react';
import { useQuery, useStoreApi, useAppState } from '../hooks.js';
import { Button, Panel, Notice, Table, Empty, Skeleton, Pill, Ref, CaseProgress, Icon, Glyph, cx } from '../../ui/index.jsx';
import { fmtDateTime, fmtPeriod, fmtBytes, fmtAgo, fmtDay } from '../format.js';
import { DemoScenariosSection } from './Demo.jsx';

export const STATUSES = ['IN_PROGRESS', 'WAITING', 'PENDING', 'COMPLETED'];
const BUCKETS = [
  ['', 'All open cases', 'dot', 'neutral', 'Not completed'],
  ['IN_PROGRESS', 'In progress', 'active', 'progress', 'Being processed'],
  ['WAITING', 'Not started', 'waiting', 'waiting', 'Uploaded, not started'],
  ['PENDING', 'On hold', 'paused', 'attention', 'Paused · resume to continue']
];
export const nowOf = (store) => (store && store.svc && store.svc.now ? store.svc.now() : Date.now());

/* Shared with the customer profile (S04): the case columns and cells, from CaseSummary fields only. */
export function StatusCell({ c }) {
  return <div className="as-pills">
    <Pill state={c.status} />
    {c.deferring && <Pill state="DEFERRAL_REQUESTED" />}
    {c.current_run && c.current_run.status === 'FAILED' && <Pill state="FAILED" label="Run failed" />}
    {c.completed && c.completed.case_status && <Pill state={c.completed.case_status} />}
  </div>;
}
export function caseColumns(o) {
  const cols = [{ key: 'case', label: 'Case', width: '170px' }];
  if (!o || !o.noCustomer) cols.push({ key: 'cust', label: 'Customer and period', width: '220px' });
  else cols.push({ key: 'period', label: 'Period', width: '110px' });
  if (o && o.assignment) cols.push({ key: 'who', label: 'Assigned to', width: '170px' });
  return cols.concat([
    { key: 'st', label: 'Status', width: '150px' },
    { key: 'prog', label: 'Progress' },
    { key: 'zip', label: 'Original ZIP', width: '230px' },
    { key: 'rec', label: 'Received', width: '150px' }
  ], o && o.compact ? [] : [{ key: 'last', label: 'Last activity', width: '110px' }], [{ key: 'go', label: <span className="rf-sr">Open</span>, cls: 'is-tight' }]);
}
export function caseRow(c, now, nav, o) {
  const open = () => nav('cases/' + c.case_ref + '/overview');
  const others = c.other_cases_for_period || 0;
  const p = c.progress || {};
  return {
    key: c.case_ref, onClick: open, selected: o && o.selected === c.case_ref,
    cells: {
      case: <Ref id={c.case_ref} />,
      cust: <><span className="rf-cell-main">{c.customer_name}</span><span className="rf-cell-sub">{fmtPeriod(c.reporting_period)}</span></>,
      period: <span className="rf-nowrap">{fmtPeriod(c.reporting_period)}</span>,
      st: <StatusCell c={c} />,
      prog: <CaseProgress steps={c.steps || []} facts={(p.summary || []).slice(0, 2)} live={!!p.current_operation} />,
      zip: c.zip ? <><span className="as-zip" title={c.zip.filename}>{c.zip.filename}</span><span className="rf-cell-sub">{fmtBytes(c.zip.size)}</span></> : null,
      rec: <div className="as-received"><b>{fmtDateTime(c.created_at)}</b><span>{fmtAgo(c.created_at, now)}</span></div>,
      last: <span className="rf-secondary rf-nowrap" title={fmtDateTime(c.last_activity_at)}>{fmtAgo(c.last_activity_at, now)}</span>,
      who: c.assigned_to ? <span className="rf-nowrap">{c.assigned_to}</span> : <span className="rf-muted">Unassigned</span>,
      // A Waiting case gets Start: it opens the case and the normal Start confirmation (the backend still decides).
      go: o && o.start && c.status === 'WAITING'
        ? <Button variant="primary" size="sm" icon="play" aria-label={'Start ' + c.case_ref} onClick={(e) => { e.stopPropagation(); nav('cases/' + c.case_ref + '/overview?action=start'); }}>Start</Button>
        : <Button variant="quiet" size="sm" iconRight="chevronRight" aria-label={'Open ' + c.case_ref} onClick={(e) => { e.stopPropagation(); open(); }}>Open</Button>
    }
  };
}

function ActiveSlot({ data, nav, now }) {
  const a = data.active_case;
  if (!a) {
    // The backend orders WAITING and PENDING oldest first, so the first of each is the oldest.
    const first = (s) => data.items.find((x) => x.status === s);
    const w = first('WAITING'), p = first('PENDING');
    return <section className="rf-panel" aria-label="Case In Progress"><div className="as-slot-empty">
      <span className="as-slot-empty__ring"><Glyph name="pending" size={12} /></span>
      <div style={{ flex: 1, minWidth: 260 }}><div className="rf-strong">Nothing is being processed</div><div className="rf-secondary" style={{ fontSize: 13, lineHeight: '18px' }}>Start a case below, or upload a new submission.</div></div>
      {w && <Button iconRight="arrowRight" onClick={() => nav('cases/' + w.case_ref + '/overview')}>Next not started · {w.case_ref}</Button>}
      {p && <Button iconRight="arrowRight" onClick={() => nav('cases/' + p.case_ref + '/overview')}>Next on hold · {p.case_ref}</Button>}
    </div></section>;
  }
  const item = data.items.find((x) => x.case_ref === a.case_ref);
  return <Panel title="Being processed" sub="One case is processed at a time." aria-label="Case in progress">
    <div className="as-slot">
      <div className="as-slot__case">
        <div className="rf-row" style={{ gap: 8 }}><Pill state="IN_PROGRESS" />{a.deferring && <Pill state="DEFERRAL_REQUESTED" />}<Ref id={a.case_ref} copy /></div>
        <span className="rf-strong">{a.customer_name} · {fmtPeriod(a.reporting_period)}</span>
        {item && <span className="rf-muted" style={{ fontSize: 12 }}>Received {fmtDateTime(item.created_at)}{item.started ? ' · started ' + fmtDateTime(item.started.at) : ''}</span>}
      </div>
      <div className="as-slot__run">{item ? <CaseProgress steps={item.steps || []} facts={((item.progress && item.progress.summary) || []).slice(0, 3)} live={!!(item.progress && item.progress.current_operation)} /> : <span className="rf-muted" style={{ fontSize: 13 }}>Open the case to see its progress.</span>}</div>
      <div className="as-slot__meta">{item && <><b>Last activity</b>{fmtAgo(item.last_activity_at, now)}<br />{fmtDateTime(item.last_activity_at)}</>}</div>
      <Button iconRight="arrowRight" onClick={() => nav('cases/' + a.case_ref + '/overview')}>Open case</Button>
    </div>
  </Panel>;
}

const SECTION = { IN_PROGRESS: ['IN_PROGRESS', 'In progress'], WAITING: ['OPEN', 'Not started and on hold'], PENDING: ['OPEN', 'Not started and on hold'], COMPLETED: ['COMPLETED', 'Completed'] };

export default function QueueScreen({ route, app, nav: navProp, focusDemo }) {
  const store = useStoreApi();
  const nav = navProp || store.nav;
  const query = route.query || {};
  // owner, 24 Nov 2026: completed cases have their own page (#/completed); the dashboard shows open work only
  React.useEffect(() => { if (query.status === 'COMPLETED') nav('completed'); }, [query.status]); // eslint-disable-line react-hooks/exhaustive-deps
  const status = STATUSES.includes(query.status) && query.status !== 'COMPLETED' ? query.status : '';
  // "My cases" needs a signed-in user (the backend resolves assigned=me from the session). Without authentication
  // (--insecure-no-auth, the mock service) there is no "me", so the queue shows all cases as before.
  const st = useAppState();
  const user = st.auth && st.auth.enabled && st.auth.user ? st.auth.user.username : null;
  const mine = !!user && query.scope !== 'all';
  const filt = Object.assign({}, status ? { status } : {}, mine ? { assigned: 'me' } : {});
  const q = useQuery('queue' + (status ? ':' + status : '') + (mine ? ':mine' : ''), (svc) => svc.listCases(Object.keys(filt).length ? filt : undefined), { poll: store.POLL.queue, focus: true });
  const scopeQ = (s, sc) => { const p = []; if (s) p.push('status=' + s); if (sc) p.push('scope=' + sc); return 'queue' + (p.length ? '?' + p.join('&') : ''); };
  const scopeParam = user && !mine ? 'all' : '';
  const [text, setText] = React.useState('');
  const searchRef = React.useRef(null);
  React.useEffect(() => { if (query.focus === 'search' && searchRef.current) searchRef.current.focus(); }, [query.focus]);
  const now = nowOf(store);
  const data = q.data;
  const counts = data && data.counts;
  const total = counts ? STATUSES.filter((s) => s !== 'COMPLETED').reduce((a, s) => a + (counts[s] || 0), 0) : null;
  const items = ((data && data.items) || []).filter((c) => c.status !== 'COMPLETED');
  const needle = text.trim().toLowerCase();
  const shown = needle ? items.filter((c) => [c.case_ref, c.customer_name, c.customer_id, c.zip && c.zip.filename, c.reporting_period, fmtPeriod(c.reporting_period)].some((v) => v && String(v).toLowerCase().indexOf(needle) > -1)) : items;

  // Section headers follow the backend's order; rows are never re-sorted.
  const rows = [];
  let section = null;
  shown.forEach((c) => {
    const s = SECTION[c.status] || [c.status, c.status];
    if (!status && s[0] !== section) { section = s[0]; rows.push({ group: <span className="rf-row" style={{ gap: 6 }}><Glyph name={{ IN_PROGRESS: 'active', OPEN: 'waiting', COMPLETED: 'success' }[s[0]] || 'dot'} still />{s[1]}</span> }); }
    rows.push(caseRow(c, now, nav, { start: true }));
  });
  const open = counts ? (counts.WAITING || 0) + (counts.IN_PROGRESS || 0) + (counts.PENDING || 0) : null;

  const completed = ((data && data.items) || []).filter((c) => c.status === 'COMPLETED');
  const withExc = completed.filter((c) => c.completed && c.completed.case_status && c.completed.case_status !== 'CLEAN').length;
  return <div className="rf-page dash">
    <div className="rf-page__head">
      <div><h1 className="rf-page__title">Dashboard</h1><div className="rf-page__sub">{fmtDay(new Date(now).toISOString())}{open != null ? ' · ' + open + ' open case' + (open === 1 ? '' : 's') + (mine ? ' assigned to you' : '') : ''}</div></div>
      <span className="rf-spacer" />
      {user && <div className="rf-row" role="tablist" aria-label="Whose cases" style={{ gap: 4 }}>
        <Button size="sm" variant={mine ? 'primary' : 'quiet'} role="tab" aria-selected={mine} onClick={() => nav(scopeQ(status, ''))}>My cases</Button>
        <Button size="sm" variant={mine ? 'quiet' : 'primary'} role="tab" aria-selected={!mine} onClick={() => nav(scopeQ(status, 'all'))}>All cases</Button>
      </div>}
      {q.refreshing && data && <span className="rf-muted" style={{ fontSize: 12 }}>Refreshing…</span>}
      <Button size="sm" icon="refresh" onClick={() => q.reload()}>Refresh</Button>
      <Button variant="primary" icon="upload" onClick={() => nav('register')}>Upload a submission</Button>
    </div>

    {data && <div className="dash-kpis">
      {[['In progress', counts.IN_PROGRESS || 0, 'IN_PROGRESS'], ['Not started', (counts.WAITING || 0) + (counts.PENDING || 0), 'WAITING'],
        ['Completed', counts.COMPLETED || 0, 'COMPLETED'], ['Completed with exceptions', withExc, 'COMPLETED']].map(([label, n, s]) =>
        <button key={label} type="button" className="dash-kpi" onClick={() => nav(s === 'COMPLETED' ? 'completed' : scopeQ(s, scopeParam))}><span className="dash-kpi__n">{n}</span><span className="dash-kpi__l">{label}</span></button>)}
    </div>}

    <div className="rf-buckets" role="tablist" aria-label="Queue status">
      {BUCKETS.map(([s, label, glyph, tone, hint]) => <button key={s || 'all'} type="button" role="tab" aria-selected={s === status} className={cx('rf-bucket', 'rf-bucket--' + tone, s === status && 'is-active')} onClick={() => nav(scopeQ(s, scopeParam))}>
        <span className="rf-bucket__label"><Glyph name={glyph} still />{label}</span>
        <span className="rf-bucket__count">{counts ? (s ? counts[s] || 0 : total) : '–'}</span>
        <span className="rf-bucket__hint">{s === 'IN_PROGRESS' && counts && !counts.IN_PROGRESS ? 'Slot free' : hint}</span>
      </button>)}
    </div>

    {q.error && !data && <Notice tone="danger" title="The work queue could not be loaded" actions={<Button size="sm" icon="refresh" onClick={() => q.reload()}>Try again</Button>}>{q.error.message}</Notice>}
    {q.loading && <Skeleton rows={6} />}
    {data && <ActiveSlot data={data} nav={nav} now={now} />}

    {data && <section className="rf-panel">
      <div className="rf-panel__head"><h3 className="rf-panel__title" style={{ marginRight: 12 }}>Open cases</h3><div className="rf-toolbar" style={{ flex: 1 }}>
        <label className="rf-search" style={{ minWidth: 340 }}><Icon name="search" /><input ref={searchRef} type="search" value={text} onChange={(e) => setText(e.target.value)} placeholder="Case, customer, ZIP name or period" aria-label="Search the work queue" /></label>
        {text && <Button variant="quiet" size="sm" icon="x" onClick={() => setText('')}>Clear</Button>}
        <span className="rf-spacer" />
        <span className="rf-muted" style={{ fontSize: 12 }}>{needle ? shown.length + ' of ' + items.length : items.length} open case{items.length === 1 ? '' : 's'}</span>
        <Button variant="quiet" size="sm" iconRight="arrowRight" onClick={() => nav('completed')}>Completed cases{counts ? ' · ' + (counts.COMPLETED || 0) : ''}</Button>
      </div></div>
      {q.error && <div style={{ padding: '0 16px 12px' }}><Notice tone="danger" compact title="Refresh failed">{q.error.message}</Notice></div>}
      {shown.length
        ? <Table columns={caseColumns({ assignment: true })} rows={rows} caption="Cases" />
        : <Empty icon="inbox" title={needle ? 'No case matches “' + text.trim() + '”' : status ? 'No ' + (BUCKETS.find((b) => b[0] === status) || [0, ''])[1] + ' cases' : mine ? 'No open cases assigned to you' : 'No open cases'} action={needle ? <Button size="sm" onClick={() => setText('')}>Clear search</Button> : <Button variant="primary" icon="upload" onClick={() => nav('register')}>Upload a submission</Button>}>{needle ? 'Search covers case reference, customer, file name and period.' : 'Upload a customer’s evidence ZIP, or start one of the submissions waiting below.'}</Empty>}
    </section>}

    {app && app.demo_scenarios && <DemoScenariosSection nav={nav} focus={!!focusDemo} />}
  </div>;
}
