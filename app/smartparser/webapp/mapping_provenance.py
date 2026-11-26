"""Fix8 D3 - column-level mapping provenance of an activated package snapshot (contract I-3).

`build_mapping_provenance(ctx, package_id, snapshot_id)` is computed ONLY from stored state: the snapshot entries, the
file versions, their column-review case / proposal session, the governed file-mapping rules, the canonical preview's
provenance sidecar (SHA-verified original for the header) and the hash-chained audit log. Nothing is inferred: a value
that was never recorded stays null and a note says so. It is read-only (no audit event, no file written).

Schema "ringfence-mapping-provenance/1.0":
{"schema", "package_id", "snapshot_id",
 "files": [{"evidence_category", "file_version_id", "version_number", "original_filename", "source_sha256", "intake_id",
            "version_status", "review_kind" | None,
            "columns": [{"source_position", "source_header", "canonical_field" | None,
                         "disposition": MAPPED | IGNORED | UNRESOLVED,
                         "method": DETERMINISTIC_EXACT | DETERMINISTIC_POLICY | AI_PROPOSED | ANALYST_DEFINED |
                                   ANALYST_IGNORED | RULE,
                         "rule_id", "rule_version", "proposal_id", "proposal_class", "decided_by", "decided_at",
                         "confirmed_by", "confirmed_at", "validation": PASS | FAIL | NOT_RECORDED,
                         "audit_event_seqs": [int]}]}],
 "notes": [str]}
`source_position` is 1-based (the analyst application's column numbering).
"""
from __future__ import annotations

import hashlib
import json

SCHEMA = "ringfence-mapping-provenance/1.0"
METHODS = ("DETERMINISTIC_EXACT", "DETERMINISTIC_POLICY", "AI_PROPOSED", "ANALYST_DEFINED", "ANALYST_IGNORED", "RULE")
DISPOSITIONS = ("MAPPED", "IGNORED", "UNRESOLVED")


def _events_by_intake(events: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for e in events:
        if e.get("intake_id"):
            out.setdefault(e["intake_id"], []).append(e)
    return out


def _sidecar(svc, v) -> dict | None:
    h = v.handoff
    if h is None or not h.provenance:
        return None
    try:
        return json.loads(svc.store.abs(h.provenance).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _headers(svc, v, case, session, side) -> list[str] | None:
    if case is not None:
        return list(case.headers)
    if session is not None:
        return list(session.headers)
    data = svc.evidence.read_original(v.source_sha256)
    if data is not None and hashlib.sha256(data).hexdigest() == v.source_sha256 and data[:5] != b"%PDF-":
        from ..mapping.financial import read_columns
        return read_columns(data, v.original_filename)[0]
    return None


def _rule(svc, rule_id: str | None) -> dict | None:
    if not rule_id:
        return None
    for r in svc.o.store.read("file_mappings").get("file_mappings", []):
        if r.get("file_mapping_id") == rule_id:
            return r
    return None


def _det_method(header: str, field: str | None, side_method: str | None) -> str:
    if side_method in ("alias", "approved_layout"):
        return "RULE"
    if field is not None and header == field:
        return "DETERMINISTIC_EXACT"
    return "DETERMINISTIC_POLICY"


def _file(ctx, svc, pkg, entry, by_intake, notes) -> dict:
    v = pkg.versions[entry.file_version_id]
    case = svc.store.load_case(pkg.package_id, v.review_case_id) if v.review_case_id else None
    session = None
    if v.review_session_id:
        session, _ = svc.store.load_session(pkg.package_id, v.review_session_id)
    out = {"evidence_category": v.evidence_category, "file_version_id": v.file_version_id,
           "version_number": v.version_number, "original_filename": v.original_filename,
           "source_sha256": v.source_sha256, "intake_id": v.intake_id, "version_status": v.version_status,
           "review_kind": case.kind if case else ("PROPOSAL_REVIEW" if session else None), "columns": []}
    tag = f"{v.evidence_category} {v.file_version_id}"
    if v.handoff is not None and v.handoff.basis == "PDF_CONTENT_CLASSIFICATION_ONLY":
        notes.append(f"{tag}: PDF evidence (classification only); no column mapping exists")
        return out
    side = _sidecar(svc, v)
    if side is None:
        notes.append(f"{tag}: no canonical-preview provenance sidecar is recorded; canonical fields and rule ids are "
                     "taken from the review record only")
    headers = _headers(svc, v, case, session, side)
    if headers is None:
        notes.append(f"{tag}: the stored original is unavailable; columns cannot be listed")
        return out
    mapped = {c["source_index"]: c for c in (side or {}).get("columns", [])}
    ignored = {c["source_index"]: c for c in (side or {}).get("ignored_columns", [])}
    validation = "NOT_RECORDED" if v.handoff is None or not v.handoff.checks else \
        ("PASS" if v.handoff.eligible else "FAIL")
    evs = by_intake.get(v.intake_id, [])
    vid_events = [e for e in ctx.events() if (e.get("details") or {}).get("file_version_id") == v.file_version_id]
    eff = case.effective() if case else {}
    rule_id_case = case.file_mapping_id if case else None
    rule_doc = _rule(svc, rule_id_case)
    resolved = next((e for e in evs if e["event_type"] == "INTAKE_CASE_RESOLVED"), None)
    confirms = [e for e in vid_events if e["event_type"] == "ANALYST_REVIEW_CONFIRMED"]
    if resolved is not None:
        # Fix8 D2: the confirmation is recorded right AFTER the case resolution; before Fix8 it was recorded before
        # the attempt, so a failed attempt left a confirmation event that did not take effect
        after = [e for e in confirms if e["seq"] > resolved["seq"]]
        before = [e for e in confirms if e["seq"] <= resolved["seq"]]
        if after:
            confirms = after[:1]
        else:
            if len(before) > 1:
                notes.append(f"{tag}: {len(before)} ANALYST_REVIEW_CONFIRMED events precede the case resolution (seqs "
                             f"{[e['seq'] for e in before]}); earlier ones belong to attempts that did not take effect "
                             "(pre-Fix8 D2 behaviour); the last one is used")
            confirms = before[-1:]
    conf_ev = confirms[-1] if confirms else None
    if conf_ev is not None:
        confirmed_by, confirmed_at = conf_ev.get("actor_id"), conf_ev.get("at")
    elif resolved is not None:
        confirmed_by, confirmed_at = resolved.get("actor_id"), resolved.get("at")
    elif session is not None and v.confirmation is not None:
        confirmed_by, confirmed_at = v.confirmation.reviewer_id, v.confirmation.confirmed_at
    else:
        confirmed_by = confirmed_at = None
    if case is None and session is None:
        notes.append(f"{tag}: mapped by the deterministic rules at intake; no analyst decision or confirmation exists "
                     "for its columns")
    sess_dec = {int(k): d for k, d in (session.decisions.items() if session else [])}
    sess_cols = {c.source_index: c for c in (session.columns if session else [])}
    sess_resolved = {c["source_index"]: c["canonical_field"] for c in (session.resolved_columns if session else [])}
    legacy_rule_note = False
    for i, h in enumerate(headers):
        m, ig = mapped.get(i), ignored.get(i)
        fld = m["canonical_field"] if m else None
        col = {"source_position": i + 1, "source_header": h, "canonical_field": fld,
               "disposition": "MAPPED" if m else "IGNORED" if ig else "UNRESOLVED",
               "method": None, "rule_id": (m or ig or {}).get("rule_id"), "rule_version": (m or ig or {}).get("rule_version"),
               "proposal_id": None, "proposal_class": None, "decided_by": None, "decided_at": None,
               "confirmed_by": confirmed_by if (case or session) else None,
               "confirmed_at": confirmed_at if (case or session) else None,
               "validation": validation, "audit_event_seqs": []}
        seqs = set()
        if case is not None:
            cc = case.columns[i]
            d = eff.get(i)
            if d is not None:
                col["decided_by"], col["decided_at"] = d.reviewer_id, d.decided_at
                seqs |= {e["seq"] for e in evs if e["event_type"] == "INTAKE_DECISION"
                         and (e.get("details") or {}).get("source_index") == i}
            from_proposal = cc.suggestion_basis == "proposal" or bool(cc.proposal_field)
            if from_proposal and case.proposal_id:
                col["proposal_id"], col["proposal_class"] = case.proposal_id, cc.validation_class
            if ig or (d is not None and d.action == "IGNORE_COLUMN"):
                col["method"] = "ANALYST_IGNORED"
            elif d is not None and d.action == "CHANGE":
                col["method"] = "AI_PROPOSED" if (cc.proposal_field and d.canonical_field == cc.proposal_field) \
                    else "ANALYST_DEFINED"
            elif d is not None and cc.suggestion_basis == "proposal":
                col["method"] = "AI_PROPOSED"
            else:
                col["method"] = _det_method(h, fld or cc.suggested_field, (m or {}).get("method"))
            if col["disposition"] != "UNRESOLVED" and not col["rule_id"] and rule_id_case and rule_doc is not None:
                # the case's governed file mapping covers every position of this exact header list (stored fact)
                col["rule_id"], col["rule_version"] = rule_id_case, int(rule_doc.get("rule_version", 1))
                legacy_rule_note = True
        elif session is not None:
            sc, d = sess_cols.get(i), sess_dec.get(i)
            if sc is not None:
                col["proposal_id"], col["proposal_class"] = session.proposal_id, str(sc.validation_class)
            if d is not None:
                col["decided_by"], col["decided_at"] = d.reviewer_id, d.decided_at
                col["method"] = "AI_PROPOSED" if d.action == "APPROVE" else "ANALYST_DEFINED" \
                    if d.action == "CHANGE" else "ANALYST_IGNORED"
            else:
                col["method"] = _det_method(h, sess_resolved.get(i) or fld, (m or {}).get("method"))
        else:
            col["method"] = "ANALYST_IGNORED" if ig else _det_method(h, fld, (m or {}).get("method"))
        rid = col["rule_id"]
        if rid:
            seqs |= {e["seq"] for e in evs if e.get("rule_id") == rid}
        if col["proposal_id"]:
            seqs |= {e["seq"] for e in evs if e["event_type"] in ("PROVIDER_CALL", "PROPOSAL_DEDUPLICATED")
                     or (e.get("proposal_id") == col["proposal_id"] and e["event_type"] != "INTAKE_DECISION")}
        seqs |= {e["seq"] for e in vid_events if e["event_type"] == "ANALYST_MAPPING_CLARIFIED"
                 and (e.get("details") or {}).get("source_index") == i}
        if conf_ev is not None and (case or session):
            seqs.add(conf_ev["seq"])
        if resolved is not None:
            seqs.add(resolved["seq"])
        col["audit_event_seqs"] = sorted(seqs)
        out["columns"].append(col)
    if legacy_rule_note:
        notes.append(f"{tag}: the preview sidecar was written before rule attribution (Fix8 D3); rule ids are taken "
                     f"from the review case's governed file mapping {rule_id_case}, which covers every column")
    if (case or session) and conf_ev is None:
        notes.append(f"{tag}: no ANALYST_REVIEW_CONFIRMED event is recorded for this version; confirmed_by/at are "
                     "taken from the case resolution / category confirmation" if confirmed_by else
                     f"{tag}: no confirmation event is recorded; confirmed_by/at are null")
    return out


def build_mapping_provenance(ctx, package_id: str, snapshot_id: str) -> dict:
    svc = ctx.svc
    pkg = svc.load(package_id)
    if snapshot_id not in pkg.snapshot_ids:
        raise LookupError(f"{snapshot_id} is not a snapshot of {package_id}")
    snap = svc.store.load_snapshot(package_id, snapshot_id)
    by_intake = _events_by_intake(ctx.events())
    notes: list[str] = []
    files = [_file(ctx, svc, pkg, e, by_intake, notes) for e in snap.entries]
    return {"schema": SCHEMA, "package_id": package_id, "snapshot_id": snapshot_id, "files": files, "notes": notes}
