"""Evidence-bearing relationships and AI relationship challenges (23 Nov 2026; forensic report on TC06 01<->03).

Real pipeline on TC01-TC06 of UC042_RECONCILIATION_TEST_SUITE_V2 with engine relationship discovery ON (built once by
tests.test_relationship_register: engine -> pack with relationship register 1.1 -> investigations (provider HTTP mocked) ->
analyst ACCEPT -> review snapshot -> closing summary (real validation; SCRIPTED model output) -> final pack -> PDF/HTML).
No live AI. Expected values are the engine's own figures for the synthetic datasets, never the answer keys.

Covers: engine proofs for every CONFIRMED relationship (section 2), the separate common-cause status (3), ACKNOWLEDGED /
CHALLENGED dispositions (4), validation rules R1-R10 with negative tests (6), the final pack / PDF (7), the TC01-TC06
regressions (8) and backward compatibility.
"""
import copy
import json
import unittest
from pathlib import Path

import tests.test_relationship_register as R
from tests.final_pack_support import openai_investigator, raw, review_for
from tests.renderer_v3_support import audit_integrity, norm, pdf_text, render_all
from uc042lib.final_pack import (ChallengeReview, ClosingSummaryOutput, FinalPackValidationError, GenerationInfo,
                                 assemble_final_pack, generate_closing_summary, render_pdf, validate_closing_summary)
from uc042lib.final_pack.model import GroupAssessment, ReviewRecord
from uc042lib.final_pack.validate import validate_final_pack
from uc042lib.pack.relationships import NO_PROOF_LIMITATION, build_relationship_register

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SNAP04 = "IN-03:CBS-20260917-C0004-GBP"


def setUpModule():
    R.setUpModule()


def tearDownModule():
    R.tearDownModule()


def B(tc):
    return R.BUILT[tc]


def rel(tc, a, b, status=None):
    return R.rel(tc, a, b, status)


def errors_for(tc, edit, si=None):
    si = si or B(tc)["si"]
    return validate_closing_summary(R.scripted(si, edit), si)


def disp(d, rid):
    return next(x for x in d["relationship_dispositions"] if x["relationship_id"] == rid)


def rid_of(tc, a, b, status="CONFIRMED"):
    return rel(tc, a, b, status)[0]["relationship_id"]


def tc06_challenge(d):
    """A VALID formal challenge of the 01<->03 relationship: it cites a record outside the relationship's own proof and the
    exceptions' detection records (C0007's same-day records), states why, what is missing, confidence and limitations, and
    splits the group accordingly. The engine status is NOT changed by it."""
    rid = rid_of("TC06", "EXC-TC06-01", "EXC-TC06-03")
    x = disp(d, rid)
    x.update(disposition="CHALLENGED", confidence="LOW",
             reason="C0007 shows an equal and opposite 90.00 roll-forward difference on the same day, so the 90.00 internal "
                    "difference could be a net of two client positions rather than C0004's snapshot alone.",
             cited_evidence=[SNAP04, "IN-03:CBS-20260917-C0007-GBP"], contradicting_evidence=["IN-03:CBS-20260917-C0007-GBP"],
             missing_evidence=["the client-balance system extract for 17 September for C0004 and C0007"],
             why_engine_evidence_insufficient="The engine excludes C0007 as transaction-explained; the requirement composition "
                                              "per client is not supplied, so the exclusivity cannot be checked here.",
             limitations=["based only on the supplied snapshots; no client-balance system extract was available"])
    gas = [a for a in d["group_assessments"] if a["group_id"] != "GRP-TC06-01"]
    base = dict(related_exception_ids=[], analyst_action="SCRIPTED: obtain the client-balance extract for 17 September.",
                rationale="SCRIPTED: the 01-03 link is challenged; 03-04 is acknowledged.")
    gas += [dict(base, group_id="GRP-TC06-01", exception_ids=["EXC-TC06-01"], relationship_verdict="UNVERIFIED",
                 common_cause_status="UNVERIFIED", confidence="LOW", supporting_evidence=[SNAP04], contradicting_evidence=[],
                 common_cause_hypothesis="The internal difference may come from C0004's snapshot; this is not established.",
                 missing_evidence=["the per-client requirement composition for 17 September"]),
            dict(base, group_id="GRP-TC06-01", exception_ids=["EXC-TC06-03", "EXC-TC06-04"], relationship_verdict="EVIDENCE_BACKED",
                 common_cause_status="NOT_ESTABLISHED", confidence="MEDIUM", supporting_evidence=[SNAP04], contradicting_evidence=[],
                 common_cause_hypothesis="Both come from C0004's 17 September snapshot; why it is wrong is not established.",
                 missing_evidence=["how the snapshot was produced"])]
    d["group_assessments"] = gas


# ============================================================================================================ section 2
class EngineProofs(unittest.TestCase):
    def test_every_confirmed_relationship_carries_a_complete_proof(self):
        n = 0
        for tc, b in R.BUILT.items():
            recs = {r["evidence_id"] for r in b["pack"]["evidence_register"]["records"]}
            self.assertEqual(b["reg"]["schema"], "uc042-relationship-register/1.1")
            for r in b["reg"]["relationships"]:
                if r["status"] != "CONFIRMED":
                    continue
                n += 1
                p = r["proof"]
                self.assertEqual(r["engine_status"], "CONFIRMED")
                self.assertTrue(p and p["result"] and p["records"] and p["established"] and p["calculation"], (tc, r["relationship_id"]))
                self.assertEqual(p["relationship_type"], r["relationship_type"])
                self.assertLessEqual(set(p["records"]) | ({p["faulty_record"]} - {""}), recs, (tc, r["relationship_id"]))
                self.assertNotIn(NO_PROOF_LIMITATION, r["limitations"])
        self.assertEqual(n, 17)          # 12 TC01 + 1 TC02 + 1 TC04 + 3 TC06 (forensic report section 5)

    def test_tc06_01_03_proof_explains_the_90_and_keeps_the_cause_open(self):
        [r] = rel("TC06", "EXC-TC06-01", "EXC-TC06-03", "CONFIRMED")
        p = r["proof"]
        self.assertEqual((r["relationship_type"], p["result"], p["faulty_record"]), ("CAUSAL_PROPAGATION", "EQUAL", SNAP04))
        q = {x["name"]: x["value"] for x in p["quantities"]}
        self.assertEqual(q["C0004 snapshot balance 2026-09-17 (reported)"], "40682.24")
        self.assertEqual(q["C0004 roll-forward balance 2026-09-17 (previous snapshot + movements)"], "40592.24")
        self.assertEqual(q["snapshot error (snapshot - roll-forward)"], "90.00")                     # overstated by 90
        self.assertEqual(q["internal difference 2026-09-17 (resource - requirement)"], "-90.00")     # = the internal difference
        self.assertEqual(q["GBP requirement 2026-09-17 (recomputed from the snapshots)"], "341574.46")
        self.assertIn("341484.46", p["requirement_effect"])                                          # the requirement effect
        self.assertIn("includes C0004's snapshot balance 40682.24", p["requirement_effect"])
        self.assertTrue(any("overstated by 90.00" in e for e in p["established"]))
        self.assertTrue(any("EXC-TC06-03 is the failed roll-forward of this snapshot" in e for e in p["established"]))
        self.assertTrue(any(c.startswith("EXC-TC06-04") and "reverses by 90.00" in c for c in p["corroboration"]))  # next day
        self.assertTrue(any("C0007" in c and "transaction-side" in c for c in p["corroboration"]))   # exclusivity
        self.assertTrue(any("why the faulty record is wrong" in n for n in p["not_established"]))   # cause stays open
        self.assertEqual([c["date"] for c in p["chronology"]], sorted(c["date"] for c in p["chronology"]))

    def test_tc06_other_relationships_and_coincidences(self):
        self.assertEqual(rel("TC06", "EXC-TC06-03", "EXC-TC06-04", "CONFIRMED")[0]["proof"]["result"], "EQUAL_AND_OPPOSITE")
        self.assertEqual(rel("TC06", "EXC-TC06-05", "EXC-TC06-06", "CONFIRMED")[0]["proof"]["faulty_record"], "IN-11:TX-0917-00002")
        r15 = rel("TC06", "EXC-TC06-01", "EXC-TC06-05")
        self.assertTrue(r15 and all(r["status"] == "REJECTED" for r in r15))                        # 01-05 rejected
        coinc = [r for r in B("TC06")["reg"]["relationships"] if r["relationship_type"] == "COINCIDENCE"]
        self.assertTrue(coinc and all(r["status"] == "REJECTED" for r in coinc))                    # never a relationship
        self.assertFalse([r for r in B("TC06")["reg"]["relationships"] if "EXC-TC06-02" in r["exception_ids"] and r["status"] != "REJECTED"])

    def test_tc01_persistence_links_keep_their_proof(self):
        pers = [r for r in B("TC01")["reg"]["relationships"] if r["link_type"] == "L2 PERSISTENCE"]
        self.assertEqual(len(pers), 2)
        for r in pers:
            self.assertEqual((r["status"], r["relationship_type"], r["proof"]["result"]), ("CONFIRMED", "PERSISTENCE", "CONSECUTIVE_EQUAL"))
            self.assertEqual([q["value"] for q in r["proof"]["quantities"][:2]], ["1246.80", "1246.80"])
        dup = [r for r in B("TC01")["reg"]["relationships"] if r["link_type"] == "L6 DUPLICATE LINEAGE"]
        self.assertTrue(dup and all(r["proof"]["faulty_record"] == "IN-10:LE-GBP-0928-0007" for r in dup))   # duplicate unchanged

    def test_tc02_18_mismatch_relationship(self):
        [r] = [r for r in B("TC02")["reg"]["relationships"] if r["status"] == "CONFIRMED"]
        self.assertEqual((r["relationship_type"], r["proof"]["faulty_record"], r["proof"]["result"]),
                         ("TRANSACTION_LINEAGE", "IN-11:TX-0908-00002", "EQUAL"))
        self.assertIn("18.00", r["proof"]["calculation"])

    def test_tc04_lineage_carries_confirmation_evidence(self):
        [r] = [r for r in B("TC04")["reg"]["relationships"] if r["status"] == "CONFIRMED"]
        p = r["proof"]
        self.assertEqual((r["relationship_type"], p["result"], p["faulty_record"]), ("BALANCE_LINEAGE", "EQUAL", "IN-09:BE-EUR-0930-U01"))
        self.assertEqual(p["quantities"][0]["value"], p["quantities"][1]["value"])                   # entry = difference

    def test_tc05_stays_candidate_and_suspected(self):
        reg = B("TC05")["reg"]
        self.assertFalse([r for r in reg["relationships"] if r["status"] == "CONFIRMED"])
        self.assertEqual([c["status"] for c in reg["common_causes"]], ["SUSPECTED"])
        self.assertTrue(all(r["proof"]["result"].startswith("SUM_EQUAL") for r in reg["relationships"] if r["link_type"] == "LINE-SUM MATCH"))

    def test_register_downgrades_a_confirmed_link_without_proof(self):
        class V:
            rules = type("Rules", (), {"enrichment_v1": True})()
            enrichment = {"relationships": [{"exception_ids": ["EXC-X-01", "EXC-X-02"], "link_type": "L4 TRANSACTION LINEAGE",
                                             "strength": "CONFIRMED", "basis": "b", "evidence": [], "amounts": {}, "proof": None}],
                          "rejected_coincidences": [], "common_causes": []}
            relationship_links = []
            groups = []

            def scenario_id(self):
                return "X"
        reg = build_relationship_register(V(), lambda text, owner: [])
        [r] = reg["relationships"]
        self.assertEqual((r["status"], r["engine_status"]), ("CANDIDATE", "CONFIRMED"))             # never falsely confirmed
        self.assertIn(NO_PROOF_LIMITATION, r["limitations"])


# ============================================================================================================ sections 3-5
class AIContract(unittest.TestCase):
    def test_input_carries_the_proofs_and_the_relationships_to_dispose(self):
        si = B("TC06")["si"]
        reg = si["relationship_register"]
        self.assertEqual(reg["schema"], "uc042-relationship-register/1.1")
        rid = rid_of("TC06", "EXC-TC06-01", "EXC-TC06-03")
        self.assertIn(rid, reg["confirmed_relationship_ids"])
        r = next(x for x in reg["relationships"] if x["relationship_id"] == rid)
        self.assertEqual(r["proof"]["faulty_record"], SNAP04)
        self.assertIn("341484.46", r["proof"]["requirement_effect"])                                 # the 90 evidence reaches the AI
        self.assertLessEqual(set(r["proof"]["records"]), set(si["allowed_source_refs"]))

    def test_tc06_01_03_is_related_while_the_cause_stays_open(self):
        gas = B("TC06")["final"]["closing_summary"]["output"]["group_assessments"]
        a = next(x for x in gas if {"EXC-TC06-01", "EXC-TC06-03"} <= set(x["exception_ids"]))
        self.assertEqual((a["relationship_verdict"], a["common_cause_status"]), ("EVIDENCE_BACKED", "NOT_ESTABLISHED"))

    def test_the_four_representations(self):
        # established relationship + established common cause (TC02: two exceptions, one acknowledged CONFIRMED relationship)
        def tc02(d):
            for a in d["group_assessments"]:
                a["common_cause_status"] = "EVIDENCE_BACKED"
                a["common_cause_hypothesis"] = "Both come from transaction TX-0908-00002; why it was recorded wrongly is not established."
        self.assertEqual(errors_for("TC02", tc02), [])
        # established relationship + unverified/not established common cause (TC06 01-03): the published scripted summary
        self.assertEqual(errors_for("TC06", None), [])
        # candidate relationship (TC05): UNVERIFIED, never EVIDENCE_BACKED
        gas = B("TC05")["final"]["closing_summary"]["output"]["group_assessments"]
        self.assertTrue(all(a["relationship_verdict"] == "UNVERIFIED" and a["common_cause_status"] == "UNVERIFIED" for a in gas))
        # rejected relationship (TC06 01-05): present, REJECTED, and never inside an evidence-backed assessment
        self.assertTrue(rel("TC06", "EXC-TC06-01", "EXC-TC06-05", "REJECTED"))

    def test_tc05_no_invented_attribution_and_02_in_the_cause(self):
        gas = B("TC05")["final"]["closing_summary"]["output"]["group_assessments"]
        cc = next(a for a in gas if a["group_id"] == "CC-TC05-01")
        self.assertEqual(sorted(cc["exception_ids"]), ["EXC-TC05-01", "EXC-TC05-02", "EXC-TC05-03"])
        self.assertFalse([a for a in gas if a["relationship_verdict"] == "EVIDENCE_BACKED" or a["common_cause_status"] == "EVIDENCE_BACKED"])
        self.assertEqual(B("TC05")["final"]["closing_summary"]["output"]["relationship_dispositions"], [])   # nothing CONFIRMED

    def test_a_valid_challenge_is_accepted_and_does_not_change_the_engine(self):
        self.assertEqual(errors_for("TC06", tc06_challenge), [])                                    # no blanket rule


# ============================================================================================================ section 6
class ValidationRules(unittest.TestCase):
    def refused(self, tc, edit, needle, si=None):
        errs = errors_for(tc, edit, si)
        self.assertTrue(any(needle in e for e in errs), (needle, errs))

    def test_r1_confirmed_without_proof_in_the_input(self):
        si = copy.deepcopy(B("TC06")["si"])
        r = next(x for x in si["relationship_register"]["relationships"] if x["relationship_id"] in si["relationship_register"]["confirmed_relationship_ids"])
        r["proof"] = None
        self.refused("TC06", None, "carries no engine proof", si=si)

    def test_r2_every_confirmed_relationship_needs_one_disposition(self):
        self.refused("TC06", lambda d: d["relationship_dispositions"].pop(), "no ACKNOWLEDGED / CHALLENGED disposition")
        self.refused("TC06", lambda d: d.update(relationship_dispositions=None), "relationship_dispositions is required")
        self.refused("TC06", lambda d: d["relationship_dispositions"].append(copy.deepcopy(d["relationship_dispositions"][0])),
                     "more than one disposition")
        rej = rid_of("TC06", "EXC-TC06-01", "EXC-TC06-05", "REJECTED")

        def on_rejected(d):
            x = copy.deepcopy(d["relationship_dispositions"][0])
            x.update(relationship_id=rej, exception_ids=["EXC-TC06-01", "EXC-TC06-05"])
            d["relationship_dispositions"].append(x)
        self.refused("TC06", on_rejected, "is not a CONFIRMED relationship")

    def test_r3_live_tc06_output_is_a_silent_rejection_and_is_refused(self):
        live = json.loads((FIXTURES / "tc06_live_relreg_group_assessments_20261123.json").read_text(encoding="utf-8"))

        def replay(d):
            d["group_assessments"] = [dict(a, common_cause_status="NOT_ESTABLISHED") for a in live["group_assessments"]]
        errs = errors_for("TC06", replay)
        self.assertTrue(any("splits the CONFIRMED relationship" in e for e in errs), errs)

    def test_r3_unverified_over_a_confirmed_pair_in_a_group_is_refused(self):
        def under(d):
            a = next(x for x in d["group_assessments"] if x["group_id"] == "GRP-TC06-01")
            a.update(relationship_verdict="UNVERIFIED", confidence="LOW", common_cause_status="UNVERIFIED")
        self.refused("TC06", under, "without a CHALLENGED disposition")

    def test_r3_tc01_persistence_cannot_be_dropped_silently(self):
        rid = next(r["relationship_id"] for r in B("TC01")["reg"]["relationships"] if r["link_type"] == "L2 PERSISTENCE")
        pair = next(r["exception_ids"] for r in B("TC01")["reg"]["relationships"] if r["relationship_id"] == rid)

        def split(d):
            g = next(x for x in d["group_assessments"] if set(pair) <= set(x["exception_ids"]))
            rest = [e for e in g["exception_ids"] if e != pair[1]]
            d["group_assessments"].append(dict(copy.deepcopy(g), exception_ids=[pair[1]], relationship_verdict="UNVERIFIED",
                                               confidence="LOW", common_cause_status="UNVERIFIED"))
            g["exception_ids"] = rest
        self.refused("TC01", split, f"splits the CONFIRMED relationship {rid}")

    def test_r4_challenge_resting_on_detection_records_is_refused(self):
        rid = rid_of("TC06", "EXC-TC06-01", "EXC-TC06-03")

        def detection_only(d):
            tc06_challenge(d)
            disp(d, rid)["contradicting_evidence"] = ["IN-05:IRR-EMONEY-GBP-20260917", SNAP04]   # what the live model cited
        self.refused("TC06", detection_only, "detection records")

    def test_r4_incomplete_challenges_are_refused(self):
        rid = rid_of("TC06", "EXC-TC06-01", "EXC-TC06-03")
        for field, value, needle in (("why_engine_evidence_insufficient", "", "why the engine's evidence is insufficient"),
                                     ("limitations", [], "must state its limitations"),
                                     ("missing_evidence", [], "must state the missing evidence"),
                                     ("contradicting_evidence", [], "must cite contradicting source records"),
                                     ("cited_evidence", [], "must cite source records"),
                                     ("reason", "Different record.", "substantive reason")):
            def e(d, f=field, v=value):
                tc06_challenge(d)
                disp(d, rid)[f] = v
            self.refused("TC06", e, needle)

    def test_r4_acknowledged_cannot_carry_contradicting_evidence(self):
        rid = rid_of("TC06", "EXC-TC06-03", "EXC-TC06-04")
        self.refused("TC06", lambda d: disp(d, rid).update(contradicting_evidence=["IN-11:TX-0917-00002"]), "challenge it instead")

    def test_r5_disposition_keeps_the_engine_identity(self):
        rid = rid_of("TC06", "EXC-TC06-01", "EXC-TC06-03")
        self.refused("TC06", lambda d: disp(d, rid).update(exception_ids=["EXC-TC06-01", "EXC-TC06-04"]), "engine's identity")
        self.refused("TC06", lambda d: disp(d, rid).update(relationship_type="SHARED_REFERENCE"), "engine's identity")

    def test_r6_common_cause_status_is_required(self):
        self.refused("TC06", lambda d: d["group_assessments"][0].pop("common_cause_status"), "common_cause_status is required")

    def test_r7_unverified_common_cause_is_never_promoted(self):
        def cc(d):
            next(x for x in d["group_assessments"] if x["group_id"] == "CC-TC05-01")["common_cause_status"] = "EVIDENCE_BACKED"
        self.refused("TC05", cc, "never promoted")
        self.refused("TC06", lambda d: d["group_assessments"][0].update(relationship_verdict="UNVERIFIED", confidence="LOW",
                                                                        common_cause_status="EVIDENCE_BACKED"),
                     "requires relationship_verdict EVIDENCE_BACKED")
        live = json.loads((FIXTURES / "tc06_live_relreg_group_assessments_20261123.json").read_text(encoding="utf-8"))

        def rej(d):
            tc06_challenge(d)
            a = next(x for x in d["group_assessments"] if x["exception_ids"] == ["EXC-TC06-01"])
            a.update(relationship_verdict="COINCIDENCE_REJECTED", common_cause_status="UNVERIFIED",
                     contradicting_evidence=live["group_assessments"][0]["contradicting_evidence"], supporting_evidence=[])
        self.refused("TC06", rej, "has common_cause_status NOT_ESTABLISHED")

    def test_r8_challenged_or_rejected_relationship_cannot_back_a_common_cause(self):
        rid = rid_of("TC06", "EXC-TC06-01", "EXC-TC06-03")

        def challenged_but_backed(d):
            x = disp(d, rid)
            tc = copy.deepcopy(d)
            tc06_challenge(tc)
            x.update(disp(tc, rid))
            a = next(g for g in d["group_assessments"] if g["group_id"] == "GRP-TC06-01")
            a["common_cause_status"] = "EVIDENCE_BACKED"
        self.refused("TC06", challenged_but_backed, "CHALLENGES cannot support an evidence-backed common cause")
        si = copy.deepcopy(B("TC06")["si"])
        si["investigation_groups"].append({"group_id": "GRP-TC06-99", "exception_ids": "EXC-TC06-01; EXC-TC06-05", "link_types": "",
                                           "links": "", "statement": "", "source_evidence_ids": []})

        def on_rejected(d):
            d["group_assessments"].append({"group_id": "GRP-TC06-99", "exception_ids": ["EXC-TC06-01", "EXC-TC06-05"],
                                           "related_exception_ids": [], "relationship_verdict": "EVIDENCE_BACKED",
                                           "common_cause_status": "EVIDENCE_BACKED", "confidence": "MEDIUM",
                                           "common_cause_hypothesis": "These may share a cause; it is not established.",
                                           "supporting_evidence": ["IN-11:TX-0917-00002"], "contradicting_evidence": [],
                                           "missing_evidence": [], "analyst_action": "Check the two exceptions together.",
                                           "rationale": "Same date and the same amount."})
        self.refused("TC06", on_rejected, "a rejected relationship cannot support an evidence-backed common cause", si=si)

    def test_r8_common_cause_needs_acknowledged_connections(self):
        si = copy.deepcopy(B("TC06")["si"])
        si["investigation_groups"].append({"group_id": "GRP-TC06-98", "exception_ids": "EXC-TC06-02; EXC-TC06-03", "link_types": "",
                                           "links": "", "statement": "", "source_evidence_ids": []})

        def unconnected(d):
            d["group_assessments"].append({"group_id": "GRP-TC06-98", "exception_ids": ["EXC-TC06-02", "EXC-TC06-03"],
                                           "related_exception_ids": [], "relationship_verdict": "EVIDENCE_BACKED",
                                           "common_cause_status": "EVIDENCE_BACKED", "confidence": "MEDIUM",
                                           "common_cause_hypothesis": "These may share a cause; it is not established.",
                                           "supporting_evidence": [SNAP04], "contradicting_evidence": [], "missing_evidence": [],
                                           "analyst_action": "Check the two exceptions together.", "rationale": "Scripted test case."})
        self.refused("TC06", unconnected, "connected through acknowledged CONFIRMED engine relationships", si=si)

    def test_r9_citations_must_be_source_records(self):
        rid = rid_of("TC06", "EXC-TC06-03", "EXC-TC06-04")
        self.refused("TC06", lambda d: disp(d, rid)["cited_evidence"].append(rid), "must be source record IDs")
        self.refused("TC06", lambda d: disp(d, rid)["cited_evidence"].append("IN-03:CBS-NOT-A-RECORD"), "must be source record IDs")


# ============================================================================================================ section 7 + R10
class FinalPackAndReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        b = B("TC06")
        out = R.scripted(b["si"], tc06_challenge)
        cls.summary = generate_closing_summary(b["snap"], openai_investigator(lambda kw, o=out: raw(o)))
        rid = rid_of("TC06", "EXC-TC06-01", "EXC-TC06-03")
        cls.rid = rid
        cls.review = review_for(b["snap"], cls.summary, relationship_challenge_reviews=[ChallengeReview(
            relationship_id=rid, analyst_position="ENGINE_RELATIONSHIP_UPHELD",
            analyst_explanation="C0007 is explained by TX-0917-00002; the engine's exclusivity holds. Snapshot error is C0004's.")])
        cls.final = assemble_final_pack(b["snap"], cls.summary, cls.review, GenerationInfo(generated_at="2026-11-23T10:00:00+00:00"))

    def test_final_pack_preserves_engine_proof_challenge_and_analyst_explanation(self):
        f, b = self.final, B("TC06")
        self.assertEqual(f["relationships"]["relationship_register"], b["reg"])                    # copied verbatim
        it = next(i for i in f["relationship_assessments"]["items"] if i["relationship_id"] == self.rid)
        self.assertEqual((it["engine_status"], it["register_status"], it["ai_disposition"]), ("CONFIRMED", "CONFIRMED", "CHALLENGED"))
        self.assertEqual(it["proof"]["faulty_record"], SNAP04)
        d = it["ai_disposition_detail"]
        self.assertTrue(d["contradicting_evidence"] and d["missing_evidence"] and d["why_engine_evidence_insufficient"])
        self.assertEqual(it["analyst_explanation"]["analyst_position"], "ENGINE_RELATIONSHIP_UPHELD")
        self.assertTrue(it["common_cause_assessments"] == [] or all(a["common_cause_status"] for a in it["common_cause_assessments"]))
        other = next(i for i in f["relationship_assessments"]["items"] if i["relationship_id"] == rid_of("TC06", "EXC-TC06-03", "EXC-TC06-04"))
        self.assertEqual(other["ai_disposition"], "ACKNOWLEDGED")
        self.assertEqual(other["common_cause_assessments"][0]["common_cause_status"], "NOT_ESTABLISHED")

    def test_pdf_and_html_show_the_challenge_apart_from_the_engine_decision(self):
        pdf, html = render_all(self.final)
        self.assertEqual(audit_integrity(self.final, B("TC06")["pack"], pdf, html, B("TC06")["snap"]), [])
        t = norm(pdf_text(pdf))
        for s in ("Engine relationships and AI assessments", "ENGINE: CONFIRMED (deterministic)", "AI challenge - not accepted by the engine",
                  "AI: CHALLENGED - ENGINE STATUS UNCHANGED", "Analyst explanation: ENGINE_RELATIONSHIP_UPHELD", "AI: ACKNOWLEDGED",
                  "NOT established", "341484.46"):
            self.assertIn(norm(s), t, s)
        self.assertIn("item ai_challenge", html)
        self.assertIn("item engine_relationship", html)

    def test_r10_tampered_engine_status_or_proof_is_refused(self):
        b = B("TC06")
        for path in (("relationships", "relationship_register"), ("relationship_assessments",)):
            f = copy.deepcopy(self.final)
            node = f
            for k in path:
                node = node[k]
            if path[0] == "relationships":
                node["relationships"][0]["status"] = "REJECTED"
            else:
                node["items"][0]["engine_status"] = "REJECTED"
            errs = validate_final_pack(f, b["snap"], self.summary, self.review)
            self.assertTrue(any("never changed" in e or "must be kept exactly" in e for e in errs), (path, errs))

    def test_r10_analyst_explanation_only_for_a_challenged_relationship(self):
        b = B("TC06")
        rid = rid_of("TC06", "EXC-TC06-03", "EXC-TC06-04")
        review = self.review.model_copy(update={"relationship_challenge_reviews": [ChallengeReview(
            relationship_id=rid, analyst_position="AI_CHALLENGE_SUPPORTED", analyst_explanation="Not challenged by the AI.")]})
        with self.assertRaises(FinalPackValidationError) as cm:
            assemble_final_pack(b["snap"], self.summary, review, GenerationInfo(generated_at="2026-11-23T10:00:00+00:00"))
        self.assertTrue(any("does not challenge that relationship" in e for e in cm.exception.errors))

    def test_acknowledged_pack_renders_every_confirmed_relationship(self):
        for tc in ("TC01", "TC02", "TC04", "TC06"):
            f = B(tc)["final"]
            n = len([r for r in B(tc)["reg"]["relationships"] if r["status"] == "CONFIRMED"])
            self.assertEqual(len(f["relationship_assessments"]["items"]), n, tc)
            self.assertTrue(all(i["ai_disposition"] == "ACKNOWLEDGED" for i in f["relationship_assessments"]["items"]), tc)
            self.assertIn(norm("Engine relationships and AI assessments"), norm(pdf_text(render_pdf(f))), tc)


# ============================================================================================================ compatibility
class BackwardCompatibility(unittest.TestCase):
    def test_absent_new_fields_are_not_serialised(self):
        a = GroupAssessment(group_id="GRP-X-01", exception_ids=["EXC-X-01"], related_exception_ids=[], relationship_verdict="UNVERIFIED",
                            common_cause_hypothesis="The cause may be shared; not established.", supporting_evidence=[],
                            contradicting_evidence=[], missing_evidence=["x"], analyst_action="Check the records.", confidence="LOW",
                            rationale="Scripted test.")
        self.assertNotIn("common_cause_status", a.model_dump())
        o = ClosingSummaryOutput.model_validate(copy.deepcopy(B("TC06")["final"]["closing_summary"]["output"]) | {"relationship_dispositions": None})
        self.assertNotIn("relationship_dispositions", o.model_dump())
        r = ReviewRecord.model_validate({k: v for k, v in self.__class__._review().model_dump().items()})
        self.assertNotIn("relationship_challenge_reviews", r.model_dump())

    @staticmethod
    def _review():
        return review_for(B("TC06")["snap"], generate_closing_summary(
            B("TC06")["snap"], openai_investigator(lambda kw, o=B("TC06")["out"]: raw(o))))

    def test_register_1_0_input_and_1_2_output_validate_as_before(self):
        si = copy.deepcopy(B("TC06")["si"])
        reg = si["relationship_register"]
        for k in ("schema", "confirmed_relationship_ids"):
            reg.pop(k)
        for r in reg["relationships"]:
            for k in ("relationship_type", "engine_status", "proof", "limitations"):
                r.pop(k)

        def old_output(d):
            d.pop("relationship_dispositions", None)
            for a in d["group_assessments"]:
                a.pop("common_cause_status", None)
        self.assertEqual(validate_closing_summary(R.scripted(si, old_output), si), [])
        with_disp = R.scripted(B("TC06")["si"])
        self.assertTrue(any("without an evidence-bearing relationship register" in e
                            for e in validate_closing_summary(with_disp, si)))


if __name__ == "__main__":
    unittest.main()
