// Upload workflow building blocks. The drop zone hands the chosen File objects to its caller: the backend upload sends
// them; the mock-data design view reads only their names and sizes.
import { useRef, useState } from "react";
import type { UploadSummary } from "../../data/models";
import { EXPECTED_DOCUMENTS } from "../../lib/upload";
import { StatusBadge } from "../common";

export function DropZone({ onFiles }: { onFiles: (files: File[]) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const take = (list: FileList | null) => list && onFiles(Array.from(list));
  return (
    <div className={`dropzone${over ? " dropzone--over" : ""}`} role="button" tabIndex={0}
      onClick={() => input.current?.click()} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); take(e.dataTransfer.files); }}>
      <div className="strong">Drop CSV and PDF files here, or click to choose</div>
      <div className="small">Up to 19 evidence files: 14 CSV and 5 PDF (IN-18 and IN-19 optional).</div>
      <input ref={input} type="file" multiple accept=".csv,.pdf" className="sr-only" aria-label="Choose files" onChange={(e) => { take(e.target.files); e.target.value = ""; }} />
    </div>
  );
}

export function UploadResults({ summary, onRemove }: { summary: UploadSummary; onRemove: (index: number) => void }) {
  return (
    <div className="table-scroll">
      <table className="dtable dtable--compact">
        <thead><tr><th>File name</th><th className="num">Size</th><th>Document</th><th>Category</th><th>Type</th><th>Check</th><th /></tr></thead>
        <tbody>
          {summary.files.map((f, i) => (
            <tr key={`${f.file_name}-${i}`} className={f.status === "VALID" ? undefined : "is-fail"}>
              <td><code>{f.file_name}</code>{f.messages.map((m) => <div key={m} className="xsmall muted">{m}</div>)}</td>
              <td className="num small">{f.size ? `${(f.size / 1024).toFixed(1)} KB` : "—"}</td>
              <td className="id">{f.document_id ?? "—"}</td>
              <td className="small">{f.category ?? "—"}</td>
              <td className="small">{f.source_type ?? "—"}</td>
              <td><StatusBadge status={f.status} /></td>
              <td><button className="link-btn" onClick={() => onRemove(i)} aria-label={`Remove ${f.file_name}`}>Remove</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ExpectedChecklist({ summary }: { summary: UploadSummary }) {
  const present = new Set(summary.files.filter((f) => f.status === "VALID").map((f) => f.document_id));
  const categories = [...new Set(EXPECTED_DOCUMENTS.map((d) => d.category))];
  return (
    <div>
      {categories.map((c) => (
        <div key={c}>
          <div className="section-label">{c}</div>
          <table className="dtable dtable--compact"><tbody>
            {EXPECTED_DOCUMENTS.filter((d) => d.category === c).map((d) => (
              <tr key={d.id}>
                <td className="id">{d.id}</td>
                <td className="small">{d.description} <span className="faint">· {d.source_type}{d.required ? "" : " · optional"}</span></td>
                <td className="num">{present.has(d.id) ? <StatusBadge status="PRESENT" label="Present" /> : d.required ? <StatusBadge status="MISSING" label="Missing" /> : <StatusBadge status="NOT_APPLICABLE" label="Not provided" />}</td>
              </tr>
            ))}
          </tbody></table>
        </div>
      ))}
    </div>
  );
}

export function UploadSteps({ current }: { current: number }) {
  const steps = ["Select month", "Add files", "Classify and validate", "Review summary", "Start processing"];
  return (
    <ol className="steps-bar" aria-label="Upload steps">
      {steps.map((s, i) => (
        <li key={s} className={`steps-bar__step${i < current ? " steps-bar__step--done" : i === current ? " steps-bar__step--current" : ""}`}>{i + 1}. {s}</li>
      ))}
    </ol>
  );
}
