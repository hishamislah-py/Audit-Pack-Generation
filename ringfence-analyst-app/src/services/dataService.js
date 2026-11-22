/* ==========================================================================
   Data-service contract · one method per backend operation in
   RINGFENCE_FRONTEND_API_CONTRACT.md. Requests and responses use the
   contract's payloads unchanged (snake_case); screens render them directly.
   Implementations: httpService.js (the Ringfence backend) and
   mockService.js (temporary in-browser mock with the same payloads).
   Errors reject with { status, error, message } exactly as the backend sends.
   ========================================================================== */

// [method, HTTP, path, request body, response]
export const METHODS = [
  ['getApp', 'GET', '/api/app', null, '{ reviewer, llm, engine_configured, categories }'],
  ['listCases', 'GET', '/api/cases[?status=]', null, '{ items: CaseSummary[], counts, active_case_ref, active_case, ordering }'],
  ['registerCase', 'POST', '/api/cases', '{ customer_name, reporting_period, zip_name, zip_b64, customer_id? }', 'CaseDetail'],
  ['getCase', 'GET', '/api/cases/{ref}', null, 'CaseDetail'],
  ['startCase', 'POST', '/api/cases/{ref}/start', '{ expected_revision? }', 'CaseDetail'],
  ['deferCase', 'POST', '/api/cases/{ref}/defer', '{ expected_revision? }', 'CaseDetail'],
  ['resumeCase', 'POST', '/api/cases/{ref}/resume', '{ expected_revision? }', 'CaseDetail'],
  ['retryCase', 'POST', '/api/cases/{ref}/retry', '{ confirm: true, expected_revision? }', 'CaseDetail'],
  ['validateCase', 'POST', '/api/cases/{ref}/validate', null, 'CaseDetail'],
  ['stageFile', 'POST', '/api/staging', '{ name, data_b64 }', '{ entries: [{ staging_id, ... }] }'],
  ['submitEvidence', 'POST', '/api/cases/{ref}/evidence', '{ staging_id, category }', '{ job_id, case }'],
  ['activateCase', 'POST', '/api/cases/{ref}/activate', '{ confirm: true }', '{ activated, reason, snapshot_id, case }'],
  ['reconcileCase', 'POST', '/api/cases/{ref}/reconcile', '{ expected_revision? }', '{ job_id, case }'],
  ['getRun', 'GET', '/api/cases/{ref}/runs/{run_id}', null, 'Run + { stages, events, llm_mode }'],
  ['getReview', 'GET', '/api/cases/{ref}/review/{vid}', null, 'Review'],
  ['postDecision', 'POST', '/api/cases/{ref}/review/{vid}/decision', '{ action, source_index, canonical_field?, expected_revision? }', 'Review (CaseDetail for REJECT)'],
  ['confirmReview', 'POST', '/api/cases/{ref}/review/{vid}/confirm', '{ expected_revision? }', 'CaseDetail'],
  ['rejectReview', 'POST', '/api/cases/{ref}/review/{vid}/reject', '{ expected_revision? }', 'CaseDetail'],
  ['getActivity', 'GET', '/api/cases/{ref}/activity', null, '{ case_ref, chain, status_history, events }'],
  ['listCustomers', 'GET', '/api/customers', null, 'CustomerSummary[]'],
  ['getCustomer', 'GET', '/api/customers/{customer_id}', null, '{ customer_id, customer_name, cases, reconciliation_history }'],
  ['getFileVersion', 'GET', '/api/packages/{pid}/versions/{vid}', null, '{ version, history, decisions, events }'],
  ['getVersionColumns', 'GET', '/api/packages/{pid}/versions/{vid}/columns', null, '{ columns }'],
  ['getVersionPreview', 'GET', '/api/packages/{pid}/versions/{vid}/preview', null, 'text/csv (whole canonical preview)'],
  ['getPackageHistory', 'GET', '/api/packages/{pid}/history', null, '{ categories, snapshots, validations }'],
  ['getSnapshot', 'GET', '/api/packages/{pid}/snapshots/{sid}', null, '{ snapshot, manifest, is_active, verification, reconciliation_eligible, runs }'],
  ['getJob', 'GET', '/api/jobs/{job_id}', null, '{ state, stages, files, progress, run_id }'],
  ['getReconRun', 'GET', '/api/runs/{run_id}', null, '{ case_status, exception_count, total_results, outcomes, integrity_checks, exceptions }'],
  ['getControls', 'GET', '/api/runs/{run_id}/controls?outcome=&check=', null, '{ total, rows, truncated }'],
  ['getReport', 'GET', '/api/runs/{run_id}/report', null, 'text/markdown (engine report)'],
  ['getException', 'GET', '/api/runs/{run_id}/exceptions/{exception_id}', null, '{ exception, affected_control_results, evidence, investigation_group, note }'],
  // Demo scenarios (server --demo-scenarios only)
  ['listDemoScenarios', 'GET', '/api/demo/scenarios', null, '{ enabled, folder, note, scenarios[] }'],
  ['loadDemoScenario', 'POST', '/api/demo/scenarios/{id}/load', '{}', 'CaseDetail (new WAITING case)'],
  ['getDemoVerification', 'GET', '/api/demo/scenarios/{id}/verification?case_ref=', null, '{ status, checks[] }'],
  // Closure: audit pack, AI investigations, analyst decisions, closing review and final pack (impl_20261120 CONTRACT.md).
  // Every closure mutation sends expected_revision = the CLOSURE revision (409 CLOSURE_CHANGED on mismatch).
  ['getClosure', 'GET', '/api/cases/{ref}/closure', null, 'ClosureView (404 NO_CLOSURE before reconciliation completes)'],
  ['getClosurePack', 'GET', '/api/cases/{ref}/closure/pack', null, '{ status, pack_id, reason, findings[], executive_summary, exception_register[], missing_evidence_register[], source_register[] }'],
  ['getAiConfiguration', 'GET', '/api/ai/configuration', null, '{ available, provider, model, reasoning_effort, problem, pricing_configured, store, data_notice }'],
  ['getClosureException', 'GET', '/api/cases/{ref}/closure/exceptions/{exc}', null, 'ExceptionWorkspace'],
  ['startInvestigation', 'POST', '/api/cases/{ref}/closure/exceptions/{exc}/investigations', '{ expected_revision }', '{ job_id, closure }'],
  ['getInvestigation', 'GET', '/api/cases/{ref}/closure/investigations/{inv}', null, '{ investigation, findings, evidence_ledger, tool_calls, verify }'],
  ['decideInvestigation', 'POST', '/api/cases/{ref}/closure/investigations/{inv}/decision', '{ decision: ACCEPT|REJECT, expected_revision }', '{ analyst_review, closure }'],
  ['getExceptionHistory', 'GET', '/api/cases/{ref}/closure/exceptions/{exc}/history', null, '{ events[] }'],
  ['openClosingReview', 'POST', '/api/cases/{ref}/closure/review', '{ expected_revision }', 'ReviewView'],
  ['setClosingSelections', 'POST', '/api/cases/{ref}/closure/review/selections', '{ selections[{ exception_id, inclusion, investigation_id? }], expected_revision }', 'ReviewView'],
  ['requestClosingPreview', 'POST', '/api/cases/{ref}/closure/review/preview', '{ confirm_ai, expected_revision }', '{ job_id | null, reused? }'],
  ['decideClosingReview', 'POST', '/api/cases/{ref}/closure/review/decision', '{ decision: HOLD|GENERATE, acknowledgement_accepted, acknowledged_summary_unavailable, snapshot_sha256, expected_revision }', '{ decision, closure, job_id? }'],
  ['getFinalPack', 'GET', '/api/cases/{ref}/closure/final-pack', null, '{ final_pack_id, status, verified, problems[], files[], authorised_by, generated_at }'],
  ['getClosureHistory', 'GET', '/api/cases/{ref}/closure/history', null, '{ events[], decisions[] }']
];

/* Closure file URLs (PDF, HTML, JSON). Used as plain same-origin `src=` / `href=` values and never fetched through
   request(), which reads text. kind: 'pack.html' | 'review/preview.pdf|html|json' |
   'final-pack/pdf|html|json|manifest|provenance.pdf'. */
export function closureFileUrl(ref, kind, download) {
  return '/api/cases/' + encodeURIComponent(ref) + '/closure/' + kind + (download ? '?download=1' : '');
}

export function assertDataService(svc) {
  const missing = METHODS.filter((m) => typeof svc[m[0]] !== 'function').map((m) => m[0]);
  if (missing.length) throw new Error('Data service is missing: ' + missing.join(', '));
  return svc;
}

// File → base64 for registerCase.zip_b64 and stageFile.data_b64 (contract §3.1, §3.4)
export function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(',')[1] || '');
    r.onerror = () => reject(r.error);
    r.readAsDataURL(file);
  });
}
