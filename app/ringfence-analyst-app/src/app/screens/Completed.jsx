/* Completed cases (owner, 24 Nov 2026): finished cases live on their own page, so the dashboard shows only open work.
   Each completed case can be deleted: the backend moves its record aside (kept on disk, audited) and never reuses its
   reference. */
import React from 'react';
import { useQuery, useStoreApi, useMutation } from '../hooks.js';
import { Button, Notice, Table, Empty, Skeleton, Icon, Dialog } from '../../ui/index.jsx';
import { fmtPeriod } from '../format.js';
import { caseColumns, caseRow, nowOf } from './Queue.jsx';

export default function CompletedScreen({ nav: navProp }) {
  const store = useStoreApi();
  const nav = navProp || store.nav;
  const q = useQuery('queue:COMPLETED:all', (svc) => svc.listCases({ status: 'COMPLETED' }), { poll: store.POLL.queue, focus: true });
  const m = useMutation();
  const [text, setText] = React.useState('');
  const [del, setDel] = React.useState(null);
  const now = nowOf(store);
  const items = (q.data && q.data.items) || [];
  const needle = text.trim().toLowerCase();
  const shown = needle ? items.filter((c) => [c.case_ref, c.customer_name, c.zip && c.zip.filename, c.reporting_period, fmtPeriod(c.reporting_period)]
    .some((v) => v && String(v).toLowerCase().indexOf(needle) > -1)) : items;
  const cols = caseColumns({ assignment: true }).concat([{ key: 'del', label: <span className="rf-sr">Delete</span>, cls: 'is-tight' }]);
  const rows = shown.map((c) => {
    const r = caseRow(c, now, nav, {});
    r.cells.del = <Button variant="quiet" size="sm" icon="x" aria-label={'Delete ' + c.case_ref} onClick={(e) => { e.stopPropagation(); m.reset(); setDel(c); }}>Delete</Button>;
    return r;
  });
  const confirm = async () => {
    const ok = await m.run((svc) => svc.deleteCase(del.case_ref), { inline: true, success: del.case_ref + ' deleted' });
    if (ok) setDel(null);
  };
  return <div className="rf-page dash">
    <div className="rf-page__head">
      <div><h1 className="rf-page__title">Completed cases</h1><div className="rf-page__sub">{q.data ? items.length + ' completed case' + (items.length === 1 ? '' : 's') : 'Loading…'}</div></div>
      <span className="rf-spacer" />
      <Button size="sm" icon="refresh" onClick={() => q.reload()}>Refresh</Button>
      <Button size="sm" iconRight="arrowRight" onClick={() => nav('queue')}>Dashboard</Button>
    </div>
    {q.error && !q.data && <Notice tone="danger" title="Completed cases could not be loaded" actions={<Button size="sm" icon="refresh" onClick={() => q.reload()}>Try again</Button>}>{q.error.message}</Notice>}
    {q.loading && <Skeleton rows={6} />}
    {q.data && <section className="rf-panel">
      <div className="rf-panel__head"><div className="rf-toolbar" style={{ flex: 1 }}>
        <label className="rf-search" style={{ minWidth: 340 }}><Icon name="search" /><input type="search" value={text} onChange={(e) => setText(e.target.value)} placeholder="Case, customer, ZIP name or period" aria-label="Search completed cases" /></label>
        {text && <Button variant="quiet" size="sm" icon="x" onClick={() => setText('')}>Clear</Button>}
        <span className="rf-spacer" />
        <span className="rf-muted" style={{ fontSize: 12 }}>{needle ? shown.length + ' of ' + items.length : items.length} case{items.length === 1 ? '' : 's'}</span>
      </div></div>
      {shown.length ? <Table columns={cols} rows={rows} caption="Completed cases" />
        : <Empty icon="inbox" title={needle ? 'No completed case matches “' + text.trim() + '”' : 'No completed cases'}>{needle ? 'Search covers case reference, customer, file name and period.' : 'Cases appear here once their reconciliation has finished.'}</Empty>}
    </section>}
    {del && <div className="rfd-layer"><Dialog eyebrow={del.case_ref + ' · ' + del.customer_name} title="Delete this completed case?" error={m.error} onClose={m.busy ? undefined : () => setDel(null)}
      foot={<><Button onClick={() => setDel(null)} disabled={m.busy}>Cancel</Button><Button variant="danger" icon="x" loading={m.busy} onClick={confirm}>Delete case</Button></>}>
      <p style={{ margin: 0 }}>{del.customer_name} · {fmtPeriod(del.reporting_period)} disappears from the case list. Its files, audit pack and audit trail are kept on the server, and the case number {del.case_ref} is not reused.</p>
    </Dialog></div>}
  </div>;
}
