// Document-centric report viewer. The report is the backend's own Phase 1 rendering (16 sections, the AI-Generated
// Closing Summary last), shown in a sandboxed frame without scripts. Same-origin access is allowed only so the section
// navigation can scroll the document; the report itself cannot run code.
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import type { FinalPackDocument } from "../../api/types";
import { REPORT_SECTIONS } from "../../lib/report";
import { ErrorPanel, Loading, Notice } from "../common";

export interface ReportFrameHandle { scrollTo(anchor: string): void }

export const ReportFrame = forwardRef<ReportFrameHandle, { load: () => Promise<string>; title: string; onSection?: (anchor: string) => void }>(
  function ReportFrame({ load, title, onSection }, ref) {
    const frame = useRef<HTMLIFrameElement>(null);
    const [html, setHtml] = useState<string>();
    const [error, setError] = useState<unknown>();
    useEffect(() => {
      let live = true;
      setHtml(undefined);
      setError(undefined);
      load().then((h) => live && setHtml(h), (e) => live && setError(e));
      return () => { live = false; };
    }, [load]);
    useImperativeHandle(ref, () => ({
      scrollTo(anchor: string) {
        const doc = frame.current?.contentDocument;
        doc?.getElementById(anchor)?.scrollIntoView({ block: "start" });
      },
    }));
    const onLoad = () => {
      const win = frame.current?.contentWindow;
      const doc = frame.current?.contentDocument;
      if (!win || !doc || !onSection) return;
      win.addEventListener("scroll", () => {
        let current = REPORT_SECTIONS[0].anchor;
        for (const s of REPORT_SECTIONS) {
          const el = doc.getElementById(s.anchor);
          if (el && el.getBoundingClientRect().top <= 80) current = s.anchor;
        }
        onSection(current);
      }, { passive: true });
    };
    if (error) return <ErrorPanel error={error} title="The report could not be loaded" />;
    if (html === undefined) return <Loading label="Loading report…" />;
    return <iframe ref={frame} className="doc-frame" title={title} sandbox="allow-same-origin" srcDoc={html} onLoad={onLoad} />;
  });

export function ReportNav({ active, onSelect }: { active: string; onSelect: (anchor: string) => void }) {
  return (
    <>
      <nav className="toc" aria-label="Report sections">
        <div className="toc__head">CONTENTS · 16 SECTIONS</div>
        {REPORT_SECTIONS.map((s) => (
          <button key={s.anchor} className={`toc__item${s.anchor === active ? " toc__item--active" : ""}${s.ai ? " toc__item--ai" : ""}`}
            onClick={() => onSelect(s.anchor)} aria-current={s.anchor === active || undefined}>
            <span className="toc__num">{s.n}</span><span>{s.title}</span>
          </button>
        ))}
      </nav>
    </>
  );
}

export function SectionSelect({ active, onSelect }: { active: string; onSelect: (anchor: string) => void }) {
  return (
    <select className="select toc-select" aria-label="Report section" value={active} onChange={(e) => onSelect(e.target.value)}>
      {REPORT_SECTIONS.map((s) => <option key={s.anchor} value={s.anchor}>{s.n}. {s.title}</option>)}
    </select>
  );
}

/** Whether this browser can display a PDF inline. Browsers without a built-in PDF viewer (for example headless Chromium,
 * some mobile browsers or a policy that disables the viewer) report false and would otherwise show an empty frame. */
export function inlinePdfSupported(): boolean {
  const nav = typeof navigator === "undefined" ? undefined : (navigator as Navigator & { pdfViewerEnabled?: boolean });
  return nav?.pdfViewerEnabled !== false;
}

export function PdfViewer({ load, title, downloadName, inline = inlinePdfSupported() }: {
  load: () => Promise<Blob>; title: string; downloadName?: string; inline?: boolean;
}) {
  const [url, setUrl] = useState<string>();
  const [error, setError] = useState<unknown>();
  useEffect(() => {
    let live = true;
    let objectUrl: string | undefined;
    load().then((blob) => {
      if (!live) return;
      // The viewer renders only a blob typed application/pdf; the bytes are the published file, unchanged.
      objectUrl = URL.createObjectURL(blob.type === "application/pdf" ? blob : new Blob([blob], { type: "application/pdf" }));
      setUrl(objectUrl);
    }, (e) => live && setError(e));
    return () => { live = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [load]);
  if (error) return <ErrorPanel error={error} title="The PDF could not be loaded" />;
  if (!url) return <Loading label="Loading PDF…" />;
  const actions = <div className="row"><a className="btn btn--sm" href={url} target="_blank" rel="noopener noreferrer">Open the PDF in a new tab</a>
    <a className="btn btn--sm btn--ghost" href={url} download={downloadName ?? `${title}.pdf`}>Download PDF</a></div>;
  if (!inline) {
    return (
      <div className="stack stack--sm" style={{ padding: 16 }}>
        <Notice tone="info" title="This browser cannot display PDFs inside the page">The PDF itself is available: open it in a new tab or download it. The HTML report tab shows the
          same canonical content.</Notice>
        {actions}
      </div>
    );
  }
  return (
    <div className="stack stack--sm">
      <iframe className="doc-frame" title={title} src={url} />
      <div className="xsmall muted" style={{ padding: "0 16px 12px" }}>If the PDF does not appear above, your browser's PDF viewer is unavailable: {actions}</div>
    </div>
  );
}

export function JsonView({ doc }: { doc: unknown }) {
  return <pre className="json-view" aria-label="Canonical JSON">{JSON.stringify(doc, null, 2)}</pre>;
}

/** Key facts of the previewed report, read from its canonical JSON (nothing recomputed beyond counting items). */
export function ReportFacts({ doc }: { doc: FinalPackDocument }) {
  const inv = doc.ai_investigations as Array<Record<string, unknown>>;
  const count = (k: string) => inv.reduce((n, i) => n + ((i[k] as unknown[] | undefined)?.length ?? 0), 0);
  return (
    <table className="dtable dtable--compact">
      <tbody>
        <tr><td className="muted">Exceptions</td><td className="num">{doc.exception_register.length} · all unresolved</td></tr>
        <tr><td className="muted">AI investigations included</td><td className="num">{inv.length}</td></tr>
        <tr><td className="muted">Confirmed observations</td><td className="num">{count("confirmed_findings")}</td></tr>
        <tr><td className="muted">Hypotheses (not established)</td><td className="num">{count("hypotheses")}</td></tr>
        <tr><td className="muted">Evidence gaps</td><td className="num">{count("evidence_gaps")}</td></tr>
        <tr><td className="muted">Suggested next steps</td><td className="num">{count("next_steps")}</td></tr>
        <tr><td className="muted">AI closing summary</td><td className="num">{doc.closing_summary.status}</td></tr>
      </tbody>
    </table>
  );
}
