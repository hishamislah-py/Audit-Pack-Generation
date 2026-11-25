import { useCallback } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Async, Empty, Panel, SimulatedNotice, Tabs } from "../components/common";
import { IntegrityDetail, IntegrityStatus, PackRecord } from "../components/finalpack";
import { usePage } from "../components/layout/workContext";
import { JsonView, PdfViewer, ReportFrame } from "../components/review/ReportViewer";
import { useData } from "../data/DataProvider";
import { periodFromFinalPackId, periodLabel } from "../data/periods";
import { useApi } from "../hooks/useApi";
import { dateTime, shortHash } from "../lib/format";

export function FinalPacksPage() {
  const data = useData();
  usePage([{ label: "Final audit packs" }]);
  const rows = useApi(() => data.finalPacks(), [data]);
  return (
    <div className="stack">
      <div className="page-head"><div><h1>Final audit packs</h1><p className="page-sub">Immutable packs, each created by a recorded GENERATE decision in a final review.</p></div></div>
      <Panel title="Generated packs" flush>
        <Async state={rows}>{(r) => r.length === 0 ? (
          <Empty title="No final audit pack yet">A final pack is created only after GENERATE is selected in a final review. <Link to="/reviews">Reviews</Link></Empty>
        ) : (
          <div className="table-scroll"><table className="dtable">
            <thead><tr><th>Final pack</th><th>Source pack</th><th className="num">Version</th><th>Supersedes</th><th>Generated</th><th>Content hash</th></tr></thead>
            <tbody>{[...r].reverse().map((f) => (
              <tr key={f.final_pack_id}>
                <td><Link className="id" to={`/final-packs/${f.final_pack_id}`}>{f.final_pack_id}</Link></td>
                <td><Link className="id" to={`/packs/${f.pack_id}`}>{f.pack_id}</Link></td>
                <td className="num">{f.version}</td><td className="id">{f.supersedes_final_pack_id ?? "—"}</td>
                <td className="small">{dateTime(f.generated_at)}</td><td><code>{f.final_content_sha256 ? shortHash(f.final_content_sha256) : "— (simulated)"}</code></td>
              </tr>
            ))}</tbody>
          </table></div>
        )}</Async>
      </Panel>
    </div>
  );
}

type View = "pdf" | "html" | "json" | "versions";

export function FinalPackPage() {
  const { finalPackId = "" } = useParams();
  const data = useData();
  const [params, setParams] = useSearchParams();
  const view = (params.get("view") as View) || "pdf";
  const detail = useApi(() => data.finalPack(finalPackId), [data, finalPackId]);
  const verify = useApi(() => data.verifyFinalPack(finalPackId), [data, finalPackId]);
  const doc = useApi(() => data.finalPackDocument(finalPackId), [data, finalPackId]);
  const packId = detail.data?.source_pack.pack_id;
  const versions = useApi(() => (packId ? data.finalPacks(packId, true) : Promise.resolve([])), [data, packId]); // the reassessment lineage
  const loadHtml = useCallback(() => data.finalPackHtml(finalPackId), [data, finalPackId]);
  const loadPdf = useCallback(() => data.finalPackPdf(finalPackId), [data, finalPackId]);
  const periodId = periodFromFinalPackId(finalPackId);
  usePage([...(periodId ? [{ label: periodLabel(periodId), to: `/reports/${periodId}` }] : []), { label: "Final audit packs", to: "/final-packs" }, { label: finalPackId }],
    { finalPackId, ...(packId ? { packId } : {}) });
  const integrity = <IntegrityStatus verification={verify.data} loading={verify.loading} />;
  const download = async (kind: "json" | "html" | "pdf") => {
    const url = data.finalPackFileUrl(finalPackId, kind);
    if (url) { window.open(url, "_blank", "noopener"); return; }
    const blob = kind === "pdf" ? await data.finalPackPdf(finalPackId) : new Blob([kind === "html" ? await data.finalPackHtml(finalPackId)
      : JSON.stringify(await data.finalPackDocument(finalPackId), null, 2)], { type: kind === "html" ? "text/html" : "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${finalPackId}.${kind}`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };

  return (
    <div className="stack">
      <Async state={detail} label="Loading final pack…">{(d) => (
        <>
          <div className="page-head">
            <div><div className="eyebrow">Final audit pack · immutable</div>
              <h1 className="page-title">{d.final_pack_id} <span className="page-title__muted">v{d.version}</span></h1></div>
            <div className="actions">{integrity}</div>
          </div>
          {d.status === "SIMULATED" && <SimulatedNotice>This final pack was produced by the simulated GENERATE flow in this browser session. Nothing was assembled or published; the document shown is the backend's real preview of the same pack, which still reads "PREVIEW". Real packs are assembled, published and verified by the backend.</SimulatedNotice>}
          <IntegrityDetail verification={verify.data} />
          <div className="grid-final">
            <Panel title="Pack record" flush><PackRecord detail={d} doc={doc.data} integrity={integrity} /></Panel>
            <Panel title="Artefacts" sub="PDF and HTML are rendered from the canonical JSON" flush>
              <table className="dtable">
                <thead><tr><th>Format</th><th>File</th><th>SHA-256</th><th /></tr></thead>
                <tbody>{(["pdf", "html", "json"] as const).map((k) => (
                  <tr key={k}>
                    <td><span className="tag">{k.toUpperCase()}</span></td>
                    <td><code>{d.files[k]?.name ?? "—"}</code>{d.files[k]?.size_bytes ? <div className="xsmall muted">{(d.files[k].size_bytes / 1024).toFixed(0)} KB</div> : null}</td>
                    <td><code>{d.files[k]?.sha256 ? shortHash(d.files[k].sha256, 16) : "— (simulated)"}</code></td>
                    <td className="link-cell"><button className="link-btn" onClick={() => setParams({ view: k }, { replace: true })}>Open</button>{" · "}
                      <button className="link-btn" onClick={() => download(k)}>Download</button></td>
                  </tr>
                ))}</tbody>
              </table>
            </Panel>
          </div>
          <section className="panel">
            <Tabs label="Final pack views" value={view} onChange={(v) => setParams({ view: v }, { replace: true })}
              tabs={[{ key: "pdf", label: "PDF preview" }, { key: "html", label: "HTML report" }, { key: "json", label: "Canonical JSON" }, { key: "versions", label: "Version history", count: versions.data?.length }]} />
            <div className="doc-viewer"><div className="doc-viewer__page">
              {view === "pdf" && <PdfViewer load={loadPdf} title={`${d.final_pack_id} (PDF)`} downloadName={`${d.final_pack_id}.pdf`} />}
              {view === "html" && <ReportFrame load={loadHtml} title={`${d.final_pack_id} (HTML)`} />}
              {view === "json" && <Async state={doc}>{(x) => <div className="panel"><JsonView doc={x} /></div>}</Async>}
              {view === "versions" && (
                <div className="panel"><Async state={versions}>{(v) => (
                  <table className="dtable"><thead><tr><th className="num">Version</th><th>Final pack</th><th>Supersedes</th><th>Generated</th><th>Decision</th></tr></thead>
                    <tbody>{[...v].reverse().map((f) => (
                      <tr key={f.final_pack_id} className={f.final_pack_id === d.final_pack_id ? "is-selected" : undefined}>
                        <td className="num">v{f.version}</td><td><Link className="id" to={`/final-packs/${f.final_pack_id}`}>{f.final_pack_id}</Link></td>
                        <td className="id">{f.supersedes_final_pack_id ?? "—"}</td><td className="small">{dateTime(f.generated_at)}</td>
                        <td className="id">{f.review_decision_id}</td>
                      </tr>
                    ))}</tbody></table>
                )}</Async></div>
              )}
            </div></div>
          </section>
        </>
      )}</Async>
      {detail.error !== undefined && <Link to="/final-packs">All final packs</Link>}
    </div>
  );
}
