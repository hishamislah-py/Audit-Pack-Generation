"""The integrated analyst workflow on one pack with a meaningful mix of outcomes: automatic investigation of every exception,
ACCEPT (with a comment), REJECT (mandatory reason + optional comment), a failed investigation that must be retried or
excluded with a documented reason, the readiness checklist, the closing-summary inputs, preview invalidation, and the
final audit pack in JSON, HTML and PDF. Run from uc042/: python -m unittest tests.test_end_to_end_workflow -v
(UC042_TEST_REPOSITORIES=postgres for the SQL repositories).

Offline CONTROLLED FIXTURES: the real OpenAIInvestigator with its HTTP client mocked. These are not real provider calls."""
import html as h
import io
import json

import httpx2
import openai
from pypdf import PdfReader

from tests.api_support import AI_OK, MockProvider, ApiCase
from tests.final_pack_support import PACK, investigation_output, raw, sha_tree
from tests.api_support import ROOT
from tests.view_fixtures import packet_from_message
from uc042lib.final_pack import verify_final_pack
from uc042lib.final_pack.render_pdf import pdf_text

REQ = httpx2.Request("POST", "https://api.openai.com/v1/responses")
SC3C = PACK["SC3C"]
E1, E2, E3 = "EXC-SC3C-01", "EXC-SC3C-02", "EXC-SC3C-03"
REJECT_MARK = "REJECTED-AI-TEXT-4be1: the engine difference is explained by a timing item that no record establishes."
REASON = "Not supported: the cited ledger line is the opening balance,\nnot the September movement — see BA-0915 (« pending »)."
COMMENT = "Discussed with the treasury lead; re-investigate once the bank advice is loaded."
EXCLUSION = "AI investigation failed (provider unreachable); reported from the deterministic results only."


def pdf_of(data):
    return "".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)


def norm(s):
    return "".join(pdf_text(s).split())


class Responder:
    """Investigations answered per exception (valid output, a marked output, or a provider error); closing summaries by
    the MockProvider. Every closing-summary request is kept, to check what the model was given."""

    def __init__(self, provider):
        self.mock, self.answers, self.summary_requests = MockProvider(), {}, []
        provider.respond = self.respond

    def respond(self, kw):
        content = kw["input"][0]["content"]
        if "<audit_pack_input>" in content:
            self.summary_requests.append(json.dumps(kw["input"], ensure_ascii=False))
            return self.mock.respond(kw)
        packet = packet_from_message(content)
        exc = packet["exception"]["exception_id"]
        answer = self.answers.get(exc, "error")
        if answer == "error":
            raise openai.APIConnectionError(request=REQ)
        out = investigation_output("SC3C", exc)
        if answer == "marked":
            out = out.model_copy(update={"investigation_summary": REJECT_MARK})
        return raw(out)


class MixedPackWorkflow(ApiCase):
    def test_accept_reject_failed_excluded_through_to_the_final_pack(self):
        pack_before = sha_tree(ROOT / "packs" / SC3C)
        r = Responder(self.provider)
        r.answers.update({E1: "ok", E2: "marked", E3: "error"})
        # Stage 1: every exception queued under one authorisation (an explicit pack-level start for this scenario pack)
        res = self.post(f"/api/v1/packs/{SC3C}/auto-investigations", {"authorization": AI_OK}).json()
        self.assertEqual(sorted((i["exception_id"], i["outcome"]) for i in res["items"]), [(E1, "QUEUED"), (E2, "QUEUED"), (E3, "QUEUED")])
        for i in res["items"]:
            self.wait_job(i["job_id"], 120)
        st = {e["exception_id"]: e for e in self.get(f"/api/v1/packs/{SC3C}/auto-investigations").json()["exceptions"]}
        self.assertEqual([st[e]["state"] for e in (E1, E2, E3)], ["READY_FOR_REVIEW", "READY_FOR_REVIEW", "FAILED"])
        inv = {e: self.get(f"/api/v1/packs/{SC3C}/exceptions/{e}/investigations").json()["published"] for e in (E1, E2, E3)}
        self.assertEqual(inv[E3], [])  # the failed attempt is not published
        i1, i2 = inv[E1][0]["investigation_id"], inv[E2][0]["investigation_id"]

        # Stage 2: decisions (byte-for-byte reason; comment kept separately)
        a = self.post(f"/api/v1/investigations/{i1}/analyst-review", {"decision": "ACCEPT", "comment": "Agrees with the bank statement.", "expected_revision": 0})
        self.assertEqual(a.status_code, 201, a.text)
        blank = self.post(f"/api/v1/investigations/{i2}/analyst-review", {"decision": "REJECT", "rejection_reason": " \n ", "expected_revision": 0})
        self.assertEqual((blank.status_code, blank.json()["code"]), (422, "REJECTION_REASON_REQUIRED"))
        rj = self.post(f"/api/v1/investigations/{i2}/analyst-review",
                       {"decision": "REJECT", "rejection_reason": REASON, "comment": COMMENT, "expected_revision": 0})
        self.assertEqual(rj.status_code, 201, rj.text)
        self.assertEqual((rj.json()["rejection_reason"].encode(), rj.json()["comment"].encode()), (REASON.encode(), COMMENT.encode()))

        # Stage 3: readiness checklist; the failed investigation blocks until retried or excluded; no paid call while blocked
        s = self.post(f"/api/v1/packs/{SC3C}/reviews").json()
        ck = s["readiness"]["checklist"]
        self.assertEqual({k: ck["counts"][k] for k in ("total", "investigations_completed", "awaiting_review", "accepted", "rejected",
                                                       "failed_or_not_usable", "excluded")},
                         {"total": 3, "investigations_completed": 2, "awaiting_review": 0, "accepted": 1, "rejected": 1,
                          "failed_or_not_usable": 1, "excluded": 0})
        rows = {x["exception_id"]: x for x in ck["exceptions"]}
        self.assertEqual([rows[e]["disposition"] for e in (E1, E2, E3)], ["ACCEPTED", "REJECTED", "FAILED_ACTION_NEEDED"])
        self.assertIn("connect", rows[E3]["job_error"])  # the exact reason is shown
        self.assertTrue(all(x["exception_resolution"] == "UNRESOLVED" for x in ck["exceptions"]))
        self.assertEqual((ck["preview"], ck["ready"]), ("NONE", False))
        self.assertIn("INVESTIGATION_FAILED_NO_DISPOSITION", [b["code"] for b in s["readiness"]["blockers"]])
        blocked = self.post(f"/api/v1/reviews/{s['review_id']}/preview", {"authorization": AI_OK})
        self.assertEqual((blocked.status_code, blocked.json()["code"]), (409, "BLOCKED"))
        self.assertEqual(r.summary_requests, [])  # no closing-summary call while the review is blocked

        sel = [x if x["exception_id"] != E3 else {"exception_id": E3, "inclusion": "EXCLUDED_BY_ANALYST", "reason": EXCLUSION}
               for x in s["selections"]]
        s = self.patch(f"/api/v1/reviews/{s['review_id']}/selections", {"selections": sel, "expected_revision": s["revision"]}).json()
        self.assertEqual(s["readiness"]["checklist"]["counts"]["excluded"], 1)
        self.assertEqual({x["exception_id"]: x["disposition"] for x in s["readiness"]["checklist"]["exceptions"]}[E3], "EXCLUDED")
        s = self.preview(s["review_id"])
        self.assertEqual(s["readiness"]["checklist"]["preview"], "CURRENT")
        self.assertEqual(len(r.summary_requests), 1)
        first_req = r.summary_requests[0]
        for text in (REJECT_MARK[:30], REASON[:25], COMMENT[:25]):
            self.assertNotIn(text, first_req)  # rejected AI text and the analyst's wording are never model input
        self.assertIn("REJECTED_AI_CONTENT_EXCLUDED", first_req)

        # A changed decision makes the preview stale; GENERATE on it is refused; a fresh preview reflects the new decision
        again = self.post(f"/api/v1/investigations/{i1}/analyst-review", {"decision": "ACCEPT", "comment": "Re-checked: agrees.", "expected_revision": 1})
        self.assertEqual(again.status_code, 201, again.text)
        s = self.get(f"/api/v1/reviews/{s['review_id']}").json()
        self.assertEqual(s["readiness"]["checklist"]["preview"], "STALE")
        g = self.post(f"/api/v1/reviews/{s['review_id']}/decision", {"decision": "GENERATE", "acknowledgement_accepted": True,
                                                                     "snapshot_sha256": s["current_preview"]["snapshot_sha256"]})
        self.assertEqual((g.status_code, g.json()["code"]), (409, "PREVIEW_STALE"))
        s = self.preview(s["review_id"])
        self.assertEqual(len(r.summary_requests), 2)
        self.assertNotIn(REJECT_MARK[:30], r.summary_requests[1])  # no reuse from an earlier preview or cached context
        held = self.post(f"/api/v1/reviews/{s['review_id']}/decision", {"decision": "HOLD", "comment": "Waiting for the treasury lead."})
        self.assertEqual(held.json()["session_status"], "ON_HOLD")  # HOLD publishes nothing
        s = self.preview(s["review_id"])
        g = self.post(f"/api/v1/reviews/{s['review_id']}/decision", {"decision": "GENERATE", "acknowledgement_accepted": True,
                                                                     "snapshot_sha256": s["current_preview"]["snapshot_sha256"],
                                                                     "comment": "Reviewed."})
        self.assertEqual(g.status_code, 201, g.text)
        fp = g.json()["final_pack"]["final_pack_id"]

        # The final pack: accepted content in, rejected content out (replaced by the disposition), exclusion as recorded
        final = self.get(f"/api/v1/final-packs/{fp}/json").json()
        html = self.get(f"/api/v1/final-packs/{fp}/html").text
        pdf = pdf_of(self.get(f"/api/v1/final-packs/{fp}/pdf").content)
        reg = {e["exception"]["exception_id"]: e["investigation"] for e in final["exception_register"]}
        self.assertEqual([i["investigation_id"] for i in final["ai_investigations"]], [i1])
        self.assertEqual((reg[E1]["analyst_review"]["decision"], reg[E1]["analyst_review"]["comment"]), ("ACCEPT", "Re-checked: agrees."))
        self.assertEqual((reg[E2]["analyst_review"]["disposition"], reg[E2]["analyst_review"]["rejection_reason"], reg[E2]["analyst_review"]["comment"],
                          reg[E2]["investigation_id"]), ("REJECTED_BY_ANALYST", REASON, COMMENT, i2))
        self.assertEqual((reg[E3]["inclusion"], reg[E3]["reason"], reg[E3].get("analyst_review")), ("EXCLUDED_BY_ANALYST", EXCLUSION, None))
        self.assertEqual(final["metadata"]["completeness"]["investigation_coverage"]["accepted_by_analyst"], 1)
        self.assertEqual(final["metadata"]["completeness"]["investigation_coverage"]["rejected_by_analyst"], 1)
        self.assertTrue(all(e["resolution_status"] == "UNRESOLVED" for e in final["exception_register"]))
        for out in (json.dumps(final, ensure_ascii=False), html, pdf):
            self.assertNotIn("REJECTED-AI-TEXT", out)  # rejected AI content: absent from every format
        self.assertIn(h.escape(REASON), html)
        self.assertIn(h.escape(COMMENT), html)
        self.assertIn(h.escape(EXCLUSION), html)
        for text in (REASON, COMMENT, EXCLUSION):  # extracted from the rendered PDF
            self.assertIn(norm(text), norm(pdf))
        self.assertIn("REJECTED BY ANALYST", pdf)
        self.assertEqual(verify_final_pack(self.settings.final_packs_root / fp), [])
        self.assertTrue(self.get(f"/api/v1/final-packs/{fp}/verify").json()["verified"])
        # traceable decisions per version; the original rejected artefact is kept unchanged
        trail = {d["investigation_id"]: d for d in final["audit_trail"]["analyst_reviews"]}
        self.assertEqual((trail[i1]["revision"], trail[i2]["decision"]), (2, "REJECT"))
        self.assertEqual(self.get(f"/api/v1/investigations/{i2}/findings").json()["investigation_summary"], REJECT_MARK)
        self.assertEqual(sha_tree(ROOT / "packs" / SC3C), pack_before)  # the deterministic pack is untouched


class RejectedTextGuard(ApiCase):
    def test_validation_refuses_rejected_ai_text_anywhere_in_a_pack(self):
        from uc042lib.final_pack.validate import _rejected_text_in
        job = self.run_investigation_job("SC5A", "EXC-SC5A-01", edit=lambda o: o.update(investigation_summary=REJECT_MARK))
        inv_dir = next(self.inv_root.glob(f"*/EXC-SC5A-01/{job['result']['investigation_id']}"))
        from uc042lib.final_pack.sources import load_bundle
        bundle = load_bundle(inv_dir)
        self.assertEqual(_rejected_text_in({"closing_summary": {"text": "x " + REJECT_MARK}}, bundle), [REJECT_MARK])
        self.assertEqual(_rejected_text_in({"exception_register": [{"investigation": {"analyst_review": {"rejection_reason": REJECT_MARK}}}]},
                                           bundle), [])  # the analyst may quote what they reject
        self.assertEqual(_rejected_text_in({"a": REJECT_MARK}, bundle, legitimate=[REJECT_MARK]), [])
