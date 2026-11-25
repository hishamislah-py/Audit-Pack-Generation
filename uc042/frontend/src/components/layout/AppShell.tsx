import { useEffect } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useData } from "../../data/DataProvider";
import { periodFromPackId, periodLabel } from "../../data/periods";
import { useApi } from "../../hooks/useApi";
import { StatusBadge } from "../common";
import { useWork, WorkProvider } from "./workContext";

function NavItem({ n, label, to, disabled, end }: { n: string; label: string; to: string; disabled?: boolean; end?: boolean }) {
  return (
    <NavLink to={to} end={end} aria-disabled={disabled || undefined} title={disabled ? `${label}: select a month or open a pack first` : label}
      className={({ isActive }) => `nav-item${isActive && !disabled ? " nav-item--active" : ""}${disabled ? " nav-item--disabled" : ""}`}>
      <span className="nav-item__num">{n}</span><span className="nav-item__label">{label}</span>
    </NavLink>
  );
}

export function Sidebar() {
  const { work } = useWork();
  const { pathname } = useLocation();
  const pack = work.packId;
  // Without an open pack, the selected month's report lists its packs and exceptions (one click to the pack).
  const month = !pack && work.periodId ? `/reports/${work.periodId}` : null;
  return (
    <aside className="sidebar">
      <div className="sidebar__brand">
        <div className="brand-mark" aria-hidden>U</div>
        <div className="brand-text"><strong>UC-042 Audit</strong><span>RECONCILIATION · AUDIT PACKS</span></div>
      </div>
      <div className="nav-label">WORKFLOW</div>
      <nav aria-label="Workflow">
        <NavItem n="01" label="Dashboard" to="/" end />
        <NavItem n="R" label="Monthly reports" to={work.periodId && pathname.startsWith("/reports/") ? pathname : "/reports"} />
        <NavItem n="02" label="Reconciliation pack" to={pack ? `/packs/${pack}` : month ? `${month}#reconciliation` : "/"} disabled={!pack && !month} end />
        <NavItem n="03" label="Exceptions & investigation" to={pack ? `/packs/${pack}/workspace${work.exceptionId ? `/${work.exceptionId}` : ""}` : month ? `${month}#exceptions` : "/"} disabled={!pack && !month} />
        <NavItem n="04" label="Final review" to={work.reviewId ? `/reviews/${work.reviewId}` : pack ? `/packs/${pack}/review` : "/reviews"} />
        <NavItem n="05" label="Final audit pack" to={work.finalPackId ? `/final-packs/${work.finalPackId}` : "/final-packs"} end={!!work.finalPackId} />
      </nav>
      <div className="nav-label">RECORDS</div>
      <nav aria-label="Records">
        <NavLink to="/reviews" end className={({ isActive }) => `nav-item${isActive ? " nav-item--active" : ""}`}><span className="nav-item__num">R</span><span className="nav-item__label">All reviews</span></NavLink>
        <NavLink to="/final-packs" end className={({ isActive }) => `nav-item${isActive && pathname === "/final-packs" ? " nav-item--active" : ""}`}><span className="nav-item__num">F</span><span className="nav-item__label">All final packs</span></NavLink>
        <NavLink to="/upload" className={({ isActive }) => `nav-item${isActive ? " nav-item--active" : ""}`}><span className="nav-item__num">↑</span><span className="nav-item__label">Upload documents</span></NavLink>
      </nav>
      {pack && (
        <div className="nav-context">
          <span className="nav-context__label">CURRENT PACK</span>
          <code>{pack}</code>
          <span>{periodLabel(periodFromPackId(pack) ?? work.periodId)}</span>
        </div>
      )}
      <div className="sidebar__foot">Synthetic data only. Not a compliance opinion. AI content is an aid to human review.</div>
    </aside>
  );
}

export function TopBar() {
  const data = useData();
  const { work, setWork } = useWork();
  const navigate = useNavigate();
  const periods = useApi(() => data.periods(), [data]);
  const health = useApi(() => data.health(), [data]);
  // Before anything is selected, the newest period that has results or documents (from the backend), never a fixed month.
  useEffect(() => {
    if (work.periodId || !periods.data?.length) return;
    const first = periods.data.find((p) => p.state === "AVAILABLE") ?? periods.data.find((p) => p.state === "DOCUMENTS_ONLY") ?? periods.data[0];
    setWork({ periodId: first.period_id });
  }, [work.periodId, periods.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const options = periods.data ?? (work.periodId ? [{ period_id: work.periodId, label: periodLabel(work.periodId), state: "AVAILABLE" }] : []);
  const known = options.some((p) => p.period_id === work.periodId);
  const env = health.data?.environment;
  return (
    <header className="topbar">
      <div className="topbar__item">
        <label htmlFor="period-select">Period</label>
        <select id="period-select" className="period-select" value={work.periodId ?? ""}
          onChange={(e) => { setWork({ periodId: e.target.value, packId: undefined, exceptionId: undefined, reviewId: undefined, finalPackId: undefined }); navigate(`/reports/${e.target.value}`); }}>
          {!work.periodId && <option value="">Select a period…</option>}
          {work.periodId && !known && <option value={work.periodId}>{periodLabel(work.periodId)}</option>}
          {options.map((p) => (
            <option key={p.period_id} value={p.period_id}>{p.label}{p.state === "AVAILABLE" ? "" : p.state === "OPEN_FOR_UPLOAD" ? " (open for upload)" : p.state === "DOCUMENTS_ONLY" ? " (documents, no results)" : " (no data)"}</option>
          ))}
        </select>
      </div>
      <div className="topbar__spacer" />
      {env && <span className="env-tag topbar__hide-narrow" title={`Active data environment: ${env.label}. Database ${env.database ?? "none"} · packs ${env.packs_root}${env.storage_profiles?.length ? ` · storage profiles ${env.storage_profiles.join(", ")}` : ""}. Every reporting period of this database is listed.`}>
        Data: {env.label}</span>}
      {data.kind === "mock"
        ? <span className="badge badge--mock" title="Captured backend responses; actions are simulated in this browser session">MOCK DATA · SIMULATED ACTIONS</span>
        : health.error ? <StatusBadge status="FAILED" label="Backend unreachable" /> : <StatusBadge status="COMPLETED" label="Live backend" />}
      <span className="badge badge--warn topbar__hide-narrow">SYNTHETIC DATA</span>
      <div className="topbar__item topbar__hide-narrow">
        <span className="avatar" aria-hidden>{(health.data?.analyst_id ?? "A").slice(0, 2).toUpperCase()}</span>
        <span>{health.data?.analyst_id ?? "analyst"}</span>
      </div>
    </header>
  );
}

export function Breadcrumbs() {
  const { crumbs } = useWork();
  const all = [{ label: "Reconciliation", to: "/" }, ...crumbs];
  return (
    <nav className="crumbs" aria-label="Breadcrumb">
      {all.map((c, i) => (
        <span key={`${c.label}-${i}`} className="row">
          {i > 0 && <span aria-hidden>/</span>}
          {c.to && i < all.length - 1 ? <Link to={c.to}>{c.label}</Link> : <span className="crumbs__current">{c.label}</span>}
        </span>
      ))}
    </nav>
  );
}

export function AppShell() {
  return (
    <WorkProvider>
      <div className="shell">
        <Sidebar />
        <div className="main">
          <TopBar />
          <main className="content">
            <Breadcrumbs />
            <Outlet />
          </main>
        </div>
      </div>
    </WorkProvider>
  );
}
