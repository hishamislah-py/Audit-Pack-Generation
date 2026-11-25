// AI investigation content, one visual class per kind (same semantics as the final-pack report): observation (evidence-
// supported), assessment (AI interpretation), hypothesis (NOT ESTABLISHED), evidence gap, conflict, unverified
// relationship, next step. Every finding shows why it is relevant and which evidence it cites.
import type { ReactNode } from "react";
import type { ConfirmedFinding, ContradictoryItem, Hypothesis, MissingEvidenceItem, NextStep } from "../../api/types";

export type CiteHandler = { active: string | null; onCite: (id: string) => void };

export function Cites({ ids, cite, missing }: { ids: string[] | undefined; cite: CiteHandler; missing?: (id: string) => boolean }) {
  if (!ids?.length) return <span className="faint xsmall">none</span>;
  return (
    <span className="cites">
      {ids.map((id) => (
        <button key={id} type="button" className={`cite${cite.active === id ? " cite--active" : ""}${missing?.(id) ? " cite--missing" : ""}`}
          onClick={() => cite.onCite(id)} title="Locate the cited record">{id}</button>
      ))}
    </span>
  );
}

function Card({ kind, label, id, title, children }: { kind: string; label: string; id: string; title?: ReactNode; children: ReactNode }) {
  return (
    <article className={`finding finding--${kind}`}>
      <div className="finding__head"><span className="finding__label">{label}</span><span className="finding__id">{id}</span></div>
      {title && <div className="finding__title">{title}</div>}
      <div className="finding__body">{children}</div>
    </article>
  );
}

const NOT_SUPPLIED = <span className="faint">Not supplied by this investigation (earlier findings schema)</span>;

export function ObservationCard({ f, cite }: { f: ConfirmedFinding; cite: CiteHandler }) {
  return (
    <Card kind="observation" label="Observation · evidence-supported" id={f.finding_id} title={f.title ?? f.claim}>
      {f.title && <div>{f.claim}</div>}
      {f.audit_relevance || f.establishes || f.does_not_establish ? (
        <>
          <div className="finding__why"><div className="finding__field">Relevance to the discrepancy</div>{f.audit_relevance ?? NOT_SUPPLIED}</div>
          <div><div className="finding__field">Establishes</div>{f.establishes ?? NOT_SUPPLIED}</div>
          <div><div className="finding__field">Does not establish</div>{f.does_not_establish ?? NOT_SUPPLIED}</div>
        </>
      ) : (
        <div className="finding__why"><div className="finding__field">Relevance to the discrepancy</div>{f.explanation}
          <div className="faint xsmall">Relevance / establishes / does-not-establish fields were not supplied (findings schema before 1.4).</div></div>
      )}
      <div><div className="finding__field">Cited evidence</div><Cites ids={[...f.evidence_ids, ...f.supporting_records.filter((r) => !f.evidence_ids.includes(r))]} cite={cite} /></div>
    </Card>
  );
}

export function AssessmentCard({ assessment, summary }: { assessment: string | null; summary: string }) {
  return (
    <Card kind="assessment" label="Assessment · AI interpretation, not fact" id={assessment?.replace(/_/g, " ") ?? "—"}>
      <div>{summary}</div>
    </Card>
  );
}

export function HypothesisCard({ h, cite }: { h: Hypothesis; cite: CiteHandler }) {
  return (
    <Card kind="hypothesis" label="Hypothesis · not established" id={h.hypothesis_id} title={h.possible_explanation}>
      <div className="finding__why"><div className="finding__field">Why it was considered</div>{h.rationale ?? NOT_SUPPLIED}</div>
      <div><div className="finding__field">Limitations</div>{h.limitations}</div>
      <div><div className="finding__field">Supporting evidence</div><Cites ids={h.supporting_evidence} cite={cite} /></div>
      <div><div className="finding__field">Contradicting evidence</div><Cites ids={h.contradictory_evidence} cite={cite} /></div>
    </Card>
  );
}

export function GapCard({ g, cite }: { g: MissingEvidenceItem; cite: CiteHandler }) {
  return (
    <Card kind="gap" label="Evidence gap" id={g.item_id} title={g.description}>
      <div className="finding__why"><div className="finding__field">Impact on the discrepancy</div>{g.impact}</div>
      <div><div className="finding__field">Expected source</div>{g.expected_source}</div>
      <div><div className="finding__field">Related</div><Cites ids={g.related_ids} cite={cite} /></div>
    </Card>
  );
}

export function ConflictCard({ c, cite }: { c: ContradictoryItem; cite: CiteHandler }) {
  return (
    <Card kind="conflict" label="Conflict · sources disagree" id={c.item_id} title={c.description}>
      {c.same_measure_and_scope && <div><div className="finding__field">Same measure and scope</div>{c.same_measure_and_scope}</div>}
      <div><div className="finding__field">Compared evidence</div><Cites ids={c.compared_evidence ?? c.evidence_ids} cite={cite} /></div>
    </Card>
  );
}

export function UnverifiedCard({ id, cite }: { id: string; cite: CiteHandler }) {
  return (
    <Card kind="unverified" label="Unverified relationship · inferred link" id={id}>
      <div>A candidate relationship the engine recorded but did not verify. <Cites ids={[id]} cite={cite} /></div>
    </Card>
  );
}

export function NextStepCard({ s }: { s: NextStep }) {
  return (
    <Card kind="next" label="Next step · analyst action (not completed)" id={s.step_id} title={s.action}>
      <div className="finding__why"><div className="finding__field">Rationale</div>{s.rationale}</div>
      <div><div className="finding__field">Evidence needed</div>{s.evidence_needed}</div>
    </Card>
  );
}

export function ClassLegend() {
  const items: Array<[string, string, string]> = [
    ["observation", "Observation", "Evidence-supported"], ["assessment", "Assessment", "AI interpretation"],
    ["hypothesis", "Hypothesis", "Not established"], ["gap", "Evidence gap", "Missing record"], ["conflict", "Conflict", "Sources disagree"],
    ["unverified", "Unverified", "Inferred link"], ["next", "Next step", "Analyst action"],
  ];
  return (
    <div className="class-legend" aria-label="Finding classes">
      {items.map(([k, label, sub]) => <div key={k} className={`finding--${k}`}><b className="finding__label">{label}</b><span>{sub}</span></div>)}
    </div>
  );
}
