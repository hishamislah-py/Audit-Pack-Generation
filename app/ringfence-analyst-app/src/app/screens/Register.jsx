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
  const [detected, setDetected] = React.useState(null);   // {period, basis} worked out by the server from the files
  const [detecting, setDetecting] = React.useState(false);
  const [manual, setManual] = React.useState(false);
  const [file, setFile] = React.useState(null);
  const [over, setOver] = React.useState(false);
  const fileRef = React.useRef(null);
  const m = useMutation();
  const [startNow, setStartNow] = React.useState(true);

  // A customer_id from the link that the list does not know: keep its name as a new customer.
  React.useEffect(() => {
    if (customers.data && choice && choice !== NEW && !customers.data.some((c) => c.customer_id === choice)) { setChoice(NEW); if (!newName && query.customer_name) setNewName(query.customer_name); }
  }, [customers.data]);

  const [typed, setTyped] = React.useState(query.customer_name || '');
  React.useEffect(() => { if (query.customer_id && customers.data) { const c = customers.data.find((x) => x.customer_id === query.customer_id); if (c && !typed) setTyped(c.customer_name); } }, [customers.data]);
  const selected = list.find((c) => String(c.customer_name).trim().toLowerCase() === typed.trim().toLowerCase()) || null;
  const customerName = selected ? selected.customer_name : typed.trim();
  const isZip = file && /\.zip$/i.test(file.name);
  const effPeriod = manual || !detected ? period : detected.period;
  const reason = !customerName ? 'Enter the customer’s name' : !file ? 'Choose the customer’s ZIP' : !isZip ? 'The file must be a .zip archive'
    : detecting ? 'Reading the files…' : !/^\d{4}-\d{2}$/.test(effPeriod) ? 'The period could not be read from the files: choose it' : null;
  const back = () => nav(query.customer_id ? 'customers/' + encodeURIComponent(query.customer_id) : 'queue');

  const pick = async (f) => {
    if (!f) return;
    setFile(f); m.reset(); setDetected(null); setManual(false);
    if (!/\.zip$/i.test(f.name)) return;
    setDetecting(true);
    try {
      const r = await store.svc.detectPeriod({ zip_name: f.name, zip_b64: await fileToBase64(f) });
      setDetected(r && r.detected ? r.detected : null);
      if (!(r && r.detected)) setManual(true);
    } catch (e) { setManual(true); } finally { setDetecting(false); }
  };
  const submit = async (e, start = true) => {
    if (e) e.preventDefault();
    setStartNow(start);
    if (reason || m.busy) return;
    const body = { customer_name: customerName, reporting_period: effPeriod, zip_name: file.name };
    const r = await m.run(async (svc) => svc.registerCase(Object.assign(body, { zip_b64: await fileToBase64(file) }, selected ? { customer_id: selected.customer_id } : {})), { inline: true, success: (x) => 'Case ' + ((x && x.case_ref) || '') + ' created' });
    if (r && r.case_ref) nav('cases/' + r.case_ref + '/overview' + (start ? '?action=start' : ''));
  };

  return <div className="rf-page">
    <div className="rf-breadcrumb"><a href="#/queue" onClick={(e) => { e.preventDefault(); nav('queue'); }}>Dashboard</a><Icon name="chevronRight" size={12} /><span>Upload a submission</span></div>
    <div className="rf-page__head" style={{ marginTop: -12 }}><div><h1 className="rf-page__title">Upload a submission</h1><div className="rf-page__sub">Name the customer and choose their evidence ZIP. The reporting period is read from the files.</div></div></div>
    <div className="rf-split">
      <Panel title="Submission">
        <form className="as-form" onSubmit={submit} noValidate>
          <div className="rf-field">
            <label className="rf-label" htmlFor="reg-customer">Customer<span className="rf-label__req">*</span></label>
            <input id="reg-customer" className="rf-input" list="reg-customers" placeholder="Customer name, e.g. Harbourline Payments Ltd" value={typed}
              onChange={(e) => { setTyped(e.target.value); m.reset(); }} disabled={m.busy} autoComplete="off" />
            <datalist id="reg-customers">{list.map((c) => <option key={c.customer_id} value={c.customer_name} />)}</datalist>
            {customers.error && <div className="rf-fielderror"><Icon name="alert" size={12} />Customers could not be loaded: {customers.error.message}</div>}
            <div className="rf-help">{selected ? <>Existing customer · <span className="rf-mono">{selected.customer_id}</span></> : typed.trim() ? 'A new customer is created with the case.' : 'Type the customer’s name; existing customers are suggested.'}</div>
          </div>
          <div className="rf-field">
            <span className="rf-label" id="reg-zip-label">Original ZIP<span className="rf-label__req">*</span></span>
            <input ref={fileRef} id="reg-zip" type="file" accept=".zip,application/zip" className="rf-sr" aria-labelledby="reg-zip-label" onChange={(e) => { pick(e.target.files && e.target.files[0]); e.target.value = ''; }} />
            {file
              ? <div className={cx('as-file', !isZip && 'is-error')}><Icon name="archive" /><div style={{ minWidth: 0, flex: 1 }}><div className="rf-strong as-file__name">{file.name}</div><div className="rf-help">{fmtBytes(file.size)}{!isZip ? ' · not a .zip file' : ' · stored content-addressed with its SHA-256'}</div></div><Button size="sm" onClick={() => fileRef.current && fileRef.current.click()} disabled={m.busy}>Choose another</Button></div>
              : <div className={cx('rf-dropzone', over && 'is-over')} onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files && e.dataTransfer.files[0]); }}>
                <Icon name="upload" size={20} /><div className="rf-dropzone__title">Drop the customer’s ZIP here</div><div>One .zip archive as received from the customer</div>
                <Button size="sm" icon="archive" onClick={() => fileRef.current && fileRef.current.click()}>Choose ZIP</Button></div>}
            <div className="rf-help">One .zip archive, up to 50 MB.</div>
          </div>
          {file && isZip && <div className="rf-field">
            <span className="rf-label">Reporting period</span>
            {detecting ? <div className="rf-help"><span className="rf-live" /> Reading the files…</div>
              : detected && !manual ? <div className="reg-period"><span className="reg-period__v">{fmtPeriod(detected.period)}</span><span className="rf-help">read from the {detected.basis}</span>
                  <Button size="sm" variant="link" onClick={() => { setManual(true); setPeriod(detected.period); }}>Change</Button></div>
              : <><input id="reg-period" className="rf-input" type="month" value={period} onChange={(e) => { setPeriod(e.target.value); m.reset(); }} style={{ maxWidth: 220 }} disabled={m.busy} />
                  <div className="rf-help">{detected ? 'Overriding the period read from the files.' : 'The period could not be read from the files; choose the month the evidence covers.'}</div></>}
          </div>}
          {m.error && <Notice tone="danger" title="The case was not registered">{m.error}{m.code && <> <Enum>{m.code}</Enum></>}</Notice>}
          <div className="rf-row" style={{ justifyContent: 'flex-end', gap: 8 }}>
            <Button onClick={back} disabled={m.busy}>Cancel</Button>
            <WithReason reason={reason}><Button variant="secondary" loading={m.busy && !startNow} disabled={!!reason || m.busy} onClick={() => submit(null, false)}>Upload only</Button></WithReason>
            <WithReason reason={reason}><Button type="submit" variant="primary" icon="play" loading={m.busy && startNow} disabled={!!reason}>{m.busy ? 'Uploading…' : 'Upload and start'}</Button></WithReason>
          </div>
        </form>
      </Panel>
      <div className="rf-stack rf-stack--5">
        <Panel title="What happens next">
          <Bullets items={[['archive', 'The ZIP is kept unchanged with its SHA-256 fingerprint.'], ['play', 'Upload and start runs Smart Parsing straight away; when everything checks out, reconciliation and the AI review follow automatically.'], ['clock', 'Upload only keeps the case as Not started until you start it.']]} />
        </Panel>
      </div>
    </div>
  </div>;
}
