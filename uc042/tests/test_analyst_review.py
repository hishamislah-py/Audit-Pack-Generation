"""Analyst review of AI investigations (ACCEPT / REJECT in the Exception Workspace) through the API and into the final audit
pack: the mandatory, verbatim rejection reason; append-only decisions with revision protection; the read-only review
history; final-review gating (pending investigations, rejected content excluded, stale previews); and the protection of the
deterministic exception, the pack and the investigation artefacts. Offline (mocked provider). Run from uc042/:
python -m unittest tests.test_analyst_review -v   (UC042_TEST_REPOSITORIES=sqlite|postgres for the SQL repositories)"""
import io
import json
import unittest

from pypdf import PdfReader

from tests.api_support import ROOT, TEST_REPOSITORIES, ApiCase
from tests.final_pack_support import PACK, sha_tree
from uc042lib.final_pack import verify_final_pack
from uc042lib.final_pack.render_pdf import pdf_text

SC5A = PACK["SC5A"]
EXC = "EXC-SC5A-01"
SUMMARY_MARK = "SUMMARY-MARKER-7f3a: the records show the reported difference; the evidence does not establish why."
HYPOTHESIS_MARK = "HYPOTHESIS-MARKER-91c2 a possible explanation that the evidence does not establish"
STEP_MARK = "STEP-MARKER-5d0e obtain the bank trace for the item"
# Leading and trailing spaces, line breaks, punctuation and a non-ASCII character: stored and reported exactly as written.
REASON = ("  The AI treated the 15 Sept top-up as unexplained,\nbut the bank advice BA-0915 (not in the dataset) shows it "
          "was an own-funds transfer.\n\n- Analyst: reject; re-run after the advice is loaded.  ")


def marked(o):
    o["investigation_summary"] = SUMMARY_MARK
    o["hypotheses"].append({"hypothesis_id": "H-09", "possible_explanation": HYPOTHESIS_MARK, "supporting_evidence": [],
                            "contradictory_evidence": [], "limitations": "Not established by the cited records.",
                            "status": "HYPOTHESIS", "rationale": "Considered because the amounts coincide on the same day."})
    o["recommended_next_steps"].append({"step_id": "S-09", "action": STEP_MARK, "rationale": "The item is unexplained.",
                                        "evidence_needed": "The bank's advice for the item."})


def _pdf_text(data):
    return "".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)


def _norm(s):
    return "".join(pdf_text(s).split())


class AnalystReviewCase(ApiCase):
    def setUp(self):
        super().setUp()
        self.pack_before = sha_tree(ROOT / "packs" / SC5A)
        job = self.run_investigation_job("SC5A", EXC, edit=marked)
        self.assertEqual(job["status"], "COMPLETED", job)
        self.inv_id = job["result"]["investigation_id"]
        self.inv_dir = next(self.inv_root.glob(f"*/{EXC}/{self.inv_id}"))
        self.artefact_before = sha_tree(self.inv_dir)

    # ---------------------------------------------------------------- helpers
    def decide(self, decision, expected_revision, inv=None, **body):
        return self.post(f"/api/v1/investigations/{inv or self.inv_id}/analyst-review",
                         dict({"decision": decision, "expected_revision": expected_revision}, **body))

    def history(self):
        r = self.get(f"/api/v1/packs/{SC5A}/exceptions/{EXC}/review-history")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def open_review(self):
        r = self.post(f"/api/v1/packs/{SC5A}/reviews")
        self.assertIn(r.status_code, (200, 201), r.text)
        return r.json()

    def generate(self, session):
        return self.post(f"/api/v1/reviews/{session['review_id']}/decision",
                         {"decision": "GENERATE", "snapshot_sha256": session["current_preview"]["snapshot_sha256"],
                          "acknowledgement_accepted": True, "comment": "Reviewed the preview."})

    def preview_doc(self, session):
        base = f"/api/v1/reviews/{session['review_id']}/preview"
        return self.get(base + "/json").json(), self.get(base + "/html").text, _pdf_text(self.get(base + "/pdf").content)

    def exception_status(self):
        x = self.get(f"/api/v1/packs/{SC5A}/exceptions/{EXC}").json()
        return x["exception"]["status"], x["exception"]["resolution_status"], [(r["result_id"], r["outcome"], r["computed"],
                                                                                 r["reported"]) for r in x["affected_results"]]

    def assert_untouched(self):
        self.assertEqual(sha_tree(self.inv_dir), self.artefact_before, "the investigation artefact changed")
        self.assertEqual(sha_tree(ROOT / "packs" / SC5A), self.pack_before, "the deterministic pack changed")


class AcceptedInvestigation(AnalystReviewCase):
    """Scenario A."""

    def test_accept_is_recorded_shown_and_reported_with_citations(self):
        r = self.decide("ACCEPT", 0, comment="Agrees with the bank statement.")
        self.assertEqual(r.status_code, 201, r.text)
        d = r.json()
        self.assertEqual((d["decision"], d["comment"], d["revision"], d["active"], d["rejection_reason"]),
                         ("ACCEPT", "Agrees with the bank statement.", 1, True, ""))
        self.assertEqual(d["reviewer"], {"user_id": "analyst-1", "display_name": "Test Analyst"})
        self.assertTrue(d["decided_at"] and d["findings_sha256"] and d["findings_schema_version"])
        row = self.get(f"/api/v1/packs/{SC5A}/exceptions/{EXC}/investigations").json()["published"][0]
        self.assertEqual(row["analyst_review"]["analyst_review_id"], d["analyst_review_id"])
        self.assertEqual(self.get(f"/api/v1/investigations/{self.inv_id}").json()["analyst_review"]["decision"], "ACCEPT")
        events = self.history()["events"]
        kinds = [e["kind"] for e in events]
        for k in ("AI_INVESTIGATION_REQUESTED", "AI_INVESTIGATION_STARTED", "AI_INVESTIGATION_COMPLETED",
                  "AI_INVESTIGATION_PUBLISHED", "ANALYST_DECISION_ACCEPT"):
            self.assertIn(k, kinds)
        self.assertEqual(kinds[-1], "ANALYST_DECISION_ACCEPT")  # chronological
        last = events[-1]
        self.assertEqual((last["investigation_id"], last["details"]["comment"], last["details"]["active"], last["actor"]),
                         (self.inv_id, "Agrees with the bank statement.", True, "analyst-1"))

        s = self.open_review()
        self.assertNotIn("AI_REVIEW_PENDING", [b["code"] for b in s["readiness"]["blockers"]])
        s = self.preview(s["review_id"])
        doc, html, pdf = self.preview_doc(s)
        self.assertEqual(doc["final_pack_schema_version"], "uc042-final-pack/1.3")  # 1.3 since renderer 3.0 (18 Nov 2026)
        self.assertEqual([i["investigation_id"] for i in doc["ai_investigations"]], [self.inv_id])
        review = doc["exception_register"][0]["investigation"]["analyst_review"]
        self.assertEqual((review["decision"], review["comment"], review["analyst_review_id"]), ("ACCEPT", "Agrees with the bank statement.",
                                                                                               d["analyst_review_id"]))
        inv = doc["ai_investigations"][0]
        self.assertTrue(inv["confirmed_findings"] and all(f["evidence_refs"] for f in inv["confirmed_findings"]))  # citations kept
        self.assertEqual(inv["assessment"]["summary"], SUMMARY_MARK)
        self.assertIn("ANALYST DECISION: ACCEPT", html)
        self.assertIn(_norm("ANALYST DECISION: ACCEPT"), _norm(pdf))
        g = self.generate(s)
        self.assertEqual(g.status_code, 201, g.text)
        fp = g.json()["final_pack"]["final_pack_id"]
        self.assertEqual(verify_final_pack(self.settings.final_packs_root / fp), [])
        self.assertEqual(self.get(f"/api/v1/final-packs/{fp}/verify").json()["verified"], True)
        self.assert_untouched()


class RejectedInvestigation(AnalystReviewCase):
    """Scenario B."""

    def test_reason_is_mandatory_on_the_backend(self):
        for body in ({}, {"rejection_reason": ""}, {"rejection_reason": "   \n\t  "}):
            r = self.decide("REJECT", 0, **body)
            self.assertEqual((r.status_code, r.json()["code"]), (422, "REJECTION_REASON_REQUIRED"), body)
        # an optional comment never stands in for the mandatory reason
        r = self.decide("REJECT", 0, rejection_reason="  ", comment="a comment instead of a reason")
        self.assertEqual((r.status_code, r.json()["code"]), (422, "REJECTION_REASON_REQUIRED"))
        r = self.decide("ACCEPT", 0, rejection_reason="Not a rejection.")
        self.assertEqual((r.status_code, r.json()["code"]), (422, "REASON_NOT_ALLOWED"))
        r = self.post(f"/api/v1/investigations/{self.inv_id}/analyst-review", {"decision": "REJECT", "rejection_reason": "No revision."})
        self.assertEqual(r.status_code, 422)  # expected_revision is required
        r = self.decide("MAYBE", 0)
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.get(f"/api/v1/investigations/{self.inv_id}/analyst-reviews").json(), [])  # nothing was stored

    def test_rejection_reason_is_kept_verbatim_and_replaces_the_ai_content(self):
        r = self.decide("REJECT", 0, rejection_reason=REASON)
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["rejection_reason"], REASON)  # exactly, including spaces and line breaks
        ev = [e for e in self.history()["events"] if e["kind"] == "ANALYST_DECISION_REJECT"]
        self.assertEqual((len(ev), ev[0]["details"]["rejection_reason"], ev[0]["details"]["active"]), (1, REASON, True))

        s = self.open_review()
        sel = {x["exception_id"]: x for x in s["selections"]}
        self.assertEqual((sel[EXC]["inclusion"], sel[EXC]["investigation_id"]), ("INCLUDED", self.inv_id))
        self.assertIn("AI_REJECTED_BY_ANALYST", [i["code"] for i in s["readiness"]["info"]])
        s = self.preview(s["review_id"])
        doc, html, pdf = self.preview_doc(s)
        entry = doc["exception_register"][0]["investigation"]
        self.assertEqual(entry["analyst_review"]["decision"], "REJECT")
        self.assertEqual(entry["analyst_review"]["rejection_reason"], REASON)
        self.assertIsNone(entry["overall_evidence_assessment"])
        self.assertEqual(doc["ai_investigations"], [])
        self.assertEqual(doc["executive_summary"]["key_confirmed_observations"], [])
        self.assertEqual(doc["evidence_index"], {})
        self.assertEqual(doc["metadata"]["completeness"]["investigation_coverage"]["rejected_by_analyst"], 1)
        text = json.dumps(doc)
        for mark in (SUMMARY_MARK, HYPOTHESIS_MARK, STEP_MARK):  # rejected AI content: not in JSON, HTML or PDF
            self.assertNotIn(mark.split(":")[0].split(" ")[0], text)
            self.assertNotIn(mark.split(":")[0].split(" ")[0], html)
            self.assertNotIn(mark.split(":")[0].split(" ")[0], pdf)
        self.assertNotIn(self.inv_id, json.dumps(doc["closing_summary"]))  # the AI closing summary never saw its content
        self.assertIn("REJECTED BY ANALYST", html)  # the explicit analyst disposition replaces the AI content
        self.assertIn("Reason for rejection (exactly as recorded by the analyst)", html)
        self.assertEqual(entry["analyst_review"]["disposition"], "REJECTED_BY_ANALYST")
        self.assertNotIn("comment", entry["analyst_review"])  # none was written
        import html as h
        self.assertIn(h.escape(REASON), html)  # verbatim (escaped for HTML only)

        g = self.generate(s)
        self.assertEqual(g.status_code, 201, g.text)
        fp = g.json()["final_pack"]["final_pack_id"]
        final = self.get(f"/api/v1/final-packs/{fp}/json").json()
        self.assertEqual(final["exception_register"][0]["investigation"]["analyst_review"]["rejection_reason"], REASON)
        final_pdf = _pdf_text(self.get(f"/api/v1/final-packs/{fp}/pdf").content)
        self.assertIn(_norm(REASON), _norm(final_pdf))  # the analyst's words in the final PDF
        for mark in ("SUMMARY-MARKER", "HYPOTHESIS-MARKER", "STEP-MARKER"):
            self.assertNotIn(mark, final_pdf)
        self.assertNotIn("Review history", final_pdf)  # the workflow audit trail is not report content
        self.assertEqual(verify_final_pack(self.settings.final_packs_root / fp), [])
        # The original AI investigation is still available, unchanged.
        self.assertEqual(self.get(f"/api/v1/investigations/{self.inv_id}/findings").json()["investigation_summary"], SUMMARY_MARK)
        self.assert_untouched()


class RejectedWithComment(AnalystReviewCase):
    """REJECT with the mandatory reason AND the optional comment: both kept exactly and separately, reported as the analyst
    disposition in JSON, HTML and PDF; the closing-summary model never receives the rejected AI content or the analyst's
    wording (which the report carries verbatim in its own fields)."""

    def test_reason_and_comment_are_separate_verbatim_and_in_every_output(self):
        comment = "Second reviewer agrees — « vérifié » ✓ 50 % of the item;\nfollow-up with treasury on 9 Nov."
        r = self.decide("REJECT", 0, rejection_reason=REASON, comment=comment)
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual((r.json()["rejection_reason"], r.json()["comment"]), (REASON, comment))  # byte for byte
        stored = self.get(f"/api/v1/investigations/{self.inv_id}/analyst-reviews").json()[-1]
        self.assertEqual((stored["rejection_reason"].encode("utf-8"), stored["comment"].encode("utf-8")),
                         (REASON.encode("utf-8"), comment.encode("utf-8")))
        requests = []
        orig = self.provider.respond

        def capture(kw):
            requests.append(json.dumps(kw["input"], ensure_ascii=False))
            return orig(kw)
        self.provider.respond = capture
        s = self.preview(self.open_review()["review_id"])
        summary_req = [q for q in requests if "audit_pack_input" in q]
        self.assertEqual(len(summary_req), 1)
        for text in ("SUMMARY-MARKER", "HYPOTHESIS-MARKER", "STEP-MARKER", REASON.strip()[:30], "treasury"):
            self.assertNotIn(text, summary_req[0])  # rejected AI content and the analyst's wording are not model input
        self.assertIn("REJECTED_AI_CONTENT_EXCLUDED", summary_req[0])  # the structured disposition is
        g = self.generate(s)
        self.assertEqual(g.status_code, 201, g.text)
        fp = g.json()["final_pack"]["final_pack_id"]
        final = self.get(f"/api/v1/final-packs/{fp}/json").json()
        review = final["exception_register"][0]["investigation"]["analyst_review"]
        self.assertEqual((review["decision"], review["disposition"], review["rejection_reason"], review["comment"]),
                         ("REJECT", "REJECTED_BY_ANALYST", REASON, comment))
        html = self.get(f"/api/v1/final-packs/{fp}/html").text
        pdf = _pdf_text(self.get(f"/api/v1/final-packs/{fp}/pdf").content)
        import html as h
        for out in (html, pdf):
            self.assertIn("REJECTED BY ANALYST", out)
            self.assertIn(self.inv_id, out)  # the rejected investigation's reference is kept
        self.assertIn(h.escape(REASON), html)
        self.assertIn(h.escape(comment), html)
        self.assertIn(_norm(REASON), _norm(pdf))
        self.assertIn(_norm(comment), _norm(pdf))
        for mark in ("SUMMARY-MARKER", "HYPOTHESIS-MARKER", "STEP-MARKER"):
            for out in (json.dumps(final, ensure_ascii=False), html, pdf):
                self.assertNotIn(mark, out)
        self.assertEqual(verify_final_pack(self.settings.final_packs_root / fp), [])
        self.assert_untouched()


class ChangedDecision(AnalystReviewCase):
    """Scenario C (and revision protection)."""

    def test_new_decision_is_appended_previous_kept_and_preview_becomes_stale(self):
        first = self.decide("REJECT", 0, rejection_reason=REASON).json()
        stale = self.decide("ACCEPT", 0)
        self.assertEqual((stale.status_code, stale.json()["code"]), (409, "REVIEW_DECISION_CONFLICT"))  # decided on an old view
        s = self.preview(self.open_review()["review_id"])
        doc, _, _ = self.preview_doc(s)
        self.assertEqual(doc["exception_register"][0]["investigation"]["analyst_review"]["decision"], "REJECT")

        second = self.decide("ACCEPT", 1, comment="Bank advice loaded; the AI analysis stands.")
        self.assertEqual(second.status_code, 201, second.text)
        second = second.json()
        self.assertEqual((second["revision"], second["supersedes_review_id"]), (2, first["analyst_review_id"]))
        hist = self.get(f"/api/v1/investigations/{self.inv_id}/analyst-reviews").json()
        self.assertEqual([(x["decision"], x["active"]) for x in hist], [("REJECT", False), ("ACCEPT", True)])
        self.assertEqual(hist[0]["rejection_reason"], REASON)  # the earlier reason is preserved
        events = [e for e in self.history()["events"] if e["kind"].startswith("ANALYST_DECISION_")]
        self.assertEqual([(e["kind"], e["details"]["active"]) for e in events],
                         [("ANALYST_DECISION_REJECT", False), ("ANALYST_DECISION_ACCEPT", True)])

        after = self.get(f"/api/v1/reviews/{s['review_id']}").json()
        self.assertIn("PREVIEW_STALE", [b["code"] for b in after["readiness"]["blockers"]])
        g = self.generate(after)
        self.assertEqual((g.status_code, g.json()["code"]), (409, "PREVIEW_STALE"))  # the earlier preview cannot be generated
        self.assertEqual(sorted(p.name for p in self.settings.final_packs_root.glob("FAP-*")) if self.settings.final_packs_root.is_dir() else [], [])
        s = self.preview(s["review_id"])
        doc, _, _ = self.preview_doc(s)
        self.assertEqual(doc["exception_register"][0]["investigation"]["analyst_review"]["decision"], "ACCEPT")
        self.assertEqual([i["investigation_id"] for i in doc["ai_investigations"]], [self.inv_id])
        g = self.generate(s)
        self.assertEqual(g.status_code, 201, g.text)
        final = self.get(f"/api/v1/final-packs/{g.json()['final_pack']['final_pack_id']}/json").json()
        self.assertEqual(final["exception_register"][0]["investigation"]["analyst_review"]["analyst_review_id"], second["analyst_review_id"])
        self.assertNotIn(REASON.strip()[:30], json.dumps(final))  # the superseded rejection is history, not report content


class FinancialExceptionProtection(AnalystReviewCase):
    """Scenario D."""

    def test_decisions_never_resolve_or_change_the_exception(self):
        before = self.exception_status()
        self.assertEqual(before[:2], ("OPEN", "UNRESOLVED"))
        self.assertEqual(self.decide("ACCEPT", 0).status_code, 201)
        self.assertEqual(self.exception_status(), before)
        self.assertEqual(self.decide("REJECT", 1, rejection_reason="Not supported by the records.").status_code, 201)
        self.assertEqual(self.exception_status(), before)
        self.assertEqual(self.history()["exception_status"], "UNRESOLVED")
        s = self.preview(self.open_review()["review_id"])
        doc, _, _ = self.preview_doc(s)
        self.assertTrue(all(e["resolution_status"] == "UNRESOLVED" for e in doc["exception_register"]))
        self.assertEqual(doc["exception_register"][0]["exception"]["status"], "OPEN")
        self.assert_untouched()


class PendingAndNotInvestigated(AnalystReviewCase):
    """Scenario E and the pending rule."""

    def test_pending_investigation_blocks_and_no_investigation_still_works(self):
        s = self.open_review()
        self.assertIn("AI_REVIEW_PENDING", [b["code"] for b in s["readiness"]["blockers"]])  # never treated as accepted
        r = self.post(f"/api/v1/reviews/{s['review_id']}/preview", {"authorization": {"confirmed": True}})
        self.assertEqual((r.status_code, r.json()["code"]), (409, "BLOCKED"))
        # EXCLUDED_BY_ANALYST is still available, and EXC-SC5A-02 (no investigation) stays NOT_INVESTIGATED.
        r = self.patch(f"/api/v1/reviews/{s['review_id']}/selections", {"selections": [
            {"exception_id": EXC, "inclusion": "EXCLUDED_BY_ANALYST", "reason": "Analyst excluded the AI for this pack."},
            {"exception_id": "EXC-SC5A-02", "inclusion": "NOT_INVESTIGATED"}]})
        self.assertEqual(r.status_code, 200, r.text)
        s = self.preview(s["review_id"])
        doc, _, _ = self.preview_doc(s)
        reg = {e["exception"]["exception_id"]: e["investigation"] for e in doc["exception_register"]}
        self.assertEqual((reg["EXC-SC5A-02"]["inclusion"], reg["EXC-SC5A-02"]["analyst_review"]), ("NOT_INVESTIGATED", None))
        self.assertEqual(reg[EXC]["inclusion"], "EXCLUDED_BY_ANALYST")
        self.assertEqual(doc["ai_investigations"], [])
        g = self.generate(s)
        self.assertEqual(g.status_code, 201, g.text)


class IntegrityAndImmutability(AnalystReviewCase):
    """Scenario F."""

    def test_history_is_append_only_and_artefacts_verify(self):
        self.assertEqual(self.decide("ACCEPT", 0).status_code, 201)
        self.assertEqual(self.decide("REJECT", 1, rejection_reason="Second look: not supported.").status_code, 201)
        self.assertEqual(self.decide("ACCEPT", 2, comment="Third look.").status_code, 201)
        rows = self.get(f"/api/v1/investigations/{self.inv_id}/analyst-reviews").json()
        self.assertEqual([r["revision"] for r in rows], [1, 2, 3])
        self.assertEqual([r["active"] for r in rows], [False, False, True])
        self.assertEqual(rows[1]["supersedes_review_id"], rows[0]["analyst_review_id"])
        repo = self.svc.repos.investigation_reviews
        with self.assertRaises(Exception):
            repo.append(dict(repo.list(investigation_id=self.inv_id)[0], analyst_review_id="AR-dup"), 1)  # an old revision
        self.assertEqual(len(repo.list(investigation_id=self.inv_id)), 3)
        self.assertEqual(self.get(f"/api/v1/investigations/{self.inv_id}/verify").json()["artefact_verified"], True)
        self.assertEqual(self.decide("ACCEPT", 3, inv="INV-EXC-SC5A-01-000000000000").status_code, 404)
        self.assert_untouched()

    @unittest.skipUnless(TEST_REPOSITORIES == "postgres", "PostgreSQL immutability trigger (UC042_TEST_REPOSITORIES=postgres)")
    def test_postgres_refuses_update_and_delete(self):
        from sqlalchemy import text
        self.assertEqual(self.decide("REJECT", 0, rejection_reason="Kept exactly.").status_code, 201)
        for sql in ("UPDATE audit.investigation_reviews SET rejection_reason = 'changed'", "DELETE FROM audit.investigation_reviews"):
            with self.assertRaises(Exception):
                with self.svc.engine.begin() as conn:
                    conn.execute(text(sql))
        self.assertEqual(self.get(f"/api/v1/investigations/{self.inv_id}/analyst-reviews").json()[0]["rejection_reason"], "Kept exactly.")


if __name__ == "__main__":
    unittest.main()


class LibraryGating(unittest.TestCase):
    """The final-pack library rules, independent of the API: a pending investigation is never accepted, a decision must
    match the artefact's findings, an altered rejection reason fails validation, and without analyst reviews the Phase 1
    content (schema 1.0) is unchanged."""

    @classmethod
    def setUpClass(cls):
        import shutil, tempfile
        from pathlib import Path
        from tests.final_pack_support import make_investigation
        cls.tmp = Path(tempfile.mkdtemp())
        cls.root = cls.tmp / "investigations"
        cls.inv = make_investigation("SC5A", EXC, cls.root, edit=marked)
        cls.findings_sha = __import__("hashlib").sha256(next(cls.root.glob(f"*/{EXC}/{cls.inv}")).joinpath("findings.json").read_bytes()).hexdigest()
        cls._cleanup = lambda: shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def tearDownClass(cls):
        cls._cleanup()

    def review(self, decision="REJECT", **kw):
        base = {"analyst_review_id": "AR-1", "investigation_id": self.inv, "exception_id": EXC, "decision": decision,
                "findings_sha256": self.findings_sha, "reviewer": {"user_id": "analyst-1", "display_name": "Test Analyst"},
                "decided_at": "2026-11-05T10:00:00+00:00", "rejection_reason": REASON if decision == "REJECT" else ""}
        base.update(kw)
        return base

    def selections(self):
        return [{"exception_id": EXC, "inclusion": "INCLUDED", "investigation_id": self.inv},
                {"exception_id": "EXC-SC5A-02", "inclusion": "NOT_INVESTIGATED"}]

    def test_pending_and_mismatched_reviews_are_refused(self):
        from uc042lib.final_pack import FinalPackInputError, build_review_snapshot
        with self.assertRaisesRegex(FinalPackInputError, "pending analyst review"):
            build_review_snapshot(SC5A, self.selections(), investigations_root=self.root, analyst_reviews=[])
        with self.assertRaisesRegex(FinalPackInputError, "different findings"):
            build_review_snapshot(SC5A, self.selections(), investigations_root=self.root,
                                  analyst_reviews=[self.review(findings_sha256="0" * 64)])

    def test_rejected_content_excluded_and_reason_tamper_detected(self):
        from tests.final_pack_support import resealed, summary_investigator
        from uc042lib.final_pack import assemble_preview, build_review_snapshot, generate_closing_summary
        from uc042lib.final_pack.validate import validate_final_pack
        snap = build_review_snapshot(SC5A, self.selections(), investigations_root=self.root, analyst_reviews=[self.review()])
        legacy = build_review_snapshot(SC5A, self.selections(), investigations_root=self.root)
        self.assertNotEqual(snap.sha256, legacy.sha256)
        self.assertNotIn("analyst_reviews", legacy.content)
        summary = generate_closing_summary(snap, summary_investigator(snap)[0])
        final = assemble_preview(snap, summary)
        self.assertEqual(final["ai_investigations"], [])
        self.assertEqual(final["exception_register"][0]["investigation"]["analyst_review"]["rejection_reason"], REASON)
        reworded = resealed(final, lambda f: f["exception_register"][0]["investigation"]["analyst_review"].update(
            rejection_reason=REASON.strip()))  # even a trimmed reason is a change
        self.assertTrue(any("differs from the recorded decision" in e for e in validate_final_pack(reworded, snap, summary, None, preview=True)))
        legacy_final = assemble_preview(legacy, generate_closing_summary(legacy, summary_investigator(legacy)[0]))
        self.assertEqual(legacy_final["final_pack_schema_version"], "uc042-final-pack/1.0")
        self.assertNotIn("analyst_reviews", legacy_final)
        self.assertNotIn("analyst_review", legacy_final["exception_register"][0]["investigation"])

    def test_closing_summary_model_never_receives_rejected_ai_content(self):
        """What the (mocked) OpenAI Responses request actually carries: an accepted investigation's AI content is sent; a
        rejected one's is not (only that the analyst rejected it), and the analyst's reason is not sent for restating."""
        from tests.final_pack_support import openai_investigator, raw, summary_output
        from uc042lib.final_pack import build_review_snapshot, generate_closing_summary
        from uc042lib.final_pack.summary import closing_summary_input
        sent = {}
        for decision in ("ACCEPT", "REJECT"):
            snap = build_review_snapshot(SC5A, self.selections(), investigations_root=self.root, analyst_reviews=[self.review(decision)])
            out = summary_output(closing_summary_input(snap))
            requests = []
            summary = generate_closing_summary(snap, openai_investigator(lambda kw: requests.append(kw) or raw(out)))
            self.assertEqual((summary.status, len(requests)), ("GENERATED", 1))
            sent[decision] = json.dumps(requests[0]["input"], ensure_ascii=False)
        for mark in (SUMMARY_MARK, HYPOTHESIS_MARK, STEP_MARK):
            self.assertIn(mark, sent["ACCEPT"])
            self.assertNotIn(mark, sent["REJECT"])
        self.assertIn("REJECTED_AI_CONTENT_EXCLUDED", sent["REJECT"])
        self.assertNotIn("BA-0915", sent["REJECT"])  # the reason is reported verbatim by the assembler, never by the model

    def test_reject_without_reason_is_not_a_valid_review(self):
        from pydantic import ValidationError
        from uc042lib.final_pack import AnalystReview
        for reason in ("", "  \n "):
            with self.assertRaises(ValidationError):
                AnalystReview.model_validate(self.review(rejection_reason=reason))
