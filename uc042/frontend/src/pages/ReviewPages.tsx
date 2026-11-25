import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ApiError, errorMessage } from "../api/client";
import type { AiConfirmation, ReviewSession } from "../api/types";
import { AiAuthorizationDialog } from "../components/ai/AiAuthorizationDialog";
import { periodFromPackId, periodLabel } from "../data/periods";
import { Async, Empty, ErrorPanel, Loading, Notice, Panel, SimulatedNotice, StatusBadge } from "../components/common";
import { usePage } from "../components/layout/workContext";
import { DecisionPanel, EDITABLE, SelectionEditor } from "../components/review/decision";
import { JsonView, PdfViewer, ReportFacts, ReportFrame, ReportNav, SectionSelect, type ReportFrameHandle } from "../components/review/ReportViewer";
import { useData } from "../data/DataProvider";
import { useApi } from "../hooks/useApi";
import { isActive, useJobPoller } from "../hooks/useJobPoller";
import { dateTime, shortHash } from "../lib/format";

const ACTIVE_REVIEW = ["OPEN", "ON_HOLD", "GENERATING", "GENERATION_FAILED"];

/** /packs/:packId/review is READ-ONLY: it shows the pack's active review (by navigating to it), or its earlier reviews and
 * published final packs. A new review session is created only by the explicit "Open a new final review" action, never by
 * loading, refreshing or navigating to this page. */
export function OpenReviewPage() {
  const { packId = "" } = useParams();
  const data = useData();
  const navigate = useNavigate();
  const sessions = useApi(() => data.reviews({ packId }), [data, packId]);
  const versions = useApi(() => data.finalPacks(packId, true), [data, packId]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const active = sessions.data?.find((s) => ACTIVE_REVIEW.includes(s.status));
  useEffect(() => { if (active) navigate(`/reviews/${active.review_id}`, { replace: true }); }, [active, navigate]);
  usePage([{ label: packId, to: `/packs/${packId}` }, { label: "Final review" }], { packId });
  const open = async () => {
    setBusy(true);
    setError(undefined);
    try { navigate(`/reviews/${(await data.openReview(packId)).review_id}`); } catch (e) { setError(e); setBusy(false); }
  };
  if (sessions.loading || active) return <Loading label="Looking for this pack's review…" />;
  const latest = versions.data?.at(-1);
  return (
    <div className="stack">
      <div className="page-head"><div><div className="eyebrow">Final audit-pack review · {packId}</div><h1 className="page-title">Final review</h1>
        <p className="page-sub">This pack has no active review. Opening one is an explicit action; reading this page changes nothing.</p></div></div>
      <Async state={sessions}>{(rows) => (
        <Panel title="Earlier reviews of this pack" meta={`${rows.length}`} flush>
          {rows.length === 0 ? <Empty title="No review yet">No final review has been opened for this deterministic pack.</Empty> : (
            <div className="table-scroll"><table className="dtable">
              <thead><tr><th>Review</th><th>Status</th><th>Last decision</th><th>Final audit pack</th><th>Updated</th></tr></thead>
              <tbody>{rows.map((s) => (
                <tr key={s.review_id}><td><Link className="id" to={`/reviews/${s.review_id}`}>{s.review_id}</Link></td><td><StatusBadge status={s.status} /></td>
                  <td className="small">{s.last_decision ? `${s.last_decision.decision} · ${dateTime(s.last_decision.decided_at)}` : "—"}</td>
                  <td>{s.final_pack_id ? <Link className="id" to={`/final-packs/${s.final_pack_id}`}>{s.final_pack_id}</Link> : "—"}</td>
                  <td className="small">{dateTime(s.updated_at)}</td></tr>
              ))}</tbody>
            </table></div>
          )}
        </Panel>
      )}</Async>
      <Panel title="Open a new final review">
        <div className="stack stack--sm">
          {latest ? <Notice tone="info" title={`Published: ${latest.final_pack_id} (v${latest.version})`}>A new review of this pack can publish the next
            version, v{latest.version + 1}, superseding it. The published pack is never changed.</Notice>
            : <p className="small">A review selects the investigations to include, generates the closing summary and preview, and ends with HOLD or GENERATE.</p>}
          <div><button className="btn btn--primary" onClick={open} disabled={busy}>{busy ? "Opening…" : "Open a new final review"}</button></div>
          {error !== undefined && <ErrorPanel error={error} title="The review could not be opened" />}
        </div>
      </Panel>
    </div>
  );
}

export function ReviewsPage() {
  const data = useData();
  usePage([{ label: "Reviews" }]);
  const rows = useApi(() => data.reviews(), [data]);
  return (
    <div className="stack">
      <div className="page-head"><div><h1>Final reviews</h1><p className="page-sub">Review sessions for final audit packs. Open a new review from a reconciliation pack.</p></div></div>
      <Panel title="Review sessions" flush>
        <Async state={rows}>{(r) => r.length === 0 ? <Empty title="No review sessions">Open a final review from a reconciliation pack.</Empty> : (
          <div className="table-scroll"><table className="dtable">
            <thead><tr><th>Review</th><th>Pack</th><th>Status</th><th>Preview</th><th>Last decision</th><th>Final pack</th><th>Updated</th></tr></thead>
            <tbody>{r.map((s) => (
              <tr key={s.review_id}>
                <td><Link className="id" to={`/reviews/${s.review_id}`}>{s.review_id}</Link></td>
                <td><Link className="id" to={`/packs/${s.pack_id}`}>{s.pack_id}</Link></td>
                <td><StatusBadge status={s.status} /></td>
                <td>{s.has_preview ? "Current" : <span className="faint">None</span>}</td>
                <td className="small">{s.last_decision ? `${s.last_decision.decision} · ${dateTime(s.last_decision.decided_at)}` : "—"}</td>
                <td>{s.final_pack_id ? <Link className="id" to={`/final-packs/${s.final_pack_id}`}>{s.final_pack_id}</Link> : "—"}</td>
                <td className="small">{dateTime(s.updated_at)}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}</Async>
      </Panel>
    </div>
  );
}

type Mode = "html" | "pdf" | "json";

function Workspace({ session, setSession }: { session: ReviewSession; setSession: (s: ReviewSession) => void }) {
  const data = useData();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const mode = (params.get("view") as Mode) || "html";
  const frame = useRef<ReportFrameHandle>(null);
  const [section, setSection] = useState("overview");
  const [editing, setEditing] = useState(false);
  const preview = session.current_preview;
  const snapshot = preview?.snapshot_sha256 ?? "";
  const exceptions = useApi(() => data.exceptions(session.pack_id), [data, session.pack_id]);
  const investigations = useApi(() => data.packInvestigations(session.pack_id), [data, session.pack_id, session.revision]);
  const history = useApi(() => data.reviewHistory(session.review_id), [data, session.review_id, session.revision]);
  const doc = useApi(() => (snapshot ? data.previewDocument(session.review_id, snapshot) : Promise.resolve(undefined)), [data, session.review_id, snapshot]);
  const loadHtml = useCallback(() => data.previewHtml(session.review_id, snapshot), [data, session.review_id, snapshot]);
  const loadPdf = useCallback(() => data.previewPdf(session.review_id, snapshot), [data, session.review_id, snapshot]);
  const reload = async () => setSession(await data.review(session.review_id));
  const previewJobId = isActive(session.preview_job) ? session.preview_job!.job_id : null;
  const { job: previewJob } = useJobPoller(previewJobId, () => { reload(); });
  const previewRunning = !!previewJobId && (previewJob ? isActive(previewJob) : true);
  const editable = EDITABLE.includes(session.status);
  const unresolved = exceptions.data?.length ?? 0;
  const goSection = (a: string) => { setSection(a); if (mode !== "html") setParams({ view: "html" }, { replace: true }); setTimeout(() => frame.current?.scrollTo(a), 0); };

  const [authorising, setAuthorising] = useState(false);
  const requestPreview = async (authorization: AiConfirmation) => {
    await data.requestPreview(session.review_id, authorization); // a refusal stays in the dialog
    setAuthorising(false);
    await reload();
  };

  const periodId = periodFromPackId(session.pack_id);
  const included = session.selections.filter((s) => s.inclusion === "INCLUDED").map((s) => s.investigation_id);
  return (
    <>
      {authorising && (
        <AiAuthorizationDialog operation="CLOSING_SUMMARY" onCancel={() => setAuthorising(false)} onConfirm={requestPreview} context={[
          ["Reporting period", periodId ? periodLabel(periodId) : "—"],
          ["Deterministic pack", <span className="mono">{session.pack_id}</span>],
          ["Selected investigations", included.length ? <span className="mono">{included.join(", ")}</span> : "None (every exception reported as not investigated or excluded)"],
          ["Review", <span className="mono">{session.review_id}</span>],
        ]} />
      )}
      {session.status === "ON_HOLD" && <Notice tone="warn" title={`Decision saved: HOLD${history.data?.decisions.at(-1) ? ` · ${dateTime(history.data.decisions.at(-1)!.decided_at)}` : ""}`}>
        No final pack was generated. Regenerate the preview to continue the review. {history.data?.decisions.at(-1)?.comment && <>Note: “{history.data.decisions.at(-1)!.comment}”</>}</Notice>}
      {session.status === "GENERATED" && <Notice tone="ok" title="Final audit pack generated">This review is closed. <Link to={`/final-packs/${session.final_pack_id}`}>Open {session.final_pack_id}</Link></Notice>}
      {session.status === "GENERATING" && <Notice tone="info" title={<><span className="spinner" /> Final pack generating</>}>Assembly, rendering and publication run on the backend.</Notice>}
      {session.status === "GENERATION_FAILED" && <Notice tone="bad" title="Generation failed">Nothing was published. Regenerate the preview or decide again.</Notice>}
      {(session.readiness.warnings.some((w) => w.code === "NOT_INVESTIGATED")) && (
        <Notice tone="warn">{session.readiness.warnings.filter((w) => w.code === "NOT_INVESTIGATED").length} exception(s) have no included AI investigation. They are reported as unresolved and marked not investigated.</Notice>
      )}
      {data.kind === "mock" && <SimulatedNotice>The report is the backend's real Phase 1 preview for this pack, captured with the default investigation selections. Preview generation, HOLD and GENERATE are simulated in this browser session; nothing is published.</SimulatedNotice>}

      <div className="review-layout">
        <div className="review-layout__toc sticky"><ReportNav active={section} onSelect={goSection} /></div>

        <div className="doc-viewer">
          <div className="doc-viewer__bar">
            <span>Document preview · {preview ? <code>{preview.preview_final_pack_id}</code> : "none"}{preview && ` · snapshot ${shortHash(snapshot)}`}</span>
            <SectionSelect active={section} onSelect={goSection} />
            <span className="doc-viewer__modes" role="tablist" aria-label="Preview format">
              {(["html", "pdf", "json"] as Mode[]).map((m) => (
                <button key={m} role="tab" aria-selected={mode === m} className={`doc-viewer__mode${mode === m ? " doc-viewer__mode--active" : ""}`}
                  onClick={() => setParams({ view: m }, { replace: true })}>{m.toUpperCase()}</button>
              ))}
            </span>
          </div>
          <div className="doc-viewer__page">
            {!preview ? (
              <div className="panel"><Empty title={previewRunning ? "Generating the AI closing summary and preview…" : "Preview required"}
                action={editable && !previewRunning ? <button className="btn btn--primary" onClick={() => setAuthorising(true)}>Generate closing summary and preview</button> : previewRunning ? <span className="spinner" /> : undefined}>
                {previewRunning ? `Job ${previewJobId}: ${previewJob?.status ?? "QUEUED"}` : session.status === "ON_HOLD" ? "The review was put on hold, so the earlier preview no longer applies."
                  : "There is no current preview: the selections changed or none has been generated. The analyst must read the report before GENERATE."}
              </Empty></div>
            ) : mode === "html" ? <ReportFrame ref={frame} load={loadHtml} title="Final audit-pack preview" onSection={setSection} />
              : mode === "pdf" ? <PdfViewer load={loadPdf} title="Final audit-pack preview (PDF)" />
                : <Async state={doc}>{(d) => <div className="panel"><JsonView doc={d} /></div>}</Async>}
          </div>
        </div>

        <div className="stack stack--sm sticky">
          <Panel title="Pack summary" flush>
            <table className="dtable dtable--compact"><tbody>
              <tr><td className="muted">Source pack</td><td className="id--wrap"><Link className="mono" to={`/packs/${session.pack_id}`}>{session.pack_id}</Link></td></tr>
              <tr><td className="muted">Review</td><td className="id--wrap"><StatusBadge status={session.status} /><div className="xsmall faint mono">{session.review_id}</div></td></tr>
              <tr><td className="muted">Closing summary</td><td>{preview ? <StatusBadge status={preview.closing_summary.status} /> : "—"}</td></tr>
            </tbody></table>
            {doc.data && <ReportFacts doc={doc.data} />}
          </Panel>
          <Panel title="Readiness" flush>
            <div className="panel__body stack stack--sm">
              {session.readiness.blockers.map((b) => <Notice key={b.code + b.detail} tone="bad"><strong>{b.code.replace(/_/g, " ")}</strong>: {b.detail}</Notice>)}
              {session.readiness.warnings.filter((w) => w.code !== "NOT_INVESTIGATED").map((w) => <Notice key={w.code + w.detail} tone="warn">{w.detail}</Notice>)}
              {session.readiness.info.map((i) => <Notice key={i.code} tone="info">{i.detail}</Notice>)}
              {session.readiness.ready && <Notice tone="ok">Ready for a decision.</Notice>}
              {editable && preview && <button className="btn btn--sm" onClick={() => setAuthorising(true)} disabled={previewRunning}>Regenerate preview</button>}
            </div>
          </Panel>
          <Panel title="Investigation selections" actions={editable ? <button className="btn btn--sm" onClick={() => setEditing(true)} disabled={!exceptions.data || !investigations.data}>Edit</button> : undefined} flush>
            <table className="dtable dtable--compact"><tbody>
              {session.selections.length === 0 ? <tr><td className="muted">No exceptions in this pack.</td></tr> : session.selections.map((s) => (
                <tr key={s.exception_id}><td className="id">{s.exception_id}</td><td className="id--wrap"><StatusBadge status={s.inclusion} /><div className="xsmall faint mono">{s.investigation_id ?? s.reason}</div></td></tr>
              ))}
            </tbody></table>
          </Panel>
          {editable && (
            <Panel title="Human review" sub="Decision recorded against the previewed snapshot">
              <DecisionPanel session={session} unresolved={unresolved} onDecided={(r) => {
                if (r.final_pack?.final_pack_id) navigate(`/final-packs/${r.final_pack.final_pack_id}`); else reload();
              }} />
            </Panel>
          )}
          <Panel title="Decision history" flush>
            <Async state={history}>{(h) => h.decisions.length === 0 ? <p className="panel__body small muted">No decision recorded yet.</p> : (
              <table className="dtable dtable--compact"><tbody>
                {h.decisions.map((d) => (
                  <tr key={d.review_decision_id}><td><StatusBadge status={d.decision === "HOLD" ? "ON_HOLD" : "GENERATED"} label={d.decision} /></td>
                    <td className="small">{dateTime(d.decided_at)} · {d.reviewer.display_name}{d.comment && <div className="xsmall muted">“{d.comment}”</div>}</td></tr>
                ))}
              </tbody></table>
            )}</Async>
          </Panel>
        </div>
      </div>
      {editing && exceptions.data && investigations.data && (
        <SelectionEditor session={session} exceptions={exceptions.data} investigations={investigations.data}
          onCancel={() => setEditing(false)} onSaved={(s) => { setSession(s); setEditing(false); }} />
      )}
    </>
  );
}

export function ReviewPage() {
  const { reviewId = "" } = useParams();
  const data = useData();
  const state = useApi(() => data.review(reviewId), [data, reviewId]);
  const [session, setSession] = useState<ReviewSession>();
  const current = session?.review_id === reviewId ? session : state.data;
  usePage(current ? [{ label: current.pack_id, to: `/packs/${current.pack_id}` }, { label: "Final review" }] : [{ label: "Final review" }],
    current ? { packId: current.pack_id, reviewId } : { reviewId });
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="eyebrow">Final audit-pack review{current?.current_preview ? ` · ${current.current_preview.preview_final_pack_id}` : ""}</div>
          <h1 className="page-title">Final audit pack review</h1>
          <p className="page-sub">Read the report the backend will generate, including the AI-generated closing summary, then record HOLD or GENERATE.</p>
        </div>
      </div>
      {state.error instanceof ApiError && state.error.status === 404
        ? <Panel><Empty title="Review not found">{errorMessage(state.error)} <Link to="/reviews">All reviews</Link></Empty></Panel>
        : <Async state={state} label="Loading review…">{() => current ? <Workspace session={current} setSession={setSession} /> : null}</Async>}
    </div>
  );
}
