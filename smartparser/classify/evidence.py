"""Content-only evidence classification for one file or a set of files (Phase 1 baseline).

`classify_bytes` takes the file's bytes and nothing else: no filename, path or extension reaches the decision.
`classify_batch` classifies files supplied together. Its one cross-file step is the UC-042 acknowledgement-letter rule:
if exactly one file in the set is identified (by its header) as the account inventory IN-02, its
acknowledgement_letter_ref values resolve the shared IN-15/IN-16 letter label set. No other relationship is used.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..csv_engine.reader import CsvReadError, read_csv
from ..identify.detect import IdentificationError, identify
from ..models.enums import ClassificationStatus, FileFormat
from ..models.results import ClassificationResult
from ..pdf_engine import PdfEngineError, PdfExtraction, extract_pdf
from ..schemas.registry import SchemaRegistry
from .csv_classifier import classify_csv
from .pdf_classifier import classify_pdf, letter_refs_from_inventory

CANONICAL_ENCODINGS = {"utf-8", "utf-8-sig"}


@dataclass
class FileClassification:
    file_format: str
    result: ClassificationResult
    facts: dict = field(default_factory=dict)       # encoding, delimiter, header line, pages, ...
    inventory_rows: list[dict] | None = None        # set when the file is an exactly identified account inventory
    pdf: PdfExtraction | None = None


def _unknown(fmt: str, reason: str, unsupported: str | None = None) -> FileClassification:
    return FileClassification(fmt, ClassificationResult(status=ClassificationStatus.UNKNOWN, reason=reason,
                                                        unsupported=unsupported))


def classify_bytes(data: bytes, registry: SchemaRegistry, letter_refs: dict[str, str] | None = None,
                   rules=None) -> FileClassification:
    """rules: controlled CSV mapping rules (None: the shipped active rules; EXACT_ONLY_RULES: Phase 1 behaviour)."""
    try:
        ident = identify(data, "")          # no filename: the extension check is skipped entirely
    except IdentificationError as exc:
        return _unknown("unknown", str(exc), unsupported=exc.kind)
    if ident.detected_format == FileFormat.ZIP:
        return _unknown("zip", "ZIP container: package handling is not part of Phase 1 classification", "zip")
    if ident.detected_format == FileFormat.PDF:
        return _classify_pdf_bytes(data, registry, letter_refs)
    return _classify_csv_bytes(data, ident, registry, rules)


def _classify_pdf_bytes(data, registry, letter_refs) -> FileClassification:
    try:
        ext = extract_pdf(data)
    except PdfEngineError as exc:
        return _unknown("pdf", str(exc), unsupported="pdf_unreadable")
    res = classify_pdf(ext, registry, letter_refs)
    if not data.startswith(b"%PDF-"):
        res.warnings.append("the PDF signature is not at byte 0 (UC-042 only reads files that start with %PDF-)")
    return FileClassification("pdf", res, {"page_count": ext.page_count, "image_count": ext.image_count}, pdf=ext)


def _classify_csv_bytes(data, ident, registry, rules=None) -> FileClassification:
    facts = {"encoding": ident.encoding, "encoding_method": ident.encoding_method, "has_bom": ident.has_bom,
             "delimiter": ident.delimiter, "delimiter_confidence": ident.delimiter_confidence}
    try:
        table = read_csv(data, ident.encoding, ident.delimiter)
    except CsvReadError as exc:
        fc = _unknown("csv", f"malformed CSV: {exc}", unsupported="malformed_csv")
        fc.facts = facts
        return fc
    facts.update(header_line=table.header_line, data_rows=len(table.rows), preamble_lines=len(table.preamble),
                 read_error=table.error)
    res = classify_csv(table.headers, registry, raw_headers=table.raw_headers,
                       rows=[r.cells for r in table.rows], rules=rules)
    if table.error:
        res.warnings.append(f"reading stopped early ({table.error}); {len(table.rows)} row(s) before that point")
    if res.status == ClassificationStatus.IDENTIFIED:
        deviations = []
        if ident.encoding not in CANONICAL_ENCODINGS:
            deviations.append(f"encoding {ident.encoding} (UC-042 reads UTF-8, optional BOM)")
        if ident.delimiter != ",":
            deviations.append(f"delimiter {ident.delimiter!r} (UC-042 reads comma-separated files)")
        if table.preamble:
            deviations.append(f"{len(table.preamble)} line(s) before the header (UC-042 expects the header on line 1)")
        if deviations:
            res.warnings.append("exact canonical header, but not the UC-042 serialisation: " + "; ".join(deviations))
            res.details["canonical_serialisation"] = False
        else:
            res.details["canonical_serialisation"] = True
    fc = FileClassification("csv", res, facts)
    if res.status == ClassificationStatus.IDENTIFIED and registry.get(res.category).pdf is None:
        inventory_for = {s.pdf.slot_account_id for s in registry.defined("pdf") if s.pdf.slot_account_id}
        if inventory_for and "acknowledgement_letter_ref" in table.raw_headers and "account_id" in table.raw_headers:
            fc.inventory_rows = [dict(zip(table.raw_headers, r.cells)) for r in table.rows]
    return fc


def classify_batch(items: list[tuple[str, bytes]], registry: SchemaRegistry, rules=None) -> dict[str, FileClassification]:
    """items: (opaque key, bytes). The key is only used to return results; it never influences classification."""
    out = {key: classify_bytes(data, registry, rules=rules) for key, data in items}
    inventories = [fc for fc in out.values() if fc.inventory_rows is not None]
    if len(inventories) != 1:
        note = ("no account inventory (IN-02) in this set" if not inventories else
                f"{len(inventories)} files identify as an account inventory; none is used to resolve letters")
        for fc in out.values():
            if fc.result.status == ClassificationStatus.AMBIGUOUS and fc.result.details.get("letter_reference") is not None:
                fc.result.warnings.append(note)
        return out
    refs = letter_refs_from_inventory(inventories[0].inventory_rows, registry)
    data_by_key = dict(items)
    for key, fc in out.items():
        if fc.file_format == "pdf" and fc.result.status == ClassificationStatus.AMBIGUOUS \
                and fc.result.details.get("letter_reference") is not None:
            out[key] = _classify_pdf_bytes(data_by_key[key], registry, refs)
    return out
