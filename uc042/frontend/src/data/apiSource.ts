// FastAPI adapter (the default data source). Thin: every call is the existing endpoint in ../api/endpoints.ts. Errors
// propagate as ApiError; there is no fallback to mock data.
//
// The period and pack lists are requested by the top bar and by most pages at the same time. They are shared: one request
// serves every concurrent caller, and a result is reused for a few seconds only. Any change made through this source
// (upload, confirmation, processing, reassessment, review, AI request, case entry) and any background job that finishes
// drops the cache, so new documents, investigations and publications are never hidden.
import { api } from "../api/endpoints";
import { request } from "../api/client";
import type { ActivityEvent, Job, PackListItem } from "../api/types";
import type { DataSource } from "./DataSource";
import type { ActivityItem, ReconciliationPeriod } from "./models";
import { buildArchivePeriods, periodLabel } from "./periods";

const ACTION_LABEL: Record<string, string> = {
  PERIOD_OPENED: "Monthly report created", PERIOD_REGISTERED_FROM_PACKS: "Period registered from existing packs",
  PERIOD_RETITLED: "Report title changed",
  DOCUMENTS_UPLOADED: "Documents uploaded and validated", DOCUMENT_INCLUDED: "Document included", DOCUMENT_EXCLUDED: "Document excluded",
  BATCH_CONFIRMED: "Upload batch confirmed", PROCESSING_STARTED: "Processing started", PROCESSING_SUCCEEDED: "Processing succeeded",
  PROCESSING_FAILED: "Processing failed", PROCESSING_BLOCKED: "Processing blocked (engine period contract)",
  POC_SCENARIO_DOCUMENTS_REGISTERED: "POC scenario documents registered (read-only)",
  REASSESSMENT_STARTED: "Reassessment started", PACK_LINEAGE_RECORDED: "Reassessed pack linked to the pack it reassesses",
  DATABASE_UNIFIED: "Databases unified (migration)", INVESTIGATION_AUTHORIZATION_RECORDED: "Published-investigation authorisation recorded",
  AI_AUTHORIZED: "AI operation authorised", AI_AUTHORIZATION_REFUSED: "AI request refused (recorded)",
  REVIEW_OPENED: "Final review opened", REVIEW_SELECTIONS_CHANGED: "Review selections changed", PREVIEW_REQUESTED: "Preview requested",
  REVIEW_HOLD: "Review put on HOLD", REVIEW_GENERATED: "Final audit pack generated", REVIEW_GENERATION_FAILED: "Final-pack generation failed",
  CASE_OPENED: "Investigation case opened", CASE_NOTE_ADDED: "Case note added", CASE_EVIDENCE_ADDED: "Case evidence added",
  CASE_EVIDENCE_GAP_ADDED: "Case evidence gap recorded", CASE_OBSERVATION_ADDED: "Case observation recorded",
  CASE_HYPOTHESIS_ADDED: "Case hypothesis recorded", CASE_DECISION_RECORDED: "Case decision recorded", CASE_AI_REQUESTED: "AI assistance requested for a case",
};

/** A readable label for an activity code; an unknown code is shown as words, never as a raw constant. */
export function activityLabel(action: string): string {
  return ACTION_LABEL[action] ?? action.toLowerCase().replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

function activityItem(a: ActivityEvent): ActivityItem {
  const d = a.details as Record<string, string | undefined>;
  const link = a.entity_type === "batch" ? `/uploads/${a.entity_id}` : a.entity_type === "period" ? `/reports/${a.entity_id}`
    : a.entity_type === "review" ? `/reviews/${a.entity_id}` : a.entity_type === "case" ? `/cases/${a.entity_id}`
    : a.entity_type === "pack" ? `/packs/${a.entity_id}`
    : d.final_pack_id ? `/final-packs/${d.final_pack_id}`
    : (a.entity_type === "run" || a.entity_type === "ai_authorization") && d.period_id ? `/reports/${d.period_id}`
    : a.entity_type === "run" && d.pack_id ? `/packs/${d.pack_id}` : undefined;
  const label = activityLabel(a.action);
  return { at: a.at, actor: a.actor, action: d.period_id ? `${label} · ${periodLabel(d.period_id)}` : label, entity: a.entity_id, link,
    simulated: false };
}

const TTL_MS = 10_000;

export function createApiSource(): DataSource {
  const cache = new Map<string, { at: number; value: Promise<unknown> }>();
  function cached<T>(key: string, load: () => Promise<T>): Promise<T> {
    const hit = cache.get(key);
    if (hit && Date.now() - hit.at < TTL_MS) return hit.value as Promise<T>;
    const value = load();
    cache.set(key, { at: Date.now(), value });
    value.catch(() => { if (cache.get(key)?.value === value) cache.delete(key); }); // a failure is never cached
    return value;
  }
  const invalidate = () => cache.clear();
  /** A change: run it, then drop the cached lists (also on failure: the backend may have recorded something). */
  function change<A extends unknown[], R>(fn: (...args: A) => Promise<R>) {
    return async (...args: A) => { try { return await fn(...args); } finally { invalidate(); } };
  }
  const packs = () => cached<PackListItem[]>("packs", api.packs);
  const job = async (jobId: string): Promise<Job> => {
    const j = await api.job(jobId);
    if (j.status !== "QUEUED" && j.status !== "RUNNING") invalidate(); // a finished job may have published something
    return j;
  };

  return {
    kind: "api",
    capabilities: { activity: true, upload: true, realInvestigations: true, realGeneration: true },
    health: () => cached("health", api.health),
    periods: () => cached<ReconciliationPeriod[]>("periods", async () => {
      const [archive, list] = await Promise.all([api.periods(), packs()]);
      return buildArchivePeriods(archive, list);
    }),
    activity: async () => (await api.activity()).map(activityItem),
    archivePeriod: api.period,
    openPeriod: change(api.createPeriod),
    renamePeriod: change(api.updatePeriod),
    uploadDocuments: change(api.upload),
    batch: api.batch,
    reviewDocument: change(api.reviewDocument),
    confirmBatch: change(api.confirmBatch),
    processBatch: change(api.processBatch),
    processingRun: api.processingRun,
    documentContentUrl: api.documentContentUrl,
    reconcile: change(api.reconcile),
    reassessmentPlan: api.reassessmentPlan,
    periodLineage: api.periodLineage,
    periodExceptions: api.periodExceptions,
    dashboard: api.dashboard,
    invalidate,
    packs,
    pack: api.pack,
    reconciliation: api.reconciliation,
    sources: api.sources,
    exceptions: api.exceptions,
    exception: api.exception,
    packInvestigations: api.packInvestigations,
    startInvestigation: change(api.startInvestigation),
    sourceEvidence: api.sourceEvidence,
    aiConfiguration: api.aiConfiguration,
    aiAuthorizations: (filter) => api.aiAuthorizations(filter),
    toolCalls: api.toolCalls,
    cases: (filter) => api.cases(filter),
    openCase: change(api.openCase),
    caseDetail: api.caseDetail,
    addCaseEntry: change(api.addCaseEntry),
    caseAi: change(api.caseAi),
    job,
    investigation: api.investigation,
    findings: api.findings,
    evidence: (id) => api.evidence(id, { limit: 200 }),
    verifyInvestigation: api.verifyInvestigation,
    reviews: (filter) => api.reviews(filter),
    openReview: change(api.openReview),
    review: api.review,
    setSelections: change(api.setSelections),
    requestPreview: change(api.requestPreview),
    previewHtml: api.previewHtml,
    previewDocument: api.previewDocument,
    previewPdf: (reviewId, snapshot) => request<Blob>(
      `/api/v1/reviews/${encodeURIComponent(reviewId)}/preview/pdf?snapshot=${encodeURIComponent(snapshot)}`, { as: "blob" }),
    decide: change(api.decide),
    reviewHistory: api.reviewHistory,
    finalPacks: (packId, lineage) => api.finalPacks(packId, lineage),
    finalPack: api.finalPack,
    verifyFinalPack: api.verifyFinalPack,
    finalPackDocument: api.finalPackDocument,
    finalPackHtml: api.finalPackHtml,
    finalPackPdf: api.finalPackPdf,
    finalPackFileUrl: api.finalPackFileUrl,
  };
}
