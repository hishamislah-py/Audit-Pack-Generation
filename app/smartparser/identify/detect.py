"""Module B - deterministic file identification. No AI.

Format is decided from content (magic bytes / decodability), never from the
extension. The extension is only compared afterwards to report a mismatch.
"""
from __future__ import annotations

import csv
import io
from collections import Counter
from pathlib import PurePath

from charset_normalizer import from_bytes

from ..models.enums import FileFormat
from ..models.results import FileIdentification

_EXT_FORMAT = {".csv": FileFormat.CSV, ".txt": FileFormat.CSV, ".tsv": FileFormat.CSV,
               ".pdf": FileFormat.PDF, ".zip": FileFormat.ZIP}

# Known binary signatures that are definitely not CSV/PDF/ZIP evidence.
_UNSUPPORTED_MAGIC = {
    b"\x89PNG": "PNG image", b"\xff\xd8\xff": "JPEG image", b"GIF8": "GIF image",
    b"\xd0\xcf\x11\xe0": "OLE2 (legacy Office) document", b"\x1f\x8b": "gzip archive",
    b"MZ": "Windows executable", b"\x7fELF": "ELF executable", b"Rar!": "RAR archive",
    b"7z\xbc\xaf": "7-Zip archive",
}

_BOMS = [
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe\x00\x00", "utf-32"), (b"\x00\x00\xfe\xff", "utf-32"),
    (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16"),
]

CANDIDATE_DELIMITERS = [",", ";", "\t", "|"]


class IdentificationError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind  # "empty" | "unsupported" | "corrupted"


def _extension(filename: str) -> str | None:
    suffix = PurePath(filename).suffix.lower()
    return suffix or None


def detect_encoding(data: bytes) -> tuple[str, str, bool] | None:
    """Return (encoding, method, has_bom) or None when the bytes are not text."""
    for bom, enc in _BOMS:
        if data.startswith(bom):
            return enc, "bom", True
    if b"\x00" in data[:4096]:
        return None  # NUL bytes without a UTF-16/32 BOM: binary
    try:
        data.decode("utf-8")
        return "utf-8", "utf8_strict", False
    except UnicodeDecodeError:
        pass
    best = from_bytes(data[:200_000]).best()
    if best is None:
        return None
    return best.encoding, "charset_normalizer", False


def detect_delimiter(text: str, max_lines: int = 200) -> tuple[str | None, float]:
    """Choose the delimiter giving the most consistent multi-column layout.

    Uses the real csv parser per candidate, so quoted delimiters are respected.
    Returns (delimiter, confidence) where confidence is the share of non-blank
    rows matching the modal column count.
    """
    sample_lines = text.splitlines()[:max_lines]
    sample = "\n".join(sample_lines)
    best: tuple[float, int, int, str] | None = None  # (consistency, width, -priority, delim)
    for priority, delim in enumerate(CANDIDATE_DELIMITERS):
        try:
            rows = [r for r in csv.reader(io.StringIO(sample), delimiter=delim)
                    if any(c.strip() for c in r)]
        except csv.Error:
            continue
        if not rows:
            continue
        counts = Counter(len(r) for r in rows)
        width, freq = counts.most_common(1)[0]
        if width < 2:
            continue
        consistency = freq / len(rows)
        key = (consistency, width, -priority, delim)
        if best is None or key[:3] > best[:3]:
            best = key
    if best is None:
        return None, 0.0
    return best[3], round(best[0], 3)


def identify(data: bytes, filename: str) -> FileIdentification:
    ext = _extension(filename)
    ext_fmt = _EXT_FORMAT.get(ext or "", FileFormat.UNKNOWN)

    if not data:
        raise IdentificationError("empty", "File is empty (0 bytes)")

    head = data[:1024]
    for magic, label in _UNSUPPORTED_MAGIC.items():
        if data.startswith(magic):
            raise IdentificationError("unsupported", f"Unsupported binary content: {label}")

    if b"%PDF-" in head:
        fmt = FileFormat.PDF
        ident = FileIdentification(detected_format=fmt, readable=True)
        ident.notes.append("PDF structure/text checks are performed in Phase 3")
    elif data.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        ident = FileIdentification(detected_format=FileFormat.ZIP, readable=True)
    else:
        enc = detect_encoding(data)
        if enc is None:
            raise IdentificationError(
                "corrupted" if ext_fmt != FileFormat.UNKNOWN else "unsupported",
                "Content is not decodable text and has no recognised binary signature")
        encoding, method, has_bom = enc
        try:
            text = data.decode(encoding)
        except (UnicodeDecodeError, LookupError) as exc:
            raise IdentificationError("corrupted", f"Cannot decode as {encoding}: {exc}") from exc
        if not text.strip():
            raise IdentificationError("empty", "File contains only whitespace")
        delim, conf = detect_delimiter(text.lstrip("﻿"))
        ident = FileIdentification(
            detected_format=FileFormat.CSV, readable=True, encoding=encoding,
            encoding_method=method, has_bom=has_bom, delimiter=delim, delimiter_confidence=conf,
        )
        if delim is None:
            if ext_fmt != FileFormat.CSV:
                raise IdentificationError(
                    "unsupported", "Text content with no consistent delimited structure")
            ident.delimiter = ","
            ident.notes.append("No multi-column structure found; read as single-column CSV")

    ident.extension = ext
    ident.extension_format = ext_fmt
    ident.extension_matches = ext_fmt == ident.detected_format
    return ident
