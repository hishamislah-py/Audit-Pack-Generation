import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { errorMessage } from "../api/client";
import type { DashboardSummary, PackListItem, PeriodPackRef } from "../api/types";
import { Async, Empty, Kpis, Loading, Notice, Panel, StatusBadge } from "../components/common";
import { usePage, useWork } from "../components/layout/workContext";
import { useData } from "../data/DataProvider";
import type { ReconciliationPeriod } from "../data/models";
import { PACK_KIND_LABEL, packKind } from "../data/periods";
import { useApi } from "../hooks/useApi";
import { dateTime } from "../lib/format";

const STATE_LABEL = { AVAILABLE: "Packs available", DOCUMENTS_ONLY: "Documents, no results", OPEN_FOR_UPLOAD: "Open for upload",
  NO_DATA: "No data" } as const;
const PENDING = ["OPEN", "ON_HOLD", "GENERATING", "GENERATION_FAILED"];

/** AI coverage of one pack from the backend's own counts (registry and authorisation aware): exceptions with an eligible
 * investigation, and running jobs. No per-pack request is made. */
function coverage(ref: PeriodPackRef | undefined) {
  const c = ref?.investigation_counts;
  return c ? { eligible: c.eligible_exceptions ?? 0, running: c.running ?? 0 } : null;
}

function ScenarioRow({ p, origin }: { p: PackListItem; origin?: PeriodPackRef }) {
  const data = useData();
  const navigate = useNavigate();
  const c = coverage(origin);
  const s = p.summary!;
  const kind = packKind(s);
  // The backend's pack list carries the scenario name; only older captured summaries lack it (then the pack is read once).
  const detail = useApi(() => (s.scenario_name === undefined ? data.pack(p.pack_id) : Promise.resolve(undefined)), [data, p.pack_id, s.scenario_name]);
  const name = s.scenario_name ?? detail.data?.metadata.source_dataset.scenario_name;
  return (
    <tr className="is-clickable" onClick={() => navigate(`/packs/${p.pack_id}`)}>
      <td><div className="strong">{PACK_KIND_LABEL[kind]}</div>
        <div className="xsmall muted">{kind === "UPLOADED_DOCUMENTS" ? <span className="mono">{origin?.processing_run_id ?? ""}</span>
          : kind === "DEMONSTRATION_SCENARIO" ? <>Scenario {s.scenario_id} · {name ?? "…"}</>
          : name ?? ""}</div></td>
      <td><Link to={`/packs/${p.pack_id}`} className="id" onClick={(e) => e.stopPropagation()}>{p.pack_id}</Link></td>
      <td><StatusBadge status={s.engine_case_status} /></td>
      <td><StatusBadge status={s.evidence_completeness} /></td>
      <td className="num">{s.exceptions.total}</td>
      <td className="num">{s.exceptions.open}</td>
      <td className="num">{c ? (s.exceptions.total ? `${c.eligible} / ${s.exceptions.total}` : "—") : "—"}{c?.running ? <> <StatusBadge status="RUNNING" label={`${c.running} running`} /></> : null}</td>
    </tr>
  );
}

function OpenMonth({ period }: { period: ReconciliationPeriod }) {
  const data = useData();
  const navigate = useNavigate();
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  if (!data.capabilities.upload) return null;
  const open = async () => {
    setBusy(true);
    setError(undefined);
    try {
      await data.openPeriod(period.year, period.month);
      navigate(`/upload?period=${period.period_id}`);
    } catch (e) { setError(e); setBusy(false); }
  };
  return <><button className="btn" disabled={busy} onClick={open}>Open {period.label} for upload</button>
    {error ? <Notice tone="bad">{errorMessage(error)}</Notice> : null}</>;
}

function PeriodDetail({ period }: { period: ReconciliationPeriod }) {
  const archive = period.archive;
  if (period.state === "NO_DATA") {
    return (
      <Empty title={`No reconciliation data for ${period.label}`} action={<OpenMonth period={period} />}>
        {archive === null && period.packs.length === 0
          ? "No source documents have been supplied for this month in the active data environment. Nothing is shown or invented for it."
          : "No source documents were loaded for this month."}
      </Empty>
    );
  }
  if (period.state === "OPEN_FOR_UPLOAD") {
    return (
      <Empty title={`${period.label} is open for upload`} action={<Link className="btn btn--primary" to={`/upload?period=${period.period_id}`}>Upload financial documents</Link>}>
        Upload the month's source documents to start a new reconciliation. They are identified by content, checked for dates,
        duplicates and missing categories, and processed only after you confirm the batch.
      </Empty>
    );
  }
  if (period.state === "DOCUMENTS_ONLY") {
    return (
      <Empty title={`${period.label}: documents uploaded, no results yet`} action={<Link className="btn btn--primary" to={`/reports/${period.period_id}`}>Open the monthly report</Link>}>
        {archive?.document_count} document(s) in {archive?.batch_count} batch(es). Latest validation:{" "}
        <StatusBadge status={archive?.latest_validation_status ?? "—"} />{archive?.latest_run_status ? <> · latest processing run: <StatusBadge status={archive.latest_run_status} /></> : null}
        {archive && !archive.processing_supported ? <div className="xsmall muted">The backend reports that processing is not available for this month; its documents are stored and validated.</div> : null}
      </Empty>
    );
  }
  const refs = new Map((archive?.packs ?? []).map((r) => [r.pack_id, r]));
  const scenarios = period.packs.filter((p) => packKind(p.summary) === "DEMONSTRATION_SCENARIO").length;
  return (
    <>
      {scenarios > 1 && (
        <div className="notice notice--info">
          <strong>{scenarios} demonstration scenarios for {period.label}.</strong> These are different synthetic test scenarios of the same month, not
          different months.
        </div>
      )}
      <div className="small" style={{ padding: "8px 16px" }}><Link to={`/reports/${period.period_id}`}>Open the {period.label} monthly report</Link> · documents, reconciliation, investigations and published audit packs</div>
      <div className="table-scroll">
        <table className="dtable">
          <thead><tr><th>Pack type</th><th>Pack</th><th>Engine status</th><th>Evidence</th><th className="num">Exceptions</th><th className="num">Unresolved</th><th className="num">Eligible AI</th></tr></thead>
          <tbody>{period.packs.map((p) => p.summary ? <ScenarioRow key={p.pack_id} p={p} origin={refs.get(p.pack_id)} /> : (
            <tr key={p.pack_id}><td colSpan={7}><StatusBadge status="FAILED" label="Does not verify" /> <code>{p.pack_id}</code> {p.problem}</td></tr>
          ))}</tbody>
        </table>
      </div>
    </>
  );
}

/** Exceptions with an eligible AI investigation / exceptions, from the period's backend counts (no per-pack request). */
function CoverageCell({ period }: { period: ReconciliationPeriod }) {
  const a = period.archive;
  if (!period.packs.length || !a) return <>—</>;
  return <>{a.exceptions_total ? `${a.investigation_counts?.eligible_exceptions ?? 0} / ${a.exceptions_total}` : "—"}</>;
}

export function DashboardPage() {
  const data = useData();
  const [params, setParams] = useSearchParams();
  const { work, setWork } = useWork();
  const selected = params.get("period") ?? work.periodId ?? "";
  usePage([{ label: "Overview" }], selected ? { periodId: selected } : {});
  const periods = useApi(() => data.periods(), [data]);
  const finals = useApi(() => data.finalPacks(), [data]);
  const reviews = useApi(() => data.reviews(), [data]);
  const activity = useApi(() => data.activity(), [data]);
  const period = periods.data?.find((p) => p.period_id === selected);
  // The KPI tiles: one backend summary of the selected month (authoritative counts; global totals labelled as global).
  const totals = useApi(() => (selected ? data.dashboard(selected) : Promise.resolve(undefined)), [data, selected]);
  const select = (id: string) => { setParams({ period: id }); setWork({ periodId: id }); };
  const current = periods.data?.find((p) => p.is_current_month);
  const uploadTarget = period ?? current; // the selected month (the current month only when none is selected)
  const pending = (reviews.data ?? []).filter((r) => PENDING.includes(r.status));
  const scenarioNote = period && period.packs.some((p) => packKind(p.summary) === "DEMONSTRATION_SCENARIO") ? " · demonstration scenarios" : "";

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Reconciliation overview</h1>
          <p className="page-sub">Reconciliation overview of the selected month: source documents, processing, deterministic packs, exceptions, AI investigations and audit-pack status. <Link to="/reports">All monthly reports</Link></p>
        </div>
        <div className="actions">
          {uploadTarget && <Link className="btn" to={`/upload?period=${uploadTarget.period_id}`}>Upload documents for {uploadTarget.label}</Link>}
          {period?.packs[0] && <Link className="btn btn--primary" to={`/packs/${period.packs[0].pack_id}`}>Open {period.label} packs</Link>}
        </div>
      </div>

      {totals.data && period && !totals.loading ? <DashboardKpis t={totals.data} label={period.label} scenarioNote={scenarioNote} />
        : selected ? <Loading /> : null}

      <div className="grid-dash">
        <Panel title="Reconciliation periods" meta="Monthly archive · select a month" flush footer={period ? <PeriodDetail period={period} /> : undefined}>
          <Async state={periods}>{(rows) => (
            <div className="table-scroll">
              <table className="dtable">
                <thead><tr><th>Period</th><th>Status</th><th className="num">Documents</th><th>Validation</th><th>Processing</th><th className="num">Packs</th>
                  <th className="num">Exceptions</th><th className="num">Unresolved</th><th className="num">AI coverage</th><th>Final pack</th></tr></thead>
                <tbody>
                  {rows.map((p) => {
                    const exc = p.packs.reduce((n, x) => n + (x.summary?.exceptions.total ?? 0), 0);
                    const open = p.packs.reduce((n, x) => n + (x.summary?.exceptions.open ?? 0), 0);
                    const fp = (finals.data ?? []).filter((f) => p.packs.some((x) => x.pack_id === f.pack_id)).length;
                    const a = p.archive;
                    return (
                      <tr key={p.period_id} className={`is-clickable${p.period_id === selected ? " is-selected" : ""}`} onClick={() => select(p.period_id)} aria-selected={p.period_id === selected}>
                        <td className="strong">{p.label}</td>
                        <td><StatusBadge status={p.state} label={STATE_LABEL[p.state]} /></td>
                        <td className="num">{a?.document_count || "—"}</td>
                        <td>{a?.latest_validation_status ? <StatusBadge status={a.latest_validation_status} /> : "—"}</td>
                        <td>{a?.latest_run_status ? <StatusBadge status={a.latest_run_status} /> : "—"}</td>
                        <td className="num">{p.packs.length || "—"}</td>
                        <td className="num">{p.packs.length ? exc : "—"}</td>
                        <td className="num">{p.packs.length ? open : "—"}</td>
                        <td className="num"><CoverageCell period={p} /></td>
                        <td className="small">{fp ? `${fp} generated` : p.state === "AVAILABLE" ? "None yet" : "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}</Async>
        </Panel>

        <div className="stack">
          <Panel title="Recently generated audit packs" meta="All periods" flush>
            <Async state={finals}>{(rows) => rows.length === 0 ? <Empty>No final audit pack has been generated. Packs are created only by GENERATE in a final review.</Empty> : (
              <table className="dtable"><tbody>
                {[...rows].reverse().slice(0, 5).map((f) => (
                  <tr key={f.final_pack_id}>
                    <td><Link to={`/final-packs/${f.final_pack_id}`} className="id">{f.final_pack_id}</Link><div className="xsmall muted">v{f.version} · {dateTime(f.generated_at)}</div></td>
                    <td className="num">{data.kind === "mock" ? <StatusBadge status="SIMULATED" /> : <StatusBadge status="GENERATED" />}</td>
                  </tr>
                ))}
              </tbody></table>
            )}</Async>
          </Panel>
          <Panel title="Pending reviews" meta="All periods" flush>
            <Async state={reviews}>{() => pending.length === 0 ? <Empty>No open or held reviews.</Empty> : (
              <table className="dtable"><tbody>
                {pending.map((r) => (
                  <tr key={r.review_id}><td><Link to={`/reviews/${r.review_id}`} className="id">{r.review_id}</Link><div className="xsmall muted">{r.pack_id}</div></td>
                    <td className="num"><StatusBadge status={r.status} /></td></tr>
                ))}
              </tbody></table>
            )}</Async>
          </Panel>
          <Panel title="Recent activity" flush>
            {!data.capabilities.activity ? <Empty>The backend does not expose an activity log yet.</Empty> : (
              <Async state={activity}>{(rows) => rows.length === 0 ? <Empty>No activity.</Empty> : (
                <table className="dtable dtable--compact"><tbody>
                  {rows.slice(0, 8).map((a, i) => (
                    <tr key={i}>
                      <td className="nowrap xsmall muted">{dateTime(a.at)}</td>
                      <td className="small"><span className="strong">{a.actor}</span> — {a.link ? <Link to={a.link}>{a.action}</Link> : a.action}
                        <div className="xsmall muted mono">{a.entity}</div>{a.simulated && <StatusBadge status="SIMULATED" />}</td>
                    </tr>
                  ))}
                </tbody></table>
              )}</Async>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}

function DashboardKpis({ t, label, scenarioNote }: { t: DashboardSummary; label: string; scenarioNote: string }) {
  const i = t.investigations;
  const excluded = i.unregistered + i.authorization_discrepancy + i.ineligible_other;
  const parts = [`eligible of published · ${t.exceptions_with_eligible_investigation} exception(s) covered`];
  if (i.running) parts.push(`${i.running} running`);
  if (i.rejected_attempts) parts.push(`${i.rejected_attempts} rejected attempt(s)`);
  if (excluded) parts.push(`${excluded} excluded (unregistered ${i.unregistered}, authorisation discrepancy ${i.authorization_discrepancy}`
    + `${i.ineligible_other ? `, other ${i.ineligible_other}` : ""})`);
  return (
    <Kpis items={[
      { label: "Reconciliation packs", value: t.packs, note: `${label}${t.packs > 1 ? scenarioNote : ""}` },
      { label: "Exceptions", value: t.exceptions, note: `${t.exceptions_open} unresolved`, tone: t.exceptions_open ? "bad" : undefined },
      { label: "AI investigations (eligible / published)", value: `${i.eligible} / ${i.published}`, note: parts.join(" · ") },
      { label: "Pending reviews", value: t.pending_reviews_period, note: `${label} · all periods: ${t.pending_reviews_global}` },
      { label: "Final audit packs", value: t.final_packs_period,
        note: `${label}${t.latest_final_pack_period_at ? `, last ${dateTime(t.latest_final_pack_period_at)}` : ""} · all periods: ${t.final_packs_global}` },
    ]} />
  );
}
