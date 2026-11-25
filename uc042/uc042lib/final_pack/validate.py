"""Deterministic validation of an assembled final pack (spec 06 §5.4, Phase 1 §9). It re-checks the inputs independently
of how assemble.py built the document; any problem prevents publication. Errors are specific and actionable."""
import re

from ..investigation.validation import CAUSE_PATTERNS, RESOLUTION_PATTERNS, claims_nonexistence
from .content import cited_ids
from .model import FINAL_PACK_ID_RE, SUPPORTED_PACK_SCHEMAS, ACKNOWLEDGEMENT_TEXT
from .sources import check_eligibility, evidence_of, load_pack, output_of
from .summary import closing_summary_input, summary_fingerprint, summary_sha256, validate_closing_summary


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
    included = {s.investigation_id: s for s in snapshot.selections if s.inclusion == "INCLUDED"}
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


def validate_final_pack(final, snapshot, summary, review, preview=False):
    from .assemble import content_sha256
    errors = _pack_checks(final, snapshot) + _register_checks(final, snapshot.pack) + _investigation_checks(final, snapshot)
    errors += _summary_checks(final, snapshot, summary, review, preview) + _text_checks(final)
    if not preview:
        errors += _review_checks(final, snapshot, summary, review)
        if not FINAL_PACK_ID_RE.match(final["metadata"]["final_pack_id"]):
            errors.append(f"final_pack_id {final['metadata']['final_pack_id']!r} has an invalid format")
    if content_sha256(final) != final["final_content_sha256"]:  # FV16
        errors.append("final_content_sha256 does not match the content")
    return errors
