// Right panel of the workspace: run / monitor an investigation (through the DataSource; simulated in mock mode) and read
// the selected investigation's findings by class. Running one is a paid AI operation: it starts only after the analyst's
// explicit authorisation in the AiAuthorizationDialog (Cancel sends nothing).
import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../../api/client";
import type { AiConfirmation, ExceptionInvestigations, ExceptionView, Findings, InvestigationDetail, Job } from "../../api/types";
import { periodFromPackId, periodLabel } from "../../data/periods";
import { AiAuthorizationDialog } from "../ai/AiAuthorizationDialog";
import { useData } from "../../data/DataProvider";
import { isActive, useJobPoller } from "../../hooks/useJobPoller";
import { dateTime } from "../../lib/format";
import { Empty, ErrorPanel, KeyValue, Notice, SimulatedNotice, StatusBadge, Tabs } from "../common";
import {
  AssessmentCard, ConflictCard, GapCard, HypothesisCard, NextStepCard, ObservationCard, UnverifiedCard, type CiteHandler,
} from "./findings";

export type AiTab = "summary" | "observations" | "hypotheses" | "gaps" | "next";

function JobStatus({ job }: { job: Job }) {
  const running = isActive(job);
  return (
    <div className="stack stack--sm">
      <div className="row"><span className="strong">{running ? "Investigation in progress" : job.status === "COMPLETED" ? "Investigation complete" : "Investigation did not complete"}</span>
        <StatusBadge status={job.status} /></div>
      <div className="progress" aria-hidden><div className={`progress__bar progress__bar--${job.status.toLowerCase()}`} /></div>
      <ul className="steps">
        <li className={job.status !== "QUEUED" ? "is-done" : undefined}>Queued {dateTime(job.submitted_at)}</li>
        <li className={job.completed_at ? "is-done" : undefined}>Running{job.started_at ? ` since ${dateTime(job.started_at)}` : ""}</li>
        <li className={job.status === "COMPLETED" ? "is-done" : undefined}>{job.completed_at ? `Finished ${dateTime(job.completed_at)}` : "Validation and publication"}</li>
      </ul>
      {job.error_summary && <Notice tone="bad" title="Investigation failed">{job.error_summary}</Notice>}
      {typeof job.result?.note === "string" && <p className="xsmall muted">{job.result.note}</p>}
      <p className="xsmall faint mono">{job.job_id}</p>
    </div>
  );
}

export function AiPanel({ packId, exceptionId, exception, periodTitle, row, investigationId, onSelect, detail, findings, loadError, cite, tab, onTab, onFinished }: {
  packId: string; exceptionId: string; exception?: ExceptionView; periodTitle?: string; row: ExceptionInvestigations | undefined;
  investigationId: string | null; onSelect: (id: string) => void;
  detail?: InvestigationDetail; findings?: Findings; loadError?: unknown; cite: CiteHandler; tab: AiTab; onTab: (t: AiTab) => void; onFinished: (job: Job) => void;
}) {
  const data = useData();
  const [jobId, setJobId] = useState<string | null>(null);
  const [startError, setStartError] = useState<unknown>();
  const serverJob = row?.active_jobs[0]?.job_id ?? null;
  const { job } = useJobPoller(jobId ?? serverJob, onFinished);
  const running = isActive(job) || (!!serverJob && !job);

  const [authorising, setAuthorising] = useState(false);
  /** Called only by the dialog's confirmation; an error keeps the dialog open with the refusal. */
  const run = async (authorization: AiConfirmation) => {
    setStartError(undefined);
    try {
      setJobId((await data.startInvestigation(packId, exceptionId, authorization,
        job && !isActive(job) && job.status !== "COMPLETED" ? job.job_id : null)).job_id);
      setAuthorising(false);
    } catch (e) {
      if (e instanceof ApiError && e.code === "INVESTIGATION_ACTIVE" && typeof e.extra.job_id === "string") { setJobId(e.extra.job_id); setAuthorising(false); }
      else throw e;
    }
  };
  const periodId = periodFromPackId(packId);

  const unverified = (findings?.classification_summary?.unverified_candidate_relationships as string[] | undefined) ?? [];
  const gapsCount = (findings?.missing_evidence.length ?? 0) + (findings?.contradictory_evidence.length ?? 0) + unverified.length;

  return (
    <section className="panel" aria-label="AI investigation">
      <header className="panel__head">
        <div><h2 className="panel__title">AI investigation</h2><div className="panel__sub">V2 tools mode · reads cited records only · never changes the exception status</div></div>
      </header>
      <div className="panel__body stack stack--sm">
        {data.kind === "mock" && <SimulatedNotice>Run Investigation simulates the job lifecycle locally. No AI call is made; a completed run points to an investigation already captured from the backend.</SimulatedNotice>}
        {job ? <JobStatus job={job} /> : running ? <p className="small"><span className="spinner" /> An investigation of this exception is running.</p> : null}
        {startError !== undefined && <ErrorPanel error={startError} title="The investigation could not be started" />}
        <button className="btn btn--primary" onClick={() => setAuthorising(true)} disabled={running || authorising}>
          {running ? "Investigation running…" : job && job.status !== "COMPLETED" ? "Retry investigation" : "Run investigation"}
        </button>
        {authorising && (
          <AiAuthorizationDialog operation="INVESTIGATION" onCancel={() => setAuthorising(false)} onConfirm={run} context={[
            ["Reporting period", periodId ? <>{periodLabel(periodId)}{periodTitle ? ` · ${periodTitle}` : ""}</> : "—"],
            ["Deterministic pack", <span className="mono">{packId}</span>],
            ["Exception", <><span className="mono">{exceptionId}</span>{exception ? ` · ${exception.category}${exception.account_id ? ` · ${exception.account_id}` : ""}${exception.amount ? ` · ${exception.amount} ${exception.currency ?? ""}` : ""}` : ""}</>],
          ]} />
        )}
        {detail && <Link className="xsmall" to={`/investigations/${detail.investigation_id}`}>Open the full investigation record</Link>}
        {row && row.published.length > 0 && (
          <label className="field">
            <span>Investigation record</span>
            <select className="select" value={investigationId ?? ""} onChange={(e) => onSelect(e.target.value)} aria-label="Investigation record">
              {row.published.map((p) => (
                <option key={p.investigation_id} value={p.investigation_id}>
                  {p.investigation_id} · {p.investigation_mode} · {p.eligible ? "eligible" : "ineligible"}
                </option>
              ))}
            </select>
          </label>
        )}
        {row && row.not_published.length > 0 && (
          <p className="xsmall muted">{row.not_published.length} failed or rejected attempt(s) were kept by the backend and are not shown as findings.</p>
        )}
      </div>

      {!row ? null : row.published.length === 0 ? (
        <Empty title="No investigation results">Run an investigation to produce observations, assessments, hypotheses and evidence gaps.</Empty>
      ) : loadError !== undefined ? <div className="panel__body"><ErrorPanel error={loadError} title="The investigation could not be loaded" /></div>
        : !findings || !detail ? <p className="panel__body small muted">Loading findings…</p> : (
        <>
          <Tabs label="Investigation content" value={tab} onChange={onTab} tabs={[
            { key: "summary", label: "Summary" }, { key: "observations", label: "Observations", count: findings.confirmed_findings.length },
            { key: "hypotheses", label: "Hypotheses", count: findings.hypotheses.length }, { key: "gaps", label: "Gaps & conflicts", count: gapsCount },
            { key: "next", label: "Next steps", count: findings.recommended_next_steps.length }]} />
          <div className="panel__body stack stack--sm">
            {tab === "summary" && (
              <>
                <AssessmentCard assessment={findings.overall_evidence_assessment} summary={findings.investigation_summary} />
                <KeyValue items={[
                  ["Exception status", <StatusBadge status="UNRESOLVED" label="UNRESOLVED · not resolved by investigation" />],
                  ["Final-pack eligibility", detail.eligible ? <StatusBadge status="ELIGIBLE" /> : <><StatusBadge status="INELIGIBLE" />
                    <ul className="xsmall">{detail.ineligible_reasons.map((r) => <li key={r}>{r}</li>)}</ul></>],
                  ["Model", `${String(detail.model.provider ?? "")} ${String(detail.model.model ?? "")} · ${detail.investigation_mode} mode`],
                  ["Investigated", dateTime(detail.investigated_at)],
                  ["Validation", <StatusBadge status={detail.validation_status} />],
                  ["Registry", detail.registry ? detail.registry.record_type.replace(/_/g, " ").toLowerCase() : "not registered"],
                ]} />
                {findings.open_questions.length > 0 && (
                  <div><div className="finding__field">Open questions</div><ul className="small">{findings.open_questions.map((q) => <li key={q}>{q}</li>)}</ul></div>
                )}
                <p className="xsmall muted">{findings.statement}</p>
              </>
            )}
            {tab === "observations" && (findings.confirmed_findings.length ? findings.confirmed_findings.map((f) => <ObservationCard key={f.finding_id} f={f} cite={cite} />)
              : <p className="small muted">No evidence-supported observations.</p>)}
            {tab === "hypotheses" && (findings.hypotheses.length ? (
              <>
                <Notice tone="warn">Hypotheses are possible explanations the evidence does not establish. None is a finding or a cause.</Notice>
                {findings.hypotheses.map((h) => <HypothesisCard key={h.hypothesis_id} h={h} cite={cite} />)}
              </>
            ) : <p className="small muted">No hypotheses were proposed.</p>)}
            {tab === "gaps" && (gapsCount ? (
              <>
                {findings.missing_evidence.map((g) => <GapCard key={g.item_id} g={g} cite={cite} />)}
                {findings.contradictory_evidence.map((c) => <ConflictCard key={c.item_id} c={c} cite={cite} />)}
                {unverified.map((id) => <UnverifiedCard key={id} id={id} cite={cite} />)}
              </>
            ) : <p className="small muted">No evidence gaps, conflicts or unverified relationships.</p>)}
            {tab === "next" && (findings.recommended_next_steps.length ? findings.recommended_next_steps.map((s) => <NextStepCard key={s.step_id} s={s} />)
              : <p className="small muted">No next steps were suggested.</p>)}
          </div>
        </>
      )}
    </section>
  );
}

