"""Deterministic validation of an assembled final pack (spec 06 §5.4, Phase 1 §9). It re-checks the inputs independently
of how assemble.py built the document; any problem prevents publication. Errors are specific and actionable."""
import re
import unicodedata

from ..investigation.validation import CAUSE_PATTERNS, RESOLUTION_PATTERNS, claims_nonexistence, evidence_classes
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
            # Findings schema 1.5 (20 Nov 2026, CF-1): the same support rule as the investigation validator
            # (validation.evidence_classes): a completeness result (MISS-) supports a finding only when the finding
            # declares EVIDENCE_ABSENCE and the item is traceable to INSUFFICIENT_EVIDENCE control results of the same
            # exception present in the evidence. Exception references never support; other findings are unchanged.
            support = record_ids | result_ids | search_ids
            if s.evidence_basis == "EVIDENCE_ABSENCE":
                support |= evidence_classes(evidence)["traceable_completeness"]
            if not set(f["evidence_refs"]) & support:
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
    legitimate = _legitimate_texts(snapshot) if rejected else []
    cited = _cited_texts(snapshot) if rejected else {}
    for iid in sorted(rejected):  # no AI content of a rejected investigation anywhere: sections, evidence index, provenance
        if any(i["investigation_id"] == iid for i in final["ai_investigations"]) or \
                any(r.startswith(iid + "#") for r in (k["ref"] for k in final["executive_summary"]["key_confirmed_observations"])) or \
                any(iid in x["from_investigations"] for x in final["evidence_index"].values()) or \
                any(i["investigation_id"] == iid for i in final["audit_trail"]["investigations"]):
            errors.append(f"{iid}: AI content of a REJECTED investigation is included in the report")
        leaks = _rejected_text_leaks(final, snapshot.bundles.get(iid), legitimate, cited=cited)
        if leaks:  # e.g. through a cached summary or any other rendering path
            k = leaks[0]
            more = "" if len(leaks) == 1 else f"; {len(leaks) - 1} more passage(s)"
            errors.append(f"{iid}: text of the REJECTED investigation's AI output appears in the report: {k['text'][:80]!r} "
                          f"(rejected source {k['rejected_source']}; found at {', '.join(k['found_at'][:3])}{more})")
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


# --------------------------------------------------------------------------------------------------------------
# Rejected-content leak check (rules revised 22 Nov 2026, D5 / D-04: a live preview was refused because the AI closing
# summary restated an ACCEPTED investigation's evidence gap in words that a REJECTED investigation also used).
#
# Unit of comparison: each SENTENCE (at least `min_len` characters) of a rejected investigation's AI-written passages; a
# passage of at least `min_len` characters without such a sentence is compared whole. Both sides are normalised the same
# way (Unicode NFKC, case-folded, typographic quotes/dashes folded, every run of non-alphanumeric characters -> one
# space) and containment is checked on whole words.
#
# A rejected unit LEAKS when it appears in any text of the final pack (except the analyst's own wording: the rejection
# reason and comments) AND it is NOT attributable to legitimate content, i.e. it does not appear in:
#   - the deterministic pack (any string of it),
#   - the AI output of an ACCEPTED investigation of the same snapshot (any string of it),
#   - the controlled closing-summary input (built from the two above only; it never contains rejected content), or
#   - the final-pack layer's fixed wording (upper-case string constants of model.py / assemble.py).
# A sentence the rejected investigation shares word for word with an accepted investigation or the deterministic pack is
# that source's statement, not leaked rejected content (the closing-summary model never sees rejected content:
# summary.closing_summary_input). A rejected-only sentence is still refused wherever it appears, and comparing sentences
# also catches one sentence lifted out of a longer rejected passage (previously only a whole passage was matched).
#
# Closing-summary items with citations (key_observations, unverified_hypotheses, evidence_gaps, suggested_next_steps:
# `source_refs`; unresolved_items: `exception_id`). The summary model writes its own sentences from the controlled input,
# so it can word an ACCEPTED item exactly as a REJECTED investigation happened to (live, 22 Nov 2026: "The search for
# C0003 GBP REFUND transactions in the period returned NOT_FOUND." for the accepted gap "The search for REFUND
# transactions for C0003 GBP in the period returned NOT_FOUND."). A match inside such an item is ATTRIBUTED to the item's
# own citation, and not counted, only when ALL of these hold for one sentence S of the text of a cited reference, taken
# from the controlled summary input (which holds accepted and deterministic content only):
#   (a) every word of the rejected sentence occurs in S (same normalisation; word order may differ), and
#   (b) every negation word of S (not, no, never, none, nor, neither, without, cannot, n't) occurs in the rejected
#       sentence (dropping a negation changes the meaning, so it is never attributed).
# Free summary text without citations (overall_position, summary_text, limitations) and every other part of the report
# are never attributed this way. The summary's own integrity rules (source fingerprint FV12, refs restricted to
# allowed_refs FV13) are unchanged.
# --------------------------------------------------------------------------------------------------------------
_FOLD = str.maketrans({"‘": "'", "’": "'", "‚": "'", "‛": "'", "“": '"', "”": '"',
                       "„": '"', "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
                       "−": "-", " ": " "})
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")
_WORD = re.compile(r"[^\W_]+")


def _norm(text):
    """Comparison form: NFKC, case-folded, quotes/dashes folded, words only, single-spaced."""
    return " ".join(_WORD.findall(unicodedata.normalize("NFKC", str(text)).translate(_FOLD).casefold()))


def _sentences(text):
    return [t.strip() for t in _SENTENCE_END.split(text.strip()) if t.strip()]


def _rejected_passages(bundle):
    """(source field, text) of every AI-written passage of an investigation: assessment, findings, hypotheses, gaps,
    conflicts, next steps, questions."""
    out = output_of(bundle)
    items = [("investigation_summary", out.investigation_summary)]
    items += [(f"open_questions[{i}]", q) for i, q in enumerate(out.open_questions)]
    for i, x in enumerate(out.confirmed_findings):
        items += [(f"confirmed_findings[{i}].{k}", getattr(x, k)) for k in ("title", "claim", "explanation")]
    for i, h in enumerate(out.hypotheses):
        items += [(f"hypotheses[{i}].{k}", getattr(h, k)) for k in ("possible_explanation", "rationale")]
    items += [(f"missing_evidence[{i}].description", m.description) for i, m in enumerate(out.missing_evidence)]
    items += [(f"contradictory_evidence[{i}].description", c.description) for i, c in enumerate(out.contradictory_evidence)]
    for i, s in enumerate(out.recommended_next_steps):
        items += [(f"recommended_next_steps[{i}].{k}", getattr(s, k)) for k in ("action", "rationale")]
    return [(src, t.strip()) for src, t in items if isinstance(t, str) and t.strip()]


def _legitimate_texts(snapshot):
    """Text that may legitimately appear in the report although a rejected investigation also says it (rules above)."""
    from . import assemble as _assemble, model as _model
    from .summary import closing_summary_input
    texts = _strings(snapshot.pack)
    texts += [t for a in snapshot.accepted_ids for t in _strings(output_of(snapshot.bundles[a]).model_dump())]
    texts += _strings(closing_summary_input(snapshot))
    texts += [v for mod in (_model, _assemble) for k, v in vars(mod).items() if k.isupper() and isinstance(v, str)]
    return texts


def _located_strings(v, skip=(), path=""):
    """(JSON path, string) of every string in `v`, skipping the keys in `skip`."""
    out = []
    if isinstance(v, dict):
        for k, y in v.items():
            if k not in skip:
                out += _located_strings(y, skip, f"{path}.{k}" if path else str(k))
    elif isinstance(v, list):
        for i, y in enumerate(v):
            out += _located_strings(y, skip, f"{path}[{i}]")
    elif isinstance(v, str):
        out.append((path, v))
    return out


_NEGATIONS = frozenset({"not", "no", "never", "none", "nor", "neither", "without", "cannot", "t"})  # "t": from n't
_SUMMARY_ITEM = re.compile(r"^closing_summary\.output\.(key_observations|unverified_hypotheses|evidence_gaps|"
                           r"suggested_next_steps|unresolved_items)\[(\d+)\]\.text$")


def _cited_texts(snapshot):
    """{reference: [sentences]} of every citable item of the controlled closing-summary input (accepted and
    deterministic content only; a rejected investigation's content is not in it)."""
    from .summary import closing_summary_input
    data, out = closing_summary_input(snapshot), {}

    def add(ref, texts):
        out.setdefault(ref, []).extend(x for t in texts if isinstance(t, str) for x in _sentences(t))
    for x in data["exceptions"]:
        add(x["exception_id"], _strings(x))
    for i in data["missing_evidence_register"]:
        add(i["item_id"], _strings(i))
    for g in data["investigation_groups"]:
        add(g["group_id"], _strings(g))
    for c in data["candidate_relationships"]:
        add(c["candidate_id"], _strings(c))
    for inv in data["investigations"]:
        add(inv["investigation_id"], [inv["ai_assessment"]])
        for key in ("confirmed_findings", "hypotheses", "evidence_gaps", "conflicts", "next_steps"):
            for item in inv[key]:
                add(item["ref"], _strings(item))
    return out


def _attributed_to_citation(final, path, unit_words, cited):
    """True when the match at `path` lies in a cited closing-summary item and is explained by that item's own citation
    (rules (a) and (b) above)."""
    m = _SUMMARY_ITEM.match(path)
    if not m or not cited:
        return False
    try:
        item = final["closing_summary"]["output"][m.group(1)][int(m.group(2))]
    except (KeyError, IndexError, TypeError, ValueError):
        return False
    if not isinstance(item, dict):
        return False
    refs = list(item.get("source_refs") or []) + ([item["exception_id"]] if item.get("exception_id") else [])
    for ref in refs:
        for sentence in cited.get(ref, ()):
            words = set(_norm(sentence).split())
            if unit_words <= words and (words & _NEGATIONS) <= unit_words:
                return True
    return False


def _rejected_text_matches(final, bundle, legitimate=(), min_len=40, cited=None):
    """Every unit of the rejected investigation found in the report, except legitimate text:
    [{"text", "rejected_source", "found_at": [paths NOT attributable], "attributed_at": [paths attributed to a
    closing-summary citation]}]. Rules: see the block comment above."""
    if bundle is None:
        return []
    legit = "\n" + "\n".join(f" {_norm(t)} " for t in legitimate) + "\n"
    report = [(p, f" {_norm(t)} ") for p, t in _located_strings(final, skip=("rejection_reason", "comment"))]
    units = {}
    for src, passage in _rejected_passages(bundle):
        if len(passage) < min_len:
            continue
        for u in [x for x in _sentences(passage) if len(x) >= min_len] or [passage]:
            units.setdefault(u, src)
    out = []
    for text, src in units.items():
        n = f" {_norm(text)} "
        if not n.strip() or n in legit:
            continue
        where = [p for p, t in report if n in t]
        if not where:
            continue
        words = set(n.split())
        attributed = [p for p in where if _attributed_to_citation(final, p, words, cited)]
        out.append({"text": text, "rejected_source": src, "found_at": [p for p in where if p not in attributed],
                    "attributed_at": attributed})
    return sorted(out, key=lambda k: k["text"])


def _rejected_text_leaks(final, bundle, legitimate=(), min_len=40, cited=None):
    """Every rejected-only unit found in the report outside an attributable citation, as diagnostics
    [{"text", "rejected_source", "found_at": [JSON paths]}] sorted by text. The analyst's own wording (rejection_reason,
    comment) is not scanned: an analyst may quote what they reject."""
    return [{k: m[k] for k in ("text", "rejected_source", "found_at")}
            for m in _rejected_text_matches(final, bundle, legitimate, min_len, cited) if m["found_at"]]


def _rejected_text_in(final, bundle, legitimate=(), min_len=40, cited=None):
    """The texts of `_rejected_text_leaks` (for callers that need only the leaked passages)."""
    return [k["text"] for k in _rejected_text_leaks(final, bundle, legitimate, min_len, cited)]


def rejected_text_diagnostics(final, snapshot, include_attributed=False):
    """Structured diagnostics of the rejected-content check (empty when nothing leaks or nothing was rejected):
    [{"investigation_id", "text", "rejected_source", "found_at"}]. Records WHY a preview or pack was refused. With
    include_attributed=True the matches attributed to a closing-summary citation are listed too (with "attributed_at")."""
    if not snapshot.reviewed:
        return []
    rejected = sorted({s.investigation_id for s in snapshot.selections if s.inclusion == "INCLUDED"
                       and snapshot.analyst_reviews[s.investigation_id].decision == "REJECT"})
    if not rejected:
        return []
    legitimate, cited = _legitimate_texts(snapshot), _cited_texts(snapshot)
    out = []
    for iid in rejected:
        for m in _rejected_text_matches(final, snapshot.bundles.get(iid), legitimate, cited=cited):
            if m["found_at"]:
                rec = {"investigation_id": iid, **{k: m[k] for k in ("text", "rejected_source", "found_at")}}
                if include_attributed:
                    rec["attributed_at"] = m["attributed_at"]
                out.append(rec)
            elif include_attributed:
                out.append({"investigation_id": iid, **m})
    return out


def _relationship_checks(final, pack, summary, review):
    """Evidence-bearing relationships (R10): the engine's relationship register is copied verbatim (statuses, proofs,
    citations) and the per-relationship view keeps the engine's status and proof; an analyst explanation only refers to a
    relationship the AI CHALLENGED. Nothing here applies to a pack without a register (absent sections are required)."""
    from .assemble import _relationship_assessments
    errors = []
    reg = pack["investigation_group_register"].get("relationship_register")
    have = final["relationships"].get("relationship_register")
    if reg is None:
        if have is not None or "relationship_assessments" in final:
            errors.append("relationship register content in a final pack whose original pack has none")
        return errors
    if have != reg:
        errors.append("relationships.relationship_register differs from the original pack (engine relationship statuses and "
                      "proofs are copied, never changed)")
    expected = _relationship_assessments(pack, summary, review)
    if final.get("relationship_assessments") != expected:
        errors.append("relationship_assessments differ from the engine register, the AI dispositions and the analyst "
                      "explanations (the engine's status and proof must be kept exactly)")
    challenged = {d.relationship_id for d in ((summary.output.relationship_dispositions or []) if summary.output else [])
                  if d.disposition == "CHALLENGED"}
    for c in (review.relationship_challenge_reviews if review else []):
        if c.relationship_id not in challenged:
            errors.append(f"analyst explanation for {c.relationship_id}: the AI summary does not challenge that relationship")
    return errors


def validate_final_pack(final, snapshot, summary, review, preview=False):
    from .assemble import content_sha256
    errors = _pack_checks(final, snapshot) + _register_checks(final, snapshot.pack) + _investigation_checks(final, snapshot)
    errors += _relationship_checks(final, snapshot.pack, summary, review)
    errors += _analyst_review_checks(final, snapshot)
    errors += _summary_checks(final, snapshot, summary, review, preview) + _text_checks(final)
    if not preview:
        errors += _review_checks(final, snapshot, summary, review)
        if not FINAL_PACK_ID_RE.match(final["metadata"]["final_pack_id"]):
            errors.append(f"final_pack_id {final['metadata']['final_pack_id']!r} has an invalid format")
    if content_sha256(final) != final["final_content_sha256"]:  # FV16
        errors.append("final_content_sha256 does not match the content")
    return errors
