"""Final audit-pack assembly (spec 06 §5, §9). Deterministic and AI-free: it copies the deterministic pack's values, maps
the selected, re-validated investigations (content.py), and attaches the SUPPLIED closing summary and review record.
It never calls a model, never recalculates, never changes a status and never writes files (persistence.py publishes).

The preview and the final pack are built by the same function; a preview differs only in status, ID and the pending
review, so the analyst reads exactly what GENERATE will produce.

With the analyst's investigation reviews (snapshot.reviewed; schema 1.1) only ACCEPTED investigations contribute AI content.
A REJECTED investigation contributes no AI summary, finding, hypothesis or recommendation: its exception carries the
analyst's decision and exact reason instead. Without them the pack is assembled exactly as before (schema 1.0).
"""
import copy
import hashlib
from datetime import datetime, timezone

from ..investigation import config as inv_config
from ..pack.model import canonical
from .content import evidence_index, investigation_content
from .model import (AI_DISCLAIMER, ANALYST_REVIEW_NOTICE, ASSEMBLER_VERSION, CLOSING_SUMMARY_NOTICE, DATA_HANDLING,
                    FINAL_PACK_SCHEMA_VERSION, GENERATE_MEANING, OUTCOME_FINAL_PACK_SCHEMA_VERSION, CURRENT_RENDERER_VERSION,
                    ClosingSummary, GenerationInfo, ReviewRecord)
from .outcome import outcome_summary
from .summary import summary_sha256

UNEXPLAINED_EVIDENCE_STATUSES = ("NOT_EVIDENCED", "TIMING_PARTIAL", "TIMING_UNVERIFIABLE")


class FinalPackValidationError(Exception):
    """`diagnostics` (optional, structured): why validation refused the pack, e.g. {"rejected_text_leaks": [...]}."""

    def __init__(self, errors, diagnostics=None):
        self.errors = list(errors)
        self.diagnostics = dict(diagnostics or {})
        super().__init__("final pack failed validation: " + "; ".join(self.errors[:10]))


def content_sha256(final):
    """Hash of the canonical final pack without its self-referential fields (pattern of pack.model.content_hash)."""
    body = copy.deepcopy(final)
    body["metadata"]["final_pack_id"] = ""
    body["final_content_sha256"] = ""
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


def _scenario_and_period(pack_id):
    _, scenario, per, year, month, _ = pack_id.split("-")
    return scenario, f"{per}-{year}-{month}"


def _deterministic_sections(pack):
    m, s, rec = pack["metadata"], pack["executive_summary"], pack["reconciliation_summary"]
    return {
        "source_inventory": {"files": pack["evidence_register"]["files"], "inputs": pack["audit_trail"]["inputs"],
                             "dataset": m["source_dataset"],
                             "dataset_note": "scenario_name is a synthetic test label from the dataset metadata",
                             "fingerprints": {k: pack["audit_trail"][k] for k in ("baseline_manifest_sha256", "engine_fingerprint",
                                              "configuration_fingerprint", "pack_layer_fingerprint", "correlation_version")},
                             "processing_run_id": m["processing_run_id"],
                             "missing_evidence": pack["missing_evidence_register"], "intake": pack["audit_trail"]["intake"]},
        "reconciliation_results": {
            "internal_by_currency_day": rec["internal_by_currency_day"], "external_by_account_day": rec["external_by_account_day"],
            "opening_positions": rec["opening_positions"], "client_balances_note": rec["client_balances_note"],
            "control_outcomes": s["control_outcomes"],
            "control_checks": [{k: c[k] for k in ("check_id", "control_code", "control_name", "check_outcome", "result_counts")}
                               for c in pack["control_register"]],
            "settlements": [{"batch_id": b["batch_id"], "counterparty_type": b["counterparty_type"], "settlement_date": b["settlement_date"],
                             "account_id": b["account_id"], "currency": b["currency"], "direction": b["direction"],
                             "net_amount_reported": b["net_amount_reported"],
                             "lines_outcome": (b.get("lines_result") or {}).get("outcome"),
                             "bank_outcome": (b.get("bank_result") or {}).get("outcome"),
                             "fee_top_up_outcome": (b.get("fee_top_up_result") or {}).get("outcome")}
                            for b in pack["settlement_register"]]},
        "relationships": {"investigation_groups": pack["investigation_group_register"]["groups"],
                          "group_statement": pack["investigation_group_register"]["statement"],
                          "candidate_relationships": pack["investigation_group_register"]["candidate_relationships"],
                          "candidate_statement": pack["investigation_group_register"]["candidate_statement"],
                          # enriched runs only (absent otherwise, so default-rule final packs are unchanged): the engine's
                          # relationship register copied verbatim - statuses, proofs, citations (final_pack/validate.py)
                          **({"relationship_register": copy.deepcopy(pack["investigation_group_register"]["relationship_register"])}
                             if pack["investigation_group_register"].get("relationship_register") is not None else {})},
    }


RELATIONSHIP_ASSESSMENT_NOTICE = ("Engine relationships are deterministic: their status and proof are copied from the engine "
                                  "and are never changed by the AI or by this report. The AI's acknowledgement or challenge "
                                  "and the analyst's explanation are shown beside them. An AI challenge is not accepted by "
                                  "the engine; it is a point for the analyst.")


def _relationship_assessments(pack, closing_summary, review):
    """Evidence-bearing relationships (23 Nov 2026): one entry per CONFIRMED relationship of a register 1.1 - the engine's
    status and proof (verbatim), the AI disposition (ACKNOWLEDGED / CHALLENGED with its fields, or NOT_AVAILABLE when no AI
    summary), the common-cause assessments covering the pair, and the analyst's explanation of a challenge. None when the
    pack has no evidence-bearing register (the final pack is then unchanged)."""
    reg = pack["investigation_group_register"].get("relationship_register")
    if not reg or reg.get("schema") != "uc042-relationship-register/1.1":
        return None
    out = closing_summary.output.model_dump() if closing_summary.status == "GENERATED" and closing_summary.output else {}
    disp = {d["relationship_id"]: d for d in out.get("relationship_dispositions") or []}
    notes = {c.relationship_id: c.model_dump() for c in (review.relationship_challenge_reviews if review else [])}
    items = []
    for r in reg["relationships"]:
        if r["status"] != "CONFIRMED":
            continue
        d = disp.get(r["relationship_id"])
        cover = [{"group_id": a["group_id"], "exception_ids": a["exception_ids"], "relationship_verdict": a["relationship_verdict"],
                  "common_cause_status": a.get("common_cause_status"), "common_cause_hypothesis": a["common_cause_hypothesis"],
                  "supporting_evidence": a["supporting_evidence"], "contradicting_evidence": a["contradicting_evidence"],
                  "missing_evidence": a["missing_evidence"]}
                 for a in out.get("group_assessments") or [] if set(r["exception_ids"]) <= set(a["exception_ids"])]
        items.append({"relationship_id": r["relationship_id"], "exception_ids": r["exception_ids"],
                      "relationship_type": r["relationship_type"], "engine_status": r["engine_status"],
                      "register_status": r["status"], "proof": copy.deepcopy(r["proof"]),
                      "ai_disposition": d["disposition"] if d else "NOT_AVAILABLE",
                      "ai_disposition_detail": copy.deepcopy(d) if d else None,
                      "common_cause_assessments": cover,
                      "analyst_explanation": notes.get(r["relationship_id"])})
    return {"notice": RELATIONSHIP_ASSESSMENT_NOTICE, "register_schema": reg["schema"], "items": items}


def _exception_register(pack, snapshot, investigations):
    sel = {s.exception_id: s for s in snapshot.selections}
    inv_by_id = {i["investigation_id"]: i for i in investigations}
    out = []
    for x in pack["exception_register"]["exceptions"]:
        s, att = sel[x["exception_id"]], snapshot.attempts.get(x["exception_id"], {"published": [], "not_published": []})
        inv = inv_by_id.get(s.investigation_id)
        entry = {"inclusion": s.inclusion, "investigation_id": s.investigation_id, "reason": s.reason,
                 "investigation_mode": inv["investigation_mode"] if inv else None,
                 "overall_evidence_assessment": inv["assessment"]["overall_evidence_assessment"] if inv else None,
                 "other_attempts": {"published_ineligible": [i["investigation_id"] for i in att["published"]
                                                             if not i["eligible"]],
                                    "published_not_selected": [i["investigation_id"] for i in att["published"]
                                                               if i["eligible"] and i["investigation_id"] != s.investigation_id],
                                    "not_published": len(att["not_published"])}}
        if snapshot.reviewed:
            entry["analyst_review"] = analyst_review_view(snapshot, s)
            if inv is None and s.inclusion == "INCLUDED":  # rejected: the investigation is named, its AI conclusions are not
                entry["investigation_mode"] = snapshot.bundles[s.investigation_id]["findings"].get("investigation_mode", "fixed")
        out.append({"exception": copy.deepcopy(x), "resolution_status": "UNRESOLVED", "investigation": entry})
    return out


def analyst_review_view(snapshot, selection):
    """The analyst's decision on the exception's selected investigation as reported (None when no investigation is
    included). The rejection reason and the comment are copied exactly as recorded."""
    if selection.inclusion != "INCLUDED":
        return None
    r = snapshot.analyst_reviews[selection.investigation_id]
    view = {"analyst_review_id": r.analyst_review_id, "decision": r.decision, "investigation_id": r.investigation_id,
            "findings_sha256": r.findings_sha256, "findings_schema_version": r.findings_schema_version,
            "reviewer": r.reviewer.model_dump(), "decided_at": r.decided_at, "revision": r.revision}
    if r.decision == "ACCEPT":
        view["comment"] = r.comment
    else:
        view["rejection_reason"] = r.rejection_reason
        view["ai_content"] = "EXCLUDED_REJECTED_BY_ANALYST"
        # The explicit analyst disposition that replaces the rejected investigation's AI content in the report, and the
        # optional comment (kept apart from the mandatory reason; only present when the analyst wrote one).
        view["disposition"] = "REJECTED_BY_ANALYST"
        if r.comment:
            view["comment"] = r.comment
    return view


def _limitations(pack, register, investigations):
    out = [{"source": "PACK", "text": t} for t in pack["statements"]["limitations"]]
    for e in register:
        i = e["investigation"]
        if i["inclusion"] == "NOT_INVESTIGATED":
            out.append({"source": "ASSEMBLER", "text": f"{e['exception']['exception_id']} has no eligible AI investigation; it is "
                                                       "reported from the deterministic results only."})
        elif i["inclusion"] == "EXCLUDED_BY_ANALYST":
            out.append({"source": "ASSEMBLER", "text": f"{e['exception']['exception_id']}: AI investigation excluded by the analyst "
                                                       f"({i['reason']})."})
        elif (i.get("analyst_review") or {}).get("decision") == "REJECT":
            out.append({"source": "ASSEMBLER", "text": f"{e['exception']['exception_id']}: AI investigation {i['investigation_id']} was "
                                                       "REJECTED by the analyst; its AI summary, findings, hypotheses and "
                                                       "recommendations are excluded from this report. The analyst's reason is "
                                                       "reported in the analyst review section."})
    for inv in investigations:
        if inv["evidence_examined"]["retrieval_truncated"]:
            out.append({"source": "INVESTIGATION", "text": f"{inv['investigation_id']}: evidence retrieval reached its record limit."})
        if any(f["title"] is None for f in inv["confirmed_findings"]) or any(h["rationale"] is None for h in inv["hypotheses"]):
            out.append({"source": "INVESTIGATION", "text": f"{inv['investigation_id']} uses findings schema "
                                                           f"{inv['versions']['findings_schema']}; explanatory fields it did not "
                                                           "produce are shown as 'not supplied' and were not back-filled."})
    out += [{"source": "ASSEMBLER", "text": t} for t in (
        "AI investigations examine one exception at a time; there is no group-level AI investigation.",
        "Supporting PDF documents (IN-15..IN-19) are not used as AI evidence.",
        "Reported values are copied from the deterministic engine and source records; this report recalculates nothing.",
        DATA_HANDLING)]
    return out


def _add_analyst_reviews(final, register):
    """Schema 1.1 additions: the analyst's decision per included investigation is in the exception register; this adds
    the counts, the notice and the provenance of each decision. The workflow history itself is not part of the report."""
    decisions = [e["investigation"]["analyst_review"] for e in register if e["investigation"].get("analyst_review")]
    accepted = sum(d["decision"] == "ACCEPT" for d in decisions)
    final["final_pack_schema_version"] = OUTCOME_FINAL_PACK_SCHEMA_VERSION  # 1.3 (model.py); 1.1 packs are only re-rendered
    final["metadata"]["report_renderer"] = CURRENT_RENDERER_VERSION  # 3.0: outcome-first layout (report_v3.py)
    final["metadata"]["completeness"]["investigation_coverage"].update(accepted_by_analyst=accepted,
                                                                      rejected_by_analyst=len(decisions) - accepted)
    final["analyst_reviews"] = {"notice": ANALYST_REVIEW_NOTICE, "accepted": accepted, "rejected": len(decisions) - accepted}
    final["audit_trail"]["analyst_reviews"] = [{k: d[k] for k in ("analyst_review_id", "investigation_id", "decision",
                                                                   "findings_sha256", "revision", "decided_at")} for d in decisions]


def _add_outcome_layer(final, pack):
    """Schema 1.3 additions: the engine's own note on each NO_FINDINGS check (copied, never written here) and the
    deterministic outcome summary (outcome.py), computed last so it reads the finished content."""
    notes = {c["check_id"]: c["check_outcome_note"] for c in pack["control_register"] if c.get("check_outcome_note")}
    for c in final["reconciliation_results"]["control_checks"]:
        if c["check_id"] in notes:
            c["check_outcome_note"] = notes[c["check_id"]]
    final["outcome_summary"] = outcome_summary(final)


def assemble(snapshot, closing_summary, review=None, generation=None, preview=False):
    """Build (and validate) a final pack, or a preview when preview=True (review may then be None).
    Raises FinalPackValidationError listing every problem."""
    from .validate import validate_final_pack
    pack = snapshot.pack
    m, s = pack["metadata"], pack["executive_summary"]
    closing_summary = closing_summary if isinstance(closing_summary, ClosingSummary) else ClosingSummary.model_validate(closing_summary)
    review = None if review is None else (review if isinstance(review, ReviewRecord) else ReviewRecord.model_validate(review))
    generation = generation or GenerationInfo()
    generation = generation if isinstance(generation, GenerationInfo) else GenerationInfo.model_validate(generation)
    generated_at = generation.generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")

    investigations = [investigation_content(snapshot.bundles[sel.investigation_id])
                      for sel in snapshot.selections if snapshot.accepted(sel)]
    register = _exception_register(pack, snapshot, investigations)
    det = _deterministic_sections(pack)
    assessments = {}
    for inv in investigations:
        a = inv["assessment"]["overall_evidence_assessment"]
        assessments[a] = assessments.get(a, 0) + 1
    gap_counts = {"ENGINE_MISSING": 0, "SEARCHED_NOT_FOUND": 0, "AI_IDENTIFIED": 0}
    for inv in investigations:
        for g in inv["evidence_gaps"]:
            for t in g["subtypes"]:
                gap_counts[t] += 1
    inclusion = {}
    for e in register:
        inclusion[e["investigation"]["inclusion"]] = inclusion.get(e["investigation"]["inclusion"], 0) + 1
    scenario, period = _scenario_and_period(m["pack_id"])

    final = {
        "final_pack_schema_version": FINAL_PACK_SCHEMA_VERSION,
        "metadata": {
            "final_pack_id": "", "version": generation.version, "supersedes_final_pack_id": generation.supersedes_final_pack_id,
            "status": "PREVIEW" if preview else "GENERATED", "generated_at": generated_at,
            "source_pack": {"pack_id": m["pack_id"], "pack_content_sha256": pack["audit_trail"]["pack_content_sha256"],
                            "pack_schema_version": m["pack_schema_version"], "processing_run_id": m["processing_run_id"]},
            "reporting_period": m["reporting_period"], "entity": m["entity"], "asset_pool_id": m["asset_pool_id"],
            "currency_scope": m["currency_scope"], "accounts": m["accounts"],
            "reconciliation_days_count": len(m["reconciliation_days"]),
            "completeness": {"evidence_completeness": s["evidence_completeness"], "engine_case_status": s["engine_case_status"],
                             "investigation_coverage": {"exceptions": len(register), "included": inclusion.get("INCLUDED", 0),
                                                        "not_investigated": inclusion.get("NOT_INVESTIGATED", 0),
                                                        "excluded_by_analyst": inclusion.get("EXCLUDED_BY_ANALYST", 0)},
                             "closing_summary": closing_summary.status}},
        "executive_summary": {
            "deterministic": copy.deepcopy(s),
            "exceptions": {"total": len(register), "unresolved": sum(e["resolution_status"] == "UNRESOLVED" for e in register),
                           "by_severity": s["exceptions"]["by_severity"]},
            "investigations": {"included": len(investigations), "by_assessment": assessments,
                               "modes": {mode: sum(i["investigation_mode"] == mode for i in investigations)
                                         for mode in sorted({i["investigation_mode"] for i in investigations})}},
            "key_confirmed_observations": [{"ref": f["ref"], "title": f["title"], "description": f["description"]}
                                           for inv in investigations for f in inv["confirmed_findings"]],
            "material_unexplained_differences": [
                {"exception_id": e["exception"]["exception_id"], "amount": e["exception"]["amount"], "currency": e["exception"]["currency"],
                 "category": e["exception"]["category"], "evidence_status": e["exception"]["evidence_status"]}
                for e in register if e["exception"]["evidence_status"] in UNEXPLAINED_EVIDENCE_STATUSES],
            "outstanding_evidence_gaps": {"engine_missing_items": s["missing_evidence_items"], "by_subtype": gap_counts,
                                          "refs": [g["ref"] for inv in investigations for g in inv["evidence_gaps"]]},
            "statement": ("No exceptions were raised by the deterministic engine." if not register else
                          f"{len(register)} exception(s); all remain UNRESOLVED and are reported in full.")},
        **det,
        "exception_register": register,
        "ai_investigations": investigations,
        "evidence_index": evidence_index(investigations, snapshot.bundles),
        "human_review": (review.model_dump() | {"closing_summary_status": closing_summary.status}) if review else
                        {"status": "PENDING_DECISION", "note": "Preview: no human decision has been recorded."},
        "limitations": _limitations(pack, register, investigations),
        "audit_trail": {
            "source_pack": {"pack_id": m["pack_id"], "pack_content_sha256": pack["audit_trail"]["pack_content_sha256"]},
            "review_snapshot_sha256": snapshot.sha256,
            "investigations": [{"investigation_id": i["investigation_id"], "exception_id": i["exception_id"],
                                "artefact_path": snapshot.bundles[i["investigation_id"]]["path"].relative_to(
                                    snapshot.bundles[i["investigation_id"]]["path"].parents[3]).as_posix(),
                                "findings_sha256": i["findings_sha256"], "evidence_packet_sha256": i["evidence_packet_sha256"],
                                "evidence_ledger_sha256": i["evidence_ledger_sha256"], "versions": i["versions"],
                                "verified": True} for i in investigations],
            "closing_summary": {"status": closing_summary.status, "source_fingerprint": closing_summary.source_fingerprint,
                                "closing_summary_sha256": summary_sha256(closing_summary),
                                "prompt_version": closing_summary.prompt_version,
                                "model": closing_summary.model_metadata.get("model"),
                                "provider": closing_summary.model_metadata.get("provider")},
            "assembler_version": ASSEMBLER_VERSION, "validation_rules_version": inv_config.FINDINGS_SCHEMA_VERSION,
            "traceability": ("report item ref -> ai_investigations[].* (evidence_refs) -> evidence_index (file, line, file SHA-256, "
                             "retrieved_via, join_key) -> investigation evidence ledger (ledger SHA-256) -> source CSV line "
                             "(file SHA-256 in source_inventory.inputs); deterministic figures -> result_ids -> original pack "
                             "control_register (pack_content_sha256)")},
        "statements": {"synthetic_notice": pack["statements"]["synthetic_notice"],
                       "not_a_compliance_opinion": pack["statements"]["not_a_compliance_opinion"],
                       "generate_meaning": GENERATE_MEANING, "ai_disclaimer": AI_DISCLAIMER,
                       "closing_summary_notice": CLOSING_SUMMARY_NOTICE},
        "closing_summary": closing_summary.model_dump(),
        "final_content_sha256": "",
    }
    rel_assessments = _relationship_assessments(pack, closing_summary, review)
    if rel_assessments is not None:
        final["relationship_assessments"] = rel_assessments
    if snapshot.reviewed:
        _add_analyst_reviews(final, register)
        _add_outcome_layer(final, pack)
    digest = content_sha256(final)
    final["metadata"]["final_pack_id"] = (f"PREVIEW-{scenario}-{period}-{snapshot.sha256[:12]}" if preview
                                          else f"FAP-{scenario}-{period}-v{generation.version}-{digest[:12]}")
    final["final_content_sha256"] = digest
    errors = validate_final_pack(final, snapshot, closing_summary, review, preview=preview)
    if errors:
        from .validate import rejected_text_diagnostics
        raise FinalPackValidationError(errors, {"errors": errors,
                                                "rejected_text_leaks": rejected_text_diagnostics(final, snapshot)})
    return final


def assemble_preview(snapshot, closing_summary):
    return assemble(snapshot, closing_summary, preview=True)


def assemble_final_pack(snapshot, closing_summary, review, generation=None):
    if review is None:
        raise FinalPackValidationError(["a recorded human review decision is required to assemble a final pack"])
    return assemble(snapshot, closing_summary, review, generation, preview=False)
