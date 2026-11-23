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


# Resolution claims, negation-aware (23 Nov 2026, live TC06-06 refusal of "It does not establish bank movement for this
# settlement line or resolve the discrepancy"). A resolution pattern is NOT asserted only when, in the same clause, a VERB
# negator governs it: "does not / cannot / never / neither ... nor / without ..." followed by the matched words, either
# directly ("does not resolve the exception") or through or/nor coordination ("does not establish X or resolve Y"). Bare
# "not"/"no" (for example "not material", "no evidence") never negate; a contrast word (but, however, yet, although ...) or
# "and" between the negator and the match, or a clause break (. ; : ! ?), keeps the claim asserted. Every other resolution
# rule is unchanged.
_RES_NEGATOR = re.compile(r"\b(?:does not|do not|did not|doesn't|don't|didn't|cannot|can not|can't|could not|couldn't|"
                          r"will not|won't|would not|wouldn't|may not|must not|should not|never|neither|nor|without)\b", re.I)
_RES_BLOCK = re.compile(r"\b(?:but|however|yet|although|though|whereas|while|instead|and)\b", re.I)


def asserts_resolution(text):
    """True when `text` states or implies that an exception is resolved, closed or approved (RESOLUTION_PATTERNS), unless
    that occurrence is negated as described above."""
    for p in RESOLUTION_PATTERNS:
        for m in re.finditer(p, text, re.I):
            clause = re.split(r"[.;:!?]", text[:m.start()])[-1]
            negators = list(_RES_NEGATOR.finditer(clause))
            if negators:
                gap = clause[negators[-1].end():]
                if len(gap) <= 120 and not _RES_BLOCK.search(gap):
                    continue                                   # negated occurrence: not a resolution claim
            return True
    return False


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
        if asserts_resolution(text):
            errors.append(f"{item}: {name} states or implies the exception is resolved, closed or approved")
        if claims_nonexistence(text):
            errors.append(f"{item}: {name} claims evidence does not exist; absence from the supplied data is only 'not found'")
    return errors


INSUF = "INSUFFICIENT_EVIDENCE"
# A claim that evidence is absent, unavailable or could not be assessed (findings schema 1.5 rule). A record that exists
# cannot show that another is absent: such a claim must cite a search, an engine control result or a traceable
# completeness item. Matched against the finding's claim only; a match never makes a citation acceptable.
ABSENCE_CLAIM = re.compile(
    r"\b(?:not found|not available|not supplied|not provided|not in the supplied|missing|absent|"
    r"(?:could|can)(?:not| not) be (?:assessed|evaluated|verified)|unable to be (?:assessed|evaluated|verified)|"
    r"insufficient[_ ]evidence|no (?:[\w:-]+ ){0,4}(?:records?|statements?|confirmations?|entries|entry|evidence))\b", re.I)


def evidence_classes(packet):
    """Deterministic classes of the citable IDs of a packet or tools-mode ledger (never taken from the model; never
    widens allowed_citation_ids).

    records / results / searches: source records, control results, searches (support for any confirmed finding).
    completeness: the packet's MISS- items. traceable_completeness: those that belong to the investigated exception AND
      whose related results are all INSUFFICIENT_EVIDENCE control results of that exception present in the evidence:
      only these may support an EVIDENCE_ABSENCE finding.
    absence_results / not_found_searches: INSUFFICIENT_EVIDENCE control results and NOT_FOUND searches.
    context: the exception, related exceptions, the investigation group and deterministic conflicts. Context only: they
      describe what is investigated and never support a finding on their own."""
    exc = packet["exception"]["exception_id"]
    results = {r["result_id"]: r for r in packet["control_results"]}
    searches = {s["search_id"]: s for s in packet["searches"]}
    traceable = set()
    for m in packet["missing_evidence"]:
        rel = list(m.get("related_result_ids") or [])
        if m.get("related_exception_id") == exc and rel and all(
                i in results and results[i].get("outcome") == INSUF and results[i].get("for_exception") == exc for i in rel):
            traceable.add(m["item_id"])
    context = {exc} | {e["exception_id"] for e in packet.get("related_exceptions") or []}
    context |= {c["conflict_id"] for c in packet.get("conflicts") or []}
    if packet.get("investigation_group"):
        context.add(packet["investigation_group"]["group_id"])
    return {"records": {r["evidence_id"] for r in packet["source_records"]}, "results": set(results),
            "searches": set(searches), "completeness": {m["item_id"] for m in packet["missing_evidence"]},
            "traceable_completeness": traceable,
            "absence_results": {i for i, r in results.items() if r.get("outcome") == INSUF},
            "not_found_searches": {i for i, s in searches.items() if s.get("result") == "NOT_FOUND"},
            "context": context, "exception_id": exc}


def _support_note(f, cls):
    """Why IDs a finding cites did not count as support (appended to the refusal; empty when nothing to explain)."""
    ev, parts = set(f.evidence_ids), []
    for i in sorted(ev & cls["context"]):
        parts.append(f"{i} is an exception reference (context only, never evidence for a claim)")
    for i in sorted(ev & cls["completeness"]):
        if f.evidence_basis != "EVIDENCE_ABSENCE":
            parts.append(f"{i} is a completeness result: it supports only an EVIDENCE_ABSENCE finding")
        elif i not in cls["traceable_completeness"]:
            parts.append(f"{i} is not traceable to INSUFFICIENT_EVIDENCE control results of {cls['exception_id']} in the evidence")
    return ("; " + "; ".join(parts)) if parts else ""


def _check_findings(out, cls):
    """Findings schema 1.5 citation rules (see evidence_classes). A finding without evidence_basis (schema <= 1.4) is
    checked exactly as before, plus the absence-claim rule."""
    errors = []
    base_support = cls["records"] | cls["results"] | cls["searches"]
    absence = cls["absence_results"] | cls["not_found_searches"] | cls["traceable_completeness"]
    for f in out.confirmed_findings:
        ev, basis = set(f.evidence_ids), f.evidence_basis
        support = base_support | (cls["traceable_completeness"] if basis == "EVIDENCE_ABSENCE" else set())
        if not ev & support:
            errors.append(f"{f.finding_id}: confirmed finding cites no source record, control result or search" + _support_note(f, cls))
        elif basis == "EVIDENCE_ABSENCE" and ev & (cls["completeness"] - cls["traceable_completeness"]):
            # cited next to other support: the untraceable item is never counted, and the refusal says why
            errors.append(f"{f.finding_id}: cites a completeness result that cannot support it" + _support_note(f, cls))
        if basis == "SOURCE_EVIDENCE" and not ev & cls["records"]:
            errors.append(f"{f.finding_id}: classified SOURCE_EVIDENCE but cites no source record")
        elif basis == "CONTROL_RESULT" and not ev & cls["results"]:
            errors.append(f"{f.finding_id}: classified CONTROL_RESULT but cites no control result")
        elif basis == "EVIDENCE_ABSENCE" and not ev & absence:
            errors.append(f"{f.finding_id}: classified EVIDENCE_ABSENCE but cites no absence evidence (a NOT_FOUND search, an "
                          "INSUFFICIENT_EVIDENCE control result, or a completeness result traceable to them)")
        elif basis != "EVIDENCE_ABSENCE" and ABSENCE_CLAIM.search(f.claim) and not ev & (cls["results"] | absence):
            errors.append(f"{f.finding_id}: states that evidence is absent or could not be assessed, but cites no search, control "
                          "result or completeness result (a record that exists cannot show that another is absent)")
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


def normalise_supporting_records(out, packet):
    """Session 1 citation fix (23 Nov 2026). `supporting_records` lists SOURCE records only; engine control results and
    searches are analytical context/support and belong in `evidence_ids`. A model sometimes also copies control-result or
    search IDs it already cites in evidence_ids into supporting_records (live, 22 Nov: F-02 of EXC-CASE-01). Those IDs are
    removed from supporting_records (they stay in evidence_ids) and the change is recorded in a note.

    Deliberately narrow, never widening: only IDs that are control results or searches OF THIS PACKET and ALREADY cited in
    the same finding's evidence_ids are moved. Unknown IDs, exception/group/MISS-/CAND- IDs, and results not cited in
    evidence_ids are left in place and are judged (and rejected) by validate_output exactly as before. Support checks run
    on evidence_ids and are unchanged. Returns (normalised output, notes)."""
    movable = {r["result_id"] for r in packet["control_results"]} | {s["search_id"] for s in packet["searches"]}
    notes, findings = [], []
    for f in out.confirmed_findings:
        moved = [i for i in f.supporting_records if i in movable and i in f.evidence_ids]
        if moved:
            f = f.model_copy(update={"supporting_records": [i for i in f.supporting_records if i not in moved]})
            notes.append(f"{f.finding_id}: supporting_records normalised - removed {moved} (control results/searches are "
                         "analytical context, not source records; they remain cited in evidence_ids)")
        findings.append(f)
    if not notes:
        return out, []
    return out.model_copy(update={"confirmed_findings": findings}), notes


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
    errors += _check_findings(out, evidence_classes(packet))  # schema 1.5: support, evidence basis, absence claims
    for f in out.confirmed_findings:
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
        if asserts_resolution(text):
            errors.append(f"{text_name}: states or implies the exception is resolved, closed or approved")
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
