// Shared presentational components. No data access and no visual values here: classes come from styles/components.css.
import { Fragment, useEffect, type ReactNode } from "react";
import { ApiError, errorMessage } from "../../api/client";
import type { ApiState } from "../../hooks/useApi";
import { isNonZero, money } from "../../lib/format";

export type Tone = "ok" | "warn" | "bad" | "info" | "neutral" | "mock";

// One mapping from backend status values to tones, used everywhere.
const TONES: Record<string, Tone> = {
  PASS: "ok", COMPLETED: "ok", VALID: "ok", GENERATED: "ok", COMPLETE: "ok", PRESENT: "ok", INCLUDED: "ok", ELIGIBLE: "ok", CLEAN: "ok",
  VERIFIED: "ok", AVAILABLE: "ok",
  QUEUED: "info", RUNNING: "info", OPEN: "info", GENERATING: "info", PREVIEW: "info", OPEN_FOR_UPLOAD: "info", TIMING_EVIDENCED: "info",
  ON_HOLD: "warn", INTERRUPTED: "warn", HYPOTHESIS: "warn", INSUFFICIENT_EVIDENCE: "warn", PARTIALLY_SUFFICIENT: "warn",
  EVIDENCE_INCOMPLETE: "warn", INCOMPLETE: "warn", NOT_EVIDENCED: "warn", UNAVAILABLE: "warn", High: "warn", DUPLICATE: "warn",
  WRONG_PERIOD: "warn", TIMING_PARTIAL: "warn", TIMING_UNVERIFIABLE: "warn",
  FAIL: "bad", FAILED: "bad", REJECTED: "bad", UNRESOLVED: "bad", GENERATION_FAILED: "bad", INELIGIBLE: "bad", CONFLICTING_EVIDENCE: "bad",
  EXCEPTIONS_OPEN: "bad", FAILURES_PRESENT: "bad", Critical: "bad", MISSING: "bad", UNKNOWN_DOCUMENT: "bad", UNSUPPORTED_TYPE: "bad",
  EMPTY_FILE: "bad",
  // monthly archive (Phase 4)
  SUCCEEDED: "ok", CONFIRMED: "ok", PROCESSED: "ok", INCLUDE: "ok", RESULTS_AND_FINAL_PACK: "ok",
  VALIDATED: "info", PROCESSING: "info", DOCUMENTS_UPLOADED: "info", AWAITING_UPLOAD: "info", INFO: "info", DOCUMENTS_ONLY: "info",
  RESULTS_NO_FINAL_PACK: "info", DOCUMENTS_NO_RESULTS: "info", ARCHIVED_SCENARIO: "neutral",
  WARNING: "warn", WARNINGS: "warn", EXCLUDE: "warn", BLOCKED: "warn", DECISION_REQUIRED: "warn",
  ERROR: "bad", INVALID: "bad", PROCESSING_FAILED: "bad",
  SIMULATED: "mock", MOCK: "mock",
};

export function toneFor(status: string | null | undefined): Tone {
  return (status && TONES[status]) || "neutral";
}

export function StatusBadge({ status, label, tone }: { status: string | null | undefined; label?: ReactNode; tone?: Tone }) {
  if (!status && !label) return null;
  return <span className={`badge badge--${tone ?? toneFor(status)}`}>{label ?? status!.replace(/_/g, " ")}</span>;
}

/** Exceptions are never resolved by this application. */
export function UnresolvedTag() {
  return <span className="tag tag--unresolved">Unresolved</span>;
}

export function DebitCredit({ value }: { value: string | undefined }) {
  if (!value) return <span className="faint">—</span>;
  const cls = value === "D" || value === "C" ? ` dc--${value}` : "";
  return <span className={`dc${cls}`} title={value === "D" ? "Debit" : value === "C" ? "Credit" : value}>{value.replace(/_/g, " ")}</span>;
}

export function Amount({ value, currency, flag }: { value: string | null | undefined; currency?: string | null; flag?: boolean }) {
  return <span className={flag && isNonZero(value) ? "amount-bad" : undefined}>{money(value, currency)}</span>;
}

export function Panel({ title, sub, meta, actions, children, flush, footer, id, className }: {
  title?: ReactNode; sub?: ReactNode; meta?: ReactNode; actions?: ReactNode; children: ReactNode; flush?: boolean; footer?: ReactNode;
  id?: string; className?: string;
}) {
  return (
    <section className={`panel${className ? ` ${className}` : ""}`} id={id}>
      {(title || meta || actions) && (
        <header className="panel__head">
          <div>
            {typeof title === "string" ? <h2 className="panel__title">{title}</h2> : title}
            {sub && <div className="panel__sub">{sub}</div>}
          </div>
          {(meta || actions) && <div className="row">{meta && <span className="panel__meta">{meta}</span>}{actions}</div>}
        </header>
      )}
      {flush ? children : <div className="panel__body">{children}</div>}
      {footer && <div className="panel__foot">{footer}</div>}
    </section>
  );
}

export function Kpis({ items }: { items: Array<{ label: string; value: ReactNode; note?: ReactNode; tone?: "bad" | "sm" | "mono" }> }) {
  return (
    <div className="kpis">
      {items.map((k) => (
        <div className="kpi" key={k.label}>
          <span className="kpi__label">{k.label}</span>
          <span className={`kpi__value${k.tone ? ` kpi__value--${k.tone}` : ""}`}>{k.value}</span>
          {k.note && <span className="kpi__note">{k.note}</span>}
        </div>
      ))}
    </div>
  );
}

export function Notice({ tone = "info", title, children }: { tone?: Tone; title?: ReactNode; children?: ReactNode }) {
  return (
    <div className={`notice notice--${tone}`} role={tone === "bad" ? "alert" : "status"}>
      {title && <div className="notice__title">{title}</div>}
      {children}
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div className="state" role="status"><span className="spinner" /> {label}</div>;
}

export function Empty({ title, children, action }: { title?: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="state">
      <div className="state__mark" aria-hidden>—</div>
      {title && <div className="state__title">{title}</div>}
      {children && <div>{children}</div>}
      {action}
    </div>
  );
}

export function ErrorPanel({ error, onRetry, title = "The request failed" }: { error: unknown; onRetry?: () => void; title?: string }) {
  const code = error instanceof ApiError ? error.code : undefined;
  return (
    <Notice tone="bad" title={title}>
      <p>{errorMessage(error)}</p>
      {code && <p className="xsmall">Code: {code}{error instanceof ApiError && error.status ? ` · HTTP ${error.status}` : ""}</p>}
      {onRetry && <button className="btn btn--sm" onClick={onRetry}>Retry</button>}
    </Notice>
  );
}

export function Async<T>({ state, children, label }: { state: ApiState<T>; children: (data: T) => ReactNode; label?: string }) {
  if (state.loading && state.data === undefined) return <Loading label={label} />;
  if (state.error) return <ErrorPanel error={state.error} onRetry={state.reload} />;
  if (state.data === undefined) return <Loading label={label} />;
  return <>{children(state.data)}</>;
}

export function KeyValue({ items }: { items: Array<[string, ReactNode]> }) {
  return (
    <dl className="kv">
      {items.map(([k, v]) => (
        <Fragment key={k}><dt>{k}</dt><dd>{v ?? "—"}</dd></Fragment>
      ))}
    </dl>
  );
}

export function Tabs<K extends string>({ tabs, value, onChange, label }: {
  tabs: Array<{ key: K; label: string; count?: number }>; value: K; onChange: (k: K) => void; label: string;
}) {
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {tabs.map((t) => (
        <button key={t.key} role="tab" aria-selected={t.key === value} className={`tab${t.key === value ? " tab--active" : ""}`} onClick={() => onChange(t.key)}>
          {t.label}{t.count !== undefined && <span className="tab__count">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Modal({ title, children, footer, onClose, wide }: { title: string; children: ReactNode; footer: ReactNode; onClose: () => void; wide?: boolean }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="scrim" onClick={onClose}>
      <div className={`modal${wide ? " modal--wide" : ""}`} role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <div className="modal__body">
          <h3 className="modal__title">{title}</h3>
          {children}
        </div>
        <div className="modal__foot">{footer}</div>
      </div>
    </div>
  );
}

/** Marks content or an action as simulated (mock data source): visible, never implied to be real. */
export function SimulatedNotice({ children }: { children: ReactNode }) {
  return <Notice tone="mock" title="Simulated in this design phase">{children}</Notice>;
}
