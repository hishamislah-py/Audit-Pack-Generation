"""Deterministic validation of model output before persistence (no LLM is used to validate an LLM)."""
import re

CAUSE_PATTERNS = [r"\broot cause\b", r"\bcaused by\b", r"\bthe cause (is|was)\b", r"\bdue to\b", r"\bbecause of\b"]
RESOLUTION_PATTERNS = [r"\b(exception|difference|discrepancy|issue|mismatch)\b[^.;]{0,60}\b(is|was|has been|are|were|have been)\s+"
                       r"(resolved|closed|cleared|approved|reconciled)\b",
                       r"\b(resolve[sd]?|close[sd]?|approve[sd]?) (the|this) (exception|discrepancy)\b",
                       r"\bcompliance opinion:", r"\bis compliant\b"]
ZERO_PATTERN = re.compile(r"\b(bank )?balance\b[^.;]{0,40}\b(was|is|of|=)\s*(£|€)?0(\.00)?\b", re.I)
# Absence from the supplied data is not proof of non-existence ("does not exist in the supplied data" is acceptable).
NONEXISTENCE_PATTERN = re.compile(r"\b(?:never existed|(?:does|did) not exist(?![^.;]{0,40}\b(?:in|within|among) the "
                                  r"(?:supplied|provided|available|current|retrieved)\b))", re.I)
# A negated statement ("an evidence gap, not that such records never existed") is the correct framing, not a violation.
NEGATION_BEFORE = re.compile(r"\b(?:not|no|nor|neither|cannot|can't|doesn't|does not (?:prove|establish|show|mean)|"
                             r"without (?:proving|showing))\b[^.;]{0,40}$", re.I)


def claims_nonexistence(text):
    return any(not NEGATION_BEFORE.search(text[:m.start()]) for m in NONEXISTENCE_PATTERN.finditer(text))


# Reconciliation views, keyed by evidence-ID prefix (source file, or control-result check ID). Figures from different
# views measure different things and may legitimately differ, so they cannot form a contradiction. IDs not listed here
# (CONF-, IN-14 log entries, exceptions, other checks) are not judged by this rule.
RECONCILIATION_VIEWS = {
    "internal (client-money requirement vs resource, per currency)": ("IN-05", "C04-REQUIREMENT", "C05-RESOURCE", "C06-DIFFERENCE"),
    "external (account ledger vs bank balance, per account)": ("IN-06", "IN-07", "IN-08", "C07-BANK-EVIDENCE", "C08-DIFFERENCE",
                                                               "RC2-LEDGER", "BC-VS-EOD"),
    "client balance (per client and currency)": ("IN-03", "CBAL-ROLLFWD", "CBAL-NONNEG"),
}
_VIEW_OF = {prefix: view for view, prefixes in RECONCILIATION_VIEWS.items() for prefix in prefixes}


def reconciliation_view(evidence_id):
    """The reconciliation view an evidence or control-result ID belongs to, or None if not classified."""
    return _VIEW_OF.get(re.split(r"[:|]", evidence_id or "", maxsplit=1)[0])


def _check_contradictions(out, packet, missing_ids, not_found_ids, candidate_ids):
    errors = []
    for c in out.contradictory_evidence:
        pair = list(dict.fromkeys(c.compared_evidence))
        if len(pair) != 2:
            errors.append(f"{c.item_id}: a contradiction must name exactly two different compared evidence IDs")
            continue
        if len((c.same_measure_and_scope or "").strip()) < 20:
            errors.append(f"{c.item_id}: a contradiction must explain why both items concern the same measure and scope")
        absent = [i for i in pair if i in missing_ids | not_found_ids | candidate_ids]
        if absent:
            errors.append(f"{c.item_id}: missing, not-found or unverified evidence {absent} cannot be one side of a contradiction")
        views = [reconciliation_view(i) for i in pair]
        if all(views) and views[0] != views[1]:
            errors.append(f"{c.item_id}: compares different reconciliation views ({views[0]}; {views[1]}); a difference "
                          "between views is not a contradiction - report it as an unexplained difference")
        for p in CAUSE_PATTERNS:
            if re.search(p, c.description, re.I):
                errors.append(f"{c.item_id}: states a cause in a contradiction ('{re.search(p, c.description, re.I).group(0)}')")
                break
    return errors


def _check_explanations(out):
    """Findings schema 1.4 fields, checked only where present (None means 'not supplied' under schema <= 1.3).
    title and establishes are factual, so they follow the cause rule of confirmed findings; every field follows the
    resolution and non-existence rules."""
    errors = []
    fields = [(f.finding_id, name, getattr(f, name)) for f in out.confirmed_findings
              for name in ("title", "audit_relevance", "establishes", "does_not_establish")]
    fields += [(h.hypothesis_id, "rationale", h.rationale) for h in out.hypotheses]
    for item, name, text in fields:
        if text is None:
            continue
        if not text.strip():
            errors.append(f"{item}: {name} is blank")
            continue
        if name in ("title", "establishes"):
            for p in CAUSE_PATTERNS:
                m = re.search(p, text, re.I)
                if m:
                    errors.append(f"{item}: {name} states a cause ('{m.group(0)}'); causes must be hypotheses")
                    break
        if any(re.search(p, text, re.I) for p in RESOLUTION_PATTERNS):
            errors.append(f"{item}: {name} states or implies the exception is resolved, closed or approved")
        if claims_nonexistence(text):
            errors.append(f"{item}: {name} claims evidence does not exist; absence from the supplied data is only 'not found'")
    return errors


def _cited(out):
    ids = set()
    for f in out.confirmed_findings:
        ids |= set(f.evidence_ids) | set(f.supporting_records)
    for h in out.hypotheses:
        ids |= set(h.supporting_evidence) | set(h.contradictory_evidence)
    for c in out.contradictory_evidence:
        ids |= set(c.evidence_ids) | set(c.compared_evidence)
    for m in out.missing_evidence:
        ids |= set(m.related_ids)
    return ids


def validate_output(out, packet, case):
    """Return (errors, notes, normalised evidence_references). Any error means the output is REJECTED."""
    errors, notes = [], []
    allowed = set(packet["allowed_citation_ids"])
    result_ids = {r["result_id"] for r in packet["control_results"]}
    record_ids = {r["evidence_id"] for r in packet["source_records"]}
    search_ids = {s["search_id"] for s in packet["searches"]}
    candidate_ids = {c["candidate_id"] for c in packet["candidate_relationships"]}
    cited = _cited(out)
    unknown = sorted((cited | set(out.evidence_references)) - allowed)
    if unknown:
        errors.append(f"cites IDs not present in the evidence packet: {unknown[:10]}")
    for f in out.confirmed_findings:
        if not (set(f.evidence_ids) & (record_ids | result_ids | search_ids)):
            errors.append(f"{f.finding_id}: confirmed finding cites no source record, control result or search")
        if set(f.supporting_records) - record_ids:
            errors.append(f"{f.finding_id}: supporting_records must be source record IDs from the packet")
        if set(f.evidence_ids) & candidate_ids:
            errors.append(f"{f.finding_id}: an unverified candidate relationship is cited as confirmed evidence")
        text = f"{f.claim} {f.explanation}".lower()
        for p in CAUSE_PATTERNS:
            if re.search(p, text):
                errors.append(f"{f.finding_id}: states a cause as a confirmed finding ('{re.search(p, text).group(0)}'); "
                              "causes must be hypotheses")
                break
        if packet["missing_evidence"] and ZERO_PATTERN.search(text):
            errors.append(f"{f.finding_id}: appears to substitute zero for a balance while evidence is missing")
    for text_name, text in [("investigation_summary", out.investigation_summary)] + \
                           [(f.finding_id, f"{f.claim} {f.explanation}") for f in out.confirmed_findings]:
        for p in RESOLUTION_PATTERNS:
            if re.search(p, text, re.I):
                errors.append(f"{text_name}: states or implies the exception is resolved, closed or approved")
                break
    texts = [("investigation_summary", out.investigation_summary)] + \
            [(f.finding_id, f"{f.claim} {f.explanation}") for f in out.confirmed_findings] + \
            [(m.item_id, m.description) for m in out.missing_evidence]
    for text_name, text in texts:
        if claims_nonexistence(text):
            errors.append(f"{text_name}: claims evidence does not exist; absence from the supplied data is only 'not found'")
    errors += _check_contradictions(out, packet, {m["item_id"] for m in packet["missing_evidence"]},
                                    {s["search_id"] for s in packet["searches"] if s["result"] == "NOT_FOUND"}, candidate_ids)
    errors += _check_explanations(out)
    preserved = {i for m in out.missing_evidence for i in m.related_ids}
    dropped = sorted({m["item_id"] for m in packet["missing_evidence"]} - preserved)
    if dropped:
        errors.append(f"missing evidence not preserved: {dropped}")
    if packet["missing_evidence"] and out.overall_evidence_assessment == "EVIDENCE_SUFFICIENT":
        errors.append("assessment EVIDENCE_SUFFICIENT is not permitted while required evidence is missing")
    if case["pack_id"] != packet["pack_id"] or case["pack_content_sha256"] != packet["pack_content_sha256"]:
        errors.append("pack identity changed between case and packet")
    refs = sorted(cited | (set(out.evidence_references) & allowed))
    if set(refs) != set(out.evidence_references):
        notes.append("evidence_references normalised to the set of IDs actually cited")
    return errors, notes, refs


def classification_summary(out, packet):
    """Python-derived classification of the output (never taken from the model): findings by class, and evidence gaps
    split into the engine's missing-evidence items, searches that found nothing, and gaps the AI identified itself."""
    not_found = {s["search_id"] for s in packet["searches"] if s["result"] == "NOT_FOUND"}
    miss = {m["item_id"] for m in packet["missing_evidence"]}
    gaps = {"engine_missing_evidence": [], "searched_not_found": [], "additional_gaps_identified_by_ai": []}
    for m in out.missing_evidence:
        rel = set(m.related_ids)
        if rel & miss:
            gaps["engine_missing_evidence"].append(m.item_id)
        if rel & not_found:
            gaps["searched_not_found"].append(m.item_id)
        if not rel & (miss | not_found):
            gaps["additional_gaps_identified_by_ai"].append(m.item_id)
    return {"EVIDENCE_BACKED": [f.finding_id for f in out.confirmed_findings],
            "HYPOTHESIS": [h.hypothesis_id for h in out.hypotheses],
            "INSUFFICIENT_EVIDENCE": [m.item_id for m in out.missing_evidence],
            "CONFLICTING_EVIDENCE": [c.item_id for c in out.contradictory_evidence],
            "evidence_gaps": gaps,
            "unverified_candidate_relationships": [c["candidate_id"] for c in packet["candidate_relationships"]],
            "deterministic_conflicts": [c["conflict_id"] for c in packet["conflicts"]],
            "not_found_searches": sorted(not_found)}
