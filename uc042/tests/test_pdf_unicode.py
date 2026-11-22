"""Unicode PDF rendering (B3): the analyst's exact wording in final-pack PDFs (bundled DejaVu fonts, renderer
2.0-unicode), unsupported characters refused rather than substituted, fallback fonts, font integrity, reproducibility, and
unchanged rendering of every pack that declares no renderer (the published February pack verifies byte for byte).
Offline. Run from uc042/: python -m unittest tests.test_pdf_unicode -v"""
import html
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pypdf import PdfReader

from tests.api_support import ROOT, ApiCase
from tests.final_pack_support import PACK
from uc042lib.final_pack import verify_final_pack
import importlib

rp = importlib.import_module("uc042lib.final_pack.render_pdf")  # the module (the package re-exports the function under this name)
from uc042lib.final_pack.model import CURRENT_RENDERER_VERSION, RENDERER_VERSION, UNICODE_RENDERER_VERSION  # noqa: F401

SC5A = PACK["SC5A"]
SAMPLES = ["The investigation did not consider Łódź's additional evidence.", "Difference: £812.40 → unresolved.",
           "Reviewer's note — further verification required."]
REASON = "\n".join(SAMPLES)
FEB = ROOT / "demo_history" / "final_packs" / "FAP-H202602-PER-2026-02-v1-b8dd53bd2449"


def pdf_text(data):
    return "".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)


def pdf_fonts(data):
    names = set()
    for page in PdfReader(io.BytesIO(data)).pages:
        for f in (page.get("/Resources", {}).get("/Font", {}) or {}).values():
            names.add(str(f.get_object().get("/BaseFont")))
    return names


class EndToEnd(ApiCase):
    def setUp(self):
        super().setUp()
        job = self.run_investigation_job("SC5A", "EXC-SC5A-01")
        self.inv = job["result"]["investigation_id"]

    def decide(self, **body):
        return self.post(f"/api/v1/investigations/{self.inv}/analyst-review", dict({"expected_revision": 0}, **body))

    def generate(self):
        s = self.preview(self.post(f"/api/v1/packs/{SC5A}/reviews").json()["review_id"])
        r = self.post(f"/api/v1/reviews/{s['review_id']}/decision", {"decision": "GENERATE", "acknowledgement_accepted": True,
                                                                      "snapshot_sha256": s["current_preview"]["snapshot_sha256"]})
        self.assertEqual(r.status_code, 201, r.text)
        return self.settings.final_packs_root / r.json()["final_pack"]["final_pack_id"]

    def test_rejection_reason_is_exact_in_json_html_and_pdf(self):
        r = self.decide(decision="REJECT", rejection_reason=REASON)
        self.assertEqual((r.status_code, r.json()["pdf_unsupported_characters"]), (201, []))
        d = self.generate()
        final = json.loads((d / "final_pack.json").read_text(encoding="utf-8"))
        self.assertEqual(final["exception_register"][0]["investigation"]["analyst_review"]["rejection_reason"], REASON)  # UTF-8, exact
        self.assertEqual(final["metadata"]["report_renderer"], CURRENT_RENDERER_VERSION)  # 2.1-unicode since 17 Nov 2026
        page = (d / "report.html").read_text(encoding="utf-8")
        self.assertIn(html.escape(REASON), page)
        pdf = (d / "report.pdf").read_bytes()
        text = pdf_text(pdf)
        for s in SAMPLES:
            self.assertIn(s, text)  # drawn and extractable exactly (no '?', no '->' or '-' substitutes)
        self.assertNotIn("?ód?", text)
        self.assertTrue({"/AAAAAA+DejaVuSans", "/AAAAAA+DejaVuSans-Bold"} <= pdf_fonts(pdf), pdf_fonts(pdf))
        manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        bundled = json.loads((Path(rp.FONT_DIR) / "fonts.json").read_text(encoding="utf-8"))["files"]
        self.assertEqual(manifest["renderer_version"], CURRENT_RENDERER_VERSION)
        self.assertEqual({f["file"]: f["sha256"] for f in manifest["pdf_fonts"]}, bundled)
        self.assertEqual(verify_final_pack(d), [])

    def test_accepted_comment_with_unicode(self):
        self.assertEqual(self.decide(decision="ACCEPT", comment=SAMPLES[1]).status_code, 201)
        d = self.generate()
        self.assertIn(SAMPLES[1], pdf_text((d / "report.pdf").read_bytes()))
        self.assertEqual(verify_final_pack(d), [])

    def test_unsupported_characters_block_instead_of_being_substituted(self):
        r = self.decide(decision="REJECT", rejection_reason="Contract 合同 not reviewed 🙂")
        self.assertEqual(r.status_code, 201, r.text)  # the exact wording is recorded in the application...
        self.assertEqual([c["codepoint"] for c in r.json()["pdf_unsupported_characters"]], ["U+5408", "U+540C", "U+1F642"])
        s = self.post(f"/api/v1/packs/{SC5A}/reviews").json()
        blocker = [b for b in s["readiness"]["blockers"] if b["code"] == "PDF_GLYPHS_UNSUPPORTED"]
        self.assertTrue(blocker and "U+5408" in blocker[0]["detail"], s["readiness"])  # ...but never published with substitutes
        p = self.post(f"/api/v1/reviews/{s['review_id']}/preview", {"authorization": {"confirmed": True}})
        self.assertEqual((p.status_code, p.json()["code"]), (409, "BLOCKED"))
        self.assertFalse(self.settings.final_packs_root.is_dir() and list(self.settings.final_packs_root.glob("FAP-*")))


class Renderer(unittest.TestCase):
    def test_historical_pack_renders_byte_identically(self):
        final = json.loads((FEB / "final_pack.json").read_text(encoding="utf-8"))
        self.assertNotIn("report_renderer", final["metadata"])
        self.assertEqual(rp.renderer_of(final), RENDERER_VERSION)
        self.assertEqual(rp.render_pdf(final), (FEB / "report.pdf").read_bytes())
        self.assertEqual(verify_final_pack(FEB), [])

    def test_internal_fallback_and_missing_glyph_detection(self):
        f = rp._unicode_fonts()
        only_regular = next(ch for ch in map(chr, range(0x2000, 0x2FFF))
                            if ord(ch) in f.faces[f.base] and ord(ch) not in f.faces[f.oblique])
        self.assertEqual(f.font_for(only_regular, f.oblique), f.base)  # drawn with the regular face, not dropped
        self.assertIn(f'<font name="{f.base}">', f.markup(f"x{only_regular}y", f.oblique))
        self.assertIsNone(f.font_for("合", f.base))
        with self.assertRaises(rp.PdfGlyphError) as e:
            f.markup("合", f.base)
        self.assertIn("U+5408", str(e.exception))
        self.assertEqual(rp.unsupported_in_text("Łódź £ → — ’"), [])

    def test_tampered_bundled_font_is_refused(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            shutil.copytree(rp.FONT_DIR, tmp / "fonts")
            with open(tmp / "fonts" / "DejaVuSans.ttf", "ab") as fh:
                fh.write(b"\0")
            with mock.patch.object(rp, "FONT_DIR", tmp / "fonts"), mock.patch.object(rp, "_UNICODE", None):
                with self.assertRaises(rp.PdfFontError):
                    rp._unicode_fonts()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


SCRIPT = r"""
import hashlib, json, sys
sys.path.insert(0, sys.argv[1])
from uc042lib.final_pack.render_pdf import render_pdf
final = json.load(open(sys.argv[2], encoding="utf-8"))
print(hashlib.sha256(render_pdf(final)).hexdigest())
"""


class Reproducibility(unittest.TestCase):
    """The same pack renders to the same bytes in separate processes (verification re-renders in a new process)."""

    @classmethod
    def setUpClass(cls):
        from tests.final_pack_support import make_investigation, summary_investigator
        from uc042lib.final_pack import assemble_preview, build_review_snapshot, generate_closing_summary
        import hashlib
        cls.tmp = Path(tempfile.mkdtemp())
        root = cls.tmp / "inv"
        inv = make_investigation("SC5A", "EXC-SC5A-01", root)
        sha = hashlib.sha256(next(root.glob(f"*/EXC-SC5A-01/{inv}")).joinpath("findings.json").read_bytes()).hexdigest()

        def preview(reason):
            rv = {"analyst_review_id": "AR-1", "investigation_id": inv, "exception_id": "EXC-SC5A-01", "decision": "REJECT",
                  "findings_sha256": sha, "rejection_reason": reason, "reviewer": {"user_id": "u", "display_name": "U"},
                  "decided_at": "2026-11-05T06:20:04+00:00"}
            snap = build_review_snapshot(SC5A, [{"exception_id": "EXC-SC5A-01", "inclusion": "INCLUDED", "investigation_id": inv},
                                                {"exception_id": "EXC-SC5A-02", "inclusion": "NOT_INVESTIGATED"}],
                                         investigations_root=root, analyst_reviews=[rv])
            return assemble_preview(snap, generate_closing_summary(snap, summary_investigator(snap)[0]))
        cls.final = preview(REASON)
        cls.cjk = preview("Contract 合同 reviewed")
        for name, doc in (("unicode.json", cls.final), ("cjk.json", cls.cjk)):
            (cls.tmp / name).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_render(self, name, env=None):
        r = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT), str(self.tmp / name)], capture_output=True, encoding="utf-8",
                           errors="replace", env=dict(os.environ, PYTHONIOENCODING="utf-8", **(env or {})), timeout=300)
        return r

    def test_byte_identical_across_processes(self):
        import hashlib
        here = hashlib.sha256(rp.render_pdf(self.final)).hexdigest()
        self.assertEqual(rp.render_pdf(self.final), rp.render_pdf(self.final))
        outs = {self.run_render("unicode.json").stdout.strip() for _ in range(2)}
        self.assertEqual(outs, {here})

    @unittest.skipUnless(os.environ.get("UC042_TEST_FALLBACK_FONT"), "set UC042_TEST_FALLBACK_FONT to a CJK-capable .ttf/.ttc")
    def test_configured_fallback_font_draws_what_the_bundled_fonts_cannot(self):
        self.assertNotEqual(self.run_render("cjk.json").returncode, 0)  # bundled fonts only: refused
        r = self.run_render("cjk.json", {rp.ENV_FALLBACK_FONTS: os.environ["UC042_TEST_FALLBACK_FONT"]})
        self.assertEqual(r.returncode, 0, r.stderr[-500:])


if __name__ == "__main__":
    unittest.main()
