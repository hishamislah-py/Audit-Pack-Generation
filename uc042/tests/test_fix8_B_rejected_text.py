"""Fix8 D5 (D-04): the rejected-content leak check of the final pack (validate._rejected_text_leaks).

OFFLINE / MOCKED: every investigation and closing summary here is produced by the real OpenAIInvestigator, graph,
validation and persistence with only the HTTP layer mocked (tests/final_pack_support.py). No network, no live AI.

Live defect reproduced: Kestrel (RF-DEMO-06), ACCEPT EXC-01, REJECT EXC-03; the AI closing summary restated the accepted
investigation's evidence gap as "The posting-level client ledger for C0003 was not found in the supplied data." The
rejected investigation used exactly that sentence, the accepted one wrote "... supplied data (SEARCH-03).", so the old
exact-substring exemption did not apply and the preview failed at random (it depends on the model's wording).

Run from the engine root: python -m unittest tests.test_fix8_B_rejected_text -v
"""
import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.final_pack_support import PACK, make_investigation, summary_investigator
from uc042lib.final_pack import FinalPackValidationError, assemble_preview, build_review_snapshot, generate_closing_summary
from uc042lib.final_pack.validate import (_legitimate_texts, _rejected_text_in, _rejected_text_leaks, _strings,
                                          rejected_text_diagnostics)
from uc042lib.final_pack.sources import output_of

SC3C = PACK["SC3C"]
E1, E2, E3 = "EXC-SC3C-01", "EXC-SC3C-02", "EXC-SC3C-03"
CORE = "The posting-level client ledger for C0003 was not found in the supplied data"
ACCEPTED_GAP = CORE + " (SEARCH-01)."             # the accepted investigation's wording (with its search reference)
SHARED = CORE + "."                               # the rejected investigation's wording = what the summary wrote live
REJ2_ONLY = ("REJ2-ONLY-7c1d: the cash book shows a transfer pattern that the analyst rejected as unsupported by the "
             "cited records.")
REJ3_LEAD = "REJ3-LEAD-2e9a: the records for this exception were examined in full by the investigator."
REJ3_SECOND = "REJ3-SECOND-b4f0: a second rejected sentence that only the rejected investigation wrote down."
REASON = "Rejected by the analyst in Ringfence (fixed wording; no free-text reason is captured by design, owner decision O4)"


# Live 22 Nov 2026 (port 8922): the summary cited the accepted gap (ACC_REFUND) and wrote it in the rejected wording.
ACC_REFUND = "The search for REFUND transactions for C0003 GBP in the period returned NOT_FOUND."
REJ_REFUND = "The search for C0003 GBP REFUND transactions in the period returned NOT_FOUND."
ACC_NEG = "The search did not find REFUND transactions for C0007 GBP in the period under review."
REJ_NEG = "The search did find REFUND transactions for C0007 GBP in the period under review."   # negation dropped


def _more_gaps(o, *texts):
    for n, t in enumerate(texts, start=2):
        o["missing_evidence"].append(dict(o["missing_evidence"][0], item_id=f"M-0{n}", description=t))


def _gap(text):
    def edit(o):
        o["missing_evidence"][0]["description"] = text
        _more_gaps(o, ACC_REFUND, ACC_NEG)
    return edit


def _rej2(o):
    o["missing_evidence"][0]["description"] = REJ2_ONLY


def _rej3(o):
    o["missing_evidence"][0]["description"] = SHARED
    _more_gaps(o, REJ_REFUND, REJ_NEG)
    o["investigation_summary"] = f"{REJ3_LEAD} {REJ3_SECOND}"


def _append_summary_text(text):
    def edit(d):
        d["summary_text"] += " " + text
    return edit


def _summary_gap(text):
    def edit(d):
        for g in d["evidence_gaps"]:
            g["text"] = text
    return edit


class RejectedTextRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.root = cls.tmp / "investigations"
        cls.inv = {E1: make_investigation("SC3C", E1, cls.root, edit=_gap(ACCEPTED_GAP)),
                   E2: make_investigation("SC3C", E2, cls.root, edit=_rej2),
                   E3: make_investigation("SC3C", E3, cls.root, edit=_rej3)}
        cls.sha = {e: hashlib.sha256(next(cls.root.glob(f"*/{e}/{i}")).joinpath("findings.json").read_bytes()).hexdigest()
                   for e, i in cls.inv.items()}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def snapshot(self, **decisions):
        """decisions: exception id (E1/E2/E3 by name e1/e2/e3) -> ACCEPT / REJECT."""
        ids = {"e1": E1, "e2": E2, "e3": E3}
        sels, reviews = [], []
        for key, exc in ids.items():
            sels.append({"exception_id": exc, "inclusion": "INCLUDED", "investigation_id": self.inv[exc]})
            d = decisions[key]
            reviews.append({"analyst_review_id": f"AR-{key}", "investigation_id": self.inv[exc], "exception_id": exc,
                            "decision": d, "findings_sha256": self.sha[exc],
                            "reviewer": {"user_id": "analyst-1", "display_name": "Test Analyst"},
                            "decided_at": "2026-11-22T10:00:00+00:00", "rejection_reason": REASON if d == "REJECT" else ""})
        return build_review_snapshot(SC3C, sels, investigations_root=self.root, analyst_reviews=reviews)

    def preview(self, snap, edit=None):
        summary = generate_closing_summary(snap, summary_investigator(snap, edit)[0])
        self.assertEqual(summary.status, "GENERATED")
        return assemble_preview(snap, summary)

    # ------------------------------------------------------------------------------------------------- false positive
    def test_one_accept_one_reject_shared_wording_in_summary_passes(self):
        """D-04 reproduced deterministically: ACCEPT E1, REJECT E3, the summary restates E1's gap in E3's exact words."""
        snap = self.snapshot(e1="ACCEPT", e2="ACCEPT", e3="REJECT")
        final = self.preview(snap, _summary_gap(SHARED))
        self.assertIn(SHARED, [g["text"] for g in final["closing_summary"]["output"]["evidence_gaps"]])
        # the OLD rule (exact substring against accepted / deterministic text) refuses this pack: the root cause
        out3 = output_of(snap.bundles[self.inv[E3]])
        allowed = "\n".join(_strings(snap.pack) + [t for a in snap.accepted_ids
                                                    for t in _strings(output_of(snap.bundles[a]).model_dump())])
        blob = "\n".join(_strings(final, skip=("rejection_reason", "comment")))
        old_leaks = [p for p in {m.description.strip() for m in out3.missing_evidence} if p not in allowed and p in blob]
        self.assertEqual(old_leaks, [SHARED])
        # the NEW rule: the sentence is the accepted investigation's statement, so it is not rejected-only content
        self.assertEqual(rejected_text_diagnostics(final, snap), [])

    def test_one_accept_one_reject_default_summary_passes(self):
        snap = self.snapshot(e1="ACCEPT", e2="ACCEPT", e3="REJECT")
        final = self.preview(snap)
        self.assertEqual(rejected_text_diagnostics(final, snap), [])
        self.assertEqual([i["investigation_id"] for i in final["ai_investigations"]], [self.inv[E1], self.inv[E2]])

    def test_multiple_rejected_findings_with_shared_wording_pass(self):
        snap = self.snapshot(e1="ACCEPT", e2="REJECT", e3="REJECT")
        final = self.preview(snap, _summary_gap(SHARED))
        self.assertEqual(rejected_text_diagnostics(final, snap), [])
        self.assertEqual([i["investigation_id"] for i in final["ai_investigations"]], [self.inv[E1]])
        disp = {e["exception"]["exception_id"]: e["investigation"]["analyst_review"]["decision"]
                for e in final["exception_register"]}
        self.assertEqual(disp, {E1: "ACCEPT", E2: "REJECT", E3: "REJECT"})

    def test_no_rejected_findings(self):
        snap = self.snapshot(e1="ACCEPT", e2="ACCEPT", e3="ACCEPT")
        final = self.preview(snap, _summary_gap(SHARED))
        self.assertEqual(rejected_text_diagnostics(final, snap), [])
        self.assertEqual(len(final["ai_investigations"]), 3)

    def test_analyst_may_quote_rejected_text(self):
        """Unchanged rule: rejection reasons and comments are the analyst's wording and are not scanned."""
        bundle = self.snapshot(e1="ACCEPT", e2="REJECT", e3="ACCEPT").bundles[self.inv[E2]]
        self.assertEqual(_rejected_text_in({"x": {"rejection_reason": REJ2_ONLY, "comment": REJ2_ONLY}}, bundle), [])

    # ------------------------------------------------------------------------------------------------- genuine leaks
    def test_genuine_rejected_only_text_still_fails_with_diagnostics(self):
        snap = self.snapshot(e1="ACCEPT", e2="REJECT", e3="REJECT")
        with self.assertRaises(FinalPackValidationError) as cm:
            self.preview(snap, _append_summary_text(REJ2_ONLY))
        msg = str(cm.exception)
        self.assertIn(f"{self.inv[E2]}: text of the REJECTED investigation's AI output appears in the report", msg)
        self.assertIn("rejected source missing_evidence[0].description", msg)
        self.assertIn("found at closing_summary.output.summary_text", msg)
        leaks = cm.exception.diagnostics["rejected_text_leaks"]
        self.assertEqual([(k["investigation_id"], k["text"], k["rejected_source"]) for k in leaks],
                         [(self.inv[E2], REJ2_ONLY, "missing_evidence[0].description")])
        self.assertEqual(leaks[0]["found_at"], ["closing_summary.output.summary_text"])
        self.assertEqual(cm.exception.diagnostics["errors"], cm.exception.errors)

    def test_one_sentence_lifted_from_a_longer_rejected_passage_fails(self):
        """Strengthened: the old rule matched whole passages only, so this sentence alone was not detected."""
        snap = self.snapshot(e1="ACCEPT", e2="ACCEPT", e3="REJECT")
        with self.assertRaises(FinalPackValidationError) as cm:
            self.preview(snap, _append_summary_text(REJ3_SECOND))
        leaks = cm.exception.diagnostics["rejected_text_leaks"]
        self.assertEqual([(k["text"], k["rejected_source"]) for k in leaks], [(REJ3_SECOND, "investigation_summary")])

    def test_reworded_case_and_quotes_still_detected(self):
        snap = self.snapshot(e1="ACCEPT", e2="REJECT", e3="ACCEPT")
        variant = REJ2_ONLY.upper().replace(": ", " — ")
        with self.assertRaises(FinalPackValidationError) as cm:
            self.preview(snap, _append_summary_text(variant))
        self.assertEqual([k["text"] for k in cm.exception.diagnostics["rejected_text_leaks"]], [REJ2_ONLY])

    def test_shared_wording_is_exempt_only_when_an_accepted_source_states_it(self):
        """With E1 also REJECTED nothing accepted states the gap any more: the same summary is now refused."""
        snap = self.snapshot(e1="REJECT", e2="ACCEPT", e3="REJECT")
        # the summary may only cite accepted refs; E1 is rejected, so put the sentence in free summary text
        with self.assertRaises(FinalPackValidationError) as cm:
            self.preview(snap, _append_summary_text(SHARED))
        leaks = cm.exception.diagnostics["rejected_text_leaks"]
        self.assertIn((self.inv[E3], SHARED), [(k["investigation_id"], k["text"]) for k in leaks])

    # ------------------------------------------------------------------------------------------------- citations
    def _cited_gap(self, text, gap="M-02", exc=None):
        inv = self.inv[exc or E1]

        def edit(d):
            d["evidence_gaps"] = [{"text": text, "source_refs": [f"{inv}#{gap}"]}]
        return edit

    def test_reordered_wording_in_a_cited_summary_item_is_attributed(self):
        """The live case of 22 Nov 2026: same words, different order, in an evidence gap citing the accepted gap."""
        snap = self.snapshot(e1="ACCEPT", e2="ACCEPT", e3="REJECT")
        final = self.preview(snap, self._cited_gap(REJ_REFUND + " This does not establish that such records do not exist."))
        self.assertEqual(rejected_text_diagnostics(final, snap), [])
        full = rejected_text_diagnostics(final, snap, include_attributed=True)
        self.assertEqual([(d["text"], d["found_at"], d["attributed_at"]) for d in full],
                         [(REJ_REFUND, [], ["closing_summary.output.evidence_gaps[0].text"])])

    def test_reordered_wording_without_a_matching_citation_still_fails(self):
        snap = self.snapshot(e1="ACCEPT", e2="ACCEPT", e3="REJECT")
        for edit, where in ((_append_summary_text(REJ_REFUND), "closing_summary.output.summary_text"),   # no citation
                            (self._cited_gap(REJ_REFUND, gap="M-01"), "closing_summary.output.evidence_gaps[0].text")):
            with self.assertRaises(FinalPackValidationError) as cm:
                self.preview(snap, edit)
            leaks = cm.exception.diagnostics["rejected_text_leaks"]
            self.assertEqual([(k["text"], k["found_at"]) for k in leaks], [(REJ_REFUND, [where])])

    def test_dropping_a_negation_is_never_attributed(self):
        snap = self.snapshot(e1="ACCEPT", e2="ACCEPT", e3="REJECT")
        with self.assertRaises(FinalPackValidationError) as cm:
            self.preview(snap, self._cited_gap(REJ_NEG, gap="M-03"))
        self.assertEqual([k["text"] for k in cm.exception.diagnostics["rejected_text_leaks"]], [REJ_NEG])

    def test_leak_function_units_and_legitimate_set(self):
        snap = self.snapshot(e1="ACCEPT", e2="REJECT", e3="REJECT")
        legit = _legitimate_texts(snap)
        b3 = snap.bundles[self.inv[E3]]
        report = {"closing_summary": {"output": {"summary_text": f"{SHARED} {REJ3_LEAD}"}}}
        self.assertEqual(_rejected_text_leaks(report, b3, legit),
                         [{"text": REJ3_LEAD, "rejected_source": "investigation_summary",
                           "found_at": ["closing_summary.output.summary_text"]}])


if __name__ == "__main__":
    unittest.main()
