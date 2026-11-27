/* One-click "Start reconciliation" (simplified flow). Activation is no longer a separate screen or dialog:
   when the package is not yet activated, this button activates it (POST /activate {confirm:true}) and then
   starts reconciliation (POST /reconcile) with the new case revision. The backend still enforces every rule:
   activation is only offered when actions.activate.enabled (validation PASSED and current), and reconciliation
   only runs on the sealed snapshot. */
import React from 'react';
import { useMutation } from '../hooks.js';
import { Button, WithReason } from '../../ui/index.jsx';

export function reconAvailability(c) {
  const a = (c && c.actions) || {};
  if (!c || c.status === 'COMPLETED') return { enabled: false, reason: 'The case is Completed.' };
  if (!c.activation) return { enabled: !!(a.activate && a.activate.enabled), reason: (a.activate && a.activate.reason) || null };
  return { enabled: !!(a.reconcile && a.reconcile.enabled), reason: (a.reconcile && a.reconcile.reason) || null };
}

export default function StartReconButton({ c, nav, label, size, variant = 'primary' }) {
  const m = useMutation();
  const av = reconAvailability(c);
  const ref = c.case_ref;
  const go = async () => {
    const r = await m.run(async (svc) => {
      try {
        let rev = c.revision;
        if (!c.activation) {
          const act = await svc.activateCase(ref, { confirm: true, expected_revision: rev });
          if (act && act.activated === false) throw { status: 409, error: 'NOT_ACTIVATED', message: 'Reconciliation could not start: ' + (act.reason || 'the package was not activated.') };
          rev = act && act.case ? act.case.revision : undefined;
        }
        return await svc.reconcileCase(ref, rev != null ? { expected_revision: rev } : {});
      } catch (e) {
        // The backend starts activation + reconciliation by itself once Smart Parsing passes (AUTO_AFTER_SMART_PARSER).
        // If that won the race with this click (409 ALREADY_ACTIVATED / stale revision), open the run it started.
        if (e && e.status === 409) {
          const fresh = await svc.getCase(ref);
          const rec = fresh && fresh.progress && fresh.progress.reconciliation;
          if (fresh && fresh.activation && rec && rec.state && rec.state !== 'NOT_RUN') return { case: fresh };
        }
        throw e;
      }
    }, { success: 'Reconciliation started' });
    if (r) {
      const rid = r.case && r.case.progress && r.case.progress.reconciliation && r.case.progress.reconciliation.run_id;
      nav('cases/' + ref + '/recon' + (rid ? '/' + rid : ''));
    }
  };
  const btn = <Button variant={variant} size={size} icon="play" loading={m.busy} disabled={!av.enabled || m.busy} onClick={go}>{m.busy ? 'Starting…' : label || 'Start reconciliation'}</Button>;
  return <span className="rf-row" style={{ gap: 8, flexWrap: 'wrap' }}>
    {av.enabled ? btn : <WithReason reason={av.reason || 'Not available yet.'}>{btn}</WithReason>}
    {m.error && <span className="rf-tone-danger" style={{ fontSize: 12 }}>{m.error}</span>}
  </span>;
}
