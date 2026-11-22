"""Deterministic validation of an assembled final pack (spec 06 §5.4, Phase 1 §9). It re-checks the inputs independently
of how assemble.py built the document; any problem prevents publication. Errors are specific and actionable."""
import re

from ..investigation.validation import CAUSE_PATTERNS, RESOLUTION_PATTERNS, claims_nonexistence
from .content import cited_ids
from .model import (ACKNOWLEDGEMENT_TEXT, CURRENT_RENDERER_VERSION, FINAL_PACK_ID_RE, FINAL_PACK_SCHEMA_VERSION,
                    OUTCOME_FINAL_PACK_SCHEMA_VERSION, SUPPORTED_PACK_SCHEMAS)
from .outcome import outcome_summary
from .sources import check_eligibility, evidence_of, load_pack, output_of
from .summary import (closing_summary_input, closing_summary_required, summary_fingerprint, summary_sha256,
                      validate_closing_summary)


def _pack_checks(final, snapshot):
    errors, pack = [], snapshot.pack
    src = final["metadata"]["source_pack"]
    try:
        disk = load_pack(src["pack_id"], snapshot.packs_root)  # FV1/FV2: still present and unmodified (identity + content hash)
        if disk["audit_trail"]["pack_content_sha256"] != pack["audit_trail"]["pack_content_sha256"]:
            errors.append("original pack on disk differs from the reviewed snapshot")
    except Exception as e:
        errors.append(f"original deterministic pack cannot be loaded and verified: {e}")
    if src["pack_content_sha256"] != pack["audit_trail"]["pack_content_sha256"] or \
            snapshot.content["pack"]["pack_content_sha256"] != src["pack_content_sha256"]:
        errors.append("original pack content hash does not match the reviewed snapshot")
    if src["pack_schema_version"] not in SUPPORTED_PACK_SCHEMAS:
        errors.append(f"unsupported original pack schema {src['pack_schema_version']!r}")
    return errors


def _register_checks(final, pack):
    """FV10/FV11: every exception preserved once, in order, verbatim, labelled UNRESOLVED."""
    errors = []
    orig, reg = pack["exception_register"]["exceptions"], final["exception_register"]
    if [x["exception_id"] for x in orig] != [e["exception"]["exception_id"] for e in reg]:
        errors.append("exception register does not contain exactly the pack's exceptions in the original order")
    for x, e in zip(orig, reg):
        if e["exception"] != x:
            errors.append(f"{x['exception_id']}: exception fields differ from the original pack (statuses must not change)")
        if e["resolution_status"] != "UNRESOLVED":
            errors.append(f"{x['exception_id']}: resolution_status must be UNRESOLVED")
    if final["executive_summary"]["exceptions"]["total"] != len(orig) or \
            final["executive_summary"]["exceptions"]["unresolved"] != len(orig):
        errors.append("executive summary exception counts differ from the original pack")
    for name in ("internal_by_currency_day", "external_by_account_day", "opening_positions"):
        if final["reconciliation_results"][name] != pack["reconciliation_summary"][name]:
            errors.append(f"reconciliation_results.{name} differs from the original pack (values must be copied)")
    if final["executive_summary"]["deterministic"] != pack["executive_summary"]:
        errors.append("deterministic executive summary differs from the original pack")
    return errors


def _investigation_checks(final, snapshot):
    errors = []
    # Only investigations whose AI content belongs in the report: every INCLUDED one without analyst reviews (Phase 1), only
    # the ACCEPTED ones with them.
    included = {s.investigation_id: s for s in snapshot.selections if snapshot.accepted(s)}
    listed = {i["investigation_id"] for i in final["ai_investigations"]}
    if listed != set(included):
        errors.append(f"ai_investigations {sorted(listed)} do not match the snapshot selections {sorted(included)}")
    for inv in final["ai_investigations"]:
        iid = inv["investigation_id"]
        bundle = snapshot.bundles.get(iid)
        if bundle is None:
            continue
        reasons = check_eligibility(bundle, snapshot.pack)  # FV4/FV5: published, verified, not simulated, current rules
        errors += [f"{iid}: not eligible: {r}" for r in reasons]
        if inv["exception_id"] != included[iid].exception_id:
            errors.append(f"{iid}: investigates {inv['exception_id']}, selected for {included[iid].exception_id}")
        out, evidence = output_of(bundle), evidence_of(bundle)
        allowed = set(evidence["allowed_citation_ids"])
        record_ids = {r["evidence_id"] for r in evidence["source_records"]}
        result_ids = {r["result_id"] for r in evidence["control_results"]}
        search_ids = {s["search_id"] for s in evidence["searches"]}
        conf_ids = {c["conflict_id"] for c in evidence["conflicts"]}
        for eid, refs in cited_ids(inv).items():  # FV6: citations resolve to the selected ledger
            if eid not in allowed:
                errors.append(f"{refs[0]}: cites {eid}, which is not in the selected investigation's evidence")
            elif eid in record_ids and eid not in final["evidence_index"]:
                errors.append(f"{refs[0]}: cited record {eid} is missing from the evidence index")
        src_findings = {f.finding_id: f for f in out.confirmed_findings}
        src_hyps = {h.hypothesis_id for h in out.hypotheses}
        for f in inv["confirmed_findings"]:  # FV7/FV8
            s = src_findings.get(f["finding_id"])
            if s is None or s.claim != f["description"] or f["finding_id"] in src_hyps:
                errors.append(f"{f['ref']}: confirmed observation is not a validated confirmed finding of {iid}")
                continue
            if not set(f["evidence_refs"]) & (record_ids | result_ids | search_ids):
                errors.append(f"{f['ref']}: confirmed observation has no supporting source record, control result or search")
            if f["class"] != "EVIDENCE_CONFIRMED_OBSERVATION":
                errors.append(f"{f['ref']}: wrong classification {f['class']}")
            for k in ("title", "audit_relevance", "establishes", "does_not_establish"):
                if f[k] != getattr(s, k):
                    errors.append(f"{f['ref']}: {k} differs from the investigation (explanations are never rewritten or back-filled)")
        for h in inv["hypotheses"]:
            if h["hypothesis_id"] not in src_hyps or h["verification_status"] != "NOT_ESTABLISHED" or h["class"] != "HYPOTHESIS":
                errors.append(f"{h['ref']}: hypotheses must stay hypotheses (NOT_ESTABLISHED)")
        a = inv["assessment"]  # FV9: the AI assessment is reported as an assessment, never as an observation
        if a["class"] != "AI_INVESTIGATIVE_ASSESSMENT" or a["summary"] != out.investigation_summary or \
                a["ref"] in {f["ref"] for f in inv["confirmed_findings"]}:
            errors.append(f"{iid}: AI assessment must be kept distinct and verbatim")
        for c in inv["conflicts"]:
            if c["source"] == "DETERMINISTIC" and c["ref"].split("#")[1] not in conf_ids:
                errors.append(f"{c['ref']}: deterministic conflict not present in the evidence")
        for g in inv["evidence_gaps"]:
            if claims_nonexistence(g["description"]):
                errors.append(f"{g['ref']}: gap wording claims non-existence")
    for eid, entry in final["evidence_index"].items():
        for iid in entry["from_investigations"]:
            rec = next((r for r in evidence_of(snapshot.bundles[iid])["source_records"] if r["evidence_id"] == eid), None)
            if rec is None or rec["file_sha256"] != entry["file_sha256"] or rec["source_line"] != entry["source_line"]:
                errors.append(f"evidence_index {eid}: provenance differs from {iid}'s evidence")
    return errors


def _summary_checks(final, snapshot, summary, review, preview):
    errors = []
    expected = summary_fingerprint(closing_summary_input(snapshot))
    if summary.source_fingerprint != expected:  # FV12
        errors.append("closing summary was generated from different inputs (source fingerprint mismatch); regenerate it")
    if summary.snapshot_sha256 != snapshot.sha256:
        errors.append("closing summary belongs to a different review snapshot")
    if summary.status == "GENERATED":
        errors += [f"closing summary: {e}" for e in validate_closing_summary(summary.output, closing_summary_input(snapshot))]  # FV13
        if summary.model_metadata.get("simulated"):
            errors.append("closing summary is simulated output, not AI analysis")
    elif summary.status == "NOT_REQUIRED":  # schema 1.3: no exception and no included investigation, no AI request made
        if not snapshot.reviewed:
            errors.append("a NOT_REQUIRED closing summary needs final-pack schema 1.3 (a pack assembled with analyst reviews)")
        if closing_summary_required(snapshot):
            errors.append("closing summary is NOT_REQUIRED but the pack has exceptions or included investigations")
    elif not preview and not (review and review.acknowledged_summary_unavailable):
        errors.append("closing summary is UNAVAILABLE; publishing requires the reviewer's explicit acknowledgement")
    return errors


def _review_checks(final, snapshot, summary, review):
    """FV14: a recorded GENERATE decision on exactly this snapshot and summary."""
    errors = []
    if review is None:
        return ["a recorded human review decision is required before publication"]
    if review.decision != "GENERATE":
        errors.append(f"review decision is {review.decision}; only GENERATE authorises a final pack")
    if not review.acknowledgement_accepted or review.acknowledgement_text != ACKNOWLEDGEMENT_TEXT:
        errors.append("the reviewer has not accepted the generation acknowledgement")
    if review.snapshot_sha256 != snapshot.sha256:
        errors.append("review decision was made on a different snapshot (preview stale); re-preview and decide again")
    if review.closing_summary_sha256 != summary_sha256(summary):
        errors.append("review decision was made on a different closing summary")
    return errors


def _text_checks(final):
    errors = []
    for inv in final["ai_investigations"]:
        for f in inv["confirmed_findings"]:
            text = f"{f['title'] or ''} {f['description']} {f['establishes'] or ''}"
            if any(re.search(p, text, re.I) for p in CAUSE_PATTERNS):
                errors.append(f"{f['ref']}: cause stated in a confirmed observation")
            if any(re.search(p, text, re.I) for p in RESOLUTION_PATTERNS):
                errors.append(f"{f['ref']}: resolution stated in a confirmed observation")
    return errors


def _analyst_review_checks(final, snapshot):
    """The analyst's decisions are reported exactly as recorded, a REJECTED investigation contributes no AI content
    anywhere in the report, and a pack assembled without analyst reviews carries none."""
    from .assemble import analyst_review_view
    errors = []
    if not snapshot.reviewed:
        if "analyst_reviews" in final or final["final_pack_schema_version"] != FINAL_PACK_SCHEMA_VERSION \
                or "report_renderer" in final["metadata"]:
            errors.append("analyst review content in a pack assembled without analyst reviews")
        return errors
    if final["final_pack_schema_version"] != OUTCOME_FINAL_PACK_SCHEMA_VERSION or "analyst_reviews" not in final:
        errors.append(f"a pack assembled with analyst reviews must use schema {OUTCOME_FINAL_PACK_SCHEMA_VERSION}")
    if final["metadata"].get("report_renderer") != CURRENT_RENDERER_VERSION:
        errors.append(f"a newly assembled pack must declare the current renderer {CURRENT_RENDERER_VERSION}")
    errors += _outcome_checks(final, snapshot)
    sel = {s.exception_id: s for s in snapshot.selections}
    rejected = set()
    for e in final["exception_register"]:
        s = sel.get(e["exception"]["exception_id"])
        if s is None:
            continue
        if e["investigation"].get("analyst_review") != analyst_review_view(snapshot, s):
            errors.append(f"{s.exception_id}: the analyst review differs from the recorded decision (it is copied exactly)")
        if s.inclusion == "INCLUDED" and snapshot.analyst_reviews[s.investigation_id].decision == "REJECT":
            rejected.add(s.investigation_id)
            if e["investigation"]["overall_evidence_assessment"] is not None:
                errors.append(f"{s.exception_id}: the rejected AI assessment is reported")
    for iid in sorted(rejected):  # no AI content of a rejected investigation anywhere: sections, evidence index, provenance
        if any(i["investigation_id"] == iid for i in final["ai_investigations"]) or \
                any(r.startswith(iid + "#") for r in (k["ref"] for k in final["executive_summary"]["key_confirmed_observations"])) or \
                any(iid in x["from_investigations"] for x in final["evidence_index"].values()) or \
                any(i["investigation_id"] == iid for i in final["audit_trail"]["investigations"]):
            errors.append(f"{iid}: AI content of a REJECTED investigation is included in the report")
        leaked = _rejected_text_in(final, snapshot.bundles.get(iid), _strings(snapshot.pack) +
                                   [t for a in snapshot.accepted_ids for t in _strings(output_of(snapshot.bundles[a]).model_dump())])
        if leaked:  # e.g. through a cached summary or any other rendering path
            errors.append(f"{iid}: text of the REJECTED investigation's AI output appears in the report: {leaked[0][:80]!r}")
    return errors


def _outcome_checks(final, snapshot):
    """Schema 1.3: the deterministic outcome summary is exactly what the rules produce from this pack, its figures agree
    with the engine's own fields, and every NO_FINDINGS note is the engine's note, copied."""
    errors = []
    body = {k: v for k, v in final.items() if k != "outcome_summary"}
    if final.get("outcome_summary") != outcome_summary(body):
        errors.append("outcome_summary differs from the deterministic outcome rules applied to this pack")
        return errors
    f = final["outcome_summary"]["figures"]
    co = snapshot.pack["executive_summary"]["control_outcomes"]
    if f["control_results_total"] != co["total_results"] or sum(f["control_results_by_outcome"].values()) != co["total_results"]:
        errors.append("outcome_summary control-result counts do not add up to the engine's total_results")
    if f["checks_listed"] != len(snapshot.pack["control_register"]):
        errors.append("outcome_summary check count differs from the pack's control register")
    if f["exceptions_total"] != len(snapshot.pack["exception_register"]["exceptions"]):
        errors.append("outcome_summary exception count differs from the pack's exception register")
    if f["missing_evidence_items"] != len(snapshot.pack["missing_evidence_register"]["items"]):
        errors.append("outcome_summary missing-evidence count differs from the pack's missing-evidence register")
    notes = {c["check_id"]: c.get("check_outcome_note") for c in snapshot.pack["control_register"]}
    for c in final["reconciliation_results"]["control_checks"]:
        if c.get("check_outcome_note") is not None and c["check_outcome_note"] != notes.get(c["check_id"]):
            errors.append(f"{c['check_id']}: check_outcome_note is not the engine's note")
    return errors


def _strings(v, skip=()):
    out = []

    def walk(x):
        if isinstance(x, dict):
            for k, y in x.items():
                if k not in skip:
                    walk(y)
        elif isinstance(x, list):
            for y in x:
                walk(y)
        elif isinstance(x, str):
            out.append(x)
    walk(v)
    return out


def _rejected_text_in(final, bundle, legitimate=(), min_len=40):
    """AI-written passages of a rejected investigation (assessment, findings, hypotheses, gaps, conflicts, next steps,
    questions) that appear verbatim in any text of the final pack. The analyst's own wording (reason, comment) is not
    scanned: an analyst may quote what they reject. A passage that is also deterministic pack text, or text of an accepted
    investigation, legitimately appears and is not counted."""
    if bundle is None:
        return []
    out = output_of(bundle)
    passages = [out.investigation_summary, *out.open_questions]
    passages += [t for x in out.confirmed_findings for t in (x.title, x.claim, x.explanation)]
    passages += [t for h in out.hypotheses for t in (h.possible_explanation, h.rationale)]
    passages += [m.description for m in out.missing_evidence] + [c.description for c in out.contradictory_evidence]
    passages += [t for s in out.recommended_next_steps for t in (s.action, s.rationale)]
    allowed = "\n".join(legitimate)
    passages = {p.strip() for p in passages if isinstance(p, str) and len(p.strip()) >= min_len and p.strip() not in allowed}
    blob = "\n".join(_strings(final, skip=("rejection_reason", "comment")))
    return sorted(p for p in passages if p in blob)


def validate_final_pack(final, snapshot, summary, review, preview=False):
    from .assemble import content_sha256
    errors = _pack_checks(final, snapshot) + _register_checks(final, snapshot.pack) + _investigation_checks(final, snapshot)
    errors += _analyst_review_checks(final, snapshot)
    errors += _summary_checks(final, snapshot, summary, review, preview) + _text_checks(final)
    if not preview:
        errors += _review_checks(final, snapshot, summary, review)
        if not FINAL_PACK_ID_RE.match(final["metadata"]["final_pack_id"]):
            errors.append(f"final_pack_id {final['metadata']['final_pack_id']!r} has an invalid format")
    if content_sha256(final) != final["final_content_sha256"]:  # FV16
        errors.append("final_content_sha256 does not match the content")
    return errors
