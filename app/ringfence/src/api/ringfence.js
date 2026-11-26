// One function per endpoint of RINGFENCE_FRONTEND_API_CONTRACT.md. No business rule lives here.
// Every case mutation sends `expected_revision` (the revision the screen was rendered from) so the backend can refuse a
// stale action with 409 CASE_CHANGED.
import { get, post, fileToBase64 } from "./client.js";

const enc = encodeURIComponent;
const rev = (r) => (r === undefined || r === null ? {} : { expected_revision: r });

export const api = {
  // application context (analyst, LLM mode, category registry, engine availability)
  app: () => get("app"),

  // queue and customers
  cases: (status) => get("cases" + (status ? "?status=" + enc(status) : "")),
  customers: () => get("customers"),
  customer: (id) => get("customers/" + enc(id)),

  // case
  caseDetail: (ref) => get("cases/" + enc(ref)),
  caseActivity: (ref) => get(`cases/${enc(ref)}/activity`),
  run: (ref, runId) => get(`cases/${enc(ref)}/runs/${enc(runId)}`),

  async registerCase({ customerName, period, file }) {
    return post("cases", { customer_name: customerName, reporting_period: period, zip_name: file.name,
                           zip_b64: await fileToBase64(file) });
  },
  start: (ref, r) => post(`cases/${enc(ref)}/start`, rev(r)),
  defer: (ref, r) => post(`cases/${enc(ref)}/defer`, rev(r)),
  resume: (ref, r) => post(`cases/${enc(ref)}/resume`, rev(r)),
  retry: (ref, r) => post(`cases/${enc(ref)}/retry`, { confirm: true, ...rev(r) }),
  activate: (ref, r) => post(`cases/${enc(ref)}/activate`, { confirm: true, ...rev(r) }),
  reconcile: (ref, r) => post(`cases/${enc(ref)}/reconcile`, rev(r)),

  // evidence: stage the file, then hand it to the case (the backend decides intake vs correction)
  async uploadEvidence(ref, file, category, r) {
    const staged = await post("staging", { name: file.name, data_b64: await fileToBase64(file) });
    const entry = (staged.entries || []).find((e) => e.staging_id);
    if (!entry) throw new Error("The file could not be staged.");
    return post(`cases/${enc(ref)}/evidence`, { staging_id: entry.staging_id, category, ...rev(r) });
  },

  // mapping review
  review: (ref, vid) => get(`cases/${enc(ref)}/review/${enc(vid)}`),
  decide: (ref, vid, { action, sourceIndex, field }, r) =>
    post(`cases/${enc(ref)}/review/${enc(vid)}/decision`,
         { action, source_index: sourceIndex, ...(field ? { canonical_field: field } : {}), ...rev(r) }),
  confirmFile: (ref, vid, r) => post(`cases/${enc(ref)}/review/${enc(vid)}/confirm`, rev(r)),
  rejectFile: (ref, vid, r) => post(`cases/${enc(ref)}/review/${enc(vid)}/reject`, rev(r)),

  // evidence detail, snapshot
  fileVersion: (pid, vid) => get(`packages/${enc(pid)}/versions/${enc(vid)}`),
  fileColumns: (pid, vid) => get(`packages/${enc(pid)}/versions/${enc(vid)}/columns`),
  packageHistory: (pid) => get(`packages/${enc(pid)}/history`),
  snapshot: (pid, sid) => get(`packages/${enc(pid)}/snapshots/${enc(sid)}`),

  // reconciliation results
  reconRun: (runId) => get("runs/" + enc(runId)),
  controls: (runId, outcome) => get(`runs/${enc(runId)}/controls` + (outcome ? "?outcome=" + enc(outcome) : "")),
  exception: (runId, excId) => get(`runs/${enc(runId)}/exceptions/${enc(excId)}`),
};
