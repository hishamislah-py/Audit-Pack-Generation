"""Module G - PDF text extraction (Phase 1: what classification needs; no OCR).

``extract_pdf(data) -> PdfExtraction`` reads the selectable text of every page with pypdf (the library UC-042 itself
uses for its PDF evidence) and counts image XObjects, so an image-only (scanned) document can be reported as
unsupported instead of being misread as an empty one. OCR and scanned-document processing are out of scope.
Document-field extraction with page references remains Phase 3.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field


class PdfEngineError(Exception):
    pass


class PdfEngineNotImplemented(NotImplementedError):  # kept for callers of the Phase-0 interface
    pass


@dataclass
class PdfExtraction:
    page_count: int
    page_texts: list[str]
    image_count: int
    encrypted: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.page_texts)

    @property
    def has_text(self) -> bool:
        return any(t.strip() for t in self.page_texts)

    @property
    def image_only(self) -> bool:
        return not self.has_text and self.image_count > 0


def _count_images(page) -> int:
    try:
        res = page.get("/Resources")
        res = res.get_object() if res is not None else None
        xo = res.get("/XObject") if res is not None else None
        xo = xo.get_object() if xo is not None else None
        if not xo:
            return 0
        return sum(1 for k in xo if xo[k].get_object().get("/Subtype") == "/Image")
    except Exception:  # damaged resource dictionaries: no image information
        return 0


def extract_pdf(data: bytes) -> PdfExtraction:
    """Selectable text and image count of a PDF. Raises PdfEngineError when the PDF cannot be read."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency declared in pyproject
        raise PdfEngineError("pypdf is required for PDF evidence") from exc
    try:
        reader = PdfReader(io.BytesIO(data))
        encrypted = bool(reader.is_encrypted)
        if encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:
                raise PdfEngineError(f"encrypted PDF ({type(exc).__name__})") from exc
        texts, images = [], 0
        for page in reader.pages:
            texts.append(page.extract_text() or "")
            images += _count_images(page)
    except PdfEngineError:
        raise
    except Exception as exc:  # damaged PDFs raise many error types
        raise PdfEngineError(f"PDF not readable ({type(exc).__name__}: {exc})") from exc
    return PdfExtraction(page_count=len(texts), page_texts=texts, image_count=images, encrypted=encrypted)
