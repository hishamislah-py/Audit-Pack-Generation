"""Analyst edition (renderer uc042-final-report-renderer/4.0-analyst), 23 Nov 2026.

Fixtures (read-only copies, tests/fixtures/analyst_edition/): the stored September pack FAP-CASE-PER-2026-09-v1-2711660abe93
(final pack, its Ringfence provenance record, its deterministic source pack, its published technical report.pdf) and the
June clean pack FAP-CASE-PER-2026-06-v1-26596c6743aa, plus the owner's reference PDF.

1 golden September render; 2 value fidelity; 3 clean pack; 4 decision variants; 5 rejected-content exclusion; 6 removed
elements; 7 layout; 8 palette; 9 technical report byte-identical; plus source-pack verification and no AI."""
import copy
import io
import json
import re
import unittest
from pathlib import Path

from pypdf import PdfReader

from uc042lib.final_pack import report_analyst as RA
from uc042lib.final_pack.render_pdf import render_pdf

FX = Path(__file__).parent / "fixtures" / "analyst_edition"
PAGE_COUNTS = {}


def load(name):
    d = FX / name
    final = json.loads((d / "final_pack.json").read_text(encoding="utf-8"))
    prov = json.loads((d / "ringfence_provenance.json").read_text(encoding="utf-8"))
    pack = json.loads((d / "source_pack.json").read_text(encoding="utf-8"))
    return final, prov, pack


def text_of(pdf):
    r = PdfReader(io.BytesIO(pdf))
    return [p.extract_text() or "" for p in r.pages]


def flat(pages):
    return re.sub(r"\s+", " ", " ".join(pages))


SEP, SEP_PROV, SEP_PACK = load("sep")
JUN, JUN_PROV, JUN_PACK = load("jun")


def render(final, prov, pack, key=None):
    pdf, model = RA.render_analyst_pdf(final, prov, RA.verified_source_pack(final, pack))
    pages = text_of(pdf)
    if key:
        PAGE_COUNTS[key] = len(pages)
    return pdf, model, pages


class Golden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pdf, cls.model, cls.pages = render(SEP, SEP_PROV, SEP_PACK, "September (exceptions, accept + reject)")
        cls.t = flat(cls.pages)

    def test_1_section_order_and_reference_content(self):
        order = ["September 2026 — Exceptions open", "1. Outcome", "Exceptions at a glance", "What is needed next",
                 "2. Exceptions", "EXC-CASE-01 — Settlement batch arithmetic", "EXC-CASE-02 — Client balance roll-forward",
                 "POSSIBLE LINK BETWEEN THE EXCEPTIONS — UNVERIFIED", "3. Reconciliation results", "Control checks",
                 "4. Evidence received", "5. Review and sign-off", "Appendix — Integrity record"]
        pos = [self.t.find(x) for x in order]
        self.assertTrue(all(p >= 0 for p in pos), dict(zip(order, pos)))
        self.assertEqual(pos, sorted(pos))
        for v in ["Reporting period 1–30 September 2026 · 22 reconciliation days", "EXCEPTIONS OPEN", "1,884", "of 1,886 control results passed",
                  "17 / 17", "£443.55", "15 September 2026", "engine roll-forward £48,257.08", "17:00 snapshot £47,813.53",
                  "14 Sep: £48,492.79", "net reported £2,868.50", "Batch lines FAIL (bank matching PASS)",
                  "settlement_batches_2026-09.csv line 43", "settlement_lines_2026-09.csv lines 199–204",
                  "client_balance_snapshots_2026-09.csv lines 123, 135", "Awaiting human review",
                  "overall evidence assessment: partially sufficient", "“agrred”",
                  "“it showcaes the error and it is a duplication error”", "23 Nov 2026, 10:29:34 UTC",
                  "Every exception remains UNRESOLVED", "Not evidence-backed and not an investigation group",
                  "The engine established no relationship between the exceptions",
                  "30 checks passed in full", "C11-BATCH-ARITH (1 failed, 87 passed)", "CBAL-ROLLFWD (1 failed, 263 passed)",
                  "BANK-CASH-LINK reports problems only; it ran and found none", "Results (summed per area)", "1,884 passed · 2 failed",
                  "12_Harrowgate_Card_Services_Ltd_September_2026_M2_incomplete.zip", "RF-2026-09-003",
                  "All 153 columns across 19 files mapped by exact deterministic match", "01_reconciliation_calendar.csv",
                  "REP027_receipt_Aug2026.pdf", "AR-7A04E6AA3D6E", "AR-D95A3128C9E3", "RD-EB7EAA2F5F73",
                  "RECON-20261123T102720Z-566933c7", "SNAP-001-566933c7",
                  "2711660abe93978ad3ab48e19adc7068e300732ca9701208f6fceddca207279d",
                  "914b21ddc93e1f743cc478892981414150e29b9d9e312c3d2fa6b20d5c5ef76c",
                  "renderer uc042-final-report-renderer/4.0-analyst", "processing run RUN-75214c6daeccefb8",
                  "ILLUSTRATIVE SYNTHETIC DATA · not an audit opinion or compliance certification · analyst edition of the generated report"]:
            self.assertIn(v, self.t, v)
        self.assertEqual(len(self.pages), 6)  # 24 Nov 2026: the reconciliation statement box added one page
        self.assertTrue(all(f"Page {i} of 6" in p for i, p in enumerate(self.pages, 1)))
        self.assertEqual(self.model["omitted"], [])

    def test_1_reconciliation_statement_with_failures(self):
        st = self.model["outcome"]["statement"]
        self.assertEqual(st["state"], "FAILURES")
        self.assertEqual(st["headline"], "Not everything checks out")
        fails = {x["area"]: x["text"] for x in st["lines"] if x["state"] == "FAIL"}
        self.assertEqual(sorted(fails), ["Client balances and transactions", "Settlement"])
        self.assertIn("C11-BATCH-ARITH", fails["Settlement"])
        for v in ["RECONCILIATION STATEMENT", "Not everything checks out", "5 of 7 areas passed in full",
                  "settlement batch arithmetic (C11-BATCH-ARITH)", "not by AI"]:
            self.assertIn(v, self.t, v)
        self.assertLess(self.t.find("RECONCILIATION STATEMENT"), self.t.find("Exceptions at a glance"))

    def test_1_accepted_ai_conclusion_is_verbatim(self):
        summary = SEP["ai_investigations"][0]["assessment"]["summary"]
        self.assertIn("“" + summary + "”", self.t)

    def test_2_value_fidelity(self):
        stored = json.dumps([SEP, SEP_PROV], ensure_ascii=False) + json.dumps(SEP_PACK, ensure_ascii=False)
        for a in set(re.findall(r"[£€]-?[\d,]+\.\d{2}", self.t)):
            digits = a.lstrip("£€").replace(",", "")
            self.assertIn(f'"{digits}"', stored, a)
        for h in set(re.findall(r"\b[0-9a-f]{64}\b", self.t)):
            self.assertIn(h, stored, h)
        for ident in set(re.findall(r"\b(?:FAP|PACK|INV|AR|RD|RECON|SNAP|RUN|EXC|SB|SL|TX|CAND)-[A-Za-z0-9-]+[A-Za-z0-9]\b", self.t)):
            self.assertIn(ident, stored, ident)
        for fn in set(re.findall(r"\b[\w.-]+\.(?:csv|pdf|zip)\b", self.t)):
            if fn != "ringfence_provenance.json":
                self.assertIn(fn, stored, fn)

    def test_6_removed_elements(self):
        for gone in ["closing summary", "Closing summary", "Limitations", "Most important evidence-supported observations",
                     "Hypothes", "Key observations", "Daily reconciliation at a glance", "Opening positions",
                     "Exact amounts and dates", "Related exceptions", "Group assessments", "Cited source records",
                     "Two high-severity exceptions remain unresolved"]:       # the stored AI closing summary text
            self.assertNotIn(gone, self.t, gone)

    def test_7_layout_short_labels_never_wrap_and_no_empty_labels(self):
        lines = [ln for p in self.pages for ln in p.splitlines()]
        for token in ["OPEN · UNRESOLVED", "Rejected", "Accepted", "REJECT", "ACCEPT", "GENERATE", "AR-7A04E6AA3D6E",
                      "AR-D95A3128C9E3", "RD-EB7EAA2F5F73", "23 Nov 2026, 10:29:34", "23 Nov 2026, 11:10:32", "Severity"]:
            self.assertTrue(any(token in ln for ln in lines), f"{token!r} is split across lines")
        for card in self.model["cards"]:
            for k, v in card["engine_rows"] + card["ai_rows"]:
                self.assertTrue(v not in (None, "", []), (card["exception_id"], k))
        # each exception card and the appendix are kept on one page
        for eid in ("EXC-CASE-01", "EXC-CASE-02"):
            on = [i for i, p in enumerate(self.pages) if f"{eid} — " in p]
            self.assertEqual(len(on), 1, eid)
            self.assertIn("AI INVESTIGATION AND ANALYST DECISION", self.pages[on[0]])
        self.assertTrue(any("Appendix — Integrity record" in p and "Versions" in p for p in self.pages))

    def test_9_technical_report_is_byte_identical(self):
        self.assertEqual(render_pdf(SEP), (FX / "sep" / "report.pdf").read_bytes())

    def test_source_pack_must_be_the_pinned_one(self):
        self.assertIsNotNone(RA.verified_source_pack(SEP, SEP_PACK))
        self.assertIsNone(RA.verified_source_pack(SEP, JUN_PACK))
        tampered = copy.deepcopy(SEP_PACK)
        tampered["control_register"][0]["results"][0]["note"] = "changed"
        self.assertIsNone(RA.verified_source_pack(SEP, tampered))
        _, model, _ = render(SEP, SEP_PROV, None)
        self.assertTrue(any("source pack was not supplied" in o for o in model["omitted"]))

    def test_without_provenance_the_elements_are_omitted_and_logged(self):
        _, model, pages = render(SEP, None, SEP_PACK)
        t = flat(pages)
        self.assertNotIn("Package ", t)
        self.assertNotIn("01_reconciliation_calendar.csv", t)
        self.assertTrue(any("no provenance record" in o for o in model["omitted"]))


class Clean(unittest.TestCase):
    def test_3_clean_pack(self):
        pdf, model, pages = render(JUN, JUN_PROV, JUN_PACK, "June (clean)")
        t = flat(pages)
        self.assertIn("June 2026 — Clean", t)
        self.assertIn("No exceptions were raised; no AI investigation was required.", t)
        for gone in ["Exceptions at a glance", "2. Exceptions", "What is needed next", "POSSIBLE LINK", "Possible link"]:
            self.assertNotIn(gone, t)
        self.assertIn("2. Reconciliation results", t)
        self.assertIn("4. Review and sign-off", t)
        self.assertTrue(3 <= len(pages) <= 4, len(pages))
        st = model["outcome"]["statement"]
        self.assertEqual((st["state"], st["headline"]), ("ALL_PASSED", "Everything checks out"))
        self.assertTrue(all(x["state"] == "PASS" for x in st["lines"]))
        self.assertEqual(len(st["lines"]), 7)
        for v in ["Everything checks out", "All 33 checks passed across 1,965 control results",
                  "the safeguarding position for June 2026 reconciles in full",
                  "The firm's ledger agreed with the bank on all 44 account-days.",
                  "All 88 settlement batches agreed with their lines and with the bank."]:
            self.assertIn(v, t, v)


class Statement(unittest.TestCase):
    """The deterministic reconciliation statement (24 Nov 2026), from stored per-check counts only."""
    from uc042lib.final_pack.statement import build_statement as _b
    build = staticmethod(_b)

    def test_insufficient_evidence_only(self):
        st = self.build({"C06-DIFFERENCE": {"PASS": 10}, "C08-DIFFERENCE": {"PASS": 9, "INSUFFICIENT_EVIDENCE": 1}},
                        "September 2026", 1)
        self.assertEqual(st["state"], "INCOMPLETE")
        ext = [x for x in st["lines"] if x["key"] == "external"][0]
        self.assertEqual(ext["state"], "INCOMPLETE")
        self.assertIn("could not be evaluated for lack of evidence", ext["text"])

    def test_unknown_check_goes_to_other(self):
        st = self.build({"C06-DIFFERENCE": {"PASS": 4}, "ZZ-NEW": {"FAIL": 2}}, "September 2026", 1)
        self.assertEqual([x["area"] for x in st["lines"]], ["Internal reconciliation", "Other checks"])
        self.assertIn("2 results failed: ZZ-NEW (ZZ-NEW)", st["lines"][1]["text"])

    def test_app_copy_is_identical(self):
        app = Path(__file__).resolve().parents[2] / "app_merge" / "smartparser" / "webapp" / "statement.py"
        if not app.is_file():
            self.skipTest("app worktree not alongside")
        strip = lambda s: s.split('"""', 2)[2]  # noqa: E731 - the docstrings name each other
        eng = (Path(__file__).resolve().parents[1] / "uc042lib" / "final_pack" / "statement.py").read_text(encoding="utf-8")
        self.assertEqual(strip(eng), strip(app.read_text(encoding="utf-8")))


def variant(kind):
    f = copy.deepcopy(SEP)
    e1, e2 = f["exception_register"]
    inv2 = f["ai_investigations"][0]
    if kind == "all_accepted":
        clone = copy.deepcopy(inv2)
        clone.update(investigation_id=e1["investigation"]["investigation_id"], exception_id="EXC-CASE-01")
        clone["assessment"] = dict(clone["assessment"], summary="SYNTHETIC VARIANT accepted summary for EXC-CASE-01.")
        f["ai_investigations"].append(clone)
        ar = e1["investigation"]["analyst_review"]
        ar.pop("rejection_reason", None)
        ar.update(decision="ACCEPT", comment="variant comment")
    elif kind == "all_rejected":
        ar = e2["investigation"]["analyst_review"]
        ar.pop("comment", None)
        ar.update(decision="REJECT", rejection_reason="variant reason, kept verbatim")
        # the accepted content is deliberately LEFT in ai_investigations: the renderer must still never show it
    elif kind == "not_investigated":
        e1["investigation"] = {"inclusion": "NOT_INVESTIGATED", "investigation_id": None}
    elif kind == "no_ai":
        for e in (e1, e2):
            e["investigation"] = {"inclusion": "NOT_INVESTIGATED", "investigation_id": None}
        f["ai_investigations"] = []
    return f


class Variants(unittest.TestCase):
    def test_4_all_accepted(self):
        _, model, pages = render(variant("all_accepted"), SEP_PROV, SEP_PACK, "variant: all accepted")
        t = flat(pages)
        self.assertEqual([g["ai_review"] for g in model["outcome"]["glance"]], ["Accepted", "Accepted"])
        self.assertIn("“SYNTHETIC VARIANT accepted summary for EXC-CASE-01.”", t)
        self.assertIn("“variant comment”", t)
        self.assertNotIn("Not reported. The analyst rejected", t)

    def test_4_and_5_all_rejected_never_shows_ai_content(self):
        _, model, pages = render(variant("all_rejected"), SEP_PROV, SEP_PACK, "variant: all rejected")
        t = flat(pages)
        self.assertEqual([g["ai_review"] for g in model["outcome"]["glance"]], ["Rejected", "Rejected"])
        inv = SEP["ai_investigations"][0]
        texts = [inv["assessment"]["summary"]] + [x.get("description", "") for x in inv["confirmed_findings"]] + \
                [s.get("action", "") for s in inv["next_steps"]] + [h.get("statement", h.get("description", "")) for h in inv["hypotheses"]]
        for txt in [x for x in texts if x]:
            self.assertNotIn(re.sub(r"\s+", " ", txt)[:60], t)
        self.assertEqual(t.count("Not reported. The analyst rejected this investigation"), 2)
        self.assertIn("“variant reason, kept verbatim”", t)
        self.assertNotIn("What is needed next", t)                         # next steps come from accepted investigations only

    def test_4_mixed_is_the_golden_pack(self):
        _, model, _ = render(SEP, SEP_PROV, SEP_PACK)
        self.assertEqual([g["ai_review"] for g in model["outcome"]["glance"]], ["Rejected", "Accepted"])

    def test_4_not_investigated(self):
        _, model, pages = render(variant("not_investigated"), SEP_PROV, SEP_PACK, "variant: one not investigated")
        t = flat(pages)
        self.assertEqual(model["outcome"]["glance"][0]["ai_review"], "Not investigated")
        self.assertIn("No AI investigation was included for this exception.", t)

    def test_4_exceptions_without_any_ai(self):
        _, model, pages = render(variant("no_ai"), SEP_PROV, SEP_PACK, "variant: exceptions without AI")
        t = flat(pages)
        self.assertEqual(t.count("No AI investigation was included for this exception."), 2)
        self.assertNotIn("AI conclusion", t)
        self.assertNotIn("What is needed next", t)


class Palette(unittest.TestCase):
    def test_8_navy_and_grey_only(self):
        src = Path(RA.__file__).read_text(encoding="utf-8")
        found = {h.lower() for h in re.findall(r"#[0-9a-fA-F]{6}\b", src)}
        self.assertTrue(found <= set(RA.PALETTE_HEX), found - set(RA.PALETTE_HEX))
        self.assertIsNone(re.search(r"colors\.(red|green|orange|yellow|amber|darkred|darkgreen)", src))
        for h in found:
            r, g, b = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
            self.assertFalse(r > g + 40 and r > b + 40, h)                 # reddish / amber
            self.assertFalse(g > r + 40 and g > b + 10, h)                 # greenish


class ZZPageCounts(unittest.TestCase):
    def test_zz_page_counts_recorded(self):
        out = Path(__file__).parent / "fixtures" / "analyst_edition"
        if PAGE_COUNTS:
            (out / "PAGE_COUNTS.last_run.json").write_text(json.dumps(PAGE_COUNTS, indent=1, ensure_ascii=False), encoding="utf-8")
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
