/* Register a case (S02 / O8): POST /api/cases { customer_name, reporting_period, zip_name, zip_b64, customer_id? }.
   The case is created WAITING; registration never starts processing (contract §3.1). */
import React from 'react';
import { useQuery, useMutation, useStoreApi } from '../hooks.js';
import { Button, WithReason, Panel, Notice, Enum, Icon, Bullets, cx } from '../../ui/index.jsx';
import { fmtBytes, fmtPeriod } from '../format.js';
import { fileToBase64 } from '../../services/dataService.js';

const NEW = '__new';

export default function RegisterScreen({ route, nav: navProp }) {
  const store = useStoreApi();
  const nav = navProp || store.nav;
  const query = route.query || {};
  const customers = useQuery('customers', (svc) => svc.listCustomers());
  const list = React.useMemo(() => (customers.data || []).slice().sort((a, b) => String(a.customer_name).localeCompare(String(b.customer_name))), [customers.data]);
  const [choice, setChoice] = React.useState(query.customer_id || (query.customer_name ? NEW : ''));
  const [newName, setNewName] = React.useState(query.customer_id ? '' : query.customer_name || '');
  const [period, setPeriod] = React.useState('');
  const [file, setFile] = React.useState(null);
  const [over, setOver] = React.useState(false);
  const fileRef = React.useRef(null);
  const m = useMutation();

  // A customer_id from the link that the list does not know: keep its name as a new customer.
  React.useEffect(() => {
    if (customers.data && choice && choice !== NEW && !customers.data.some((c) => c.customer_id === choice)) { setChoice(NEW); if (!newName && query.customer_name) setNewName(query.customer_name); }
  }, [customers.data]);

  const selected = choice && choice !== NEW ? list.find((c) => c.customer_id === choice) : null;
  const customerName = choice === NEW ? newName.trim() : selected ? selected.customer_name : '';
  const isZip = file && /\.zip$/i.test(file.name);
  const reason = !customerName ? (choice === NEW ? 'Enter the new customer’s name' : 'Choose a customer') : !/^\d{4}-\d{2}$/.test(period) ? 'Choose the reporting period' : !file ? 'Attach the customer’s original ZIP' : !isZip ? 'The file must be a .zip archive' : null;
  const back = () => nav(query.customer_id ? 'customers/' + encodeURIComponent(query.customer_id) : 'queue');

  const pick = (f) => { if (f) { setFile(f); m.reset(); } };
  const submit = async (e) => {
    if (e) e.preventDefault();
    if (reason || m.busy) return;
    const body = { customer_name: customerName, reporting_period: period, zip_name: file.name };
    const r = await m.run(async (svc) => svc.registerCase(Object.assign(body, { zip_b64: await fileToBase64(file) }, selected ? { customer_id: selected.customer_id } : {})), { inline: true, success: (x) => 'Case ' + ((x && x.case_ref) || '') + ' registered · Waiting' });
    if (r && r.case_ref) nav('cases/' + r.case_ref + '/overview');
  };

  return <div className="rf-page">
    <div className="rf-breadcrumb"><a href="#/queue" onClick={(e) => { e.preventDefault(); nav('queue'); }}>Work queue</a><Icon name="chevronRight" size={12} /><span>Register case</span></div>
    <div className="rf-page__head" style={{ marginTop: -12 }}><div><h1 className="rf-page__title">Register a case</h1><div className="rf-page__sub">Attach a customer’s original evidence ZIP for one reporting period. The case is created as Waiting.</div></div></div>
    <div className="rf-split">
      <Panel title="Case details" sub="Several cases may share a customer and a period">
        <form className="as-form" onSubmit={submit} noValidate>
          <div className="rf-field">
            <label className="rf-label" htmlFor="reg-customer">Customer<span className="rf-label__req">*</span></label>
            <select id="reg-customer" className="rf-input" value={choice} onChange={(e) => { setChoice(e.target.value); m.reset(); }} disabled={m.busy}>
              <option value="">{customers.loading ? 'Loading customers…' : 'Choose a customer…'}</option>
              {list.map((c) => <option key={c.customer_id} value={c.customer_id}>{c.customer_name} · {c.customer_id}</option>)}
              <option value={NEW}>New customer…</option>
            </select>
            {customers.error && <div className="rf-fielderror"><Icon name="alert" size={12} />Customers could not be loaded: {customers.error.message}</div>}
            {choice === NEW && <input className="rf-input" aria-label="New customer name" placeholder="Legal name, e.g. Harbourline Payments Ltd" value={newName} onChange={(e) => setNewName(e.target.value)} disabled={m.busy} />}
            <div className="rf-help">{choice === NEW ? 'The backend creates the customer with the case.' : selected ? <>Customer ID <span className="rf-mono">{selected.customer_id}</span> is sent with the case.</> : 'Choose an existing customer, or add a new one.'}</div>
          </div>
          <div className="rf-field">
            <label className="rf-label" htmlFor="reg-period">Reporting period<span className="rf-label__req">*</span></label>
            <input id="reg-period" className="rf-input" type="month" value={period} onChange={(e) => { setPeriod(e.target.value); m.reset(); }} style={{ maxWidth: 220 }} disabled={m.busy} />
            <div className="rf-help">{/^\d{4}-\d{2}$/.test(period) ? <>{fmtPeriod(period)} · sent as <span className="rf-mono">{period}</span></> : 'The month the evidence covers (YYYY-MM).'}</div>
          </div>
          <div className="rf-field">
            <span className="rf-label" id="reg-zip-label">Original ZIP<span className="rf-label__req">*</span></span>
            <input ref={fileRef} id="reg-zip" type="file" accept=".zip,application/zip" className="rf-sr" aria-labelledby="reg-zip-label" onChange={(e) => { pick(e.target.files && e.target.files[0]); e.target.value = ''; }} />
            {file
              ? <div className={cx('as-file', !isZip && 'is-error')}><Icon name="archive" /><div style={{ minWidth: 0, flex: 1 }}><div className="rf-strong as-file__name">{file.name}</div><div className="rf-help">{fmtBytes(file.size)}{!isZip ? ' · not a .zip file' : ' · stored content-addressed with its SHA-256'}</div></div><Button size="sm" onClick={() => fileRef.current && fileRef.current.click()} disabled={m.busy}>Choose another</Button></div>
              : <div className={cx('rf-dropzone', over && 'is-over')} onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files && e.dataTransfer.files[0]); }}>
                <Icon name="upload" size={20} /><div className="rf-dropzone__title">Drop the customer’s ZIP here</div><div>One .zip archive as received from the customer</div>
                <Button size="sm" icon="archive" onClick={() => fileRef.current && fileRef.current.click()}>Choose ZIP</Button></div>}
            <div className="rf-help">The server refuses files that are not ZIP archives or are larger than 50 MB.</div>
          </div>
          {m.error && <Notice tone="danger" title="The case was not registered">{m.error}{m.code && <> <Enum>{m.code}</Enum></>}</Notice>}
          <div className="rf-row" style={{ justifyContent: 'flex-end', gap: 8 }}>
            <Button onClick={back} disabled={m.busy}>Cancel</Button>
            <WithReason reason={reason}><Button type="submit" variant="primary" icon="check" loading={m.busy} disabled={!!reason}>{m.busy ? 'Registering…' : 'Register case'}</Button></WithReason>
          </div>
        </form>
      </Panel>
      <div className="rf-stack rf-stack--5">
        <Panel title="What happens next">
          <Bullets items={[['archive', 'The ZIP is attached to the new case unchanged and its SHA-256 recorded.'], ['clock', 'The case is Waiting. Registration never starts processing.'], ['play', 'Open the case and choose Start Smart Parsing when you are ready. Only one case can be In Progress at a time.']]} />
        </Panel>
        <Notice tone="info" title="Nothing starts automatically" compact>Starting, deferring and resuming are separate, confirmed steps on the case.</Notice>
      </div>
    </div>
  </div>;
}
