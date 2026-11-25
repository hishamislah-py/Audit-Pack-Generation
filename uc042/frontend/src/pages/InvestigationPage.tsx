// One published AI investigation, read-only: status, eligibility (registry and authorisation decisions), assessment,
// findings by class, cited evidence, recorded tool calls and verification. Every value comes from the investigation's
// stored artefacts through the backend; the pack and exception links use the identifiers recorded in the findings.
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Async, Empty, KeyValue, Notice, Panel, StatusBadge, Tabs } from "../components/common";
import { usePage } from "../components/layout/workContext";
import { CitationInspector, EvidenceRecords } from "../components/workspace/evidence";
import { AssessmentCard, ConflictCard, GapCard, HypothesisCard, NextStepCard, ObservationCard } from "../components/workspace/findings";
import { useData } from "../data/DataProvider";
import { periodFromPackId, periodLabel } from "../data/periods";
import { useApi } from "../hooks/useApi";
import { dateTime } from "../lib/format";

type Tab = "findings" | "evidence" | "tools" | "verification";

export function InvestigationPage() {
  const { investigationId = "" } = useParams();
  const data = useData();
  const detail = useApi(() => data.investigation(investigationId), [data, investigationId]);
  const findings = useApi(() => data.findings(investigationId), [data, investigationId]);
  const evidence = useApi(() => data.evidence(investigationId), [data, investigationId]);
  const tools = useApi(() => data.toolCalls(investigationId), [data, investigationId]);
  const verify = useApi(() => data.verifyInvestigation(investigationId), [data, investigationId]);
  const [tab, setTab] = useState<Tab>("findings");
  const [active, setActive] = useState<string | null>(null);
  const cite = { active, onCite: (id: string) => setActive((a) => (a === id ? null : id)) };
  const d = detail.data;
  const packId = d?.pack_id ?? undefined;
  const periodId = periodFromPackId(packId);
  usePage([...(periodId ? [{ label: periodLabel(periodId), to: `/reports/${periodId}` }] : []),
    ...(packId ? [{ label: packId, to: `/packs/${packId}` }] : []), { label: investigationId }],
  packId ? { packId, ...(d?.exception_id ? { exceptionId: d.exception_id } : {}) } : {});
  return (
    <div className="stack">
      <div className="page-head">
        <div><div className="eyebrow">AI investigation · an aid to human review; it resolves nothing</div>
          <h1 className="page-title mono">{investigationId}</h1>
          {d && <p className="page-sub">{d.investigation_mode} mode · investigated {dateTime(d.investigated_at)} · validation <StatusBadge status={d.validation_status} />
            {" "}· {d.eligible ? <StatusBadge status="ELIGIBLE" label="Eligible for a final audit pack" /> : <StatusBadge status="INELIGIBLE" label="Not eligible" />}</p>}
        </div>
        <div className="actions">{d?.pack_id && d.exception_id && <Link className="btn" to={`/packs/${d.pack_id}/workspace/${d.exception_id}?inv=${investigationId}`}>Open the exception workspace</Link>}</div>
      </div>
      <Async state={detail} label="Loading the investigation…">{(x) => (
        <div className="grid-final">
          <Panel title="Record" flush>
            <KeyValue items={[["Exception", x.exception_id ?? "—"], ["Deterministic pack", <span className="mono">{x.pack_id ?? "—"}</span>],
              ["Status", <StatusBadge status={x.investigation_status} />], ["Exception resolution", x.exception_resolution ?? "—"],
              ["Model", `${String(x.model.provider ?? "")} ${String(x.model.model ?? "")}${x.model.simulated ? " (simulated)" : ""}`],
              ["Prompt / schema", `${String(x.model.prompt_version ?? "—")} · ${String(x.model.findings_schema_version ?? "—")}`],
              ["Publication registry", x.registry ? `${x.registry.record_type.replace(/_/g, " ").toLowerCase()} (seq ${x.registry.seq})` : "not registered"],
              ["Authorisation decision", x.authorization ? x.authorization.status : "none recorded (the registry decides)"],
              ["Findings SHA-256", <span className="mono xsmall">{x.findings_sha256}</span>]]} />
          </Panel>
          <Panel title="Eligibility" sub="From the publication registry, the authorisation decisions and the current validation rules">
            {x.eligible ? <Notice tone="ok">Eligible: it can be selected in a final review.</Notice>
              : <Notice tone="warn" title="Not eligible"><ul>{x.ineligible_reasons.map((r) => <li key={r}>{r}</li>)}</ul></Notice>}
          </Panel>
        </div>
      )}</Async>
      <section className="panel">
        <Tabs label="Investigation content" value={tab} onChange={setTab} tabs={[{ key: "findings", label: "Findings" },
          { key: "evidence", label: "Evidence", count: evidence.data?.total_records }, { key: "tools", label: "Tool calls", count: tools.data?.tool_calls.length },
          { key: "verification", label: "Validation and publication" }]} />
        <div className="panel__body stack stack--sm">
          {tab === "findings" && <Async state={findings}>{(f) => (
            <>
              {active && <CitationInspector id={active} evidence={evidence.data} results={[]} onClose={() => setActive(null)} />}
              <AssessmentCard assessment={f.overall_evidence_assessment} summary={f.investigation_summary} />
              <h3 className="section-label">Confirmed findings ({f.confirmed_findings.length})</h3>
              {f.confirmed_findings.length ? f.confirmed_findings.map((o) => <ObservationCard key={o.finding_id} f={o} cite={cite} />) : <p className="small muted">None.</p>}
              <h3 className="section-label">Hypotheses ({f.hypotheses.length}) · not established</h3>
              {f.hypotheses.map((h) => <HypothesisCard key={h.hypothesis_id} h={h} cite={cite} />)}
              <h3 className="section-label">Missing evidence ({f.missing_evidence.length}) and conflicts ({f.contradictory_evidence.length})</h3>
              {f.missing_evidence.map((g) => <GapCard key={g.item_id} g={g} cite={cite} />)}
              {f.contradictory_evidence.map((c) => <ConflictCard key={c.item_id} c={c} cite={cite} />)}
              <h3 className="section-label">Suggested next steps ({f.recommended_next_steps.length})</h3>
              {f.recommended_next_steps.map((s) => <NextStepCard key={s.step_id} s={s} />)}
              {f.open_questions.length > 0 && <div><div className="finding__field">Open questions</div><ul className="small">{f.open_questions.map((q) => <li key={q}>{q}</li>)}</ul></div>}
            </>
          )}</Async>}
          {tab === "evidence" && <Async state={evidence}>{(ev) => ev.source_records.length ? <EvidenceRecords evidence={ev} active={active} onSelect={cite.onCite} /> : <Empty>No records.</Empty>}</Async>}
          {tab === "tools" && <Async state={tools}>{(t) => t.tool_calls.length === 0 ? <Empty>No tool calls (fixed-mode investigation, or none were made).</Empty> : (
            <div className="table-scroll"><table className="dtable dtable--compact">
              <thead><tr><th>#</th><th>Tool</th><th>Arguments</th><th>Status</th><th className="num">Records</th><th>Evidence IDs</th></tr></thead>
              <tbody>{t.tool_calls.map((c, i) => (
                <tr key={c.call_id ?? i}><td className="xsmall">{i + 1} · r{c.round}</td><td className="mono small">{c.tool}</td>
                  <td className="mono xsmall">{JSON.stringify(c.arguments)}</td><td><StatusBadge status={c.status} /></td><td className="num">{c.records_returned}</td>
                  <td className="mono xsmall">{(c.evidence_ids ?? []).join(", ") || (c.search_ids ?? []).join(", ") || "—"}</td></tr>
              ))}</tbody>
            </table></div>
          )}</Async>}
          {tab === "verification" && <Async state={verify}>{(v) => (
            <KeyValue items={[["Artefact verified (hashes)", v.artefact_verified ? "Yes" : <span>No: {v.artefact_problems.join("; ")}</span>],
              ["Registry verified", v.registry_verified ? "Yes" : <span>No: {v.registry_problems.join("; ")}</span>],
              ["Eligible", v.eligible ? "Yes" : v.ineligible_reasons.join("; ")]]} />
          )}</Async>}
        </div>
      </section>
    </div>
  );
}
