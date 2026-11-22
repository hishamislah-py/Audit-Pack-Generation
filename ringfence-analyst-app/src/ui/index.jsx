/* Ringfence design system · React components.
   A port of the design-system helpers (components/bundle.js) with the same markup and class names,
   styled by styles/ringfence.css and styles/tokens.css. */
import React from 'react';
import { ICONS, GLYPHS, MARK, STATES, TAGS } from './design.js';

export const cx = (...a) => a.filter(Boolean).join(' ');
const svgHtml = (html) => ({ __html: html || '' });

export function Icon({ name, size = 16, className, style }) {
  return <svg className={cx('rf-icon', className)} width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={style} dangerouslySetInnerHTML={svgHtml(ICONS[name])} />;
}
export function Glyph({ name, size = 12, still, className }) {
  return <svg className={cx('rf-glyph', name === 'progress' && !still && 'rf-glyph--spin', className)} width={size} height={size} viewBox="0 0 12 12" aria-hidden="true" dangerouslySetInnerHTML={svgHtml(GLYPHS[name])} />;
}
export function Mark({ size = 22, className }) {
  return <svg className={cx('rf-mark', className)} width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" dangerouslySetInnerHTML={svgHtml(MARK)} />;
}
export const stateOf = (key) => STATES[key] || { key, label: key, tone: 'neutral', glyph: 'pending' };
export function Pill({ state, label, size, count, title }) {
  const s = stateOf(state);
  return <span className={cx('rf-pill', 'rf-pill--' + s.tone, size === 'lg' && 'rf-pill--lg')} title={title || s.enumName || undefined}><Glyph name={s.glyph} /><span>{label || s.label}</span>{count != null && <span className="rf-pill__count">{count}</span>}</span>;
}
export const Enum = ({ children }) => <code className="rf-enum">{children}</code>;
export function ToneGlyph({ state }) { const s = stateOf(state); return <span className={'rf-tone-' + s.tone}><Glyph name={s.glyph} /></span>; }
export function Tag({ kind, text }) { const t = TAGS[kind] || [kind, '', '']; return <span className={cx('rf-tag', t[1] && 'rf-tag--' + t[1])} title={t[2] || undefined}>{text || t[0]}</span>; }
export function Ref({ id, copy }) { return <span className="rf-id">{id}{copy && <CopyButton value={id} label="Copy reference" />}</span>; }
export function CopyButton({ value, label }) {
  const [done, setDone] = React.useState(false);
  return <button type="button" className={cx('rf-copy', done && 'is-copied')} aria-label={label} title={label} onClick={(e) => { e.stopPropagation(); try { navigator.clipboard && navigator.clipboard.writeText(value); } catch (x) { /* clipboard unavailable */ } setDone(true); setTimeout(() => setDone(false), 1200); }}><Icon name={done ? 'check' : 'copy'} size={12} /></button>;
}
export const shortHash = (sha) => (sha ? sha.slice(0, 8) + '…' + sha.slice(-6) : '');
export function Hash({ sha, full, copy = true }) {
  return <span className={cx('rf-hash', full && 'rf-hash--full')} title={'SHA-256 ' + sha}><span className="rf-hash__algo">sha256</span><span className="rf-hash__val">{full ? sha : shortHash(sha)}</span>{copy && <CopyButton value={sha} label="Copy SHA-256" />}</span>;
}
export function Money({ amount, ccy }) {
  const sym = { GBP: '£', EUR: '€', USD: '$' }[ccy] || '';
  const v = Math.abs(amount).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return <span className="rf-amount"><span className="rf-amount__ccy">{ccy}</span>{amount < 0 ? '−' : ''}{sym}{v}</span>;
}
export function Severity({ level }) { const l = String(level).toLowerCase(); return <span className={'rf-sev rf-sev--' + l}><span className="rf-sev__bars" aria-hidden="true"><i /><i /><i /></span>{String(level).toUpperCase()}</span>; }

export function Button({ children, variant = 'secondary', size, icon, iconRight, block, loading, disabled, kbd, describedBy, onClick, type = 'button', className, title, ...rest }) {
  return <button type={type} className={cx('rf-btn', 'rf-btn--' + variant, size && 'rf-btn--' + size, block && 'rf-btn--block', loading && 'is-loading', className)} disabled={disabled || loading} aria-disabled={disabled || loading || undefined} aria-describedby={describedBy} onClick={onClick} title={title} {...rest}>
    {loading ? <span className="rf-spinner" aria-hidden="true" /> : icon ? <Icon name={icon} /> : null}{children != null && children !== '' && <span>{children}</span>}{iconRight && <Icon name={iconRight} />}{kbd && !loading && <span className="rf-kbd">{kbd}</span>}
  </button>;
}
let rid = 0;
export function WithReason({ reason, children }) {
  const id = React.useMemo(() => 'why' + (++rid), []);
  return <div className="rf-action">{React.cloneElement(children, { describedBy: reason ? id : undefined })}{reason && <div className="rf-action__reason" id={id}><Icon name="info" size={14} /><span>{reason}</span></div>}</div>;
}
export function Panel({ title, sub, actions, flush, foot, className, children, ...rest }) {
  return <section className={cx('rf-panel', className)} {...rest}>
    {title && <header className="rf-panel__head"><div><h3 className="rf-panel__title">{title}</h3>{sub && <div className="rf-panel__sub">{sub}</div>}</div><span className="rf-spacer" />{actions}</header>}
    <div className={cx('rf-panel__body', flush && 'rf-panel__body--flush')}>{children}</div>
    {foot && <footer className="rf-panel__foot">{foot}</footer>}
  </section>;
}
export function KV({ pairs, cols }) {
  if (cols) return <dl className="rf-kv rf-kv--cols">{pairs.map((p, i) => <div key={i}><dt>{p[0]}</dt><dd>{p[1]}</dd></div>)}</dl>;
  return <dl className="rf-kv">{pairs.map((p, i) => <React.Fragment key={i}><dt>{p[0]}</dt><dd>{p[1]}</dd></React.Fragment>)}</dl>;
}
export function Notice({ tone = 'info', title, children, actions, compact }) {
  const icon = { info: 'info', success: 'check', attention: 'alert', danger: 'alert', locked: 'lock' }[tone] || 'info';
  return <div className={cx('rf-notice', 'rf-notice--' + tone, compact && 'rf-notice--compact')} role={tone === 'danger' ? 'alert' : 'note'}><Icon name={icon} /><div>{title && <div className="rf-notice__title">{title}</div>}{children && <div className="rf-notice__body">{children}</div>}</div>{actions ? <div className="rf-notice__actions">{actions}</div> : <span />}</div>;
}
// rows: [{ key, cells: {colKey: node}, onClick, selected, className, group }]
export function Table({ columns, rows, dense, caption, maxHeight }) {
  return <div className="rf-table-wrap" style={maxHeight ? { maxHeight } : undefined}><table className={cx('rf-table', dense && 'rf-table--dense')}>
    {caption && <caption className="rf-sr">{caption}</caption>}
    <thead><tr>{columns.map((c) => <th key={c.key} className={c.cls} style={c.width ? { width: c.width } : undefined}>{c.label}</th>)}</tr></thead>
    <tbody>{rows.map((r, i) => r.group != null
      ? <tr key={'g' + i} className="is-group"><td colSpan={columns.length}>{r.group}</td></tr>
      : <tr key={r.key || i} className={cx(r.onClick && 'is-clickable', r.selected && 'is-selected', r.className)} onClick={r.onClick} tabIndex={r.onClick ? 0 : undefined} onKeyDown={r.onClick ? (e) => { if (e.key === 'Enter') r.onClick(e); } : undefined} aria-selected={r.selected || undefined}>
        {columns.map((c) => <td key={c.key} className={c.cls}>{r.cells[c.key] == null ? <span className="rf-muted">—</span> : r.cells[c.key]}</td>)}</tr>)}</tbody>
  </table></div>;
}
export function Tabs({ items, active, onChange }) {
  return <div className="rf-tabs" role="tablist">{items.map(([id, label]) => <button key={id} type="button" role="tab" aria-selected={id === active} className={cx('rf-tabs__tab', id === active && 'is-active')} onClick={() => onChange(id)}>{label}</button>)}</div>;
}
export function Segmented({ items, active, onChange }) {
  return <div className="rf-seg" role="radiogroup">{items.map(([id, label]) => <button key={id} type="button" role="radio" aria-checked={id === active} className={cx('rf-seg__btn', id === active && 'is-active')} onClick={() => onChange(id)}>{label}</button>)}</div>;
}
export function Empty({ icon = 'inbox', title, children, action, danger }) {
  return <div className="rf-empty" style={{ padding: '28px 12px' }}><span className="rf-empty__icon" style={danger ? { color: 'var(--danger-fg)' } : undefined}><Icon name={icon} size={20} /></span><div className="rf-empty__title">{title}</div><div style={{ maxWidth: 560 }}>{children}</div>{action && <div style={{ marginTop: 8 }}>{action}</div>}</div>;
}
export function Skeleton({ rows = 4 }) { return <Panel><div aria-busy="true" aria-label="Loading">{Array.from({ length: rows }).map((_, i) => <span key={i} className="rf-skel" style={{ width: (90 - i * 12) + '%', margin: '10px 0' }} />)}</div></Panel>; }
export function Dialog({ eyebrow, title, children, foot, error, onClose, width }) {
  return <div className="rf-scrim" onMouseDown={(e) => { if (e.target === e.currentTarget && onClose) onClose(); }}><div className="rf-dialog" role="dialog" aria-modal="true" aria-labelledby="rf-dlg-title" style={width ? { width } : undefined}>
    <div className="rf-dialog__head">{eyebrow && <div className="rf-dialog__eyebrow">{eyebrow}</div>}<h2 className="rf-dialog__title" id="rf-dlg-title">{title}</h2></div>
    <div className="rf-dialog__body">{error && <Notice tone="danger" title="Not completed" compact>{error}</Notice>}{children}</div>
    <div className="rf-dialog__foot">{foot}</div></div></div>;
}
export function Drawer({ label, head, children, foot, width }) {
  return <aside className="rf-drawer" role="dialog" aria-label={label} style={width ? { width } : undefined}><div className="rf-drawer__head">{head}</div><div className="rf-drawer__body">{children}</div>{foot && <div className="rf-drawer__foot">{foot}</div>}</aside>;
}
export const Bullets = ({ items }) => <ul className="rf-steps-mini">{items.map((l, i) => <li key={i}><span><Icon name={l[0]} size={12} /></span><span>{l[1]}</span></li>)}</ul>;

/* ---------- app shell, case header, status ---------- */
export function AppShell({ analyst, active, activeCase, onNav, menuOpen, onMenu, onSignOut, children, overlay, demo }) {
  // Demo scenarios are a section of the Work queue (no separate nav item); `demo` is accepted for compatibility.
  const nav = [['queue', 'Work queue', 'inbox'], ['customers', 'Customers', 'building']];
  const go = (to) => (e) => { e.preventDefault(); onNav(to); };
  return <div className="rf-app">
    <header className="rf-topbar">
      <a className="rf-brand" href="#/queue" onClick={go('queue')} aria-label="Ringfence home"><Mark size={22} /><span>Ringfence</span></a>
      <span className="rf-brand__ctx">Moorwand · UC-042</span>
      <nav className="rf-nav" aria-label="Primary">{nav.map((n) => <a key={n[0]} href={'#/' + n[0]} onClick={go(n[0])} className={cx('rf-nav__item', active === n[0] && 'is-active')} aria-current={active === n[0] ? 'page' : undefined}><Icon name={n[2]} />{n[1]}</a>)}</nav>
      {activeCase
        ? <a href={'#/cases/' + activeCase.ref + '/overview'} onClick={go('cases/' + activeCase.ref + '/overview')} className="rf-activecase" title={'In Progress: ' + activeCase.ref + ' · ' + activeCase.customer + ' · ' + activeCase.period + '. Only one case can be In Progress at a time.'}><Glyph name="active" size={10} /><span className="rf-activecase__label">In Progress</span><span className="rf-mono">{activeCase.ref}</span></a>
        : <span className="rf-activecase is-empty" title="Only one case can be In Progress at a time"><Glyph name="pending" size={10} /><span>No case In Progress</span></span>}
      <button type="button" className="rf-gsearch" role="search" onClick={() => onNav('queue?focus=search')}><Icon name="search" /><span>Search cases, customers, files</span><span className="rf-kbd">/</span></button>
      <span className="rf-env" title="Proof-of-concept environment with synthetic data">POC · SYNTHETIC DATA</span>
      <div className="rf-user"><button type="button" className="rf-userbtn" aria-haspopup="menu" aria-expanded={!!menuOpen} onClick={onMenu}><span className="rf-avatar">{analyst.initials}</span><span>{analyst.name}</span><Icon name="chevronDown" size={14} /></button>
        {menuOpen && <div className="rf-menu" role="menu" aria-label="Analyst profile"><div className="rf-menu__head"><span className="rf-avatar rf-avatar--lg">{analyst.initials}</span><div><div className="rf-strong">{analyst.name}</div><div className="rf-muted" style={{ fontSize: 12 }}>{analyst.role}</div><div className="rf-mono rf-muted" style={{ fontSize: 12, marginTop: 2 }}>{analyst.email}</div></div></div>
          <button type="button" className="rf-menu__item" role="menuitem" onClick={onSignOut}><Icon name="logout" />Sign out</button></div>}
      </div>
    </header>
    <main className="rf-main">{children}</main>{overlay}
  </div>;
}
export const LIFECYCLE = [['overview', 'Overview'], ['evidence', 'Evidence'], ['parser', 'Smart Parser'], ['review', 'Review'], ['package', 'Validation & activation'], ['recon', 'Reconciliation'], ['closing', 'Closing & Audit Pack']];
export function Lifecycle({ active, steps = {}, onTab }) {
  const tab = ([id, label]) => {
    const s = steps[id] || {};
    const st = s.state ? stateOf(s.state) : null;
    return <a key={id} href="#" role="tab" aria-selected={active === id} className={cx('rf-lifecycle__tab', active === id && 'is-active', s.locked && 'is-locked')} title={s.title} onClick={(e) => { e.preventDefault(); onTab(id); }}>
      {st && <span className={'rf-tone-' + st.tone}><Glyph name={st.glyph} still /></span>}<span>{label}</span>{s.count != null && <span className={cx('rf-lifecycle__count', s.countTone && 'rf-lifecycle__count--' + s.countTone)}>{s.count}</span>}{s.locked && <Icon name="lock" size={12} />}</a>;
  };
  const items = [];
  LIFECYCLE.forEach((t, i) => { if (i) items.push(<span key={'a' + i} className="rf-lifecycle__arrow" aria-hidden="true"><Icon name="chevronRight" size={12} /></span>); items.push(tab(t)); });
  return <nav className="rf-lifecycle" role="tablist" aria-label="Case lifecycle">{items}<span className="rf-lifecycle__gap" />{tab(['activity', 'Activity'])}</nav>;
}
export function CaseBanner({ kind, title, children, actions }) {
  const st = { waiting: 'WAITING', blocked: 'WAITING', 'in-progress': 'IN_PROGRESS', deferring: 'IN_PROGRESS', pending: 'PENDING', 'pending-blocked': 'PENDING', completed: 'COMPLETED' }[kind];
  return <div className={cx('rf-casebanner', 'rf-casebanner--' + kind)} role="status"><Pill state={st} /><div className="rf-casebanner__text"><b>{title}</b> {children && <span>{children}</span>}</div>{actions && <div className="rf-casebanner__actions">{actions}</div>}</div>;
}
export function CaseHeader({ c, onNav, tab, onTab, state, actions, steps, banner }) {
  const go = (to) => (e) => { e.preventDefault(); onNav(to); };
  return <><header className="rf-casehead">
    <div className="rf-breadcrumb"><a href="#/queue" onClick={go('queue')}>Work queue</a><Icon name="chevronRight" size={12} /><a href={'#/customers/' + c.customerId} onClick={go('customers/' + c.customerId)}>{c.customer}</a><Icon name="chevronRight" size={12} /><span className="rf-mono">{c.ref}</span></div>
    <div className="rf-casehead__top"><div style={{ minWidth: 0 }}>
      <h1 className="rf-casehead__title">{c.customer} — {c.period}</h1>
      <div className="rf-casehead__meta"><span>Case <Ref id={c.ref} copy /></span><span>Period <b>{c.periodRange}</b></span><span>Submission <span className="rf-mono rf-secondary">{c.submission}</span></span><span>Received <b>{c.receivedLabel}</b></span></div>
      <div className="rf-casehead__state">{state}</div>
    </div><div className="rf-casehead__actions">{actions}</div></div>
    <Lifecycle active={tab} steps={steps} onTab={onTab} />
  </header>{banner}</>;
}
const STEP_NAMES = ['Smart Parser', 'Review', 'Validation', 'Activation', 'Reconciliation'];
const STEP_CODE = { d: 'done', c: 'current', a: 'attention', f: 'failed', p: 'paused', t: 'todo' };
const STEP_LABEL = { done: 'done', current: 'started, not finished', attention: 'needs attention', failed: 'failed', paused: 'paused · case Pending', todo: 'not started' };
export function CaseProgress({ steps, facts = [], live, labels, notes }) {
  const st = Array.isArray(steps) ? steps.map((x) => (x && x.state) || x) : steps.split('').map((c) => STEP_CODE[c]); // contract steps[] or codes
  const label = st.map((s, i) => STEP_NAMES[i] + ' ' + STEP_LABEL[s]).join(', ');
  if (labels) return <div className="rf-cprog rf-cprog--labeled"><ol className="rf-cprog__steps" aria-label={label}>{st.map((s, i) => <li key={i}><i className={'is-' + s} /><span className="rf-cprog__name">{STEP_NAMES[i]}</span><span className="rf-cprog__state">{(notes && notes[i]) || STEP_LABEL[s]}</span></li>)}</ol></div>;
  return <div className="rf-cprog"><span className="rf-cprog__track" role="img" aria-label={label}>{st.map((s, i) => <i key={i} className={'is-' + s} title={STEP_NAMES[i] + ' · ' + STEP_LABEL[s]} />)}</span>
    <div className="rf-cprog__facts">{facts.map((f, i) => <span key={i}>{i === 0 && live && <><span className="rf-tone-progress"><Glyph name="progress" size={10} /></span> </>}{f}</span>)}</div></div>;
}
export function Tasks({ title, sub, groups, kept, keptTitle, readOnly }) {
  return <section className={cx('rf-tasks', readOnly && 'is-readonly')} aria-label="Outstanding tasks"><header className="rf-tasks__head"><Icon name="checklist" /><div style={{ flex: 1, minWidth: 0 }}><div className="rf-panel__title">{title}</div>{sub && <div className="rf-panel__sub">{sub}</div>}</div></header>
    {groups.map((g, gi) => <div key={gi} className="rf-tasks__group"><div className="rf-tasks__label"><span className={'rf-tone-' + (g.tone || 'attention')}><Glyph name={g.glyph || 'review'} still /></span>{g.label}<span className={cx('rf-lifecycle__count', g.countTone && 'rf-lifecycle__count--' + g.countTone)}>{g.count != null ? g.count : g.items.length}</span></div>
      <ul className="rf-tasks__list">{g.items.map((it, i) => <li key={i} className="rf-tasks__item"><span className={'rf-tone-' + (g.tone || 'attention')}><Glyph name={g.glyph || 'review'} still /></span><div style={{ minWidth: 0 }}><div className="rf-strong">{it.title}</div>{it.detail && <div className="rf-tasks__detail">{it.detail}</div>}</div><div>{it.action}</div></li>)}</ul></div>)}
    {kept && <div className="rf-tasks__kept"><div className="rf-tasks__keptlabel"><Icon name="lock" size={12} />{keptTitle || 'Kept'}</div><ul>{kept.map((k, i) => <li key={i}><Glyph name="success" size={10} /><span>{k}</span></li>)}</ul></div>}
  </section>;
}

/* ---------- Smart Parser ---------- */
function StageGlyph({ state }) {
  if (state === 'done') return <Icon name="check" size={14} />;
  if (state === 'running') return <Glyph name="progress" size={14} />;
  if (state === 'attention') return <Glyph name="review" size={10} />;
  if (state === 'failed') return <Icon name="x" size={14} />;
  if (state === 'skipped') return <Glyph name="na" size={12} />;
  return null;
}
export function Stages({ stages }) {
  return <ol className="rf-stages">{stages.map((s, i) => { const st = s.state || 'pending'; return <li key={i} className={cx('rf-stage', 'is-' + st)} aria-current={st === 'running' ? 'step' : undefined}>
    <span className="rf-stage__glyph">{st === 'pending' ? <span className="rf-stage__num">{i + 1}</span> : <StageGlyph state={st} />}</span>
    <div style={{ minWidth: 0 }}><div className="rf-stage__head"><span className="rf-stage__name">{s.name}</span></div><div className="rf-stage__desc">{s.desc}</div>{s.note && <div className="rf-stage__note">{s.note}</div>}</div>
    <div className="rf-stage__meta">{s.meta}{s.time && <div className="rf-muted rf-mono" style={{ fontSize: 11 }}>{s.time}</div>}</div></li>; })}</ol>;
}
export function StageStrip({ states }) {
  return <div className="rf-stagestrip" role="img" aria-label={states.filter((s) => s === 'done' || s === 'attention').length + ' of ' + states.length + ' stages complete'}>{states.map((s, i) => <span key={i} className={'is-' + s} />)}</div>;
}
export function RunLog({ rows }) {
  return <div className="rf-log" role="log" aria-live="polite">{rows.map((r, i) => <div key={i} className={cx('rf-log__row', r.latest && 'is-latest')}><span className="rf-log__time">{r.t}</span><span className={'rf-log__lvl rf-tone-' + (r.tone || 'neutral')}><Glyph name={r.glyph || 'dot'} size={10} still /></span><span className="rf-log__msg">{r.m}</span></div>)}</div>;
}
export function Coverage({ cats }) {
  return <div className="rf-coverage">{cats.map((c) => {
    const g = { present: 'success', 'missing-required': 'danger', 'missing-optional': 'pending', issue: 'warning' }[c.state];
    const meta = { present: c.files + ' file' + (c.files > 1 ? 's' : '') + ' · ' + (c.required ? 'required' : 'optional'), 'missing-required': 'Missing · required', 'missing-optional': 'Not supplied · optional', issue: c.note || 'Present · has issues' }[c.state];
    return <div key={c.code} className={cx('rf-cov', 'is-' + c.state)} title={c.label}><Glyph name={g} /><div style={{ minWidth: 0 }}><div className="rf-cov__name">{c.code}</div><div className="rf-cov__meta">{c.type} · {meta}</div></div></div>;
  })}</div>;
}

/* ---------- validation, versions, reconciliation ---------- */
export function Checks({ checks }) {
  return <div className="rf-checks">{checks.map((c) => {
    const g = { pass: 'success', fail: 'danger', warn: 'warning', notrun: 'pending' }[c.result];
    const label = c.result === 'pass' ? <Pill state="PASS" label="Passed" /> : c.result === 'fail' ? <Pill state="FAIL" label="Failed" /> : c.result === 'warn' ? <span className="rf-pill rf-pill--attention"><Glyph name="warning" /><span>Warning</span></span> : <Pill state={c.pendingState || 'NOT_PROCESSED'} label={c.pendingLabel || 'Not run'} />;
    return <div key={c.id} className={cx('rf-check', 'is-' + c.result)}><Glyph name={g} /><span className="rf-check__id">{c.id}</span><div style={{ minWidth: 0 }}><div className="rf-check__title">{c.title}</div><div className="rf-check__explain">{c.explain}</div>{c.affected && c.affected.length > 0 && <div className="rf-check__affected">{c.affected.map((a, i) => a.kind === 'file' ? <span key={i} className="rf-evref"><Icon name="file" size={12} />{a.label}</span> : <Enum key={i}>{a.label}</Enum>)}</div>}</div><div className="rf-check__side">{label}{(c.result === 'fail' || c.result === 'warn') && <Tag kind={c.blocking ? 'BLOCKING' : 'NONBLOCKING'} />}{c.fix}</div></div>;
  })}</div>;
}
export function Readiness({ tone = 'blocked', title, sub, items, headAction, children }) {
  const icon = tone === 'ready' ? 'check' : tone === 'sealed' ? 'lock' : 'alert';
  return <section className={cx('rf-readiness', tone === 'ready' && 'rf-readiness--ready', tone === 'sealed' && 'rf-readiness--sealed')}>
    <header className="rf-readiness__head"><Icon name={icon} /><div style={{ flex: 1 }}><div className="rf-readiness__title">{title}</div><div className="rf-readiness__sub">{sub}</div></div>{headAction}</header>
    {items && items.length > 0 && <ol className="rf-readiness__list">{items.map((it, i) => <li key={i} className="rf-readiness__item"><span className="rf-readiness__n">{i + 1}</span><div><div className="rf-strong">{it.title}</div><div className="rf-secondary" style={{ fontSize: 12, lineHeight: '16px', marginTop: 2 }}>{it.detail}</div>{it.checks && <div className="rf-readiness__checks">{it.checks.map((c) => <Enum key={c}>{c}</Enum>)}</div>}</div><div>{it.action}</div></li>)}</ol>}
    {children}</section>;
}
export function Versions({ versions }) {
  return <ol className="rf-versions">{versions.map((v, i) => <li key={i} className={cx('rf-version', v.current && 'is-current', v.staged && 'is-staged')}><span className="rf-version__badge">{v.v}</span><div className="rf-version__card"><div className="rf-version__title">{v.title}</div><dl className="rf-version__meta">{v.meta.map((m, j) => <React.Fragment key={j}><dt>{m[0]}</dt><dd>{m[1]}</dd></React.Fragment>)}</dl>{v.note}</div></li>)}</ol>;
}
export function Outcome({ status, title, children, actions }) {
  const m = { CLEAN: ['clean', 'success'], EXCEPTIONS_OPEN: ['exceptions', 'danger'], EVIDENCE_INCOMPLETE: ['incomplete', 'warning'] }[status];
  return <section className={'rf-outcome rf-outcome--' + m[0]} aria-label="Reconciliation outcome"><span className="rf-outcome__icon"><Glyph name={m[1]} size={18} /></span><div><div className="rf-outcome__title">{title}<Enum>{status}</Enum></div><div className="rf-outcome__desc">{children}</div></div><div className="rf-row">{actions}</div></section>;
}
export function Stats({ items }) {
  return <div className="rf-stats" style={{ gridTemplateColumns: 'repeat(' + items.length + ',minmax(0,1fr))' }}>{items.map((s, i) => <div key={i} className="rf-stat"><div className="rf-stat__label">{s.glyph && <span className={'rf-tone-' + s.tone}><Glyph name={s.glyph} /></span>}{s.label}</div><div className="rf-stat__value">{s.value}</div>{s.note && <div className="rf-stat__note">{s.note}</div>}</div>)}</div>;
}
export function SegBar({ parts }) {
  const total = parts.reduce((a, p) => a + p.value, 0) || 1;
  return <><div className="rf-segbar" role="img" aria-label={parts.map((p) => p.label + ' ' + p.value).join(', ') + ' of ' + total + ' results'}>{parts.filter((p) => p.value > 0).map((p) => <div key={p.key} className={'rf-segbar__part rf-segbar__part--' + p.key} style={{ flex: p.value + ' 1 0' }} title={p.label + ': ' + p.value + ' of ' + total} tabIndex={0}><span className="rf-segbar__label">{p.value}</span></div>)}</div>
    <div className="rf-legend">{parts.map((p) => <span key={p.key} className="rf-legend__item"><span className={'rf-legend__key rf-legend__key--' + p.key} />{p.label}</span>)}</div></>;
}
export function Timeline({ days }) {
  return <div className="rf-timeline">{days.map((d, di) => <React.Fragment key={di}><div className="rf-tl-day">{d.day}</div>{d.items.map((it, ii) => <div key={ii} className={cx('rf-tl-item', di === days.length - 1 && ii === d.items.length - 1 && 'is-last')}><span className="rf-tl-item__time">{it.t}</span><span className={cx('rf-tl-item__glyph', it.tone && 'rf-tl-item__glyph--' + it.tone)}><Icon name={it.icon || 'activity'} size={13} /></span><div style={{ minWidth: 0 }}><div className="rf-tl-item__title">{it.title}</div><div className="rf-tl-item__actor">{it.actor}</div>{it.detail && <div className="rf-tl-item__detail">{it.detail}</div>}{it.refs && it.refs.length > 0 && <div className="rf-tl-item__refs">{it.refs.map((r, i) => <span key={i} className="rf-evref"><Icon name="hash" size={12} />{r}</span>)}</div>}</div></div>)}</React.Fragment>)}</div>;
}

/* ---------- mapping review ---------- */
export const DECISIONS = [['MAP', 'Map', 'Use the proposed canonical field.'], ['CHANGE', 'Change', 'Map to a different canonical field. Overrides the proposal.'], ['IGNORE', 'Ignore', 'Exclude this column. It supplies no canonical field.']];
export const decisionLabel = (code) => (DECISIONS.find((d) => d[0] === code) || [code, code])[1];
export const decisionText = (d, it) => { const t = d.target || (d.type === 'MAP' && it ? it.proposal : null); return decisionLabel(d.type) + (t ? ' → ' + t : ''); };
export function decisionRules(it) { const r = { MAP: it.proposal && it.source !== 'NONE' ? null : 'No proposal to map. Use Change or Ignore', CHANGE: null, IGNORE: null }; if (it.mapBlocked) r.MAP = it.mapBlocked; return r; }
export function DecisionPicker({ item, selected, readOnly, onPick }) {
  const rules = decisionRules(item);
  return <>{readOnly && <div className="rf-help" style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}><Icon name="lock" size={12} />{readOnly}</div>}
    <div className={cx('rf-decisions', 'rf-decisions--3', readOnly && 'is-readonly')} role="radiogroup" aria-label="Mapping action">{DECISIONS.map((d, i) => { const why = rules[d[0]], off = !!readOnly || !!why; return <button key={d[0]} type="button" role="radio" aria-checked={selected === d[0]} className={cx('rf-decision', selected === d[0] && 'is-selected')} disabled={off} onClick={() => onPick(d[0])}><span className="rf-row" style={{ justifyContent: 'space-between' }}><span className="rf-decision__label">{d[1]}</span>{!off && <span className="rf-kbd">{i + 1}</span>}</span><span className="rf-decision__code">{d[0]}</span><span className="rf-decision__desc">{why || d[2]}</span></button>; })}</div></>;
}
export function FileReviewBar({ name, version, attention, decided, state = 'open', by, at, meta, readOnly, busy, blockedReason, onConfirm, onReject }) {
  const outstanding = attention - decided;
  const pill = state === 'confirmed' ? <Pill state="FILE_CONFIRMED" /> : state === 'rejected' ? <Pill state="FILE_REJECTED" /> : <Pill state={outstanding ? 'M_REVIEW' : 'D_RECORDED'} label={outstanding ? outstanding + ' outstanding' : 'All columns decided'} />;
  let actions;
  if (state === 'confirmed' || state === 'rejected') actions = <span className="rf-muted" style={{ fontSize: 12 }}>{state === 'confirmed' ? 'Confirmed' : 'Rejected'} by {by} · {at}</span>;
  else if (readOnly) actions = <WithReason reason={readOnly}><div className="rf-row"><Button variant="danger" disabled>Reject / Request correction</Button><Button icon="check" disabled>Confirm file</Button></div></WithReason>;
  else actions = <div className="rf-row rf-row--top"><Button variant="danger" onClick={onReject} disabled={!!busy}>Reject / Request correction</Button>{outstanding || blockedReason ? <WithReason reason={blockedReason || outstanding + (outstanding > 1 ? ' columns' : ' column') + ' outstanding'}><Button icon="check" disabled>Confirm file</Button></WithReason> : <Button variant="primary" icon="check" loading={busy === 'confirm'} onClick={onConfirm}>{busy === 'confirm' ? 'Confirming…' : 'Confirm file'}</Button>}</div>;
  return <section className={cx('rf-filereview', 'is-' + state)} aria-label="File review"><Icon name="fileTable" /><div className="rf-filereview__file"><div className="rf-row rf-row--wrap" style={{ gap: 8 }}><span className="rf-mono rf-strong" style={{ fontSize: 13 }}>{name}</span><span className="rf-mono rf-muted" style={{ fontSize: 12 }}>{version}</span>{pill}</div><div className="rf-filereview__meta">{meta}</div></div><div className="rf-filereview__actions">{actions}</div></section>;
}
