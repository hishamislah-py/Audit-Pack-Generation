/* S04 · Customer profile. GET /api/customers/{customer_id} → { customer_id, customer_name, cases[CaseSummary],
   reconciliation_history[] } (contract §3.8). Cases render in the order returned. */
import React from 'react';
import { useQuery, useStoreApi } from '../hooks.js';
import { Button, Panel, Notice, Table, Empty, Skeleton, Pill, Ref, KV, Icon } from '../../ui/index.jsx';
import { fmtDateTime, fmtPeriod } from '../format.js';
import { caseColumns, caseRow, nowOf } from './Queue.jsx';

export default function CustomerScreen({ route, nav: navProp }) {
  const store = useStoreApi();
  const nav = navProp || store.nav;
  const id = route.id;
  const q = useQuery(id ? 'customer:' + id : null, (svc) => svc.getCustomer(id), { poll: store.POLL.queue, focus: true });
  const now = nowOf(store);
  const d = q.data;
  const crumb = <div className="rf-breadcrumb"><a href="#/customers" onClick={(e) => { e.preventDefault(); nav('customers'); }}>Customers</a><Icon name="chevronRight" size={12} /><span>{d ? d.customer_name : id}</span></div>;

  if (q.error && !d) return <div className="rf-page">{crumb}<Notice tone="danger" title="This customer could not be loaded" actions={<><Button size="sm" onClick={() => nav('customers')}>All customers</Button><Button size="sm" icon="refresh" onClick={() => q.reload()}>Try again</Button></>}>{q.error.message}</Notice></div>;
  if (!d) return <div className="rf-page">{crumb}<Skeleton rows={8} /></div>;

  const cases = d.cases || [];
  const hist = d.reconciliation_history || [];
  const by = {}; cases.forEach((c) => { by[c.status] = (by[c.status] || 0) + 1; });
  const open = (by.WAITING || 0) + (by.IN_PROGRESS || 0) + (by.PENDING || 0);
  const lastRec = hist.reduce((m, h) => (!m || Date.parse(h.at) > Date.parse(m.at) ? h : m), null);
  const register = () => nav('register?customer_id=' + encodeURIComponent(d.customer_id) + '&customer_name=' + encodeURIComponent(d.customer_name));

  // Reporting periods: the cases grouped by period (display only), most recent period first.
  const periods = [];
  cases.forEach((c) => { let p = periods.find((x) => x.period === c.reporting_period); if (!p) { p = { period: c.reporting_period, cases: [] }; periods.push(p); } p.cases.push(c); });
  periods.sort((a, b) => (a.period < b.period ? 1 : a.period > b.period ? -1 : 0));

  const histCols = [
    { key: 'p', label: 'Period', width: '130px' }, { key: 'ref', label: 'Case', width: '160px' }, { key: 'run', label: 'Reconciliation run' },
    { key: 'snap', label: 'Snapshot' }, { key: 'out', label: 'Outcome', width: '170px' }, { key: 'at', label: 'Completed', width: '160px' }
  ];
  const histRows = hist.map((h, i) => ({ key: h.reconciliation_run_id || i, onClick: () => nav('cases/' + h.case_ref + '/recon'), cells: {
    p: <span className="rf-nowrap">{fmtPeriod(h.reporting_period)}</span>, ref: <Ref id={h.case_ref} />, run: <Ref id={h.reconciliation_run_id} copy />,
    snap: <Ref id={h.snapshot_id} copy />, out: <Pill state={h.case_status} />, at: <span className="rf-nowrap rf-secondary">{fmtDateTime(h.at)}</span>
  } }));

  return <div className="rf-page">
    {crumb}
    <div className="rf-page__head" style={{ marginTop: -12 }}>
      <div><h1 className="rf-page__title">{d.customer_name}</h1><div className="rf-page__sub"><span className="rf-mono">{d.customer_id}</span> · {cases.length} case{cases.length === 1 ? '' : 's'} · {open} open</div></div>
      <span className="rf-spacer" />
      {q.refreshing && <span className="rf-muted" style={{ fontSize: 12 }}>Refreshing…</span>}
      <Button size="sm" icon="refresh" onClick={() => q.reload()}>Refresh</Button>
      <Button variant="primary" icon="plus" onClick={register}>Register case</Button>
    </div>
    <div className="rf-split" style={{ gridTemplateColumns: 'minmax(0,1fr) 320px' }}>
      <div className="rf-stack rf-stack--5">
        {periods.length > 0 && <Panel title="Reporting periods" sub="A period can have more than one case">
          <div className="as-periods">{periods.slice(0, 12).map((p) => <div key={p.period} className="as-period">
            <div className="as-period__head"><span className="as-period__name">{fmtPeriod(p.period)}</span><span className="rf-mono rf-muted" style={{ fontSize: 11 }}>{p.cases.length} case{p.cases.length > 1 ? 's' : ''}</span></div>
            {p.cases.map((c) => <button key={c.case_ref} type="button" className="as-period__case" onClick={() => nav('cases/' + c.case_ref + '/overview')} title={'Open ' + c.case_ref}>
              <span className="rf-mono">{c.case_ref}</span><span className="as-pills"><Pill state={c.status} />{c.completed && c.completed.case_status && <Pill state={c.completed.case_status} />}</span>
            </button>)}
          </div>)}</div>
        </Panel>}
        <Panel title="Cases" sub={cases.length + ' case' + (cases.length === 1 ? '' : 's') + ' · in the order returned by the backend'} flush>
          {cases.length ? <Table columns={caseColumns({ noCustomer: true, compact: true })} rows={cases.map((c) => caseRow(c, now, nav))} caption={'Cases for ' + d.customer_name} />
            : <Empty icon="inbox" title="No cases for this customer" action={<Button variant="primary" icon="plus" onClick={register}>Register case</Button>}>Register a case with the customer’s original evidence ZIP.</Empty>}
        </Panel>
        <Panel title="Reconciliation history" sub="Results belong to the snapshot they ran against" flush>
          {hist.length ? <Table columns={histCols} rows={histRows} dense caption="Reconciliation history" />
            : <Empty icon="scale" title="No completed reconciliation yet">A case completes when its reconciliation run finishes.</Empty>}
        </Panel>
      </div>
      <div className="rf-stack rf-stack--5">
        <Panel title="Customer" sub="From the customer record (read only)">
          <KV pairs={[
            ['Customer ID', <span className="rf-mono">{d.customer_id}</span>],
            ['Name', d.customer_name],
            ['Cases', cases.length],
            ['Open cases', open ? <span className="rf-row rf-row--wrap" style={{ gap: 6 }}>{['IN_PROGRESS', 'WAITING', 'PENDING'].filter((s) => by[s]).map((s) => <Pill key={s} state={s} count={by[s]} />)}</span> : <span className="rf-muted">None</span>],
            ['Last reconciliation', lastRec ? <span className="rf-stack rf-stack--2" style={{ gap: 4, alignItems: 'flex-start' }}><span>{fmtPeriod(lastRec.reporting_period)} · {fmtDateTime(lastRec.at)}</span><Pill state={lastRec.case_status} /></span> : <span className="rf-muted">None</span>]
          ]} />
        </Panel>
      </div>
    </div>
  </div>;
}
