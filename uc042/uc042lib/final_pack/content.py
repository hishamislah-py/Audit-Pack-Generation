"""Deterministic mapping of validated investigation artefacts into final-pack AI content (spec 06 §4). Values are copied
from the stored findings and evidence; nothing is recalculated, reworded or generated here."""
import re

from ..investigation.validation import classification_summary
from .sources import evidence_of, output_of

# Fields copied as "exact amounts and dates" for a finding: money, balances, differences and dates/timestamps of the
# records it cites, plus currency and debit/credit indicator for context. Values are the source strings, verbatim.
_AMOUNT_FIELD = re.compile(r"(amount|balance|difference|requirement|resource|item_[a-d]|gross|net_|fees|adjustments)")
_DATE_FIELD = re.compile(r"(date|_ts)$")
_CONTEXT_FIELDS = ("currency", "dc_indicator", "balance_dc_indicator")


def _ref(inv_id, item_id):
    return f"{inv_id}#{item_id}"


def amounts_and_dates(evidence_ids, evidence):
    records = {r["evidence_id"]: r for r in evidence["source_records"]}
    results = {r["result_id"]: r for r in evidence["control_results"]}
    out = []
    for eid in evidence_ids:
        if eid in records:
            for field, value in records[eid]["fields"].items():
                if value and (_AMOUNT_FIELD.search(field) or _DATE_FIELD.search(field) or field in _CONTEXT_FIELDS):
                    out.append({"evidence_id": eid, "field": field, "value": value})
        elif eid in results:
            for field in ("computed", "reported"):
                if results[eid].get(field):
                    out.append({"evidence_id": eid, "field": field, "value": results[eid][field]})
    return out


def _gap_subtypes(item, miss_ids, not_found_ids):
    rel = set(item.related_ids)
    subtypes = [t for t, hit in (("ENGINE_MISSING", rel & miss_ids), ("SEARCHED_NOT_FOUND", rel & not_found_ids)) if hit]
    return subtypes or ["AI_IDENTIFIED"]


def investigation_content(bundle):
    """The final-pack representation of one selected investigation."""
    f, out, evidence = bundle["findings"], output_of(bundle), evidence_of(bundle)
    inv_id, meta = f["investigation_id"], f.get("model_metadata") or {}
    miss_ids = {m["item_id"] for m in evidence["missing_evidence"]}
    not_found = {s["search_id"]: s for s in evidence["searches"] if s["result"] == "NOT_FOUND"}
    hyps = [{"ref": _ref(inv_id, h.hypothesis_id), "class": "HYPOTHESIS", "hypothesis_id": h.hypothesis_id,
             "description": h.possible_explanation, "rationale": h.rationale, "supporting_evidence": h.supporting_evidence,
             "contradictory_evidence": h.contradictory_evidence, "limitations": h.limitations,
             "verification_status": "NOT_ESTABLISHED"} for h in out.hypotheses]
    gaps = [{"ref": _ref(inv_id, m.item_id), "class": "EVIDENCE_GAP", "item_id": m.item_id,
             "subtypes": _gap_subtypes(m, miss_ids, set(not_found)), "description": m.description,
             "expected_source": m.expected_source, "impact": m.impact, "related_ids": m.related_ids} for m in out.missing_evidence]
    findings = []
    for x in out.confirmed_findings:
        cited = list(dict.fromkeys(x.evidence_ids + x.supporting_records))
        related = [h["ref"] for h in hyps if set(h["supporting_evidence"] + h["contradictory_evidence"]) & set(cited)]
        related += [g["ref"] for g in gaps if set(g["related_ids"]) & set(cited)]
        findings.append({"ref": _ref(inv_id, x.finding_id), "class": "EVIDENCE_CONFIRMED_OBSERVATION", "finding_id": x.finding_id,
                         "title": x.title, "description": x.claim, "evidence_relationship": x.explanation,
                         "audit_relevance": x.audit_relevance, "establishes": x.establishes,
                         "does_not_establish": x.does_not_establish,
                         "evidence_refs": x.evidence_ids, "supporting_records": x.supporting_records,
                         "amounts_and_dates": amounts_and_dates(cited, evidence),
                         "linked_relationships": [r for r in evidence["relationships"] if r["from"] in cited and r["to"] in cited],
                         "related_open_items": related})
    conflicts = [{"ref": _ref(inv_id, c.item_id), "class": "CONFLICT", "source": "AI", "description": c.description,
                  "compared_evidence": c.compared_evidence, "same_measure_and_scope": c.same_measure_and_scope,
                  "evidence_refs": c.evidence_ids} for c in out.contradictory_evidence]
    conflicts += [{"ref": _ref(inv_id, c["conflict_id"]), "class": "CONFLICT", "source": "DETERMINISTIC",
                   "description": c["description"], "compared_evidence": [], "same_measure_and_scope": None,
                   "evidence_refs": c["evidence_ids"]} for c in evidence["conflicts"]]
    ts = f.get("tool_summary") or {}
    return {
        "investigation_id": inv_id, "exception_id": f["exception_id"], "investigation_mode": f.get("investigation_mode", "fixed"),
        "provider": meta.get("provider"), "model": meta.get("model"), "simulated": meta.get("simulated"),
        "versions": {"prompt": meta.get("prompt_version"), "findings_schema": meta.get("findings_schema_version"),
                     "workflow": meta.get("workflow_version"), "tool_registry": meta.get("tool_registry_version") or None},
        "investigated_at": f.get("investigated_at"), "route": f.get("investigation_route"),
        "evidence_packet_sha256": f["evidence_packet_sha256"], "evidence_ledger_sha256": f.get("evidence_ledger_sha256", ""),
        "findings_sha256": bundle["findings_sha256"],
        "validation": {"status": f["validation_status"], "revalidated": True},
        "evidence_examined": {"records_initial": len(bundle["packet"]["source_records"]),
                              "records_final": len(evidence["source_records"]),
                              "source_files": sorted({r["file_id"] for r in evidence["source_records"]}),
                              "searches": len(evidence["searches"]), "llm_calls": ts.get("llm_calls"),
                              "tool_calls_requested": ts.get("tool_calls_requested"), "tool_rounds": ts.get("tool_rounds"),
                              "tools_used": ts.get("tools_used", []), "retrieval_truncated": evidence.get("retrieval_truncated", False)},
        "assessment": {"ref": _ref(inv_id, "ASSESSMENT"), "class": "AI_INVESTIGATIVE_ASSESSMENT",
                       "summary": out.investigation_summary, "overall_evidence_assessment": out.overall_evidence_assessment},
        "confirmed_findings": findings, "hypotheses": hyps, "conflicts": conflicts, "evidence_gaps": gaps,
        "not_found_searches": [{"search_id": s["search_id"], "description": s["description"]} for s in not_found.values()],
        "unverified_relationships": [{"candidate_id": c["candidate_id"], "exception_ids": c["exception_ids"], "basis": c["basis"],
                                      "label": "UNVERIFIED - NOT EVIDENCE-BACKED"} for c in evidence["candidate_relationships"]],
        "next_steps": [{"ref": _ref(inv_id, s.step_id), "class": "SUGGESTED_NEXT_STEP", "action": s.action,
                        "rationale": s.rationale, "evidence_needed": s.evidence_needed} for s in out.recommended_next_steps],
        "open_questions": [{"ref": _ref(inv_id, f"Q-{i + 1:02d}"), "class": "OPEN_QUESTION", "text": q}
                           for i, q in enumerate(out.open_questions)],
        "classification_summary": classification_summary(out, evidence),
    }


def cited_ids(inv):
    """Every evidence ID an investigation's final-pack items rely on, with the items that cite it."""
    cites = {}

    def add(ids, ref):
        for i in ids:
            cites.setdefault(i, []).append(ref)
    for x in inv["confirmed_findings"]:
        add(x["evidence_refs"] + x["supporting_records"], x["ref"])
    for h in inv["hypotheses"]:
        add(h["supporting_evidence"] + h["contradictory_evidence"], h["ref"])
    for c in inv["conflicts"]:
        add(c["evidence_refs"] + c["compared_evidence"], c["ref"])
    for g in inv["evidence_gaps"]:
        add(g["related_ids"], g["ref"])
    return cites


def evidence_index(investigations, bundles):
    """Cited source records only (not whole files), with provenance; keyed by evidence ID."""
    index = {}
    for inv in investigations:
        records = {r["evidence_id"]: r for r in evidence_of(bundles[inv["investigation_id"]])["source_records"]}
        for eid, refs in sorted(cited_ids(inv).items()):
            if eid not in records:
                continue  # control results, searches, MISS/CONF/candidate IDs are indexed in their own sections
            r = records[eid]
            entry = index.setdefault(eid, {"file_id": r["file_id"], "record_type": r["record_type"], "source_file": r["source_file"],
                                           "source_line": r["source_line"], "file_sha256": r["file_sha256"],
                                           "retrieved_via": r["retrieved_via"], "join_key": r["join_key"], "fields": r["fields"],
                                           "from_investigations": [], "cited_by": []})
            entry["from_investigations"] = sorted(set(entry["from_investigations"]) | {inv["investigation_id"]})
            entry["cited_by"] = sorted(set(entry["cited_by"]) | set(refs))
    return index
