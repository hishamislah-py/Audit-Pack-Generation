"""Experiment A - native PDF field extraction and canonical mapping (no OCR, no AI, no network).

Isolated experiment: nothing in the pipeline, packages, handoff or submission calls this module, and its output is a
PROPOSAL record only (``applied`` is always False). It reuses, and does not duplicate:
  * smartparser.pdf_engine.extract_pdf      - pypdf text layer + image count (image-only detection);
  * smartparser.classify.pdf_classifier     - category identification (full label set, policy recognition,
                                              letter slot via IN-02), the same rules UC-042 applies;
  * smartparser.orchestration.policy.Decision - the routing vocabulary.

What it adds: per-field extraction with provenance (file, SHA-256, page, line, exact source line), detection of
missing / conflicting / not-line-anchored / possibly wrapped values and near-miss labels, mapping of each value to its
canonical field (the registry label of the identified category, plus the registry's cross-document target), and
validation against the UC-042 consumer rules (rules.py). Uncertain values are routed to HUMAN_REVIEW; values are never
inferred, completed or corrected.
"""
from __future__ import annotations

import difflib
import hashlib
import re
from typing import Any

from pydantic import BaseModel, Field

from ..classify.pdf_classifier import classify_pdf, letter_refs_from_inventory
from ..models.enums import ClassificationStatus
from ..orchestration.policy import Decision
from ..pdf_engine import PdfEngineError, extract_pdf
from ..schemas.registry import SchemaRegistry
from .rules import NO_RULE_REASON, PARSE, RULES, Context, document_rules

EXPERIMENT_VERSION = "pdf-native-extraction/0.1-experiment"
_KV_LINE = re.compile(r"^([A-Z][A-Za-z0-9 ()/'&.-]{1,60}?):\s(.+)$")   # any 'Key: value' line (for unmapped reporting)
_WRAP_FILL = 0.85    # a label line at least this share of the page's longest line may have wrapped


class SourceRef(BaseModel):
    page: int                       # 1-based
    line: int                       # 1-based line number in the page's extracted text
    text: str                       # the exact extracted line


class ValidationResult(BaseModel):
    rule_id: str
    level: str                      # PARSE | CROSS_DOC | CONTROL
    result: str                     # PASS | FAIL | NOT_EVALUATED
    detail: str
    source: str = ""


class ExtractedField(BaseModel):
    label: str
    canonical_field: str            # "<category>.<label>" (the registry's canonical identity for PDF evidence)
    cross_document_target: str | None = None
    status: str                     # EXTRACTED | MISSING | CONFLICT | NOT_LINE_ANCHORED
    value: str | None = None        # as UC-042 parses it: the text after 'Label: ', stripped; never corrected
    occurrences: list[SourceRef] = Field(default_factory=list)
    candidate_values: list[str] = Field(default_factory=list)
    validations: list[ValidationResult] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    review_reasons: list[str] = Field(default_factory=list)


class UnmappedLine(BaseModel):
    key: str
    value: str
    source: SourceRef
    near_miss_of: str | None = None   # a canonical label it resembles (never mapped)


class ExtractionResult(BaseModel):
    experiment_version: str = EXPERIMENT_VERSION
    filename: str
    sha256: str
    size_bytes: int
    native_text: str                # SUCCEEDED | NO_TEXT | IMAGE_ONLY | UNREADABLE
    page_count: int = 0
    image_count: int = 0
    characters_per_page: list[int] = Field(default_factory=list)
    classification_status: str = ""
    category: str | None = None
    candidate_categories: list[str] = Field(default_factory=list)
    classification_reason: str = ""
    structure: dict[str, Any] = Field(default_factory=dict)
    fields: list[ExtractedField] = Field(default_factory=list)
    unmapped: list[UnmappedLine] = Field(default_factory=list)
    document_validations: list[ValidationResult] = Field(default_factory=list)
    decision: str = Decision.REJECT_OR_HOLD
    reasons: list[str] = Field(default_factory=list)
    applied: bool = False           # an experiment never applies, accepts or submits anything
    ocr_used: bool = False

    def summary(self) -> dict:
        by = {}
        for f in self.fields:
            by[f.status] = by.get(f.status, 0) + 1
        return {"file": self.filename, "native_text": self.native_text, "pages": self.page_count,
                "category": self.category or "/".join(self.candidate_categories) or None,
                "fields": len(self.fields), "by_status": by, "unmapped": len(self.unmapped), "decision": self.decision}


def _lines(page_text: str) -> list[str]:
    return page_text.split("\n")


def _label_occurrences(label: str, pages: list[list[str]]) -> tuple[list[tuple[SourceRef, str]], list[SourceRef]]:
    """Anchored 'Label: value' hits (as uc042lib.prepare._pdf_details) and unanchored mentions of the label."""
    anchored, loose = [], []
    pat = re.compile("^" + re.escape(label) + r": (.+)$")
    for p, lines in enumerate(pages, start=1):
        for n, line in enumerate(lines, start=1):
            m = pat.match(line)
            if m:
                anchored.append((SourceRef(page=p, line=n, text=line), m.group(1).strip()))
            elif re.search(r"(^|\s)" + re.escape(label) + r"\b", line):
                loose.append(SourceRef(page=p, line=n, text=line))
    return anchored, loose


def _possibly_wrapped(ref: SourceRef, pages: list[list[str]], label_lines: set[tuple[int, int]]) -> bool:
    """The value line fills (almost) the page width and the next line is plain continuation text."""
    lines = pages[ref.page - 1]
    width = max((len(x) for x in lines), default=0)
    if ref.line >= len(lines) or width == 0:
        return False
    nxt = lines[ref.line].strip()
    if not nxt or (ref.page, ref.line + 1) in label_lines or _KV_LINE.match(nxt):
        return False
    return len(ref.text) >= _WRAP_FILL * width


def _slot_inventory_row(category: str | None, registry: SchemaRegistry, inventory: list[dict] | None) -> dict | None:
    if not category or inventory is None:
        return None
    acct = registry.get(category).pdf.slot_account_id
    return next((r for r in inventory if r.get("account_id") == acct), None) if acct else None


def extract_document(data: bytes, filename: str, registry: SchemaRegistry, *, inventory: list[dict] | None = None,
                     period_id: str | None = None) -> ExtractionResult:
    """Extract, map and validate one PDF. `inventory`: IN-02 rows of the same package (letter slot and C10 values);
    `period_id`: PER-YYYY-MM for the period-dependent rules. Pure: reads `data`, writes nothing."""
    sha = hashlib.sha256(data).hexdigest()
    res = ExtractionResult(filename=filename, sha256=sha, size_bytes=len(data), native_text="UNREADABLE")
    if not data.startswith(b"%PDF-"):
        res.reasons.append("not a PDF (no %PDF- signature)")
        return res
    try:
        ext = extract_pdf(data)
    except PdfEngineError as e:
        res.reasons.append(f"PDF not readable: {e}")
        return res
    res.page_count, res.image_count = ext.page_count, ext.image_count
    res.characters_per_page = [len(t.strip()) for t in ext.page_texts]
    if not ext.has_text:
        res.native_text = "IMAGE_ONLY" if ext.image_only else "NO_TEXT"
        res.reasons.append("no selectable text layer" + (f" ({ext.image_count} image(s)): OCR is out of scope, nothing is "
                                                         "extracted" if ext.image_only else ""))
        return res
    res.native_text = "SUCCEEDED"

    letter_refs = letter_refs_from_inventory(inventory, registry) if inventory is not None else None
    cls = classify_pdf(ext, registry, letter_refs)
    res.classification_status, res.classification_reason = cls.status.value, cls.reason
    res.category = cls.category
    pages = [_lines(t) for t in ext.page_texts]

    # Which label set to extract: the identified category, else the shared candidates (letters), else the closest
    # partial match (reported only: an unidentified document is never mapped).
    if cls.status == ClassificationStatus.IDENTIFIED:
        label_cats = [cls.category]
    else:
        found = (cls.details or {}).get("labels_found", {})
        label_cats = [s.category for s in registry.defined("pdf") if s.pdf.labels and all(l.label in found for l in s.pdf.labels)]
        if not label_cats and cls.diagnosis and cls.diagnosis.get("closest"):
            label_cats = [cls.diagnosis["closest"]]
    if not label_cats:   # report-only: label sets present without 'Label: value' anchoring (for example a table)
        label_cats = [s.category for s in registry.defined("pdf") if s.pdf.labels and
                      all(_label_occurrences(l.label, pages)[1] for l in s.pdf.labels)]
        if label_cats:
            res.reasons.append("every label of " + "/".join(label_cats) + " appears, but not as 'Label: value' lines "
                               "(for example a table layout): reported for review, nothing is mapped")
    res.candidate_categories = label_cats if cls.status != ClassificationStatus.IDENTIFIED else []
    if not label_cats:
        res.reasons.append("no category could be identified: " + cls.reason)
        return res
    schema = registry.get(label_cats[0])
    cat_label = label_cats[0] if len(label_cats) == 1 else "|".join(sorted(label_cats))
    policy = None
    if schema.pdf.policy_versions:
        policy = (cls.details or {}).get("policy_version")
        policy = next((v.model_dump() for v in schema.pdf.policy_versions if v.version == policy), None)
    successor = None
    if policy is not None:
        later = sorted(v.effective for v in schema.pdf.policy_versions if v.effective > policy["effective"])
        successor = later[0] if later else None
    ctx = Context(period_id=period_id, inventory_row=_slot_inventory_row(cls.category, registry, inventory),
                  policy_version=policy, policy_successor_effective=successor)
    targets = {r.field: f"{r.target_category}.{r.target_field}" for r in schema.relationships if r.target_field}

    anchored_lines: set[tuple[int, int]] = set()
    values: dict[str, str] = {}
    for lbl in schema.pdf.labels:
        hits, loose = _label_occurrences(lbl.label, pages)
        f = ExtractedField(label=lbl.label, canonical_field=f"{cat_label}.{lbl.label}",
                           cross_document_target=targets.get(lbl.label), status="MISSING")
        for ref, _ in hits:
            anchored_lines.add((ref.page, ref.line))
        distinct = sorted({v for _, v in hits})
        if len(distinct) == 1:
            f.status, f.value = "EXTRACTED", distinct[0]
            f.occurrences = [r for r, _ in hits]
            if len(hits) > 1:
                f.flags.append(f"REPEATED_IDENTICAL ({len(hits)} lines)")
            if not f.value:
                f.status, f.value = "MISSING", None
                f.review_reasons.append("label present with an empty value")
        elif len(distinct) > 1:
            f.status, f.candidate_values, f.occurrences = "CONFLICT", distinct, [r for r, _ in hits]
            f.review_reasons.append(f"{len(distinct)} different values for one label; none is chosen")
        elif loose:
            f.status, f.occurrences = "NOT_LINE_ANCHORED", loose
            cands = []
            for r in loose:   # label alone on its line (table cell order): the next line is only a CANDIDATE
                rest = re.split(re.escape(lbl.label), r.text, maxsplit=1)[1].lstrip(" :")
                if not rest and r.line < len(pages[r.page - 1]):
                    rest = pages[r.page - 1][r.line].strip()
                cands.append(rest)
            f.candidate_values = cands
            f.review_reasons.append("the label appears, but not as a 'Label: value' line (for example a table cell); "
                                    "the value is not extracted deterministically")
        else:
            f.review_reasons.append("label not found in the text layer")
        if f.value is not None:
            values[lbl.label] = f.value
        res.fields.append(f)

    for f in res.fields:   # second pass: wrap detection needs every label line
        if f.status == "EXTRACTED" and any(_possibly_wrapped(r, pages, anchored_lines) for r in f.occurrences):
            f.flags.append("POSSIBLY_WRAPPED")
            f.review_reasons.append("the value line fills the text width and is followed by continuation text: the "
                                    "value may be truncated")
        if f.status != "EXTRACTED":
            continue
        rules = RULES.get(label_cats[0], {}).get(f.label, [])
        if len(label_cats) > 1:   # slot not resolved: cross-document rules wait for the slot
            rules = [r for r in rules if r.level != "CROSS_DOC"]
        for r in rules:
            result, detail = r.check(f.value, ctx)
            f.validations.append(ValidationResult(rule_id=r.rule_id, level=r.level, result=result, detail=detail,
                                                  source=r.source))
            if result == "FAIL" and (r.level in (PARSE, "CROSS_DOC") or detail.startswith("FORMAT:")):
                f.review_reasons.append(f"{r.rule_id} failed: {detail}")
        if not rules:
            reason = NO_RULE_REASON.get((label_cats[0], f.label), "no UC-042 rule")
            f.validations.append(ValidationResult(rule_id="NONE", level="-", result="NOT_EVALUATED", detail=reason))
    if cls.status == ClassificationStatus.IDENTIFIED:
        for rid, level, result, detail in document_rules(cls.category, values):
            res.document_validations.append(ValidationResult(rule_id=rid, level=level, result=result, detail=detail))

    labels = [l.label for l in schema.pdf.labels]
    for p, lines in enumerate(pages, start=1):
        for n, line in enumerate(lines, start=1):
            if (p, n) in anchored_lines:
                continue
            m = _KV_LINE.match(line)
            if not m:
                continue
            key = m.group(1).strip()
            near = difflib.get_close_matches(key.casefold(), [l.casefold() for l in labels], n=1, cutoff=0.8)
            near_label = next((l for l in labels if near and l.casefold() == near[0]), None)
            res.unmapped.append(UnmappedLine(key=key, value=m.group(2).strip(), source=SourceRef(page=p, line=n, text=line),
                                             near_miss_of=near_label))
    first = min(anchored_lines, default=None)
    res.structure = {"pages": res.page_count, "label_lines": len(anchored_lines),
                     "key_details_heading": next(({"page": p, "line": n} for p, ls in enumerate(pages, 1)
                                                  for n, l in enumerate(ls, 1) if l.strip() == "Key details"), None),
                     "first_label_line": {"page": first[0], "line": first[1]} if first else None,
                     "layout": "key-value lines" if anchored_lines else "no anchored key-value lines"}

    # Routing (never auto-accept): REJECT_OR_HOLD when the document cannot be mapped at all; HUMAN_REVIEW for any
    # uncertainty; DETERMINISTIC only when every canonical field was extracted once, unflagged, with no PARSE or
    # CROSS_DOC failure. CONTROL failures are business results reported for UC-042, not extraction uncertainty.
    if cls.status == ClassificationStatus.UNKNOWN:
        res.decision = Decision.REJECT_OR_HOLD
        res.reasons.append("category not identified: " + cls.reason)
        if any(u.near_miss_of for u in res.unmapped):
            res.reasons.append("near-miss labels present: " + ", ".join(f"{u.key!r} ~ {u.near_miss_of!r}"
                                                                        for u in res.unmapped if u.near_miss_of))
        return res
    review = [f"{f.label}: {r}" for f in res.fields for r in f.review_reasons]
    review += [f"near-miss label {u.key!r} ~ {u.near_miss_of!r} (not mapped)" for u in res.unmapped if u.near_miss_of]
    if cls.status == ClassificationStatus.AMBIGUOUS:
        review.insert(0, "category ambiguous: " + cls.reason)
    res.decision = Decision.HUMAN_REVIEW if review else Decision.DETERMINISTIC
    res.reasons = review or ["every canonical field extracted exactly once from a line-anchored 'Label: value' line; "
                             "no PARSE or CROSS_DOC rule failed (proposal only, nothing applied)"]
    return res
