// Final audit-pack building blocks: integrity status (verified / failed / not available) and the pack record.
import type { ReactNode } from "react";
import type { FinalPackDetail, FinalPackDocument, FinalPackVerification } from "../../api/types";
import { dateTime } from "../../lib/format";
import { Notice, StatusBadge } from "../common";

export function IntegrityStatus({ verification, loading }: { verification: FinalPackVerification | null | undefined; loading?: boolean }) {
  if (loading) return <StatusBadge status="RUNNING" label="Verifying integrity…" />;
  if (verification === null) return <StatusBadge status="SIMULATED" label="Integrity: not verified (simulated pack)" />;
  if (!verification) return null;
  return verification.verified ? <StatusBadge status="VERIFIED" label="✓ Integrity verified" /> : <StatusBadge status="FAILED" label="Integrity verification failed" />;
}

export function IntegrityDetail({ verification }: { verification: FinalPackVerification | null | undefined }) {
  if (verification === null) {
    return <Notice tone="mock" title="Integrity verification not available">This pack is a simulated record from the design phase. The backend verifies manifest hashes, the content hash and both renderings for real final packs.</Notice>;
  }
  if (!verification) return null;
  return verification.verified
    ? <Notice tone="ok" title="Integrity verified">Manifest hashes, the content hash and both renderings (HTML, PDF) match the canonical JSON.</Notice>
    : <Notice tone="bad" title="Integrity verification failed"><ul>{verification.problems.map((p) => <li key={p}>{p}</li>)}</ul></Notice>;
}

export function PackRecord({ detail, doc, integrity }: { detail: FinalPackDetail; doc?: FinalPackDocument; integrity: ReactNode }) {
  const refs = doc?.exception_register ?? [];
  const rows: Array<[string, ReactNode]> = [
    ["Final audit-pack ID", <code>{detail.final_pack_id}</code>],
    ["Version", `${detail.version}${detail.supersedes_final_pack_id ? ` (supersedes ${detail.supersedes_final_pack_id})` : ""}`],
    ["Original deterministic pack", <><code>{detail.source_pack.pack_id}</code><div className="xsmall muted mono">{detail.source_pack.pack_content_sha256}</div></>],
    ["Investigation references", refs.length ? (
      <div className="stack stack--sm">{refs.map((e) => (
        <div key={e.exception.exception_id} className="small"><code>{e.investigation.investigation_id ?? "—"}</code> → <code>{e.exception.exception_id}</code>{" "}
          <span className="muted">({e.investigation.inclusion.replace(/_/g, " ").toLowerCase()})</span></div>
      ))}</div>) : "No exceptions"],
    ["Generation time", dateTime(detail.generated_at)],
    ["Authorised by (GENERATE)", `${detail.human_review.reviewer?.display_name} (${detail.human_review.reviewer?.user_id}) · ${dateTime(detail.human_review.decided_at)}`],
    ["Reviewer note", detail.human_review.comment || "—"],
    ["Unresolved exceptions", <span className="amount-bad">{refs.length} carried in the pack as UNRESOLVED</span>],
    ["Integrity status", integrity],
  ];
  return (
    <table className="record"><tbody>{rows.map(([k, v]) => <tr key={k}><td>{k}</td><td>{v}</td></tr>)}</tbody></table>
  );
}
