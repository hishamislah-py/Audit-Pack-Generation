import { Link, useParams, useSearchParams } from "react-router-dom";
import { Async, Kpis, Loading, Panel, StatusBadge, Tabs } from "../components/common";
import { usePage } from "../components/layout/workContext";
import {
  AccountsTable, DifferencesTable, ExceptionRegisterTable, ExternalReconciliationTable, InternalReconciliationTable, SourceInventoryTable,
} from "../components/pack";
import { useData } from "../data/DataProvider";
import { PACK_KIND_LABEL, packKind, periodLabel } from "../data/periods";
import { useApi } from "../hooks/useApi";
import { date, shortHash } from "../lib/format";

type ReconTab = "internal" | "external" | "differences";
const RECON_SUB: Record<ReconTab, string> = {
  internal: "Safeguarding requirement vs safeguarding resources, per currency and reconciliation day",
  external: "The firm's ledger balance vs the bank balance, per safeguarding account and reconciliation day",
  differences: "Every non-zero difference or FAIL outcome from either view; nothing is netted or recalculated",
};

export function PackDetailPage() {
  const { packId = "" } = useParams();
  const data = useData();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("recon") as ReconTab) || "external";
  const pack = useApi(() => data.pack(packId), [data, packId]);
  const recon = useApi(() => data.reconciliation(packId), [data, packId]);
  const sources = useApi(() => data.sources(packId), [data, packId]);
  const exceptions = useApi(() => data.exceptions(packId), [data, packId]);
  const investigations = useApi(() => data.packInvestigations(packId), [data, packId]);
  const periodId = pack.data?.summary.period_id ?? undefined;
  const kind = pack.data ? packKind(pack.data.summary) : undefined;
  usePage([{ label: "Monthly reports", to: "/reports" }, { label: periodLabel(periodId), to: periodId ? `/reports/${periodId}` : "/reports" },
    { label: kind === "DEMONSTRATION_SCENARIO" ? `Scenario ${pack.data?.summary.scenario_id}` : packId }],
    { packId, ...(periodId ? { periodId } : {}) });

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="eyebrow">{kind ? PACK_KIND_LABEL[kind] : "Deterministic reconciliation pack"} · {periodLabel(periodId)} · immutable</div>
          <h1 className="page-title">{packId}</h1>
          {pack.data && <p className="page-sub">{kind === "DEMONSTRATION_SCENARIO" ? <>Demonstration scenario {pack.data.metadata.source_dataset.scenario_id} · </> : null}
            {pack.data.metadata.source_dataset.scenario_name} · a deterministic pack, not a final audit report</p>}
        </div>
        <div className="actions">
          <Link className="btn" to={`/packs/${packId}/workspace`}>Investigate exceptions</Link>
          <Link className="btn btn--primary" to={`/packs/${packId}/review`}>Open final review</Link>
        </div>
      </div>

      <Async state={pack} label="Loading pack…">{(p) => (
        <Kpis items={[
          { label: "Reconciliation period", value: periodLabel(p.summary.period_id), note: `${date(p.summary.reporting_period.start)} – ${date(p.summary.reporting_period.end)}`, tone: "sm" },
          { label: "Currencies", value: p.metadata.currency_scope.join(", "), tone: "sm" },
          { label: "Accounts", value: p.metadata.accounts.length, tone: "sm" },
          { label: "Engine status", value: <StatusBadge status={p.summary.engine_case_status} />, note: `Controls: ${Object.entries(p.summary.outcomes).map(([k, v]) => `${k} ${v}`).join(" · ")}` },
          { label: "Evidence", value: <StatusBadge status={p.summary.evidence_completeness} />, note: `${p.summary.missing_evidence_items} missing item(s)` },
          { label: "Exceptions", value: `${p.summary.exceptions.total}`, note: `${p.summary.exceptions.open} unresolved`, tone: p.summary.exceptions.open ? "bad" : undefined },
          { label: "Pack content hash", value: shortHash(p.summary.pack_content_sha256, 16), note: "verified on load", tone: "mono" },
        ]} />
      )}</Async>

      <div className="stack">
        <Panel title="Currencies and accounts" sub="Bank balance as reported on the last external reconciliation day" flush>
          {recon.data ? <AccountsTable accounts={recon.data.accounts} external={recon.data.external_by_account_day} /> : <Loading />}
        </Panel>
        <Panel title="Source document inventory" sub="Files the deterministic engine read for this pack, with their SHA-256"
          actions={<Link className="btn btn--sm" to="/upload">Add documents for a new period</Link>} flush
          footer={sources.data ? <span className="small">{sources.data.missing_evidence.statement}</span> : undefined}>
          <Async state={sources}>{(s) => <SourceInventoryTable sources={s} />}</Async>
        </Panel>
      </div>

      <Panel title="Reconciliation results" sub={RECON_SUB[tab]} flush>
        <Tabs label="Reconciliation view" value={tab} onChange={(k) => setParams({ recon: k }, { replace: true })}
          tabs={[{ key: "external", label: "External reconciliation", count: recon.data?.external_by_account_day.length },
            { key: "internal", label: "Internal reconciliation", count: recon.data?.internal_by_currency_day.length },
            { key: "differences", label: "Reconciliation differences" }]} />
        <Async state={recon}>{(r) => (
          tab === "internal" ? <InternalReconciliationTable rows={r.internal_by_currency_day} />
            : tab === "external" ? <ExternalReconciliationTable rows={r.external_by_account_day} />
              : <DifferencesTable internal={r.internal_by_currency_day} external={r.external_by_account_day} />
        )}</Async>
      </Panel>

      <Panel title="Exception register" meta={exceptions.data ? `${exceptions.data.length} exception(s) · all unresolved · exceptions are not resolved by this application` : undefined} flush>
        <Async state={exceptions}>{(x) => <ExceptionRegisterTable packId={packId} exceptions={x} investigations={investigations.data} />}</Async>
      </Panel>
    </div>
  );
}
