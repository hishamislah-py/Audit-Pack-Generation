// Monthly reports: the archive of reporting periods (one entry per month), the creation of a new monthly report, and the
// monthly workspace (overview, documents, reconciliation, exceptions, AI investigations, closing summary, published audit
// packs, document history), including adding supporting documents to an existing month.
//
// Everything shown comes from the active backend (its database and packs root). Nothing is invented: a month without
// records is shown as having no data, September's nine demonstration scenarios stay one month, and published packs are
// read-only. Adding a document never changes a pack, investigation or published final audit pack.
import { useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { errorMessage } from "../api/client";
import type {
  ExceptionInvestigations, ExceptionView, FinalPackListItem, Health, PackListItem, PeriodDetail, PeriodExceptionOverview, PeriodPackRef, ReportingStatus,
  SourceDocument, SubmissionKind,
} from "../api/types";
import { Async, Empty, Kpis, Loading, Notice, Panel, StatusBadge, UnresolvedTag } from "../components/common";
import { usePage } from "../components/layout/workContext";
import { ReassessmentPanel } from "../components/report/Reassessment";
import { DropZone } from "../components/upload";
import { DocumentTable, kb, RunTable } from "../components/upload/documents";
import { useData } from "../data/DataProvider";
import type { ReconciliationPeriod } from "../data/models";
import {
  MONTHS, PACK_KIND_LABEL, packKind, periodId as toPeriodId, periodLabel, REPORTING_STATUS_LABEL, REPORTING_STATUS_TONE, reportTitle,
} from "../data/periods";
import { type ApiState, useApi } from "../hooks/useApi";
import { date, dateTime } from "../lib/format";

// ------------------------------------------------------------------------------------------------ shared helpers
/** The period's reporting status: the backend's (from its records); with mock data, from the packs listed. */
export function statusOf(p: ReconciliationPeriod): ReportingStatus {
  if (p.archive) return p.archive.reporting_status;
  return p.packs.length ? "DETERMINISTIC_PACK_AVAILABLE" : "NO_DATA";
}

function ReportingBadge({ status }: { status: ReportingStatus }) {
  return <StatusBadge status={status} tone={REPORTING_STATUS_TONE[status]} label={REPORTING_STATUS_LABEL[status]} />;
}

function finalsFor(p: ReconciliationPeriod, finals: FinalPackListItem[] | undefined): FinalPackListItem[] {
  const ids = new Set(p.packs.map((x) => x.pack_id));
  return (finals ?? []).filter((f) => ids.has(f.pack_id));
}

function kindSummary(packs: PackListItem[]): string {
  if (!packs.length) return "—";
  const kinds = new Map<string, number>();
  for (const x of packs) {
    const k = packKind(x.summary);
    kinds.set(k, (kinds.get(k) ?? 0) + 1);
  }
  return [...kinds].map(([k, n]) => k === "DEMONSTRATION_SCENARIO" ? `${n} demonstration scenario${n > 1 ? "s" : ""}`
    : k === "HISTORICAL_MONTHLY" ? `${n} historical monthly pack${n > 1 ? "s" : ""}` : `${n} pack${n > 1 ? "s" : ""} from uploads`).join(", ");
}

/** The active data environment, shown unobtrusively. Environments are separate databases and are never combined here. */
export function EnvironmentNote({ health }: { health: Health | undefined }) {
  const env = health?.environment;
  if (!env) return null;
  return (
    <p className="xsmall muted">
      Data environment: <span className="strong">{env.label}</span>{env.database ? <> (database <span className="mono">{env.database}</span></> : " ("}
      {env.database ? ", " : ""}packs <span className="mono">{env.packs_root}</span>). Every reporting period of this database is listed
      {env.storage_profiles && env.storage_profiles.length > 1 ? <>; artefacts are read from the storage profiles {env.storage_profiles.join(", ")}</> : ""}.
    </p>
  );
}

// ------------------------------------------------------------------------------------------------ archive
const ALL = "";

export function ReportsPage() {
  const data = useData();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  usePage([{ label: "Monthly reports" }]);
  const periods = useApi(() => data.periods(), [data]);
  const finals = useApi(() => data.finalPacks(), [data]);
  const health = useApi(() => data.health(), [data]);
  const f = { q: params.get("q") ?? "", year: params.get("year") ?? ALL, month: params.get("month") ?? ALL,
    status: params.get("status") ?? ALL, final: params.get("final") ?? ALL, sort: params.get("sort") ?? "newest" };
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v); else next.delete(k);
    setParams(next, { replace: true });
  };

  return (
    <div className="stack">
      <div className="page-head">
        <div><div className="eyebrow">Reconciliation archive</div><h1 className="page-title">Monthly reports</h1>
          <p className="page-sub">One entry per reporting month: its documents, deterministic reconciliation, exceptions, AI investigations and published audit packs.</p></div>
        <div className="actions">
          <Link className={`btn btn--primary${data.capabilities.upload ? "" : " is-disabled"}`} to="/reports/new" aria-disabled={!data.capabilities.upload || undefined}>Add New Monthly Report</Link>
        </div>
      </div>
      <Async state={periods}>{(rows) => {
        const years = [...new Set(rows.map((p) => String(p.year)))].sort().reverse();
        const q = f.q.trim().toLowerCase();
        const shown = rows.filter((p) => {
          const fp = finalsFor(p, finals.data).length;
          return (!f.year || String(p.year) === f.year) && (!f.month || String(p.month) === f.month)
            && (!f.status || statusOf(p) === f.status)
            && (!f.final || (f.final === "published" ? fp > 0 : fp === 0))
            && (!q || [p.label, p.period_id, p.archive?.title ?? ""].some((s) => s.toLowerCase().includes(q)));
        }).sort((a, b) => (f.sort === "oldest" ? a.period_id.localeCompare(b.period_id) : b.period_id.localeCompare(a.period_id)));
        return (
          <Panel title="Reporting periods" meta={`${shown.length} of ${rows.length}`} flush>
            <div className="filters" role="search">
              <label className="field field--grow"><span>Search title or period</span>
                <input className="input" type="search" value={f.q} placeholder="e.g. February or PER-2026-02" onChange={(e) => set("q", e.target.value)} /></label>
              <label className="field"><span>Year</span>
                <select className="select" value={f.year} onChange={(e) => set("year", e.target.value)}>
                  <option value={ALL}>All years</option>{years.map((y) => <option key={y} value={y}>{y}</option>)}</select></label>
              <label className="field"><span>Month</span>
                <select className="select" value={f.month} onChange={(e) => set("month", e.target.value)}>
                  <option value={ALL}>All months</option>{MONTHS.map((m, i) => <option key={m} value={String(i + 1)}>{m}</option>)}</select></label>
              <label className="field"><span>Reporting status</span>
                <select className="select" value={f.status} onChange={(e) => set("status", e.target.value)}>
                  <option value={ALL}>All statuses</option>
                  {(Object.keys(REPORTING_STATUS_LABEL) as ReportingStatus[]).map((s) => <option key={s} value={s}>{REPORTING_STATUS_LABEL[s]}</option>)}</select></label>
              <label className="field"><span>Final audit pack</span>
                <select className="select" value={f.final} onChange={(e) => set("final", e.target.value)}>
                  <option value={ALL}>Any</option><option value="published">Published</option><option value="none">Not published</option></select></label>
              <label className="field"><span>Sort</span>
                <select className="select" value={f.sort} onChange={(e) => set("sort", e.target.value)}>
                  <option value="newest">Newest month first</option><option value="oldest">Oldest month first</option></select></label>
            </div>
            {shown.length === 0 ? <Empty title="No reporting period matches">Change the filters or the search.</Empty> : (
              <div className="table-scroll">
                <table className="dtable">
                  <thead><tr><th>Month</th><th>Report title</th><th>Period ID</th><th className="num">Documents</th><th>Packs</th>
                    <th className="num">Exceptions</th><th className="num">Investigations</th><th>Final audit pack</th><th>Status</th></tr></thead>
                  <tbody>{shown.map((p) => {
                    const fp = finalsFor(p, finals.data);
                    const exc = p.packs.reduce((n, x) => n + (x.summary?.exceptions.total ?? 0), 0);
                    return (
                      <tr key={p.period_id} className="is-clickable" onClick={() => navigate(`/reports/${p.period_id}`)}>
                        <td className="strong nowrap"><Link to={`/reports/${p.period_id}`} onClick={(e) => e.stopPropagation()}>{p.label}</Link></td>
                        <td className="small">{p.archive?.title || <span className="muted">{p.archive ? "Untitled" : "—"}</span>}</td>
                        <td className="id">{p.period_id}</td>
                        <td className="num">{p.archive ? p.archive.document_count : "—"}</td>
                        <td className="small">{kindSummary(p.packs)}</td>
                        <td className="num">{p.packs.length ? exc : "—"}</td>
                        <td className="num">{p.archive ? p.archive.published_investigations : "—"}
                          {p.archive?.excluded_investigations ? <span className="xsmall muted" title="Published artefacts that are unregistered or an authorisation discrepancy (kept, not counted)"> +{p.archive.excluded_investigations} excluded</span> : null}</td>
                        <td className="small">{fp.length ? <StatusBadge status="GENERATED" label={`Published${fp.length > 1 ? ` (${fp.length} versions)` : ""}`} /> : "—"}
                          {p.archive?.pending_reassessment ? <div className="xsmall">Pending reassessment</div> : null}</td>
                        <td><ReportingBadge status={statusOf(p)} /></td>
                      </tr>
                    );
                  })}</tbody>
                </table>
              </div>
            )}
          </Panel>
        );
      }}</Async>
      <EnvironmentNote health={health.data} />
    </div>
  );
}

// ------------------------------------------------------------------------------------------------ new monthly report
export function NewReportPage() {
  const data = useData();
  const navigate = useNavigate();
  usePage([{ label: "Monthly reports", to: "/reports" }, { label: "Add new monthly report" }]);
  const periods = useApi(() => data.periods(), [data]);
  const now = new Date();
  const [year, setYear] = useState(String(now.getFullYear()));
  const [month, setMonth] = useState(String(now.getMonth() + 1));
  const [title, setTitle] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const y = Number(year);
  const m = Number(month);
  const validYear = /^\d{4}$/.test(year) && y >= 2000 && y <= 2100;
  const pid = validYear && m >= 1 && m <= 12 ? toPeriodId(y, m) : null;
  const future = pid !== null && (y > now.getFullYear() || (y === now.getFullYear() && m > now.getMonth() + 1));
  const existing = pid ? periods.data?.find((p) => p.period_id === pid && p.archive) : undefined;
  const shownTitle = title ?? (pid ? `${periodLabel(pid)} Reconciliation Audit` : "");
  const titleOk = shownTitle.trim().length >= 3 && shownTitle.trim().length <= 120;

  const create = async () => {
    if (!pid) return;
    setBusy(true);
    setError(undefined);
    try {
      const p = await data.openPeriod(y, m, shownTitle.trim());
      navigate(`/upload?period=${p.period_id}&new=1`);
    } catch (e) { setError(e); setBusy(false); }
  };

  return (
    <div className="stack">
      <div className="page-head">
        <div><div className="eyebrow">Monthly reports</div><h1 className="page-title">Add new monthly report</h1>
          <p className="page-sub">Create the reporting period, then upload its financial documents. Nothing is processed, investigated or published until you continue through the workflow.</p></div>
      </div>
      {!data.capabilities.upload && <Notice tone="info" title="Backend required">Creating a reporting period needs the backend database. Mock data never simulates it.</Notice>}
      <div className="grid-final">
        <Panel title="1. Reporting period">
          <div className="stack stack--sm">
            <div className="form-grid">
              <label className="field"><span>Month</span>
                <select className="select" value={month} onChange={(e) => { setMonth(e.target.value); setTitle(undefined); }}>
                  {MONTHS.map((name, i) => <option key={name} value={String(i + 1)}>{name}</option>)}</select></label>
              <label className="field"><span>Year</span>
                <input className="input" inputMode="numeric" value={year} onChange={(e) => { setYear(e.target.value.trim()); setTitle(undefined); }} aria-invalid={!validYear || undefined} /></label>
            </div>
            <label className="field"><span>Report title</span>
              <input className="input" value={shownTitle} maxLength={120} onChange={(e) => setTitle(e.target.value)} aria-invalid={!titleOk || undefined} /></label>
            <div className="small">Period ID: <span className="id">{pid ?? "—"}</span> <span className="xsmall muted">(derived from the month and year; the immutable identifier used throughout the backend)</span></div>
          </div>
        </Panel>
        <Panel title="2. Check and create">
          <div className="stack stack--sm">
            {!validYear && <Notice tone="warn">Enter a four-digit year from 2000 to 2100.</Notice>}
            {future && <Notice tone="warn">{periodLabel(pid)} has not started yet: a reporting period can be created for the current or a past month.</Notice>}
            {!titleOk && pid && <Notice tone="warn">The title must be 3 to 120 characters.</Notice>}
            {periods.loading ? <Loading label="Checking existing periods…" /> : existing ? (
              <Notice tone="warn" title={`${periodLabel(pid)} already exists`}>
                It is recorded as “{reportTitle(existing.archive!)}”. A second report is never created for the same month; open the existing one to
                add documents or change its title. <Link to={`/reports/${pid}`}>Open {periodLabel(pid)}</Link>
              </Notice>
            ) : pid && validYear && !future ? <Notice tone="ok">{periodLabel(pid)} does not exist yet and can be created.</Notice> : null}
            <button className="btn btn--primary" disabled={busy || !data.capabilities.upload || !pid || !validYear || future || !titleOk || !!existing || periods.loading}
              onClick={create}>{busy ? "Creating…" : "Create and continue to upload"}</button>
            {error ? <Notice tone="bad">{errorMessage(error)}</Notice> : null}
            <p className="xsmall muted">Next: Upload → Validate → Reconcile → Investigate → Closing summary → Final review → Generate, using the existing steps and review gates.</p>
          </div>
        </Panel>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------ monthly workspace
const SECTIONS = [["overview", "1. Overview"], ["documents", "2. Source documents"], ["reconciliation", "3. Reconciliation results"],
  ["exceptions", "4. Exceptions"], ["investigations", "5. AI investigations"], ["closing-summary", "6. Closing summary"],
  ["audit-packs", "7. Published audit packs"], ["reassessment", "Reassessment"], ["history", "8. Document history"]] as const;

export function ReportPage() {
  const { periodId = "" } = useParams();
  const data = useData();
  usePage([{ label: "Monthly reports", to: "/reports" }, { label: periodLabel(periodId) }], { periodId });
  const periods = useApi(() => data.periods(), [data]);
  const archive = useApi(() => (data.capabilities.upload ? data.archivePeriod(periodId).catch(() => null) : Promise.resolve(null)), [data, periodId]);
  const finals = useApi(() => data.finalPacks(), [data]);
  const health = useApi(() => data.health(), [data]);
  if (!/^PER-\d{4}-(0[1-9]|1[0-2])$/.test(periodId)) return <Empty title="Not a reporting period">Period IDs have the form PER-YYYY-MM. <Link to="/reports">Monthly reports</Link></Empty>;
  // Only the first load replaces the page: a reload keeps the page (and its in-progress actions) mounted.
  if ((periods.loading && !periods.data) || (archive.loading && archive.data === undefined)) return <Loading label="Loading the monthly report…" />;
  if (periods.error) return <Async state={periods}>{() => null}</Async>;
  const period = periods.data?.find((p) => p.period_id === periodId);
  const detail = archive.data ?? null;
  if (!period && !detail) {
    return <Empty title={`No report for ${periodLabel(periodId)}`} action={<Link className="btn" to="/reports/new">Add New Monthly Report</Link>}>
      The active data environment has no records for this month.</Empty>;
  }
  return <ReportWorkspace periodId={periodId} period={period} detail={detail} finals={finals.data ?? []} health={health.data}
    reload={() => { periods.reload(); archive.reload(); finals.reload(); }} />;
}

function ReportWorkspace({ periodId, period, detail, finals, health, reload }: {
  periodId: string; period: ReconciliationPeriod | undefined; detail: PeriodDetail | null; finals: FinalPackListItem[]; health: Health | undefined; reload: () => void;
}) {
  const data = useData();
  const rec = detail?.period ?? period?.archive ?? null;
  const packs: PackListItem[] = period?.packs ?? [];
  const refs = new Map((rec?.packs ?? []).map((r) => [r.pack_id, r]));
  const packIds = new Set(packs.map((p) => p.pack_id));
  const published = finals.filter((f) => packIds.has(f.pack_id));
  const status: ReportingStatus = rec?.reporting_status ?? (packs.length ? "DETERMINISTIC_PACK_AVAILABLE" : "NO_DATA");
  const docs = detail?.documents ?? [];
  const overview = usePeriodExceptions(periodId, packs);
  const exceptions = packs.reduce((n, p) => n + (p.summary?.exceptions.total ?? 0), 0);
  return (
    <div className="stack">
      <section id="overview" className="stack">
        <div className="page-head">
          <div>
            <div className="eyebrow">Monthly report · {periodId}</div>
            <h1 className="page-title">{rec ? reportTitle(rec) : `${periodLabel(periodId)} reconciliation`}</h1>
            <p className="page-sub">{periodLabel(periodId)} · {date(`${periodId.slice(4)}-01`)} to month end · <ReportingBadge status={status} /></p>
          </div>
          <div className="actions">
            {data.capabilities.upload && rec && <a className="btn" href="#documents">Add Supporting Document</a>}
            {data.capabilities.upload && rec && <Link className="btn btn--primary" to={`/upload?period=${periodId}`}>Upload documents</Link>}
          </div>
        </div>
        <nav className="section-index" aria-label="Report sections">{SECTIONS.map(([id, label]) => <a key={id} href={`#${id}`}>{label}</a>)}</nav>
        <Kpis items={[
          { label: "Month", value: periodLabel(periodId), note: `Period ID ${periodId}`, tone: "sm" },
          { label: "Source documents", value: rec ? rec.document_count : "—", note: rec ? `${rec.batch_count} upload batch(es)` : "No archive record" },
          { label: "Deterministic packs", value: packs.length, note: kindSummary(packs) },
          { label: "Exceptions", value: exceptions, note: packs.length ? (exceptions ? "All unresolved" : "Clean month: no exceptions") : "No reconciliation yet", tone: exceptions ? "bad" : undefined },
          { label: "Published audit packs", value: published.length, note: rec?.latest_final_pack_at ? `Latest ${dateTime(rec.latest_final_pack_at)}` : "None" },
        ]} />
        {rec && <RenameTitle periodId={periodId} title={rec.title} onDone={reload} />}
        {rec?.pending_reassessment && (
          <Notice tone="warn" title="Additional evidence received after publication — pending reassessment">
            {rec.documents_after_publication} document(s) were added after the latest final audit pack was published. The published pack does not
            incorporate them and has not been changed. Confirm the new batch, then use <a href="#reassessment">Reassess</a>: it produces a new deterministic
            pack linked to the published one, and its final review publishes the next final-pack version (earlier versions stay available).
          </Notice>
        )}
        <EnvironmentNote health={health} />
      </section>

      <Panel id="documents" title="2. Source documents" meta={`${docs.length}`} sub="Original documents are immutable: a correction is stored as a new version linked to the earlier one" flush>
        {!data.capabilities.upload ? <Empty>Source documents come from the backend database (not available with mock data).</Empty>
          : docs.length === 0 ? <Empty title="No documents uploaded through the application for this month">
              {packs.length ? "The deterministic pack(s) were registered from their dataset folders; their source files and hashes are listed in each pack's source inventory." : "Upload the month's financial documents to start its reconciliation."}
            </Empty>
          : <DocumentTable documents={docs} showBatch current={new Set(Object.values(detail?.current_set ?? {}))} />}
        {data.capabilities.upload && rec && <div style={{ padding: 16 }}><AddSupportingDocument periodId={periodId} documents={docs} publishedFinalPacks={published.map((f) => f.final_pack_id)} /></div>}
      </Panel>

      <Panel id="reconciliation" title="3. Reconciliation results" sub="Deterministic packs (immutable); a deterministic pack is not a final audit report" flush>
        {packs.length === 0 ? <Empty title="No deterministic reconciliation yet">{rec?.document_count ? "Documents are uploaded; process a confirmed batch with every required evidence type to produce the deterministic pack." : "Upload and validate the month's documents first."}</Empty> : (
          <>
            {packs.filter((p) => packKind(p.summary) === "DEMONSTRATION_SCENARIO").length > 1 && (
              <Notice tone="info">{packs.length} demonstration scenarios of this one month ({periodLabel(periodId)}). They are separate synthetic test scenarios, not separate months.</Notice>
            )}
            <div className="table-scroll"><table className="dtable">
              <thead><tr><th>Pack</th><th>Type</th><th>Engine status</th><th>Evidence</th><th className="num">Exceptions</th><th className="num">Unresolved</th><th /></tr></thead>
              <tbody>{packs.map((p) => <PackRow key={p.pack_id} p={p} ref_={refs.get(p.pack_id)} />)}</tbody>
            </table></div>
          </>
        )}
      </Panel>

      <Panel id="exceptions" title="4. Exceptions" sub="From the deterministic packs; exceptions are never resolved by this application" flush>
        {packs.length === 0 ? <Empty>No reconciliation yet, so no exceptions.</Empty>
          : exceptions === 0 ? <Empty title="No exceptions">The deterministic reconciliation reports no exceptions. A clean month is a valid monthly report.</Empty>
          : <ExceptionsTable packs={packs} overview={overview} />}
      </Panel>

      <Panel id="investigations" title="5. AI investigations" sub="Published investigation artefacts (an aid to human review; they resolve nothing). Unregistered artefacts and authorisation discrepancies are listed but not eligible." flush>
        {packs.length === 0 ? <Empty>No reconciliation yet.</Empty> : exceptions === 0 ? <Empty>No exceptions, so nothing to investigate.</Empty> : <InvestigationsTable overview={overview} />}
      </Panel>

      <Panel id="closing-summary" title="6. Closing summary" sub="The AI-generated closing summary of the latest published final audit pack" flush>
        {published.length === 0 ? <Empty>No closing summary is available. Closing summaries are generated in final review and published inside a final audit pack.</Empty>
          : <ClosingSummaryView finalPackId={published[published.length - 1].final_pack_id} />}
      </Panel>

      <Panel id="audit-packs" title="7. Published audit packs" sub="Immutable; a new version never replaces an earlier one" flush>
        {published.length === 0 ? <Empty>No final audit pack has been published for this month. A final pack is created only by GENERATE in a final review.</Empty> : (
          <div className="table-scroll"><table className="dtable">
            <thead><tr><th>Final audit pack</th><th className="num">Version</th><th>Source deterministic pack</th><th>Published</th><th>Downloads</th></tr></thead>
            <tbody>{[...published].reverse().map((f) => (
              <tr key={f.final_pack_id}>
                <td><Link className="id" to={`/final-packs/${f.final_pack_id}`}>{f.final_pack_id}</Link>
                  {rec?.pending_reassessment && f.final_pack_id === published[published.length - 1].final_pack_id && <div className="xsmall">Does not include evidence received after publication</div>}</td>
                <td className="num">v{f.version}</td><td className="id">{f.pack_id}</td><td className="small">{dateTime(f.generated_at)}</td>
                <td className="small"><Downloads finalPackId={f.final_pack_id} /></td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
        {rec?.pending_reassessment && <div style={{ padding: 16 }} className="small">To assess the new evidence, use <a href="#reassessment">Reassess</a> below.</div>}
      </Panel>

      {data.capabilities.upload && published.length > 0 && <ReassessmentPanel periodId={periodId} onDone={reload} />}

      <Panel id="history" title="8. Document history" sub="Uploads, corrections, packs and publications, newest first (read-only)" flush>
        <History detail={detail} packs={rec?.packs ?? []} finals={published} />
        {detail && detail.runs.length > 0 && <RunTable runs={detail.runs} />}
      </Panel>
    </div>
  );
}

function PackRow({ p, ref_ }: { p: PackListItem; ref_?: PeriodPackRef }) {
  const s = p.summary;
  if (!s) return <tr><td colSpan={7}><StatusBadge status="FAILED" label="Does not verify" /> <code>{p.pack_id}</code> {p.problem}</td></tr>;
  const kind = packKind(s);
  return (
    <tr>
      <td><Link className="id" to={`/packs/${p.pack_id}`}>{p.pack_id}</Link>
        <div className="xsmall muted">{kind === "DEMONSTRATION_SCENARIO" ? `Scenario ${s.scenario_id}` : s.scenario_name || (ref_?.processing_run_id ? `Processing run ${ref_.processing_run_id}` : "")}</div>
        {ref_?.predecessor_pack_id && <div className="xsmall">Reassessment of <Link className="id" to={`/packs/${ref_.predecessor_pack_id}`}>{ref_.predecessor_pack_id}</Link></div>}</td>
      <td className="small">{PACK_KIND_LABEL[kind]}</td>
      <td><StatusBadge status={s.engine_case_status} /></td><td><StatusBadge status={s.evidence_completeness} /></td>
      <td className="num">{s.exceptions.total}</td><td className="num">{s.exceptions.open}</td>
      <td className="small nowrap"><Link to={`/packs/${p.pack_id}/workspace`}>Workspace</Link> · <Link to={`/packs/${p.pack_id}/review`}>Final review</Link></td>
    </tr>
  );
}

/** The month's exceptions and investigations, read once for every pack of the period (one request, not one per pack). */
function usePeriodExceptions(periodId: string, packs: PackListItem[]) {
  const data = useData();
  const ids = packs.map((p) => p.pack_id).join(",");
  return useApi(() => (packs.some((p) => p.summary?.exceptions.total) ? data.periodExceptions(periodId) : Promise.resolve([])), [data, periodId, ids]);
}

function ExceptionsTable({ packs, overview }: { packs: PackListItem[]; overview: ApiState<PeriodExceptionOverview[]> }) {
  const byId = new Map(packs.map((p) => [p.pack_id, p]));
  const rows = { ...overview, data: overview.data?.flatMap((o) => (byId.has(o.pack_id) ? o.exceptions.map((x) => ({ pack: byId.get(o.pack_id)!, x })) : [])) };
  return (
    <Async state={rows}>{(r: Array<{ pack: PackListItem; x: ExceptionView }>) => (
      <div className="table-scroll"><table className="dtable dtable--compact">
        <thead><tr><th>Exception</th><th>Pack</th><th>Severity</th><th>Category</th><th>Account</th><th>Status</th></tr></thead>
        <tbody>{r.map(({ pack, x }) => (
          <tr key={`${pack.pack_id}/${x.exception_id}`}>
            <td><Link className="id" to={`/packs/${pack.pack_id}/workspace/${x.exception_id}`}>{x.exception_id}</Link></td>
            <td className="id xsmall">{pack.pack_id}</td><td><StatusBadge status={x.severity} /></td><td className="small">{x.category}</td>
            <td className="small">{x.account_id ?? "—"}</td><td><UnresolvedTag /></td>
          </tr>
        ))}</tbody>
      </table></div>
    )}</Async>
  );
}

function InvestigationsTable({ overview }: { overview: ApiState<PeriodExceptionOverview[]> }) {
  const rows = { ...overview, data: overview.data?.flatMap((o) => o.investigations) };
  return (
    <Async state={rows}>{(r: ExceptionInvestigations[]) => {
      const published = r.flatMap((e) => e.published.map((i) => ({ e, i })));
      if (!published.length) return <Empty title="AI investigation not yet performed">The deterministic pack exists; no investigation has been published for its exceptions. Investigations are started explicitly in the exception workspace.</Empty>;
      return (
        <div className="table-scroll"><table className="dtable dtable--compact">
          <thead><tr><th>Investigation</th><th>Exception</th><th>Mode</th><th>Assessment</th><th>Model</th><th>Review eligibility</th></tr></thead>
          <tbody>{published.map(({ e, i }) => (
            <tr key={i.investigation_id}>
              <td><Link className="id" to={`/investigations/${i.investigation_id}`}>{i.investigation_id}</Link><div className="xsmall muted">{dateTime(i.investigated_at)}</div></td>
              <td><Link className="id" to={`/packs/${e.pack_id}/workspace/${e.exception_id}`}>{e.exception_id}</Link></td>
              <td className="small">{i.investigation_mode ?? "—"}</td><td><StatusBadge status={i.overall_evidence_assessment} /></td>
              <td className="small">{i.simulated ? <StatusBadge status="SIMULATED" /> : `${i.provider ?? ""} ${i.model ?? ""}`}</td>
              <td>{i.eligible ? <StatusBadge status="ELIGIBLE" label="Eligible (registered)" /> : <span className="small" title={i.ineligible_reasons.join("; ")}>Not eligible: {i.ineligible_reasons[0] ?? "—"}</span>}</td>
            </tr>
          ))}</tbody>
        </table></div>
      );
    }}</Async>
  );
}

function ClosingSummaryView({ finalPackId }: { finalPackId: string }) {
  const data = useData();
  const doc = useApi(() => data.finalPackDocument(finalPackId), [data, finalPackId]);
  return (
    <Async state={doc}>{(d) => {
      const cs = d.closing_summary;
      if (cs.status !== "GENERATED" || !cs.output) return <Empty>The closing summary of {finalPackId} is unavailable: {cs.unavailable_reason || "not generated"}.</Empty>;
      return (
        <div className="panel__body stack stack--sm">
          <Notice tone="info">AI-generated, from {finalPackId}; not an audit opinion or compliance certification, and it resolves no exception.</Notice>
          <p><span className="strong">Overall position.</span> {cs.output.overall_position}</p>
          <p>{cs.output.summary_text}</p>
          {cs.output.unresolved_items.length > 0 && <div className="small"><span className="strong">Unresolved:</span> {cs.output.unresolved_items.map((u) => u.exception_id).join(", ")}</div>}
          <div className="xsmall muted">Generated {dateTime(cs.created_at)} · <Link to={`/final-packs/${finalPackId}?view=html`}>Read it in the report (section 16)</Link></div>
        </div>
      );
    }}</Async>
  );
}

function Downloads({ finalPackId }: { finalPackId: string }) {
  const data = useData();
  const kinds = ["json", "html", "pdf"] as const;
  return <>{kinds.map((k, i) => {
    const url = data.finalPackFileUrl(finalPackId, k);
    return <span key={k}>{i > 0 ? " · " : ""}{url ? <a href={url} target="_blank" rel="noopener noreferrer">{k.toUpperCase()}</a> : <Link to={`/final-packs/${finalPackId}?view=${k}`}>{k.toUpperCase()}</Link>}</span>;
  })}</>;
}

function History({ detail, packs, finals }: { detail: PeriodDetail | null; packs: PeriodPackRef[]; finals: FinalPackListItem[] }) {
  const events = useMemo(() => {
    const out: Array<{ at: string; what: ReactNode; who?: string }> = [];
    for (const b of detail?.batches ?? []) {
      const docs = (detail?.documents ?? []).filter((d) => d.batch_id === b.batch_id);
      const kinds = [...new Set(docs.map((d) => d.submission_kind ?? "INITIAL"))];
      out.push({ at: b.created_at, who: b.created_by, what: <>{b.origin === "UPLOAD" ? "Upload" : "Registered dataset"} <Link className="id" to={`/uploads/${b.batch_id}`}>{b.batch_id}</Link>: {b.file_count} file(s)
        {kinds.some((k) => k !== "INITIAL") ? ` · ${kinds.map((k) => k === "ADDITIONAL_EVIDENCE" ? "additional evidence" : k === "CORRECTION" ? "correction" : "source documents").join(", ")}` : ""} · <StatusBadge status={b.status} /></> });
      for (const d of docs.filter((x) => x.replaces_document_id)) {
        out.push({ at: d.created_at, who: b.created_by, what: <>Correction <span className="mono">{d.document_id}</span> ({d.original_filename}) replaces <span className="mono">{d.replaces_document_id}</span>; the earlier version is kept</> });
      }
    }
    for (const p of packs) out.push({ at: p.registered_at, what: <>Deterministic pack <Link className="id" to={`/packs/${p.pack_id}`}>{p.pack_id}</Link> registered</> });
    for (const f of finals) out.push({ at: f.generated_at, what: <>Final audit pack <Link className="id" to={`/final-packs/${f.final_pack_id}`}>{f.final_pack_id}</Link> v{f.version} published</> });
    return out.sort((a, b) => (a.at < b.at ? 1 : -1));
  }, [detail, packs, finals]);
  if (!events.length) return <Empty>No history yet.</Empty>;
  return (
    <table className="dtable dtable--compact"><tbody>{events.map((e, i) => (
      <tr key={i}><td className="nowrap xsmall muted">{dateTime(e.at)}</td><td className="small">{e.what}{e.who ? <span className="xsmall muted"> · {e.who}</span> : null}</td></tr>
    ))}</tbody></table>
  );
}

function RenameTitle({ periodId, title, onDone }: { periodId: string; title: string; onDone: () => void }) {
  const data = useData();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(title);
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  if (!data.capabilities.upload) return null;
  if (!editing) return <div className="small">Report title: <span className="strong">{title || "not set"}</span> · <button className="link-btn" onClick={() => { setValue(title); setEditing(true); }}>Change title</button>
    <span className="xsmall muted"> (the period ID {periodId} and its packs do not change)</span></div>;
  const save = async () => {
    setBusy(true);
    setError(undefined);
    try { await data.renamePeriod(periodId, value.trim()); setEditing(false); onDone(); } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <div className="stack stack--sm">
      <label className="field"><span>Report title</span><input className="input" value={value} maxLength={120} onChange={(e) => setValue(e.target.value)} /></label>
      <div className="row"><button className="btn btn--primary btn--sm" disabled={busy || value.trim().length < 3} onClick={save}>Save title</button>
        <button className="btn btn--sm btn--ghost" onClick={() => setEditing(false)}>Cancel</button></div>
      {error ? <Notice tone="bad">{errorMessage(error)}</Notice> : null}
    </div>
  );
}

/** Add a document to this month (the period comes from the workspace; it is never asked again). Every file is stored as a new
 * immutable original and goes through the existing identification, validation and duplicate checks; it is not processed here. */
export function AddSupportingDocument({ periodId, documents, publishedFinalPacks }: { periodId: string; documents: SourceDocument[]; publishedFinalPacks: string[] }) {
  const data = useData();
  const navigate = useNavigate();
  const [kind, setKind] = useState<Exclude<SubmissionKind, "INITIAL">>("ADDITIONAL_EVIDENCE");
  const [reason, setReason] = useState("");
  const [replaces, setReplaces] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const correction = kind === "CORRECTION";
  const ready = reason.trim().length >= 3 && files.length > 0 && (!correction || (files.length === 1 && replaces));
  const submit = async () => {
    setBusy(true);
    setError(undefined);
    try {
      const b = await data.uploadDocuments(periodId, files, { kind, reason: reason.trim(), replacesDocumentId: correction ? replaces : undefined });
      navigate(`/uploads/${b.batch.batch_id}`);
    } catch (e) { setError(e); setBusy(false); }
  };
  return (
    <div className="panel">
      <div className="panel__head"><div><h3 className="panel__title">Add Supporting Document · {periodLabel(periodId)}</h3>
        <div className="panel__sub">Recorded with the reason, uploader, time and SHA-256. Originals are never overwritten.</div></div></div>
      <div className="panel__body stack stack--sm">
        {publishedFinalPacks.length > 0 && <Notice tone="info">This month has a published final audit pack ({publishedFinalPacks.join(", ")}). New documents are recorded as received after
          publication; the published pack is not changed and will show as pending reassessment.</Notice>}
        <div className="form-grid">
          <label className="field"><span>Type</span>
            <select className="select" value={kind} onChange={(e) => { setKind(e.target.value as typeof kind); setFiles([]); }}>
              <option value="ADDITIONAL_EVIDENCE">Additional evidence</option><option value="CORRECTION">Correction / replacement of an earlier document</option></select></label>
          {correction && <label className="field"><span>Replaces</span>
            <select className="select" value={replaces} onChange={(e) => setReplaces(e.target.value)}>
              <option value="">Select the earlier document…</option>
              {documents.map((d) => <option key={d.document_id} value={d.document_id}>{d.original_filename} · {d.evidence_id ?? "unidentified"} · {d.document_id}</option>)}</select></label>}
        </div>
        {correction && documents.length === 0 && <p className="xsmall muted">There is no earlier document in this month to correct.</p>}
        <label className="field"><span>Reason for adding</span>
          <textarea className="input" rows={2} value={reason} maxLength={2000} placeholder="e.g. Bank confirmation for 16 Feb received from the bank on 4 Nov" onChange={(e) => setReason(e.target.value)} /></label>
        <DropZone onFiles={(f) => setFiles((x) => (correction ? f.slice(0, 1) : [...x, ...f]))} />
        {files.length > 0 && <ul className="file-list" aria-label="Selected supporting files">{files.map((f, i) => (
          <li key={`${f.name}-${i}`}><span><code>{f.name}</code> <span className="xsmall muted">{kb(f.size)}</span></span>
            <button className="link-btn" onClick={() => setFiles((x) => x.filter((_, j) => j !== i))} aria-label={`Remove ${f.name}`}>Remove</button></li>))}</ul>}
        <button className="btn btn--primary" disabled={busy || !ready} onClick={submit}>{busy ? "Uploading…" : "Upload and validate"}</button>
        {error ? <Notice tone="bad" title="Upload failed">{errorMessage(error)}</Notice> : null}
        <p className="xsmall muted">The upload is validated like any other (identification by content, dates, duplicates); you then review and confirm the batch. Nothing is processed or investigated automatically.</p>
      </div>
    </div>
  );
}
