"""Minimal PDF builders for tests (no third-party library): text-only pages and image-only (scanned-like) pages."""
from __future__ import annotations

import zlib


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _assemble(objects: list[bytes]) -> bytes:
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def _stream(content: bytes, extra: str = "") -> bytes:
    return f"<< /Length {len(content)}{extra} >>\nstream\n".encode() + content + b"\nendstream"


def text_pdf(lines: list[str]) -> bytes:
    """One page; each string is its own text line (pypdf extracts them as separate lines)."""
    ops, y = [], 780
    for line in lines:
        ops.append(f"BT /F1 10 Tf 50 {y} Td ({_escape(line)}) Tj ET")
        y -= 16
    content = "\n".join(ops).encode("latin-1")
    return _assemble([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        _stream(content),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ])


def image_only_pdf() -> bytes:
    """One page carrying only an image (as a scanner produces): no selectable text."""
    pixels = zlib.compress(bytes([200] * 64 * 64))
    return _assemble([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /XObject << /Im1 5 0 R >> >> >>",
        _stream(b"q 400 0 0 400 100 300 cm /Im1 Do Q"),
        _stream(pixels, " /Type /XObject /Subtype /Image /Width 64 /Height 64 /ColorSpace /DeviceGray "
                        "/BitsPerComponent 8 /Filter /FlateDecode"),
    ])


def blank_pdf() -> bytes:
    """One empty page: neither text nor images."""
    return _assemble([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R >>",
        _stream(b""),
    ])
