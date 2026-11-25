import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import type { ExceptionInvestigations } from "../api/types";
import { errorMessage } from "../api/client";
import { Amount, Async, Empty, Kpis, Notice, Panel, StatusBadge, UnresolvedTag } from "../components/common";
import { usePage } from "../components/layout/workContext";
import { AiPanel, type AiTab } from "../components/workspace/AiPanel";
import { CitationInspector, DeterministicResults, EvidenceRecords, mergeEvidence, recordOrigin, Relationships } from "../components/workspace/evidence";
import { useData } from "../data/DataProvider";
import { periodLabel } from "../data/periods";
import { useApi } from "../hooks/useApi";
import { date } from "../lib/format";

function aiDot(row: ExceptionInvestigations | undefined) {
  if (!row) return null;
  if (row.active_jobs.length) return <StatusBadge status="RUNNING" label="Running" />;
  if (row.published.some((p) => p.eligible)) return <StatusBadge status="COMPLETED" label="AI eligible" />;
  if (row.published.length) return <StatusBadge status="INTERRUPTED" label="AI ineligible" />;
  return <StatusBadge status="NOT_RUN" label="Not run" />;
}

export function WorkspacePage() {
  const { packId = "", exceptionId: routeExc } = useParams();
  const data = useData();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const exceptions = useApi(() => data.exceptions(packId), [data, packId]);
  const exceptionId = routeExc ?? exceptions.data?.[0]?.exception_id;
  const [tick, setTick] = useState(0);
  const rows = useApi(() => data.packInvestigations(packId), [data, packId, tick]);
  const detail = useApi(() => (exceptionId ? data.exception(packId, exceptionId) : Promise.resolve(undefined)), [data, packId, exceptionId, tick]);
  const row = rows.data?.find((r) => r.exception_id === exceptionId);
  const published = row?.published ?? [];
  const invId = params.get("inv") && published.some((p) => p.investigation_id === params.get("inv")) ? params.get("inv")
    : (published.find((p) => p.eligible) ?? published[0])?.investigation_id ?? null;
  const inv = useApi(() => (invId ? data.investigation(invId) : Promise.resolve(undefined)), [data, invId]);
  const findings = useApi(() => (invId ? data.findings(invId) : Promise.resolve(undefined)), [data, invId]);
  const evidence = useApi(() => (invId ? data.evidence(invId) : Promise.resolve(undefined)), [data, invId]);
  // The exception's supporting source records are always inspectable without AI: retrieved deterministically from the
  // pack's hash-verified sources by the same approved retrieval an investigation starts from. Records an AI investigation
  // added with its tool calls are shown apart and labelled as such (they are source records, not AI findings).
  const sourceEvidence = useApi(() => (exceptionId && data.capabilities.upload ? data.sourceEvidence(packId, exceptionId)
    : Promise.resolve(undefined)), [data, packId, exceptionId]);
  // Mock data has no backend retrieval: it shows the captured investigation's records, as before.
  const engineEvidence = data.capabilities.upload ? sourceEvidence : evidence;
  const aiRecords = invId && data.capabilities.upload ? (evidence.data?.source_records ?? []).filter((r) => recordOrigin(r) === "AI_TOOL") : [];
  const lookup = mergeEvidence(engineEvidence.data, evidence.data);
  const cases = useApi(() => (data.capabilities.upload ? data.cases({ packId }) : Promise.resolve([])), [data, packId, tick]);
  const caseFor = cases.data?.find((c) => c.exception_id === exceptionId);
  const periods = useApi(() => data.periods(), [data]);
  const [active, setActive] = useState<string | null>(null);
  const tab = (params.get("tab") as AiTab) || "summary";
  useEffect(() => { setActive(null); }, [exceptionId, invId]);
  const pack = useApi(() => data.pack(packId), [data, packId]);
  const periodId = pack.data?.summary.period_id ?? undefined;
  usePage([{ label: periodLabel(periodId), to: periodId ? `/?period=${periodId}` : "/" }, { label: packId, to: `/packs/${packId}` }, { label: exceptionId ?? "Exceptions" }],
    { packId, exceptionId, ...(periodId ? { periodId } : {}) });
  const setParam = (k: string, v: string) => { const p = new URLSearchParams(params); p.set(k, v); setParams(p, { replace: true }); };
  const cite = { active, onCite: (id: string) => setActive((a) => (a === id ? null : id)) };
  const x = detail.data?.exception;

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="eyebrow">Exception and investigation workspace · {packId}</div>
          <h1 className="page-title">{exceptionId ?? "Exceptions"} {x && <UnresolvedTag />}</h1>
          {x && <p className="page-sub">{x.category} · {x.account_id ?? "—"}</p>}
        </div>
        <div className="actions">
          <Link className="btn" to={`/packs/${packId}`}>← Reconciliation pack</Link>
          <Link className="btn btn--primary" to={`/packs/${packId}/review`}>Continue to final review</Link>
        </div>
      </div>

      <Async state={exceptions} label="Loading exceptions…">{(list) => list.length === 0 ? (
        <Panel><Empty title="No exceptions">The deterministic engine raised no exceptions for this pack, so there is nothing to investigate. <Link to={`/packs/${packId}/review`}>Go to final review</Link></Empty></Panel>
      ) : (
        <div className="workspace">
          <Panel title="Exceptions" meta={`${list.length}`} flush>
            <div className="exlist" role="listbox" aria-label="Exceptions">
              {list.map((e) => (
                <button key={e.exception_id} role="option" aria-selected={e.exception_id === exceptionId}
                  className={`exitem${e.exception_id === exceptionId ? " exitem--active" : ""}`} onClick={() => navigate(`/packs/${packId}/workspace/${e.exception_id}`)}>
                  <span className="exitem__id">{e.exception_id}</span>
                  <span className="exitem__amount"><Amount value={e.amount} currency={e.currency} /></span>
                  <span className="exitem__meta">{date(e.first_date)} · {e.severity} · <UnresolvedTag /> {aiDot(rows.data?.find((r) => r.exception_id === e.exception_id))}</span>
                </button>
              ))}
            </div>
          </Panel>

          <div className="stack">
            <Async state={detail} label="Loading exception…">{(d) => d ? (
              <>
                <Kpis items={[
                  { label: "Amount", value: <Amount value={d.exception.amount} currency={d.exception.currency} /> },
                  { label: "Exception date", value: `${date(d.exception.first_date)}${d.exception.last_date && d.exception.last_date !== d.exception.first_date ? ` – ${date(d.exception.last_date)}` : ""}`, tone: "sm" },
                  { label: "Severity", value: <StatusBadge status={d.exception.severity} /> },
                  { label: "Evidence status", value: <StatusBadge status={d.exception.evidence_status} /> },
                  { label: "Deterministic status", value: <><StatusBadge status={d.exception.status} /> <UnresolvedTag /></>, note: d.exception.review_status?.replace(/_/g, " ").toLowerCase() },
                ]} />
                {active && <CitationInspector id={active} evidence={lookup} results={d.affected_results} onClose={() => setActive(null)} />}
                <Panel title="Deterministic reconciliation results" sub="Engine results behind this exception (copied from the pack's control register)" flush>
                  <DeterministicResults results={d.affected_results} active={active} />
                </Panel>
                <Panel title="Supporting evidence · engine retrieval (no AI)" flush
                  sub={data.capabilities.upload ? "Source records retrieved deterministically from the pack's hash-verified source files, grouped by source · select a record for its file, line, SHA-256 and fields"
                    : invId ? `Records retrieved for ${invId}, grouped by source · D/C as recorded` : undefined}>
                  {!invId && !data.capabilities.upload ? <Empty title="No retrieved records yet">Supporting records are retrieved by the backend (not available with mock data).</Empty>
                    : <Async state={engineEvidence}>{(ev) => ev ? <EvidenceRecords evidence={ev} active={active} onSelect={cite.onCite} /> : null}</Async>}
                </Panel>
                {invId && data.capabilities.upload && evidence.data && (
                  <Panel title="Records retrieved by the AI investigation's tool calls" flush
                    sub={`Further source records ${invId} retrieved with its tools (lines of the same verified files). They are evidence the AI looked at, not AI findings.`}>
                    {aiRecords.length ? <EvidenceRecords evidence={evidence.data} records={aiRecords} active={active} onSelect={cite.onCite} />
                      : <Empty>This investigation retrieved no records beyond the engine's.</Empty>}
                  </Panel>
                )}
                {engineEvidence.data && (
                  <Panel title="Evidence relationships" sub={active ? `Relationships involving ${active}` : "How the records are linked: verified join keys as recorded (unverified candidate relationships are never shown as links)"} flush>
                    <Relationships evidence={lookup ?? engineEvidence.data} active={active} onSelect={cite.onCite} />
                  </Panel>
                )}
              </>
            ) : null}</Async>
          </div>

          <div className="workspace__ai stack">
            {exceptionId && data.capabilities.upload && <CasePanel packId={packId} exceptionId={exceptionId} existing={caseFor} loading={cases.loading} />}
            {exceptionId && (
              <AiPanel packId={packId} exceptionId={exceptionId} exception={x} row={row} investigationId={invId} onSelect={(id) => setParam("inv", id)}
                periodTitle={periods.data?.find((p) => p.period_id === periodId)?.archive?.title}
                detail={inv.data} findings={findings.data} loadError={inv.error ?? findings.error} cite={cite} tab={tab} onTab={(t) => setParam("tab", t)}
                onFinished={(j) => { setTick((t) => t + 1); if (typeof j.result?.investigation_id === "string") setParam("inv", j.result.investigation_id); }} />
            )}
          </div>
        </div>
      )}</Async>
    </div>
  );
}

/** The analyst's own investigation case for this exception (opened explicitly; a case never changes the pack). */
function CasePanel({ packId, exceptionId, existing, loading }: { packId: string; exceptionId: string; existing?: { case_id: string; status: string; human_resolution: string }; loading: boolean }) {
  const data = useData();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const open = async () => {
    setBusy(true);
    setError(undefined);
    try { navigate(`/cases/${(await data.openCase(packId, exceptionId)).case_id}`); } catch (e) { setError(e); setBusy(false); }
  };
  return (
    <Panel title="Investigation case" sub="Your notes, evidence, observations and decision for this exception">
      <div className="stack stack--sm">
        {existing ? <div className="small"><Link className="id" to={`/cases/${existing.case_id}`}>{existing.case_id}</Link> · <StatusBadge status={existing.status} />
          {" "}<StatusBadge status={existing.human_resolution} /></div>
          : <button className="btn" disabled={busy || loading} onClick={open}>{busy ? "Opening…" : "Open investigation case"}</button>}
        <p className="xsmall muted">A case disposition never resolves the deterministic exception or changes a published audit pack.</p>
        {error !== undefined && <Notice tone="bad">{errorMessage(error)}</Notice>}
      </div>
    </Panel>
  );
}
