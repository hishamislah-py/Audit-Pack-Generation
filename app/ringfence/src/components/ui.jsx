// Ringfence design-system primitives (ported from the design bundle as React components: class-based, no inline styles).
import React, { useEffect, useRef } from "react";

const P = {
  chevronRight: <path d="M6 3.5 10.5 8 6 12.5" />,
  chevronDown: <path d="M3.5 6 8 10.5 12.5 6" />,
  lock: <><rect x="3.25" y="7" width="9.5" height="6.75" rx="1.25" /><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" /></>,
  check: <path d="M3.25 8.5 6.5 11.75 12.75 4.75" />,
  x: <path d="M4 4l8 8M12 4l-8 8" />,
  alert: <><path d="M8 2.25 14.25 13.25H1.75z" /><path d="M8 6.5v3" /><path d="M8 11.5v.01" strokeWidth="2" /></>,
  info: <><circle cx="8" cy="8" r="5.75" /><path d="M8 7.25v4" /><path d="M8 4.9v.01" strokeWidth="2" /></>,
  inbox: <><path d="M2.25 9.25 3.75 3.25h8.5l1.5 6v4.5H2.25z" /><path d="M2.25 9.25h3.5l.75 1.5h3l.75-1.5h3.5" /></>,
  play: <path d="M4.75 3.25v9.5L12.5 8z" />,
  refresh: <><path d="M13.25 8a5.25 5.25 0 1 1-1.54-3.71" /><path d="M13.25 2.25v3h-3" /></>,
  upload: <path d="M8 10.75V2.75M4.75 6 8 2.75 11.25 6M2.75 13.25h10.5" />,
  archive: <><rect x="2.25" y="2.75" width="11.5" height="10.5" rx="1" /><path d="M2.25 6h11.5M7.25 6v1.25M8.75 7.25v1.25M7.25 8.5v1.25M8.75 9.75V11" /></>,
  plus: <path d="M8 3v10M3 8h10" />,
  clock: <><circle cx="8" cy="8" r="5.75" /><path d="M8 4.75V8l2.25 1.5" /></>,
  pause: <path d="M5.5 3.5v9M10.5 3.5v9" />,
  building: <path d="M2 13.75h12M3.25 13.75V2.75h6.5v11M9.75 6.25h3v7.5M5.25 5h2.5M5.25 7.5h2.5M5.25 10h2.5" />,
  activity: <path d="M1.75 8h2.75l2-4.75 3 9.5 2-4.75h2.75" />,
  seal: <><circle cx="8" cy="6.5" r="4.25" /><path d="M5.75 10.25 4.75 14.25 8 12.75l3.25 1.5-1-4" /></>,
};
export function Icon({ name, size = 16 }) {
  return <svg className="rf-icon" width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor"
    strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{P[name]}</svg>;
}

const G = {
  pending: <circle cx="6" cy="6" r="4.25" fill="none" stroke="currentColor" strokeWidth="1.5" />,
  progress: <><circle cx="6" cy="6" r="4.25" fill="none" stroke="currentColor" strokeOpacity=".28" strokeWidth="1.5" /><path d="M6 1.75A4.25 4.25 0 0 1 10.25 6" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></>,
  review: <path d="M6 .9 11.1 6 6 11.1.9 6z" fill="currentColor" />,
  warning: <><path d="M6 .9l5.4 9.6H.6z" fill="currentColor" /><path d="M6 4.5v2.6" stroke="#fff" strokeWidth="1.3" strokeLinecap="round" /><circle cx="6" cy="8.85" r=".75" fill="#fff" /></>,
  danger: <><circle cx="6" cy="6" r="5.1" fill="currentColor" /><path d="M4.15 4.15l3.7 3.7M7.85 4.15l-3.7 3.7" stroke="#fff" strokeWidth="1.4" strokeLinecap="round" /></>,
  success: <><circle cx="6" cy="6" r="5.1" fill="currentColor" /><path d="M3.6 6.15l1.65 1.65L8.5 4.4" fill="none" stroke="#fff" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" /></>,
  na: <><circle cx="6" cy="6" r="4.25" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M3.9 6h4.2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></>,
  sealed: <><rect x="1.9" y="5.1" width="8.2" height="5.9" rx="1.2" fill="currentColor" /><path d="M3.85 5.1V3.95a2.15 2.15 0 0 1 4.3 0V5.1" fill="none" stroke="currentColor" strokeWidth="1.3" /></>,
  waiting: <><circle cx="6" cy="6" r="4.25" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M6 3.6V6l1.6 1.05" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" /></>,
  resubmit: <><path d="M10 3.95A4.3 4.3 0 1 0 10.3 6.6" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /><path d="M10.5 1.4v2.9H7.6" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></>,
  dot: <circle cx="6" cy="6" r="3" fill="currentColor" />,
};
export function Glyph({ name, size = 12, still }) {
  return <svg className={"rf-glyph" + (name === "progress" && !still ? " rf-glyph--spin" : "")} width={size} height={size}
    viewBox="0 0 12 12" aria-hidden="true">{G[name]}</svg>;
}

export function Mark({ size = 22 }) {
  return <svg className="rf-mark" width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
    <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="2.6" strokeDasharray="7.22 2.2"
      strokeDashoffset="-1.1" transform="rotate(-90 12 12)" />
    <rect x="8.6" y="8.6" width="6.8" height="6.8" rx="1.3" fill="currentColor" /></svg>;
}

// One registry: backend state -> label, tone, glyph (presentation only; the state itself always comes from the API).
const S = {};
const def = (k, label, tone, glyph, e) => { S[k] = { label, tone, glyph, enumName: e || null }; };
def("WAITING", "Waiting", "neutral", "pending", "WAITING");
def("IN_PROGRESS", "In progress", "progress", "progress", "IN_PROGRESS");
def("DEFERRING", "Deferring…", "attention", "waiting", "IN_PROGRESS");
def("PENDING", "Pending", "waiting", "waiting", "PENDING");
def("COMPLETED", "Completed", "success", "success", "COMPLETED");
def("RUN_PROCESSING", "Running", "progress", "progress", "PROCESSING");
def("RUN_COMPLETED", "Completed", "success", "success", "COMPLETED");
def("RUN_FAILED", "Failed", "danger", "danger", "FAILED");
def("VALIDATED", "Validated", "success", "success", "VALIDATED");
def("ACTIVE", "Active · locked", "sealed", "sealed", "ACTIVE");
def("REVIEW_REQUIRED", "Review required", "attention", "review", "REVIEW_REQUIRED");
def("RESUBMISSION_REQUIRED", "Correction required", "attention", "resubmit", "RESUBMISSION_REQUIRED");
def("FAILED_VALIDATION", "Failed validation", "danger", "danger", "FAILED_VALIDATION");
def("REJECTED", "Rejected · correction required", "danger", "resubmit", "REJECTED");
def("SUPERSEDED", "Superseded", "neutral", "na", "SUPERSEDED");
def("RECEIVED", "Received", "neutral", "pending", "RECEIVED");
def("MISSING", "Missing", "danger", "danger");
def("PASS", "PASS", "success", "success", "PASS");
def("FAIL", "FAIL", "danger", "danger", "FAIL");
def("CLEAN", "Clean", "success", "success", "CLEAN");
def("EXCEPTIONS_OPEN", "Exceptions open", "danger", "danger", "EXCEPTIONS_OPEN");
def("EVIDENCE_INCOMPLETE", "Evidence incomplete", "attention", "warning", "EVIDENCE_INCOMPLETE");
def("D_OPEN", "Decision needed", "attention", "review");
def("D_DONE", "Decided", "success", "success");
def("RECOGNISED", "Recognised", "neutral", "na");
def("INTERRUPTED", "Interrupted", "danger", "danger", "INTERRUPTED");
def("RECON_RUNNING", "Running", "progress", "progress", "RUNNING");
def("RECON_COMPLETED", "Completed", "success", "success", "COMPLETED");
def("RECON_FAILED", "Failed", "danger", "danger", "FAILED");
def("RECON_NOT_RUN", "Not run", "neutral", "pending", "NOT_RUN");
def("INSUFFICIENT_EVIDENCE", "INSUFFICIENT_EVIDENCE", "attention", "warning", "INSUFFICIENT_EVIDENCE");
def("NOT_APPLICABLE", "NOT_APPLICABLE", "neutral", "na", "NOT_APPLICABLE");
export const state = (k) => S[k] || { label: k, tone: "neutral", glyph: "pending", enumName: k };

export function Pill({ k, label, large, count }) {
  const s = state(k);
  return <span className={`rf-pill rf-pill--${s.tone}${large ? " rf-pill--lg" : ""}`} title={s.enumName || undefined}>
    <Glyph name={s.glyph} /><span>{label || s.label}</span>{count != null && <span className="rf-pill__count">{count}</span>}</span>;
}
export const Enum = ({ children }) => <code className="rf-enum">{children}</code>;
export const Tag = ({ kind, children, title }) => <span className={"rf-tag" + (kind ? " rf-tag--" + kind : "")} title={title}>{children}</span>;

export function Notice({ tone = "info", title, children, actions }) {
  const icon = { info: "info", success: "check", attention: "alert", danger: "alert", locked: "lock" }[tone] || "info";
  return <div className={`rf-notice rf-notice--${tone}`} role={tone === "danger" ? "alert" : "note"}>
    <Icon name={icon} /><div>{title && <div className="rf-notice__title">{title}</div>}
      {children && <div className="rf-notice__body">{children}</div>}</div>
    {actions && <div className="rf-notice__actions">{actions}</div>}</div>;
}

export function Panel({ title, sub, actions, children, foot, flush, id }) {
  return <section className="rf-panel" id={id}>
    {title && <header className="rf-panel__head"><div><h3 className="rf-panel__title">{title}</h3>
      {sub && <div className="rf-panel__sub">{sub}</div>}</div><span className="rf-spacer" />{actions}</header>}
    <div className={"rf-panel__body" + (flush ? " rf-panel__body--flush" : "")}>{children}</div>
    {foot && <footer className="rf-panel__foot">{foot}</footer>}</section>;
}

export function Button({ children, variant = "secondary", size, icon, busy, disabled, onClick, title, id, type }) {
  return <button type={type || "button"} id={id} title={title} className={`rf-btn rf-btn--${variant}${size ? " rf-btn--" + size : ""}${busy ? " is-loading" : ""}`}
    disabled={disabled || busy} aria-disabled={disabled || busy || undefined} onClick={onClick}>
    {busy ? <span className="rf-spinner" aria-hidden="true" /> : icon && <Icon name={icon} />}<span>{children}</span></button>;
}

// A backend-driven action: enabled/disabled and the reason come from case.actions[key]
export function Action({ spec, children, variant, icon, onClick, busy, id }) {
  const a = spec || { enabled: false, reason: "not available" };
  return <div className="rf-action" id={id}><Button variant={variant} icon={icon} busy={busy} disabled={!a.enabled}
    onClick={onClick}>{children}</Button>
    {!a.enabled && a.reason && <div className="rf-action__reason"><Icon name="info" size={14} /><span>{a.reason}</span></div>}</div>;
}

export function Dialog({ title, eyebrow, children, onClose, foot }) {
  const ref = useRef(null);
  useEffect(() => {
    const k = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", k);
    ref.current && ref.current.focus();
    return () => document.removeEventListener("keydown", k);
  }, []);
  return <div className="rf-scrim rf-scrim--fixed" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
    <div className="rf-dialog" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={ref}>
      <header className="rf-dialog__head">{eyebrow && <div className="rf-dialog__eyebrow">{eyebrow}</div>}
        <h2 className="rf-dialog__title">{title}</h2></header>
      <div className="rf-dialog__body">{children}</div>
      <footer className="rf-dialog__foot">{foot}</footer></div></div>;
}

export function KV({ pairs, cols }) {
  return <dl className={"rf-kv" + (cols ? " rf-kv--cols" : "")}>{pairs.map(([k, v]) => cols
    ? <div key={k}><dt>{k}</dt><dd>{v}</dd></div> : <React.Fragment key={k}><dt>{k}</dt><dd>{v}</dd></React.Fragment>)}</dl>;
}

export function Hash({ sha }) {
  if (!sha) return null;
  return <span className="rf-hash" title={"SHA-256 " + sha}><span className="rf-hash__algo">sha256</span>
    <span className="rf-hash__val">{sha.slice(0, 8)}…{sha.slice(-6)}</span></span>;
}

export const when = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
};
export const bytes = (n) => n == null ? "—" : n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(2)} MB`;

export function ErrorBox({ error }) {
  if (!error) return null;
  return <Notice tone="danger" title={error.code || "Error"}>{error.message}</Notice>;
}

// ---------------------------------------------------------------------------------------------- case steps
const STEP_LABEL = { smart_parser: "Smart Parser", review: "Review", validation: "Validation", activation: "Activation",
                     reconciliation: "Reconciliation" };
const STEP_GLYPH = { done: ["success", "success"], current: ["progress", "progress"], attention: ["review", "attention"],
                     failed: ["danger", "danger"], paused: ["waiting", "neutral"], todo: ["pending", "neutral"] };
export function StepStrip({ steps, compact }) {
  return <ol className={"rf-steps" + (compact ? " rf-steps--compact" : "")} aria-label="Case progress">
    {(steps || []).map((s) => {
      const [g, tone] = STEP_GLYPH[s.state] || STEP_GLYPH.todo;
      return <li key={s.key} className={"rf-step is-" + s.state} title={`${STEP_LABEL[s.key]}: ${s.state}`}>
        <span className={"rf-tone-" + tone}><Glyph name={g} still={s.state !== "current"} /></span>
        {!compact && <span>{STEP_LABEL[s.key]}</span>}</li>;
    })}</ol>;
}

export function Drawer({ title, sub, onClose, children }) {
  const ref = useRef(null);
  useEffect(() => {
    const k = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", k);
    ref.current && ref.current.focus();
    return () => document.removeEventListener("keydown", k);
  }, []);
  return <div className="rf-scrim rf-scrim--fixed rf-scrim--drawer" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
    <aside className="rf-drawer rf-drawer--fixed" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={ref}>
      <header className="rf-drawer__head"><div><h2 className="rf-dialog__title">{title}</h2>{sub && <div className="rf-muted rf-small">{sub}</div>}</div>
        <span className="rf-spacer" /><Button size="sm" onClick={onClose} id="drawer-close">Close</Button></header>
      <div className="rf-drawer__body">{children}</div></aside></div>;
}

// A refused mutation: the backend's code and message, "Nothing was changed" for every 4xx, and a reload hint when stale.
export function MutationError({ error, onReload }) {
  if (!error) return null;
  return <Notice tone="danger" title={error.code === "CASE_CHANGED" ? "This case changed" : (error.code || "Error")}
    actions={error.code === "CASE_CHANGED" && onReload ? <Button size="sm" onClick={onReload}>Reload</Button> : null}>
    {error.message}{error.nothingChanged ? " Nothing was changed." : ""}</Notice>;
}

export function Skeleton({ lines = 3 }) {
  return <div className="rf-stack rf-stack--2" aria-busy="true">{Array.from({ length: lines }).map((_, i) =>
    <div key={i} className="rf-skel" />)}</div>;
}

export function Empty({ title, children }) {
  return <div className="rf-empty"><div className="rf-empty__title">{title}</div>{children && <div className="rf-muted">{children}</div>}</div>;
}

// Poll fn every `ms` while `active` is true (and once on mount / when deps change). Never advances anything itself.
export function usePolling(fn, ms, active, deps = []) {
  const saved = useRef(fn);
  saved.current = fn;
  useEffect(() => { saved.current(); }, deps);
  useEffect(() => {
    if (!active) return undefined;
    const t = setInterval(() => saved.current(), ms);
    return () => clearInterval(t);
  }, [active, ms, ...deps]);
}
