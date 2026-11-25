// Centre-panel evidence: the deterministic results behind the exception and its supporting source records, grouped by
// source (bank, cashbook, settlement, ...). Every record is a line of a hash-verified source file; its ORIGIN says how it
// was retrieved: by the engine's deterministic retrieval (no AI) or by an AI investigation's tool call. A record retrieved
// by AI is still a source record, never an AI finding. A selected citation is highlighted and scrolled into view; IDs that
// are not records (results, searches, gaps) are explained in the citation inspector.
import { Fragment, useEffect, useRef } from "react";
import type { AffectedResult, Evidence, SourceRecord } from "../../api/types";
import { groupRecords, summarise } from "../../lib/evidence";
import { date } from "../../lib/format";
import { Amount, DebitCredit, Empty, KeyValue, StatusBadge } from "../common";

function useScrollTo(active: string | null, own: (id: string) => boolean) {
  const ref = useRef<HTMLTableRowElement | null>(null);
  useEffect(() => { if (active && own(active)) ref.current?.scrollIntoView?.({ block: "center", behavior: "smooth" }); }, [active]); // eslint-disable-line react-hooks/exhaustive-deps
  return ref;
}

export function DeterministicResults({ results, active }: { results: AffectedResult[]; active: string | null }) {
  const ref = useScrollTo(active, (id) => results.some((r) => r.result_id === id));
  if (!results.length) return <Empty>No affected engine results are recorded.</Empty>;
  return (
    <div className="table-scroll table-scroll--tall">
      <table className="dtable dtable--compact">
        <thead><tr><th>Result</th><th>Control</th><th>Outcome</th><th className="num">Computed</th><th className="num">Reported</th><th>Evidence</th></tr></thead>
        <tbody>
          {results.map((r) => (
            <Fragment key={r.result_id}>
              <tr ref={active === r.result_id ? ref : undefined} className={`result-row${active === r.result_id ? " is-highlight" : ""}`}>
                <td className="id id--wrap">{r.result_id}</td>
                <td className="small nowrap">{r.control_code}</td>
                <td><StatusBadge status={r.outcome} /></td>
                <td className="num">{r.computed}</td><td className="num">{r.reported}</td>
                <td>{r.evidence_status ? <StatusBadge status={r.evidence_status} /> : <span className="faint">—</span>}</td>
              </tr>
              <tr className={active === r.result_id ? "is-highlight" : undefined}>
                <td colSpan={6} className="result-note">{r.control_name}{r.note ? ` · ${r.note}` : ""}</td>
              </tr>
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** How a source record was retrieved: an AI investigation's tool call ("tool …"), otherwise the deterministic retrieval. */
export function recordOrigin(r: SourceRecord): "AI_TOOL" | "ENGINE" {
  return typeof r.retrieved_via === "string" && r.retrieved_via.startsWith("tool ") ? "AI_TOOL" : "ENGINE";
}

export const ORIGIN_LABEL = { ENGINE: "Engine retrieval (no AI)", AI_TOOL: "Retrieved by an AI tool call" } as const;

function RecordRow({ r, active, onSelect, rowRef }: { r: SourceRecord; active: boolean; onSelect: (id: string) => void; rowRef?: React.Ref<HTMLTableRowElement> }) {
  const s = summarise(r);
  const origin = recordOrigin(r);
  return (
    <tr ref={rowRef} className={`is-clickable${active ? " is-highlight" : ""}`} onClick={() => onSelect(r.evidence_id)}>
      <td className="id id--wrap">{r.evidence_id}<div><StatusBadge status={origin} tone={origin === "ENGINE" ? "neutral" : "info"} label={origin === "ENGINE" ? "Engine" : "AI tool"} /></div></td>
      <td className="nowrap">{date(s.date)}</td>
      <td className="small">{s.description}<div className="xsmall muted">{r.source_file?.split("/").pop()}{r.source_line ? `:${r.source_line}` : ""}</div></td>
      <td><DebitCredit value={s.dc} /></td>
      <td className="num strong">{s.amount ? <Amount value={s.amount} currency={s.currency} /> : <span className="faint">—</span>}</td>
    </tr>
  );
}

export function EvidenceRecords({ evidence, active, onSelect, records }: { evidence: Evidence; active: string | null; onSelect: (id: string) => void;
  /** a subset of evidence.source_records to show (default: all) */ records?: SourceRecord[] }) {
  const shown = records ?? evidence.source_records;
  const ref = useScrollTo(active, (id) => shown.some((r) => r.evidence_id === id));
  const groups = groupRecords(shown).filter((g) => g.records.length);
  if (!groups.length) return <Empty>No records.</Empty>;
  return (
    <div>
      {groups.map((g) => (
        <div key={g.key}>
          <div className="section-label">{g.title} <span className="faint">({g.records.length})</span></div>
          <div className="table-scroll">
            <table className="dtable dtable--compact">
              <thead><tr><th>Record</th><th>Date</th><th>Description</th><th>D/C</th><th className="num">Amount</th></tr></thead>
              <tbody>{g.records.map((r) => <RecordRow key={r.evidence_id} r={r} active={active === r.evidence_id} onSelect={onSelect}
                rowRef={active === r.evidence_id ? ref : undefined} />)}</tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  );
}

export function Relationships({ evidence, active, onSelect }: { evidence: Evidence; active: string | null; onSelect: (id: string) => void }) {
  const rels = active ? evidence.relationships.filter((r) => r.from === active || r.to === active) : evidence.relationships;
  if (!evidence.relationships.length) return <Empty>No relationships were recorded between these records.</Empty>;
  return (
    <div className="table-scroll table-scroll--tall">
      <table className="dtable dtable--compact">
        <thead><tr><th>From</th><th>Relationship</th><th>To</th><th>Join key</th></tr></thead>
        <tbody>
          {rels.map((r, i) => (
            <tr key={i}>
              <td><button className="link-btn mono" onClick={() => onSelect(r.from)}>{r.from}</button></td>
              <td className="small">{r.relationship.replace(/_/g, " ")}</td>
              <td><button className="link-btn mono" onClick={() => onSelect(r.to)}>{r.to}</button></td>
              <td className="small muted">{r.join_key ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Several evidence sets as one, for looking up a citation (records de-duplicated by ID; the first set wins). */
export function mergeEvidence(...sets: Array<Evidence | undefined>): Evidence | undefined {
  const all = sets.filter((e): e is Evidence => !!e);
  if (!all.length) return undefined;
  const uniq = <T,>(rows: T[], key: (t: T) => unknown) => rows.filter((r, i) => rows.findIndex((x) => key(x) === key(r)) === i);
  const cat = <K extends keyof Evidence>(k: K) => all.flatMap((e) => (e[k] as unknown[]) ?? []);
  return { ...all[0], source_records: uniq(cat("source_records") as SourceRecord[], (r) => r.evidence_id),
    control_results: cat("control_results") as Evidence["control_results"], searches: cat("searches") as Evidence["searches"],
    relationships: uniq(cat("relationships") as Evidence["relationships"], (r) => `${r.from}|${r.relationship}|${r.to}`), conflicts: cat("conflicts") as Evidence["conflicts"],
    missing_evidence: cat("missing_evidence") as Evidence["missing_evidence"], candidate_relationships: cat("candidate_relationships") as Evidence["candidate_relationships"],
    allowed_citation_ids: [...new Set(cat("allowed_citation_ids") as string[])], total_records: 0 };
}

/** What a cited ID refers to: a source record (with its provenance), an engine result, a search, an engine gap or a
 * candidate relationship (unverified). */
export function resolveCitation(evidence: Evidence | undefined, results: AffectedResult[], id: string): { kind: string; fields: Record<string, unknown> } | null {
  const rec = evidence?.source_records.find((r) => r.evidence_id === id);
  if (rec) {
    return { kind: `Source record · ${ORIGIN_LABEL[recordOrigin(rec)]}`, fields: { origin: ORIGIN_LABEL[recordOrigin(rec)],
      source_file: rec.source_file, line: rec.source_line, file_sha256: rec.file_sha256, evidence_type: rec.file_id, record_type: rec.record_type,
      retrieved_via: rec.retrieved_via, join_key: rec.join_key, ...rec.fields } };
  }
  const res = results.find((r) => r.result_id === id) ?? evidence?.control_results.find((r) => r.result_id === id);
  if (res) return { kind: "Deterministic engine result", fields: res as Record<string, unknown> };
  const search = evidence?.searches.find((x) => x.search_id === id);
  if (search) return { kind: "Search of the supplied data", fields: { description: search.description, result: search.result, query: search.query } };
  const miss = evidence?.missing_evidence.find((m) => m.item_id === id);
  if (miss) return { kind: "Engine missing-evidence item", fields: miss };
  const cand = evidence?.candidate_relationships.find((c) => c.candidate_id === id);
  if (cand) return { kind: "Candidate relationship (unverified)", fields: cand };
  const conflict = evidence?.conflicts.find((c) => c.conflict_id === id);
  if (conflict) return { kind: "Deterministic conflict", fields: conflict };
  return null;
}

export function CitationInspector({ id, evidence, results, onClose }: { id: string; evidence?: Evidence; results: AffectedResult[]; onClose: () => void }) {
  const hit = resolveCitation(evidence, results, id);
  return (
    <section className="panel" aria-label={`Citation ${id}`}>
      <header className="panel__head">
        <div><div className="eyebrow">Cited evidence</div><code className="strong">{id}</code></div>
        <button className="btn btn--sm btn--ghost" onClick={onClose}>Close</button>
      </header>
      <div className="panel__body">
        {!hit ? <p className="small muted">This ID is not among the retrieved records, engine results or searches shown here.</p> : (
          <div className="stack stack--sm">
            <StatusBadge status="INFO" tone="info" label={hit.kind} />
            <KeyValue items={Object.entries(hit.fields).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, typeof v === "object" ? <code>{JSON.stringify(v)}</code> : String(v)])} />
          </div>
        )}
      </div>
    </section>
  );
}
