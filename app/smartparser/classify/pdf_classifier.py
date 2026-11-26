"""Module C (PDF) - deterministic PDF evidence classification from extracted text. No AI, no OCR, no filename.

Rules (all read from the registry, which is generated from UC-042):
* labels: each category lists its key-detail labels; a label is found when the text has a line
  ``<label>: <value>`` (pattern ``pdf.label_pattern``, as uc042lib.prepare._pdf_details).
* candidates: categories whose every label was found (uc042lib.prepare.identify).
* one candidate: identified; for the policy (IN-17) the version must also be recognised - registered version, its
  effective date, and every required marking in the whitespace-normalised text (uc042lib.policy.recognise).
* the acknowledgement letters (IN-15 / IN-16) share their label set; the slot is chosen by matching the letter's
  'Letter reference' to acknowledgement_letter_ref of the slot's account in an account inventory (IN-02), as
  uc042lib.prepare.prepare_case does. Without that context the letter stays AMBIGUOUS.
* no text but images: image-only (scanned) PDF, unsupported (no OCR).
"""
from __future__ import annotations

import re

from ..models.enums import ClassificationMethod, ClassificationStatus
from ..models.results import ClassificationResult
from ..pdf_engine import PdfExtraction
from ..schemas.registry import SchemaRegistry


def normalise_text(text: str) -> str:
    """As uc042lib.policy.normalise: whitespace runs -> one space; em dash and U+FFFD -> '-'."""
    return re.sub(r"\s+", " ", (text or "").replace("—", "-").replace("�", "-")).strip()


def find_labels(text: str, registry: SchemaRegistry) -> dict[str, str]:
    found = {}
    for s in registry.defined("pdf"):
        for lbl in s.pdf.labels:
            if lbl.label in found:
                continue
            pattern = "^" + re.escape(lbl.label) + s.pdf.label_pattern[len("^{label}"):]
            m = re.search(pattern, text, re.M)
            if m:
                found[lbl.label] = m.group(1).strip()
    return found


def letter_refs_from_inventory(rows: list[dict], registry: SchemaRegistry) -> dict[str, str]:
    """{letter reference: category} from account-inventory rows, for slots defined by an account."""
    slot_of = {s.pdf.slot_account_id: s.category for s in registry.defined("pdf") if s.pdf.slot_account_id}
    refs = {}
    for r in rows:
        cat = slot_of.get(r.get("account_id"))
        ref = (r.get("acknowledgement_letter_ref") or "").strip()
        if cat and ref:
            refs[ref] = cat
    return refs


def recognise_policy(details: dict, text: str, schema) -> tuple[str | None, list[str], dict | None]:
    """(version, problems, registered version info) - as uc042lib.policy.recognise."""
    version = (details.get("Document version") or "").strip()
    reg = next((v for v in schema.pdf.policy_versions if v.version == version), None)
    if reg is None:
        known = ", ".join(v.version for v in schema.pdf.policy_versions)
        return None, [f"unsupported policy version {version or '(none)'!r}; recognised versions: {known}"], None
    problems = []
    if (details.get("Effective date") or "").strip() != reg.effective:
        problems.append(f"policy v{version} states effective date {details.get('Effective date') or '(none)'}, "
                        f"not the registered {reg.effective}")
    norm = normalise_text(text)
    problems += [f"policy v{version} lacks the required marking {m!r}" for m in reg.required_markings
                 if normalise_text(m) not in norm]
    return version, problems, reg.model_dump()


def classify_pdf(ext: PdfExtraction, registry: SchemaRegistry,
                 letter_refs: dict[str, str] | None = None) -> ClassificationResult:
    """letter_refs: {letter reference: category} from an account inventory (None: no inventory supplied)."""
    facts = {"page_count": ext.page_count, "has_text": ext.has_text, "image_count": ext.image_count}
    if not ext.has_text:
        if ext.image_only:
            return ClassificationResult(
                status=ClassificationStatus.UNKNOWN, unsupported="image_only_pdf", details=facts,
                reason=f"Image-only (scanned) PDF: {ext.image_count} image(s), no selectable text. OCR is not "
                       "supported, so the category cannot be determined")
        return ClassificationResult(status=ClassificationStatus.UNKNOWN, unsupported="pdf_no_text", details=facts,
                                    reason="PDF has no selectable text and no images")
    schemas = registry.defined("pdf")
    found = find_labels(ext.text, registry)
    facts["labels_found"] = found
    cands = [s.category for s in schemas if all(lbl.label in found for lbl in s.pdf.labels)]
    if not cands:
        partial = sorted(((sum(l.label in found for l in s.pdf.labels), len(s.pdf.labels), s.category) for s in schemas),
                         key=lambda x: (-x[0] / x[1], x[2]))
        hits, total, best = partial[0]
        diag = None
        if hits:
            missing = [l.label for l in registry.get(best).pdf.labels if l.label not in found]
            diag = {"status": "PARTIAL", "closest": best, "labels_present": hits, "labels_expected": total,
                    "missing_labels": missing}
        return ClassificationResult(
            status=ClassificationStatus.UNKNOWN, details=facts, diagnosis=diag,
            reason="PDF text does not contain the full key-details label set of any category"
                   + (f" (closest {best}: {hits}/{total} labels, missing {diag['missing_labels']})" if diag else ""))

    if len(cands) == 1:
        cat = cands[0]
        schema = registry.get(cat)
        if schema.pdf.policy_versions:
            version, problems, reg = recognise_policy(found, ext.text, schema)
            facts.update(policy_version=version, policy_problems=problems)
            if problems:
                return ClassificationResult(
                    status=ClassificationStatus.UNKNOWN, details=facts,
                    diagnosis={"status": "POLICY_NOT_RECOGNISED", "closest": cat, "problems": problems},
                    reason=f"PDF carries the {cat} key details but is not a recognised policy version: "
                           + "; ".join(problems))
            facts.update(policy_classification=reg["classification"], policy_effective=reg["effective"])
            return ClassificationResult(
                status=ClassificationStatus.IDENTIFIED, category=cat, method=ClassificationMethod.PDF_TEXT_PATTERN,
                confidence=1.0, details=facts,
                reason=f"All {len(schema.pdf.labels)} {cat} key-detail labels found; recognised policy v{version} "
                       f"(effective {reg['effective']}, {reg['classification']}, required markings present)")
        return ClassificationResult(
            status=ClassificationStatus.IDENTIFIED, category=cat, method=ClassificationMethod.PDF_TEXT_PATTERN,
            confidence=1.0, details=facts,
            reason=f"All {len(schema.pdf.labels)} {cat} key-detail labels found, as 'Label: value' lines")

    shared = set(registry.get(cands[0]).pdf.shared_label_group) | {cands[0]}
    if set(cands) == shared and all(registry.get(c).pdf.slot_account_id for c in cands):
        ref = found.get("Letter reference", "")
        observed = {k: found[k] for k in ("Currency", "Account name") if k in found}
        facts["letter_reference"] = ref
        # Recorded for transparency only: UC-042 chooses the slot by the IN-02 letter reference, never by these values.
        facts["observed_not_used_for_slot"] = observed
        warn: list[str] = []
        if letter_refs is None:
            return ClassificationResult(
                status=ClassificationStatus.AMBIGUOUS, details=facts, warnings=warn,
                reason=f"Acknowledgement letter: labels are shared by {', '.join(sorted(cands))}. The slot is "
                       f"chosen by matching its letter reference {ref!r} to an account inventory (IN-02); none "
                       "was supplied")
        slot = letter_refs.get(ref)
        if slot in cands:
            acct = registry.get(slot).pdf.slot_account_id
            facts["slot_resolution"] = {"account_id": acct, "via": "IN-02 acknowledgement_letter_ref"}
            return ClassificationResult(
                status=ClassificationStatus.IDENTIFIED, category=slot, method=ClassificationMethod.PDF_TEXT_PATTERN,
                confidence=1.0, details=facts, warnings=warn,
                reason=f"Acknowledgement-letter labels found; letter reference {ref!r} equals the IN-02 "
                       f"acknowledgement_letter_ref of {acct}, so the slot is {slot}")
        return ClassificationResult(
            status=ClassificationStatus.AMBIGUOUS, details=facts, warnings=warn,
            reason=f"Acknowledgement letter: letter reference {ref!r} does not match the acknowledgement_letter_ref "
                   f"of any safeguarding account in the account inventory (IN-02); {', '.join(sorted(cands))} "
                   "remain possible")
    return ClassificationResult(
        status=ClassificationStatus.AMBIGUOUS, details=facts,
        reason=f"PDF text contains the complete label sets of several categories: {', '.join(sorted(cands))}")
