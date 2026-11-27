"""Write-once publication of final audit packs (spec 06 §11). Layout:

    final_packs/<final_pack_id>/final_pack.json   canonical JSON (source of truth)
    final_packs/<final_pack_id>/report.html       rendered from final_pack.json only
    final_packs/<final_pack_id>/report.pdf        rendered from final_pack.json only
    final_packs/<final_pack_id>/manifest.json     SHA-256 and size of the three files + generation record

All four files are staged in a temporary sibling directory and published with one atomic rename; nothing partial is ever
left. An existing final pack is never overwritten; one review decision yields at most one final pack; versions per
deterministic pack are sequential and each new version names the version it supersedes. Previews are never published.
"""
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from ..pack.model import canonical
from ..runtime_paths import default_final_packs_root
from .assemble import content_sha256
from .model import FINAL_PACK_ID_RE, RENDERER_VERSION
from .render_html import render_html
from .render_pdf import PdfFontError, PdfGlyphError, pdf_fonts, render_pdf, renderer_of

MEDIA = {"final_pack.json": "application/json", "report.html": "text/html", "report.pdf": "application/pdf"}


class FinalPackExistsError(Exception):
    """A final pack for the same ID, review decision or version already exists (never overwritten)."""


class FinalPackPublicationError(Exception):
    """The final pack cannot be published (not GENERATED, inconsistent hash, wrong version chain)."""


def _root(root):
    """The given root, else the configured primary location outside the repository (uc042lib.runtime_paths)."""
    return Path(root) if root else default_final_packs_root()


def list_final_packs(root=None, pack_id=None):
    """Published final packs (manifests), oldest version first."""
    out = []
    for m in sorted(_root(root).glob("FAP-*/manifest.json")):
        try:
            data = json.loads(m.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if pack_id is None or data["generation_record"]["source_pack_id"] == pack_id:
            out.append(dict(data, path=str(m.parent)))
    return sorted(out, key=lambda d: (d["generation_record"]["source_pack_id"], d["generation_record"]["version"]))


def next_version(pack_id, root=None):
    """(version, supersedes_final_pack_id) for the next final pack of a deterministic pack."""
    existing = list_final_packs(root, pack_id)
    if not existing:
        return 1, None
    latest = existing[-1]
    return latest["generation_record"]["version"] + 1, latest["final_pack_id"]


def _files(final):
    return {"final_pack.json": canonical(final).encode("utf-8"), "report.html": render_html(final).encode("utf-8"),
            "report.pdf": render_pdf(final)}


def publish_final_pack(final, root=None, expected=None):
    """Publish a validated, GENERATED final pack. Returns the published directory.

    expected: (version, supersedes_final_pack_id) the pack must carry. By default it is the next version of the source
    pack's own final packs in `root` (next_version). A caller numbering versions over a wider lineage (a reassessed pack
    continues the version sequence of the pack it reassesses, possibly published in another root) passes its own."""
    root = _root(root)
    m = final["metadata"]
    if m["status"] != "GENERATED" or final["human_review"].get("decision") != "GENERATE":
        raise FinalPackPublicationError("only a GENERATED final pack with a recorded GENERATE decision can be published (previews never)")
    if not FINAL_PACK_ID_RE.match(m["final_pack_id"]) or content_sha256(final) != final["final_content_sha256"]:
        raise FinalPackPublicationError("final pack ID or content hash does not verify; re-assemble instead of editing")
    pack_id, decision = m["source_pack"]["pack_id"], final["human_review"]["review_decision_id"]
    existing = list_final_packs(root, pack_id)
    for e in existing:
        if e["generation_record"]["review_decision_id"] == decision:
            raise FinalPackExistsError(f"review decision {decision} already produced {e['final_pack_id']}")
    expected, supersedes = expected if expected is not None else next_version(pack_id, root)
    if m["version"] != expected or m["supersedes_final_pack_id"] != supersedes:
        raise FinalPackExistsError(f"version {m['version']} (supersedes {m['supersedes_final_pack_id']}) is not the next version: "
                                   f"expected {expected} superseding {supersedes}")
    target = root / m["final_pack_id"]
    if target.exists():
        raise FinalPackExistsError(f"{target} already exists; final packs are never overwritten")
    files = _files(final)  # rendered before anything is written: a render failure leaves nothing behind
    manifest = {"final_pack_id": m["final_pack_id"], "final_content_sha256": final["final_content_sha256"],
                "renderer_version": renderer_of(final),
                "files": {n: {"sha256": hashlib.sha256(b).hexdigest(), "size_bytes": len(b), "media_type": MEDIA[n]} for n, b in files.items()},
                "generation_record": {"source_pack_id": pack_id, "version": m["version"], "supersedes_final_pack_id": m["supersedes_final_pack_id"],
                                      "review_decision_id": decision, "generated_at": m["generated_at"]}}
    if renderer_of(final) != RENDERER_VERSION:  # Unicode renderer: the exact fonts (SHA-256) the PDF was drawn with
        manifest["pdf_fonts"] = pdf_fonts(final)
    files["manifest.json"] = canonical(manifest).encode("utf-8")
    root.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".tmp-", dir=root))
    try:
        for name, data in files.items():
            (tmp / name).write_bytes(data)
        os.replace(tmp, target)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return target


def verify_final_pack(path):
    """Read-only check of a published final pack. Returns a list of problems (empty = verified): manifest file hashes,
    content hash, ID, and that report.html / report.pdf are exactly what the stored JSON renders to."""
    d, problems = Path(path), []
    try:
        manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        final = json.loads((d / "final_pack.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [f"unreadable final pack: {e}"]
    for name, info in manifest["files"].items():
        f = d / name
        if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest() != info["sha256"]:
            problems.append(f"{name} does not match its manifest SHA-256")
    if content_sha256(final) != final.get("final_content_sha256") or manifest["final_content_sha256"] != final.get("final_content_sha256"):
        problems.append("final_content_sha256 does not match the content")
    if final["metadata"]["final_pack_id"] != d.name or manifest["final_pack_id"] != d.name:
        problems.append("final_pack_id does not match the directory")
    if manifest.get("renderer_version", RENDERER_VERSION) != renderer_of(final):
        problems.append(f"manifest renderer {manifest.get('renderer_version')} differs from the renderer the pack declares")
    if not problems:  # re-rendered with the renderer the pack declares (a published pack renders as published)
        try:
            rendered = _files(final)
        except (PdfGlyphError, PdfFontError) as e:
            return problems + [f"report.pdf cannot be re-rendered here: {e}"]
        for name in ("report.html", "report.pdf"):
            if hashlib.sha256(rendered[name]).hexdigest() != manifest["files"][name]["sha256"]:
                problems.append(f"{name} is not the rendering of final_pack.json")
    return problems
