// Exception investigation cases: the analyst's own, explicitly opened record of one exception (notes, evidence, evidence
// gaps, observations that cite evidence, hypotheses, a human decision) and the AI investigations requested for it.
// Every rule is the backend's (CaseService): the page only sends entries and shows what is refused. A case disposition
// never resolves the deterministic exception and never changes a published audit pack.
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { errorMessage } from "../api/client";
import type { AiConfirmation, CaseDetail, CaseEntryKind, CaseEntryRequest, CaseResolution, SourceRecord } from "../api/types";
import { AiAuthorizationDialog } from "../components/ai/AiAuthorizationDialog";
import { Amount, Async, Empty, KeyValue, Notice, Panel, StatusBadge, UnresolvedTag } from "../components/common";
import { usePage } from "../components/layout/workContext";
import { useData } from "../data/DataProvider";
import { periodLabel } from "../data/periods";
import { useApi } from "../hooks/useApi";
import { dateTime } from "../lib/format";

const KINDS: Array<[Exclude<CaseEntryKind, "AI_REQUEST">, string, string]> = [
  ["NOTE", "Note", "A working note"],
  ["EVIDENCE", "Supporting evidence", "Cites at least one record, uploaded document or published investigation"],
  ["EVIDENCE_GAP", "Evidence gap", "Evidence that is missing"],
  ["OBSERVATION", "Confirmed observation", "Must cite the evidence it rests on"],
  ["HYPOTHESIS", "Hypothesis", "A possible explanation, not established"],
  ["DECISION", "Human decision", "Sets the case disposition (and may close or reopen the case)"],
];
const KIND_LABEL: Record<string, string> = Object.fromEntries([...KINDS.map(([k, l]) => [k, l]), ["AI_REQUEST", "AI investigation requested"]]);
const RESOLUTION_LABEL: Record<CaseResolution, string> = { UNRESOLVED: "Unresolved", EXPLAINED_BY_ANALYST: "Explained by analyst", ESCALATED: "Escalated" };

export function CasePage() {
  const { caseId = "" } = useParams();
  const data = useData();
  const [tick, setTick] = useState(0);
  const state = useApi(() => data.caseDetail(caseId), [data, caseId, tick]);
  const c = state.data;
  usePage([{ label: c ? periodLabel(c.period_id) : "Case", to: c ? `/reports/${c.period_id}` : undefined },
    ...(c ? [{ label: c.exception_id, to: `/packs/${c.pack_id}/workspace/${c.exception_id}` }] : []), { label: caseId }],
  c ? { packId: c.pack_id, exceptionId: c.exception_id, periodId: c.period_id } : {});
  return (
    <div className="stack">
      <div className="page-head">
        <div><div className="eyebrow">Exception investigation case{c ? ` · ${periodLabel(c.period_id)}` : ""}</div>
          <h1 className="page-title mono">{caseId}</h1>
          {c && <p className="page-sub">Exception <Link className="id" to={`/packs/${c.pack_id}/workspace/${c.exception_id}`}>{c.exception_id}</Link> of <Link className="id" to={`/packs/${c.pack_id}`}>{c.pack_id}</Link>
            {" "}· case <StatusBadge status={c.status} /> · disposition <StatusBadge status={c.human_resolution} label={RESOLUTION_LABEL[c.human_resolution]} /></p>}
        </div>
      </div>
      <Notice tone="info" title="A case records your investigation; it resolves nothing by itself">A case disposition (explained by analyst, escalated) is your
        recorded decision. It does not resolve the deterministic exception, change the pack's results or alter any published final audit pack: the exception
        stays UNRESOLVED there.</Notice>
      <Async state={state} label="Loading the case…">{(d) => <CaseWorkspace c={d} onChange={() => setTick((t) => t + 1)} />}</Async>
    </div>
  );
}

function CaseWorkspace({ c, onChange }: { c: CaseDetail; onChange: () => void }) {
  const data = useData();
  const records = useApi(() => data.sourceEvidence(c.pack_id, c.exception_id), [data, c.pack_id, c.exception_id]);
  const [refs, setRefs] = useState<string[]>([]);
  const toggle = (id: string) => setRefs((r) => (r.includes(id) ? r.filter((x) => x !== id) : [...r, id]));
  const x = c.exception;
  return (
    <div className="grid-final">
      <div className="stack">
        <Panel title="The exception as recorded in the pack" sub="Read-only: never changed by the case">
          <KeyValue items={[["Category", x.category ?? "—"], ["Severity", <StatusBadge status={x.severity} />], ["Account", x.account_id ?? "—"],
            ["Amount", <Amount value={x.amount} currency={x.currency} />], ["Dates", `${x.first_date ?? "—"}${x.last_date && x.last_date !== x.first_date ? ` – ${x.last_date}` : ""}`],
            ["Deterministic status", <><StatusBadge status={x.status} /> <UnresolvedTag /></>]]} />
        </Panel>
        <Panel title="Case history" meta={`${c.entries.length} entr${c.entries.length === 1 ? "y" : "ies"}`} sub="Append-only, oldest first" flush>
          {c.entries.length === 0 ? <Empty>No entries yet.</Empty> : (
            <table className="dtable dtable--compact"><tbody>{c.entries.map((e) => (
              <tr key={e.entry_id}>
                <td className="nowrap xsmall muted">#{e.seq}<div>{dateTime(e.created_at)}</div></td>
                <td><StatusBadge status={e.kind} label={KIND_LABEL[e.kind] ?? e.kind} /></td>
                <td className="small">{e.text}
                  {e.kind === "DECISION" && typeof e.details.resolution === "string" && <div className="xsmall">Disposition: <span className="strong">{RESOLUTION_LABEL[e.details.resolution as CaseResolution] ?? e.details.resolution}</span>{e.details.close ? " · case closed" : ""}</div>}
                  {e.kind === "AI_REQUEST" && typeof e.details.job_id === "string" && <div className="xsmall mono">job {e.details.job_id}</div>}
                  {e.evidence_refs.length > 0 && <div className="xsmall mono">cites {e.evidence_refs.join(", ")}</div>}
                  <div className="xsmall muted">{e.created_by}</div></td>
              </tr>
            ))}</tbody></table>
          )}
        </Panel>
        <Panel title="Supporting financial records" sub="Retrieved deterministically from the pack's verified source files (no AI). Select records to cite them in an entry." flush>
          <Async state={records}>{(ev) => ev.source_records.length === 0 ? <Empty>No source records were retrieved for this exception.</Empty> : (
            <div className="table-scroll"><table className="dtable dtable--compact">
              <thead><tr><th /><th>Record</th><th>Source</th><th>Fields</th></tr></thead>
              <tbody>{ev.source_records.map((r: SourceRecord) => (
                <tr key={r.evidence_id}>
                  <td><input type="checkbox" aria-label={`Cite ${r.evidence_id}`} checked={refs.includes(r.evidence_id)} onChange={() => toggle(r.evidence_id)} /></td>
                  <td className="id">{r.evidence_id}</td>
                  <td className="xsmall muted">{r.source_file ?? "—"}{r.source_line ? `:${r.source_line}` : ""}</td>
                  <td className="xsmall mono">{Object.entries(r.fields).slice(0, 6).map(([k, v]) => `${k}=${String(v)}`).join(" · ")}</td>
                </tr>
              ))}</tbody>
            </table></div>
          )}</Async>
        </Panel>
      </div>
      <div className="stack">
        <AddEntry c={c} refs={refs} onRefs={setRefs} onDone={onChange} />
        <CaseAi c={c} onDone={onChange} />
        <Panel title="Investigation history" sub="Published AI investigations of this exception, with their eligibility" flush>
          {c.ai_investigations.published.length === 0 ? <Empty>No published investigation.</Empty> : (
            <table className="dtable dtable--compact"><tbody>{c.ai_investigations.published.map((i) => (
              <tr key={i.investigation_id}><td><Link className="id" to={`/investigations/${i.investigation_id}`}>{i.investigation_id}</Link>
                <div className="xsmall muted">{dateTime(i.investigated_at)} · {i.overall_evidence_assessment ?? "—"}</div></td>
                <td>{i.eligible ? <StatusBadge status="ELIGIBLE" /> : <span className="xsmall" title={i.ineligible_reasons.join("; ")}>Not eligible: {i.ineligible_reasons[0]}</span>}</td></tr>
            ))}</tbody></table>
          )}
          {c.ai_investigations.not_published.length > 0 && <p className="panel__body xsmall muted">{c.ai_investigations.not_published.length} rejected or failed attempt(s) kept unpublished.</p>}
        </Panel>
      </div>
    </div>
  );
}

function AddEntry({ c, refs, onRefs, onDone }: { c: CaseDetail; refs: string[]; onRefs: (r: string[]) => void; onDone: () => void }) {
  const data = useData();
  const [kind, setKind] = useState<Exclude<CaseEntryKind, "AI_REQUEST">>("NOTE");
  const [text, setText] = useState("");
  const [extra, setExtra] = useState("");
  const [resolution, setResolution] = useState<CaseResolution>("EXPLAINED_BY_ANALYST");
  const [close, setClose] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const decision = kind === "DECISION";
  const closed = c.status === "CLOSED";
  const save = async () => {
    setBusy(true);
    setError(undefined);
    const typed = extra.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean);
    const body: CaseEntryRequest = { kind, text: text.trim(), evidence_refs: [...new Set([...refs, ...typed])], expected_revision: c.revision,
      ...(decision ? { resolution, close } : {}) };
    try {
      await data.addCaseEntry(c.case_id, body);
      setText(""); setExtra(""); onRefs([]);
      onDone();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Panel title="Add an entry" sub={closed ? "The case is closed: only a human decision can reopen it" : "Every entry is kept; nothing is edited or deleted"}>
      <div className="stack stack--sm">
        <label className="field"><span>Entry</span>
          <select className="select" value={kind} onChange={(e) => setKind(e.target.value as typeof kind)} aria-label="Entry kind">
            {KINDS.map(([k, l]) => <option key={k} value={k} disabled={closed && k !== "DECISION"}>{l}</option>)}</select></label>
        <p className="xsmall muted">{KINDS.find(([k]) => k === kind)?.[2]}</p>
        <label className="field"><span>Text</span><textarea className="textarea" rows={3} value={text} onChange={(e) => setText(e.target.value)} aria-label="Entry text" /></label>
        <div className="small">Cited records: {refs.length ? <span className="mono">{refs.join(", ")}</span> : <span className="muted">none selected</span>}</div>
        <label className="field"><span>Other references (uploaded document IDs, investigation IDs)</span>
          <input className="input" value={extra} onChange={(e) => setExtra(e.target.value)} placeholder="DOC-… or INV-…" /></label>
        {decision && <>
          <label className="field"><span>Disposition</span>
            <select className="select" value={resolution} onChange={(e) => setResolution(e.target.value as CaseResolution)} aria-label="Disposition">
              {(Object.keys(RESOLUTION_LABEL) as CaseResolution[]).map((r) => <option key={r} value={r}>{RESOLUTION_LABEL[r]}</option>)}</select></label>
          <label className="check"><input type="checkbox" checked={close} onChange={(e) => setClose(e.target.checked)} /><span>Close the case with this decision</span></label>
          <Notice tone="warn">The disposition is your recorded decision only: the deterministic exception stays UNRESOLVED and no published audit pack changes.</Notice>
        </>}
        <button className="btn btn--primary" disabled={busy || text.trim().length < 3 || (closed && !decision)} onClick={save}>{busy ? "Saving…" : "Add entry"}</button>
        {error !== undefined && <Notice tone="bad" title="The entry was refused">{errorMessage(error)}</Notice>}
      </div>
    </Panel>
  );
}

function CaseAi({ c, onDone }: { c: CaseDetail; onDone: () => void }) {
  const data = useData();
  const [authorising, setAuthorising] = useState(false);
  const running = c.ai_jobs.some((j) => j.status === "QUEUED" || j.status === "RUNNING");
  const request = async (authorization: AiConfirmation) => {
    await data.caseAi(c.case_id, authorization); // a refusal stays in the dialog
    setAuthorising(false);
    onDone();
  };
  return (
    <Panel title="AI assistance" sub="One AI investigation of this exception, requested for this case" flush>
      <div className="panel__body stack stack--sm">
        <button className="btn" disabled={running || c.status === "CLOSED" || authorising} onClick={() => setAuthorising(true)}>
          {running ? "An investigation is running…" : "Request an AI investigation"}</button>
        {c.ai_jobs.length > 0 && <table className="dtable dtable--compact"><tbody>{c.ai_jobs.map((j) => (
          <tr key={j.job_id}><td className="xsmall mono">{j.job_id}{j.authorization_id ? <div className="muted">authorised {j.authorization_id}</div> : null}</td>
            <td><StatusBadge status={j.status} /></td></tr>))}</tbody></table>}
      </div>
      {authorising && <AiAuthorizationDialog operation="INVESTIGATION" onCancel={() => setAuthorising(false)} onConfirm={request} context={[
        ["Reporting period", periodLabel(c.period_id)], ["Deterministic pack", <span className="mono">{c.pack_id}</span>],
        ["Exception", <><span className="mono">{c.exception_id}</span> · {c.exception.category ?? ""}{c.exception.account_id ? ` · ${c.exception.account_id}` : ""}</>],
        ["Case", <span className="mono">{c.case_id}</span>]]} />}
    </Panel>
  );
}
