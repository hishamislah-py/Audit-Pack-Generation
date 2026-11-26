/* Activity tab (S14): GET /api/cases/{ref}/activity rendered as returned (newest first),
   with the hash-chain indicator and the case status history (contract §3.7). */
import React from 'react';
import { useQuery } from '../hooks.js';
import { Panel, Notice, Segmented, Empty, Skeleton, Pill, Enum, Icon, Timeline, Button } from '../../ui/index.jsx';
import { fmtDateTime, fmtTime, fmtDay } from '../format.js';

const LABELS = {
  CASE_CREATED: 'Case registered · original ZIP attached',
  CASE_STARTED: 'Smart Parsing started · case In Progress',
  CASE_RUN_STARTED: 'Smart Parser run started',
  CASE_RUN_FAILED: 'Smart Parser run failed',
  CASE_RETRY_REQUESTED: 'Retry from Beginning · new run from the original ZIP',
  CASE_DEFERRAL_REQUESTED: 'Defer Case requested · the running operation continues',
  CASE_DEFERRED: 'Case deferred · Pending',
  CASE_RESUMED: 'Processing resumed · case In Progress',
  CASE_COMPLETED: 'Case Completed',
  ANALYST_EVIDENCE_UPLOADED: 'Upload accepted · processing started automatically',
  ANALYST_REVIEW_CONFIRMED: 'File confirmed',
  ANALYST_CORRECTION_REQUESTED: 'File rejected · correction requested',
  ANALYST_VALIDATION_REQUESTED: 'Validation requested',
  ANALYST_ACTIVATION_REQUESTED: 'Package activated · snapshot sealed',
  ANALYST_RECONCILIATION_REQUESTED: 'Reconciliation requested',
  REVIEW_DECISION_RECORDED: 'Mapping decision recorded',
  REVIEW_COMPLETION_ROLLED_BACK: 'Review completion rolled back',
  PACKAGE_VALIDATION_PASSED: 'Validation passed',
  PACKAGE_VALIDATION_FAILED: 'Validation failed',
  INTAKE_STARTED: 'Intake started',
  INTAKE_COMPLETED: 'Intake completed',
  FILE_VERSION_PROCESSED: 'File version processed',
  RECONCILIATION_COMPLETED: 'Reconciliation completed',
  RECONCILIATION_FAILED: 'Reconciliation failed',
  PACKAGE_VALIDATED: 'Validation passed',
  RECONCILIATION_EXECUTED: 'Reconciliation completed'
};
const ICONS = { CASE_CREATED: 'archive', CASE_STARTED: 'play', CASE_RUN_STARTED: 'parser', CASE_RETRY_REQUESTED: 'refresh', CASE_RESUMED: 'play', ANALYST_EVIDENCE_UPLOADED: 'upload', ANALYST_REVIEW_CONFIRMED: 'check', ANALYST_VALIDATION_REQUESTED: 'checklist', ANALYST_RECONCILIATION_REQUESTED: 'scale', REVIEW_DECISION_RECORDED: 'mapping' };
const label = (t) => LABELS[t] || (t ? t.charAt(0) + t.slice(1).toLowerCase().replace(/_/g, ' ') : 'Event');
function look(e) {
  const t = e.event_type || '';
  if (/FAILED$/.test(t)) return { icon: 'alert', tone: 'danger' };
  if (t === 'ANALYST_CORRECTION_REQUESTED') return { icon: 'x', tone: 'attention' };
  if (/DEFER/.test(t)) return { icon: 'pause', tone: 'attention' };
  if (t === 'ANALYST_ACTIVATION_REQUESTED' || /SNAPSHOT|ACTIVATED/.test(t)) return { icon: 'lock', tone: 'sealed' };
  if (t === 'CASE_COMPLETED' || /(COMPLETED|PASSED|VALIDATED|EXECUTED)$/.test(t)) return { icon: 'check', tone: 'success' };
  const icon = ICONS[t] || (/^INTAKE_/.test(t) ? 'parser' : /^FILE_VERSION_/.test(t) ? 'file' : /^RECONCILIATION_/.test(t) ? 'scale' : /^PACKAGE_/.test(t) ? 'layers' : /^REVIEW_/.test(t) ? 'mapping' : /^CASE_/.test(t) ? 'flag' : 'activity');
  return { icon, tone: e.actor_role === 'analyst' ? 'analyst' : null };
}
const GROUPS = [['all', 'All'], ['case', 'Case'], ['analyst', 'Analyst'], ['system', 'System'], ['service', 'Service']];
function inGroup(g, e) {
  const t = e.event_type || '';
  if (g === 'case') return /^CASE_/.test(t);
  if (g === 'analyst') return /^ANALYST_/.test(t) || e.actor_role === 'analyst';
  if (g === 'system') return e.actor_role === 'system';
  if (g === 'service') return /^(PACKAGE_|FILE_VERSION_|INTAKE_|RECONCILIATION_|REVIEW_)/.test(t);
  return true;
}
const isHash = (v) => typeof v === 'string' && /^[0-9a-f]{64}$/i.test(v);
const short = (v) => v.slice(0, 8) + '…' + v.slice(-6);
function compact(v) {
  if (v == null) return '—';
  if (Array.isArray(v)) return v.length ? v.map(compact).join(', ') : 'none';
  if (typeof v === 'object') {
    if (v.job_id !== undefined || v.kind) return [v.job_id, v.kind && '(' + [v.kind, v.state].filter(Boolean).join(', ') + ')'].filter(Boolean).join(' ');
    return Object.entries(v).map(([k, x]) => k + '=' + compact(x)).join(' ');
  }
  if (isHash(v)) return short(v);
  return String(v);
}
function detailText(d) {
  if (!d || typeof d !== 'object') return null;
  const e = Object.entries(d).filter(([, v]) => v != null && v !== '' && !(Array.isArray(v) && !v.length));
  return e.length ? e.map(([k, v]) => k.replace(/_/g, ' ') + ': ' + compact(v)).join(' · ') : null;
}

export default function ActivityTab({ c, store }) {
  const ref = c.case_ref;
  const q = useQuery('activity:' + ref, (svc) => svc.getActivity(ref), { poll: store.casePoll(c) });
  const [group, setGroup] = React.useState('all');
  const [order, setOrder] = React.useState('newest');
  const [text, setText] = React.useState('');
  const d = q.data;
  const history = (d && d.status_history) || c.status_history || [];

  let main;
  if (q.error) main = <Notice tone="danger" title="Activity could not be loaded" actions={<Button size="sm" icon="refresh" onClick={q.reload}>Try again</Button>}>{q.error.message}</Notice>;
  else if (!d) main = <Skeleton rows={6} />;
  else {
    const events = d.events || [];
    const needle = text.trim().toLowerCase();
    const shown = events.filter((e) => inGroup(group, e) && (!needle || [e.event_type, label(e.event_type), e.actor_id, e.actor_role, e.event_id, e.intake_id, e.source_sha256, JSON.stringify(e.details || {})].join(' ').toLowerCase().includes(needle)));
    const list = order === 'oldest' ? shown.slice().reverse() : shown;
    const days = [];
    list.forEach((e) => {
      const day = fmtDay(e.at);
      if (!days.length || days[days.length - 1].day !== day) days.push({ day, items: [] });
      const lk = look(e);
      days[days.length - 1].items.push({
        t: fmtTime(e.at), icon: lk.icon, tone: lk.tone, title: label(e.event_type),
        actor: <>{e.actor_role === 'system' ? 'System' : (e.actor_id || 'Unknown') + ' · ' + (e.actor_role || 'actor')} · <Enum>{e.event_type}</Enum></>,
        detail: detailText(e.details), refs: [e.event_id, e.intake_id, e.source_sha256 ? 'sha256 ' + short(e.source_sha256) : null].filter(Boolean)
      });
    });
    main = <>
      <div className="rfd-filters">
        <Segmented items={GROUPS.map((g) => [g[0], g[1] + ' ' + events.filter((e) => inGroup(g[0], e)).length])} active={group} onChange={setGroup} />
        <label className="rf-search" style={{ minWidth: 260 }}><Icon name="search" /><input value={text} onChange={(e) => setText(e.target.value)} placeholder="Search events, actors, references" aria-label="Search activity" /></label>
        <span className="rf-spacer" />
        <Segmented items={[['newest', 'Newest first'], ['oldest', 'Oldest first']]} active={order} onChange={setOrder} />
      </div>
      <Panel>{days.length ? <Timeline days={days} /> : <Empty icon="activity" title="No events match">Change the filter or the search text.</Empty>}</Panel>
    </>;
  }

  return <div className="rf-workspace">
    <div className="rf-split" style={{ gridTemplateColumns: 'minmax(0, 1fr) 340px' }}>
      <div className="rf-stack rf-stack--3">{main}</div>
      <aside className="rf-stack rf-stack--3">
        <Panel title="Audit chain" sub="Append-only, hash-chained case events">
          {!d ? <span className="rf-skel" style={{ width: '70%' }} />
            : d.chain && d.chain.verified ? <span className="rf-integrity"><Icon name="shield" size={14} />Chain verified · {d.chain.events} events</span>
              : <Notice tone="danger" compact title="Chain not verified">The backend reports that the audit chain could not be verified.</Notice>}
        </Panel>
        <Panel title={'Case status history · ' + history.length} flush>
          <ul className="rfd-hist">{history.map((h, i) => <li key={i}><Pill state={h.status} /><span className="rfd-hist__at">{fmtDateTime(h.at)}</span>{h.note && <span className="rfd-hist__note">{h.note}</span>}</li>)}</ul>
        </Panel>
      </aside>
    </div>
  </div>;
}
