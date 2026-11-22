"""Module C - deterministic CSV evidence classification.

Classification only decides *which category* a file is. It does not extract
or validate anything, so a file can be "identified" while its contents still
fail extraction or validation. The filename is never used.

Two matching policies, chosen per schema (``classification.match_policy``):

exact_header (authoritative UC-042 schemas)
  The header row, exactly as read (case, spacing and order included), must equal
  one canonical header. That is the UC-042 identification rule
  (uc042lib.prepare.identify). Canonical headers are unique (checked when the
  registry loads), so an exact match is never ambiguous. A header that is close
  to a canonical one is NOT accepted: the result is UNKNOWN (or AMBIGUOUS when it
  is equally close to several) with a diagnosis saying what differs.

scored (synthetic / provisional schemas, tiers 1-3 of the mapping engine)
  required_coverage = mapped required fields / required fields
  header_coverage   = mapped source columns / source columns
  score             = 0.7 * required_coverage + 0.3 * header_coverage
  A category is a candidate only if its signature fields are all present and
  score >= MIN_SCORE. The best candidate wins only if it leads the runner-up by
  at least MIN_MARGIN; otherwise the result is AMBIGUOUS.
"""
from __future__ import annotations

import weakref
from collections import Counter

from ..mapping.controlled import (
    RULES_DIR, MappingPolicy, MappingRules, controlled_map, load_proposals, load_rules,
)
from ..mapping.engine import map_columns
from ..mapping.templates import TemplateRegistry, layout_fingerprint
from ..models.enums import ClassificationMethod, ClassificationStatus
from ..models.results import ClassificationCandidate, ClassificationResult
from ..schemas.model import MatchPolicy
from ..schemas.registry import SchemaRegistry
from .content_check import check_rows

# Phase 1 behaviour: exact canonical header only (no reorder, whitespace, case or alias tolerance).
EXACT_ONLY_RULES = MappingRules(MappingPolicy(allow_reorder=False, trim_whitespace=False, case_insensitive=False,
                                              source="exact-only (Phase 1 behaviour)"), [], "exact-only")

MIN_SCORE = 0.5
MIN_MARGIN = 0.15
# Near-miss diagnosis thresholds: the values uc042lib.structure.diagnose_header uses to explain a rejected header.
DIAG_MIN_OVERLAP = 0.5
DIAG_TIE = 0.1


def _norm(c: str) -> str:
    return (c or "").replace("﻿", "").strip().lower()


def diagnose_header(received: list[str], registry: SchemaRegistry) -> dict:
    """Explain how a header differs from the closest canonical header(s). Never used to accept a file."""
    received = list(received)
    dup = sorted(h for h, n in Counter(received).items() if n > 1)
    scores = []
    for header, cat in registry.exact_header_index().items():
        a, b = {_norm(c) for c in header}, {_norm(c) for c in received}
        scores.append((len(a & b) / len(a | b) if a | b else 0.0, cat, list(header)))
    scores.sort(key=lambda x: (-x[0], x[1]))
    base = {"received": received, "duplicate_columns": dup}
    if not scores or scores[0][0] < DIAG_MIN_OVERLAP:
        return dict(base, status="UNKNOWN", closest=None, candidates=[],
                    overlap=round(scores[0][0], 4) if scores else 0.0,
                    message="the header does not resemble any canonical evidence header")
    best = scores[0][0]
    near = [c for s_, c, _ in scores if s_ >= DIAG_MIN_OVERLAP and best - s_ < DIAG_TIE]
    if len(near) > 1:
        return dict(base, status="AMBIGUOUS", closest=None, candidates=near, overlap=round(best, 4),
                    message=f"the header is about equally close to {', '.join(near)}")
    expected = scores[0][2]
    exp_n = {_norm(c): c for c in expected}
    rec_n = {_norm(c): c for c in received}
    case_or_spacing = [f"{rec_n[k]!r} -> {exp_n[k]!r}" for k in exp_n if k in rec_n and rec_n[k] != exp_n[k]]
    missing = [c for c in expected if _norm(c) not in rec_n]
    extra = [c for c in received if _norm(c) not in exp_n]
    common_exp = [_norm(c) for c in expected if _norm(c) in rec_n]
    common_rec = [_norm(c) for c in received if _norm(c) in exp_n]
    misordered = [exp_n[k] for i, k in enumerate(common_exp) if i >= len(common_rec) or common_rec[i] != k]
    diffs = [label for label, flag in (("missing columns", missing), ("extra columns", extra),
                                       ("reordered columns", misordered), ("case/spacing differences", case_or_spacing),
                                       ("duplicate columns", dup)) if flag]
    return dict(base, status="LIKELY", closest=scores[0][1], candidates=[scores[0][1]], overlap=round(best, 4),
                expected=expected, missing=missing, extra=extra, misordered=misordered,
                case_or_spacing=case_or_spacing,
                message=f"closest to {scores[0][1]} but not exact: " + "; ".join(diffs))


def _classify_exact(raw_headers: list[str], registry: SchemaRegistry, rows) -> ClassificationResult | None:
    cat = registry.exact_header_index().get(tuple(raw_headers))
    if cat is None:
        return None
    schema = registry.get(cat)
    res = ClassificationResult(
        status=ClassificationStatus.IDENTIFIED, category=cat, method=ClassificationMethod.CSV_EXACT_HEADER,
        confidence=1.0,
        reason=f"Header row equals the canonical {cat} header exactly ({len(raw_headers)} columns, same order and "
               f"case; rule from {schema.definition_source})")
    if rows is not None:
        cc = check_rows(schema, list(raw_headers), rows)
        res.content_check = cc
        if cc["rows_checked"] == 0:
            res.warnings.append("no data rows" + (" (allowed for this category)" if cc["empty_allowed"] else
                                                  " (UC-042 reports NO_RECORDS as an error for this category)"))
        elif cc["nonconforming_rows"]:
            res.warnings.append(f"{cc['nonconforming_rows']} of {cc['rows_checked']} data row(s) break the {cat} "
                                "field rules (category unchanged: UC-042 identifies CSVs by header)")
    return res


_DEFAULT_RULES: "weakref.WeakKeyDictionary[SchemaRegistry, MappingRules]" = weakref.WeakKeyDictionary()


def default_rules(registry: SchemaRegistry) -> MappingRules:
    """The active controlled-mapping rules shipped in mapping/rules/ (checked against this registry, cached)."""
    if registry not in _DEFAULT_RULES:
        _DEFAULT_RULES[registry] = load_rules(registry)
    return _DEFAULT_RULES[registry]


def _classify_controlled(raw: list[str], registry: SchemaRegistry, rules: MappingRules,
                         rows) -> ClassificationResult | None:
    """Tier B/C: accept a non-canonical header only if it maps one-to-one onto exactly one category under the rules.
    File-specific mappings never take part here: they cannot decide a category (Phase 3B-3)."""
    rules = rules.without_file_identity()
    accepted = []
    for header, cat in registry.exact_header_index().items():
        cm = controlled_map(raw, registry.get(cat), rules)
        if cm.accepted:
            accepted.append(cm)
    if not accepted:
        return None
    if len(accepted) > 1:
        return ClassificationResult(
            status=ClassificationStatus.AMBIGUOUS,
            details={"controlled_mapping": [cm.as_dict() for cm in accepted]},
            reason="The header maps completely onto several categories under the controlled mapping rules: "
                   + ", ".join(cm.category for cm in accepted))
    cm = accepted[0]
    schema = registry.get(cm.category)
    res = ClassificationResult(
        status=ClassificationStatus.IDENTIFIED, category=cm.category,
        method=ClassificationMethod.CSV_CONTROLLED_MAPPING, confidence=0.9,
        details={"controlled_mapping": cm.as_dict(), "mapping_rules": rules.source,
                 "aliases_used": sorted({m["alias_id"] for m in cm.mappings if m["alias_id"]})},
        reason=f"No exact canonical header; all {len(raw)} columns map one-to-one onto the {cm.category} fields under "
               f"the controlled mapping rules (variations: {', '.join(cm.variations)})",
        warnings=[f"accepted through controlled mapping, not the canonical header ({', '.join(cm.variations)})"])
    if rows is not None:
        mapped_header = [m["canonical_field"] for m in cm.mappings]
        cc = check_rows(schema, mapped_header, rows)
        res.content_check = cc
        if cc["rows_checked"] and cc["nonconforming_rows"]:
            res.warnings.append(f"{cc['nonconforming_rows']} of {cc['rows_checked']} data row(s) break the "
                                f"{cm.category} field rules")
    return res


def _unapproved_alias_hits(raw: list[str], category: str | None) -> list[dict]:
    """Headers that equal an alias PROPOSAL that is not active (reported so the reason is visible; never applied)."""
    try:
        proposals = load_proposals(RULES_DIR / "alias_proposals.json")
    except (OSError, ValueError):
        return []
    keys = {h.strip().casefold(): h for h in raw}
    return [{"header": keys[p["proposed_header"].strip().casefold()], "proposal_id": p["proposal_id"],
             "category": p["category"], "canonical_field": p["canonical_field"], "status": p["status"]}
            for p in proposals if p["proposed_header"].strip().casefold() in keys
            and (category is None or p["category"] == category)]


def classify_csv(headers: list[str], registry: SchemaRegistry,
                 templates: TemplateRegistry | None = None, raw_headers: list[str] | None = None,
                 rows: list[list[str]] | None = None, rules: MappingRules | None = None) -> ClassificationResult:
    """headers: trimmed header names; raw_headers: the header cells exactly as read (used by exact matching; defaults
    to `headers`); rows: data rows as cell lists, for the informational content check; rules: controlled-mapping
    rules (default: the shipped active rules; EXACT_ONLY_RULES disables tiers B/C)."""
    raw = list(raw_headers if raw_headers is not None else headers)
    exact = _classify_exact(raw, registry, rows)
    if exact is not None:
        return exact
    if registry.exact_header_index():
        controlled = _classify_controlled(raw, registry, rules or default_rules(registry), rows)
        if controlled is not None:
            return controlled
    diagnosis = diagnose_header(raw, registry) if registry.exact_header_index() else None
    if diagnosis is not None:
        closest = diagnosis.get("closest")
        if closest:
            diagnosis["controlled_mapping"] = controlled_map(raw, registry.get(closest),
                                                             rules or default_rules(registry)).as_dict()
        hits = _unapproved_alias_hits(raw, closest)
        if hits:
            diagnosis["unapproved_alias_proposals"] = hits
    scored = [s for s in registry.defined("csv") if s.classification.match_policy == MatchPolicy.SCORED]
    if diagnosis is not None and not scored:
        if diagnosis["status"] == "AMBIGUOUS":
            return ClassificationResult(
                status=ClassificationStatus.AMBIGUOUS, diagnosis=diagnosis,
                reason="No exact canonical header; the header is about equally close to "
                       f"{', '.join(diagnosis['candidates'])}, so not even a likely category can be named")
        if diagnosis["status"] == "LIKELY":
            return ClassificationResult(
                status=ClassificationStatus.UNKNOWN, diagnosis=diagnosis,
                reason=f"No exact canonical header match. Not accepted: {diagnosis['message']}. Not accepted by the "
                       "controlled mapping rules either: "
                       + ("; ".join((diagnosis.get("controlled_mapping") or {}).get("rejections", [])) or "-")
                       + (f". Header(s) match alias proposals that are not approved: "
                          f"{[h['header'] + ' -> ' + h['proposal_id'] + ' (' + h['status'] + ')' for h in diagnosis['unapproved_alias_proposals']]}"
                          if diagnosis.get("unapproved_alias_proposals") else ""))
        return ClassificationResult(
            status=ClassificationStatus.UNKNOWN, diagnosis=diagnosis,
            reason=f"No exact canonical header match and no close canonical header: {len(raw)} column(s) "
                   f"{raw[:6]}{' ...' if len(raw) > 6 else ''}; best name overlap with any category is "
                   f"{diagnosis.get('overlap', 0):.0%} (at least 50% is needed even to name a likely category). "
                   "Export the file with the documented UC-042 column names")
    result = _classify_scored(headers, registry, templates, scored)
    if diagnosis is not None and result.status != ClassificationStatus.IDENTIFIED:
        result.diagnosis = diagnosis
    return result


def _classify_scored(headers: list[str], registry: SchemaRegistry, templates: TemplateRegistry | None,
                     schemas) -> ClassificationResult:
    if not schemas:
        return ClassificationResult(
            status=ClassificationStatus.UNKNOWN,
            reason="No CSV schema definitions are available in the registry "
                   f"({len(registry.missing_categories())} categories are stubs awaiting the manifest)")

    candidates: list[ClassificationCandidate] = []
    for s in schemas:
        m = map_columns(headers, s)  # tiers 1-3 only: no templates during scoring
        mapped = {x.canonical_field for x in m.mappings}
        required = [f.name for f in s.fields if f.required]
        req_cov = (len([f for f in required if f in mapped]) / len(required)) if required else 1.0
        hdr_cov = len(m.mappings) / len(headers) if headers else 0.0
        sig_ok = all(f in mapped for f in s.classification.signature_fields)
        if not mapped:
            continue
        candidates.append(ClassificationCandidate(
            category=s.category, score=round(0.7 * req_cov + 0.3 * hdr_cov, 4),
            required_coverage=round(req_cov, 4), header_coverage=round(hdr_cov, 4),
            matched_fields=sorted(mapped), missing_required_fields=m.missing_required_fields,
            signature_satisfied=sig_ok))
    candidates.sort(key=lambda c: c.score, reverse=True)
    eligible = [c for c in candidates if c.signature_satisfied and c.score >= MIN_SCORE]

    # A validated template whose exact layout fingerprint matches is strong evidence.
    tpl_categories: set[str] = set()
    if templates is not None:
        fp = layout_fingerprint(headers)
        tpl_categories = {t.category for t in templates.find_compatible(headers)
                          if t.layout_fingerprint == fp}

    if len(tpl_categories) == 1:
        cat = next(iter(tpl_categories))
        if not eligible or eligible[0].category == cat:
            return ClassificationResult(
                status=ClassificationStatus.IDENTIFIED, category=cat,
                method=ClassificationMethod.MAPPING_TEMPLATE, confidence=1.0,
                candidates=candidates, reason="Layout matches a validated mapping template")
        return ClassificationResult(
            status=ClassificationStatus.AMBIGUOUS, candidates=candidates,
            reason=f"Validated template indicates {cat} but header matching indicates "
                   f"{eligible[0].category}")
    if len(tpl_categories) > 1:
        return ClassificationResult(
            status=ClassificationStatus.AMBIGUOUS, candidates=candidates,
            reason=f"Layout matches validated templates for several categories: {sorted(tpl_categories)}")

    if not eligible:
        return ClassificationResult(
            status=ClassificationStatus.UNKNOWN, candidates=candidates,
            reason="No category matched the header structure sufficiently "
                   f"(min score {MIN_SCORE}, signature fields required)")
    best = eligible[0]
    if len(eligible) > 1 and best.score - eligible[1].score < MIN_MARGIN:
        close = [c.category for c in eligible if best.score - c.score < MIN_MARGIN]
        return ClassificationResult(
            status=ClassificationStatus.AMBIGUOUS, candidates=candidates,
            reason=f"Header structure fits several categories closely: {close}")
    return ClassificationResult(
        status=ClassificationStatus.IDENTIFIED, category=best.category,
        method=ClassificationMethod.CSV_HEADER_MATCH, confidence=best.score,
        candidates=candidates, reason="Deterministic header match")
