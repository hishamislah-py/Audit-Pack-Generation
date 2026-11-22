"""Phase 3B-3 - canonical-layout PREVIEW writer and provenance sidecar.

The canonical-layout re-serialisation has NOT been approved by the owner as a UC-042 submission format. Outputs are
therefore marked PREVIEW_ONLY_NOT_AUTHORISED_FOR_UC042_SUBMISSION, are written only to a caller-chosen directory outside
the UC-042 tree, and nothing is submitted, uploaded or copied into UC-042 (`submit_to_uc042` always refuses).

The writer only reorders columns into the canonical UC-042 order; every cell is the original source string (dates,
amounts, signs and currencies are never converted). It refuses ineligible files and verifies its own output.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .eligibility import HandoffEligibility, source_rows
from .reprocess import ReprocessResult

MARKER = "PREVIEW_ONLY_NOT_AUTHORISED_FOR_UC042_SUBMISSION"
DEFAULT_PROTECTED = [r"C:\Users\artlptp263user\p10\uc042_token_optimisation"]


class HandoffRefused(PermissionError):
    pass


class HandoffNotAuthorised(PermissionError):
    pass


def _protected_roots() -> list[Path]:
    roots = list(DEFAULT_PROTECTED)
    if os.environ.get("UC042_ROOT"):
        roots.append(os.environ["UC042_ROOT"])
    return [Path(r).resolve() for r in roots]


def write_preview(rr: ReprocessResult, eligibility: HandoffEligibility, registry, out_dir: str | Path,
                  now: str | None = None) -> dict:
    if not eligibility.eligible:
        raise HandoffRefused("not eligible for handoff: " + "; ".join(f"#{c.check_id} {c.name}" for c in eligibility.failed))
    out_dir = Path(out_dir).resolve()
    for root in _protected_roots():
        if out_dir == root or root in out_dir.parents:
            raise HandoffRefused(f"refusing to write inside the protected UC-042 tree {root}")
    out_dir.mkdir(parents=True, exist_ok=True)
    schema = registry.get(rr.category)
    canonical = list(schema.csv.header)
    by_field = {m.canonical_field: m for m in rr.result.mapping.mappings}
    order = [by_field[f].source_index for f in canonical]
    rows = source_rows(rr)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(canonical)
    for cells in rows:
        w.writerow([cells[i] for i in order])
    data = buf.getvalue().encode("utf-8")
    # self-check: the output re-reads to exactly the source cells in canonical order
    reread = list(csv.reader(io.StringIO(data.decode("utf-8"))))
    if reread[0] != canonical or any(out != [src[i] for i in order] for out, src in zip(reread[1:], rows)):
        raise HandoffRefused("output self-check failed: a cell differs from its source")
    stem = f"{MARKER}__{rr.category}__{rr.source_sha256[:12]}"
    csv_path, side_path = out_dir / f"{stem}.csv", out_dir / f"{stem}.provenance.json"
    csv_path.write_bytes(data)
    out_sha = hashlib.sha256(data).hexdigest()
    sidecar = {
        "status": MARKER,
        "submission_authorised": False,
        "note": "canonical-layout preview; the format and this sidecar are not approved as a UC-042 submission",
        "source": {"sha256": rr.source_sha256, "intake_id": rr.original_intake_id,
                   "original_filename": rr.original_filename},
        "category": {"category": rr.category, "basis": rr.category_basis, "confirmation_id": rr.confirmation_id},
        "canonical_header": canonical,
        "columns": [{"canonical_field": f, "canonical_position": p, "source_index": by_field[f].source_index,
                     "original_header": by_field[f].original_header, "method": by_field[f].method.value,
                     "rule_id": by_field[f].rule_id, "rule_version": by_field[f].rule_version}
                    for p, f in enumerate(canonical)],
        "ignored_columns": [{"source_index": x["source_position"], "original_header": x["source_header"],
                             "reason": x["reason"], "rule_id": x["rule_id"], "rule_version": x["rule_version"],
                             "note": "excluded from the canonical output by a governed reviewer decision; the source "
                                     "cells remain in the stored original and the records"}
                            for x in rr.result.mapping.ignored_columns],
        "rules_used": rr.rules_used,
        "approval_references": sorted({m.rule_id for m in rr.result.mapping.mappings if m.rule_id}),
        "rows": [{"output_row": i + 1, "source_row": rec.row_number, "source_line": rec.source_line}
                 for i, rec in enumerate(rr.result.records)],
        "validation": {"status": rr.result.metadata.validation_status.value,
                       "errors": rr.result.validation.error_count if rr.result.validation else None,
                       "eligibility": [{"id": c.check_id, "name": c.name, "passed": c.passed, "detail": c.detail}
                                       for c in eligibility.checks]},
        "handoff_timestamp": now or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "output": {"file": csv_path.name, "sha256": out_sha, "bytes": len(data)},
    }
    side_path.write_text(json.dumps(sidecar, indent=1, ensure_ascii=False), encoding="utf-8")
    return {"csv": csv_path, "sidecar": side_path, "output_sha256": out_sha, "sidecar_doc": sidecar}


def submit_to_uc042(*_args, **_kwargs):
    """The UC-042 submission gate is disabled until the owner approves the format and sidecar treatment."""
    raise HandoffNotAuthorised("submission to UC-042 is not authorised (owner decision pending); previews only")
