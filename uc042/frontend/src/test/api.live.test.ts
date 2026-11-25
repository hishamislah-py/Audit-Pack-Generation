// OPT-IN integration test of the real FastAPI adapter against a RUNNING backend. Skipped unless UC042_E2E=1.
//   UC042_E2E=1 VITE_API_BASE_URL=http://127.0.0.1:8000 npx vitest run src/test/api.live.test.ts
// Run the backend with a scratch UC042_APP_STATE_DIR, a scratch UC042_FINAL_PACKS_ROOT and UC042_LLM_PROVIDER=offline (no
// OpenAI calls). Reads cover all nine September scenario packs; the review test opens a review, previews and records
// HOLD. GENERATE runs only with UC042_E2E_GENERATE=1 (an explicit analyst-equivalent action into the scratch folder).
import { describe, expect, it } from "vitest";
import type { ApiError } from "../api/client";
import type { Job } from "../api/types";
import { createApiSource } from "../data/apiSource";

const api = createApiSource();
const ENABLED = process.env.UC042_E2E === "1";

async function wait(id: string): Promise<Job> {
  for (let i = 0; i < 240; i++) {
    const j = await api.job(id);
    if (!["QUEUED", "RUNNING"].includes(j.status)) return j;
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`job ${id} did not finish`);
}

describe.skipIf(!ENABLED)("FastAPI adapter against a running backend", () => {
  it("reads every September scenario pack, exception and investigation", async () => {
    const packs = await api.packs();
    expect(packs).toHaveLength(9);
    expect(packs.every((p) => p.verified && p.summary?.period_id === "PER-2026-09")).toBe(true);
    let exceptions = 0, investigations = 0;
    for (const p of packs) {
      const [detail, recon, sources, excs, inv] = await Promise.all([api.pack(p.pack_id), api.reconciliation(p.pack_id), api.sources(p.pack_id),
        api.exceptions(p.pack_id), api.packInvestigations(p.pack_id)]);
      expect(detail.summary.pack_id).toBe(p.pack_id);
      expect(recon.external_by_account_day.length + recon.internal_by_currency_day.length).toBeGreaterThan(0);
      expect(sources.files.length).toBeGreaterThanOrEqual(17);
      expect(inv.map((r) => r.exception_id)).toEqual(excs.map((x) => x.exception_id));
      for (const x of excs) {
        const d = await api.exception(p.pack_id, x.exception_id);
        expect(d.exception.resolution_status).toBe("UNRESOLVED");
        exceptions++;
        for (const i of d.investigations.published) {
          const [det, f, ev, ver] = await Promise.all([api.investigation(i.investigation_id), api.findings(i.investigation_id),
            api.evidence(i.investigation_id), api.verifyInvestigation(i.investigation_id)]);
          expect(det.eligible).toBe(i.eligible);
          expect(f.exception_resolution).toBe("NOT_RESOLVED_BY_INVESTIGATION");
          expect(ev.source_records.length).toBeGreaterThan(0);
          expect(ver.artefact_verified).toBe(true);
          investigations++;
        }
      }
    }
    expect(exceptions).toBe(30);
    expect(investigations).toBe(7);
    const sc2 = await api.exception(packs.find((p) => p.summary?.scenario_id === "SC2")!.pack_id, "EXC-SC2-01");
    expect([sc2.exception.amount, sc2.exception.first_date]).toEqual(["2868.50", "2026-09-15"]);
  }, 300000);

  it("review: open, preview (closing summary + report), HOLD, preview again; GENERATE only when enabled", async () => {
    const s05 = (await api.packs()).find((p) => p.summary?.scenario_id === "S05")!.pack_id;
    let session = await api.openReview(s05);
    expect((await api.reviews({ packId: s05 })).some((r) => r.review_id === session.review_id)).toBe(true);
    expect((await wait((await api.requestPreview(session.review_id, { confirmed: true })).job_id)).status).toBe("COMPLETED");
    session = await api.review(session.review_id);
    const snap = session.current_preview!.snapshot_sha256;
    expect(await api.previewHtml(session.review_id, snap)).toContain("16. AI-Generated Closing Summary");
    expect((await api.previewDocument(session.review_id, snap)).exception_register.every((e) => e.resolution_status === "UNRESOLVED")).toBe(true);
    expect((await api.previewPdf(session.review_id, snap)).size).toBeGreaterThan(10000);
    const hold = await api.decide(session.review_id, { decision: "HOLD", comment: "Integration test: awaiting evidence." });
    expect([hold.session_status, hold.final_pack]).toEqual(["ON_HOLD", null]);
    expect((await api.decide(session.review_id, { decision: "HOLD", comment: "" }).catch((e) => e) as ApiError).code).toBe("COMMENT_REQUIRED");
    await wait((await api.requestPreview(session.review_id, { confirmed: true })).job_id);
    session = await api.review(session.review_id);
    if (process.env.UC042_E2E_GENERATE !== "1") return;
    const gen = await api.decide(session.review_id, { decision: "GENERATE", snapshot_sha256: session.current_preview!.snapshot_sha256,
      acknowledgement_accepted: true, acknowledged_summary_unavailable: true, comment: "Integration test generate" });
    const fid = gen.final_pack!.final_pack_id!;
    expect((await api.verifyFinalPack(fid))!.verified).toBe(true);
    expect((await api.finalPackDocument(fid)).metadata.final_pack_id).toBe(fid);
    expect((await api.finalPackPdf(fid)).size).toBeGreaterThan(10000);
    expect(await api.finalPackHtml(fid)).toContain(fid);
    expect((await api.finalPacks(s05)).map((f) => f.final_pack_id)).toContain(fid);
  }, 300000);
});
