/* S03 · Customers. GET /api/customers → [{ customer_id, customer_name, cases, by_status }] (contract §3.8). */
import React from 'react';
import { useQuery, useStoreApi } from '../hooks.js';
import { Button, Notice, Table, Empty, Skeleton, Pill, Icon } from '../../ui/index.jsx';
import '../format.js';

const ORDER = ['IN_PROGRESS', 'WAITING', 'PENDING', 'COMPLETED'];

export default function CustomersScreen({ nav: navProp }) {
  const store = useStoreApi();
  const nav = navProp || store.nav;
  const q = useQuery('customers', (svc) => svc.listCustomers(), { focus: true });
  const [text, setText] = React.useState('');
  const list = React.useMemo(() => (q.data || []).slice().sort((a, b) => String(a.customer_name).localeCompare(String(b.customer_name))), [q.data]);
  const needle = text.trim().toLowerCase();
  const shown = needle ? list.filter((c) => (c.customer_name + ' ' + c.customer_id).toLowerCase().indexOf(needle) > -1) : list;
  const totalCases = list.reduce((a, c) => a + (c.cases || 0), 0);
  const columns = [
    { key: 'name', label: 'Customer' },
    { key: 'cases', label: 'Cases', cls: 'is-num', width: '90px' },
    { key: 'status', label: 'Cases by status' },
    { key: 'go', label: <span className="rf-sr">Open</span>, cls: 'is-tight' }
  ];
  const rows = shown.map((c) => {
    const open = () => nav('customers/' + encodeURIComponent(c.customer_id));
    const by = c.by_status || {};
    return { key: c.customer_id, onClick: open, cells: {
      name: <><span className="rf-cell-main">{c.customer_name}</span><span className="rf-cell-sub rf-mono">{c.customer_id}</span></>,
      cases: c.cases || <span className="rf-muted">0</span>,
      status: ORDER.some((s) => by[s]) ? <div className="rf-row rf-row--wrap" style={{ gap: 6 }}>{ORDER.filter((s) => by[s]).map((s) => <Pill key={s} state={s} count={by[s]} />)}</div> : <span className="rf-muted">No cases</span>,
      go: <Button variant="quiet" size="sm" icon="chevronRight" aria-label={'Open ' + c.customer_name} onClick={(e) => { e.stopPropagation(); open(); }} />
    } };
  });

  return <div className="rf-page">
    <div className="rf-page__head">
      <div><h1 className="rf-page__title">Customers</h1><div className="rf-page__sub">{q.data ? list.length + ' customer' + (list.length === 1 ? '' : 's') + ' · ' + totalCases + ' case' + (totalCases === 1 ? '' : 's') : 'Safeguarding evidence received monthly'}</div></div>
      <span className="rf-spacer" />
      <Button size="sm" icon="refresh" onClick={() => q.reload()}>Refresh</Button>
      <Button variant="primary" icon="plus" onClick={() => nav('register')}>Register case</Button>
    </div>
    {q.error && !q.data && <Notice tone="danger" title="Customers could not be loaded" actions={<Button size="sm" icon="refresh" onClick={() => q.reload()}>Try again</Button>}>{q.error.message}</Notice>}
    {q.loading && <Skeleton rows={6} />}
    {q.data && <section className="rf-panel">
      <div className="rf-panel__head"><div className="rf-toolbar" style={{ flex: 1 }}>
        <label className="rf-search" style={{ minWidth: 360 }}><Icon name="search" /><input type="search" value={text} onChange={(e) => setText(e.target.value)} placeholder="Customer name or ID" aria-label="Search customers" /></label>
        {text && <Button variant="quiet" size="sm" icon="x" onClick={() => setText('')}>Clear</Button>}
        <span className="rf-spacer" />
        <span className="rf-muted" style={{ fontSize: 12 }}>{needle ? shown.length + ' of ' + list.length : list.length} customer{list.length === 1 ? '' : 's'}</span>
      </div></div>
      {shown.length ? <Table columns={columns} rows={rows} caption="Customers" />
        : <Empty icon="building" title={needle ? 'No customer matches “' + text.trim() + '”' : 'No customers yet'} action={needle ? <Button size="sm" onClick={() => setText('')}>Clear search</Button> : <Button variant="primary" icon="plus" onClick={() => nav('register')}>Register case</Button>}>{needle ? 'Search covers customer name and ID.' : 'A customer is created when its first case is registered.'}</Empty>}
    </section>}
  </div>;
}
