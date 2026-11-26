"""Evidence-bearing relationships with the SIMPLIFIED analyst workflow (23 Nov 2026).

Workflow under test: the engine identifies exceptions and establishes evidence-backed relationships (with proofs) -> the AI
investigates and explains -> the analyst ACCEPTs or REJECTs each AI finding (optional explanation) -> the decision is in the
final audit pack and PDF. The AI never acknowledges, challenges, confirms or rejects an engine relationship.

Real pipeline on TC01-TC06 of UC042_RECONCILIATION_TEST_SUITE_V2 with engine relationship discovery ON (built once by
tests.test_relationship_register: engine -> pack with relationship register 1.1 -> investigations through the real graph
(provider HTTP MOCKED, scripted findings) -> analyst decisions -> review snapshot -> closing summary (real validation;
SCRIPTED model output) -> final pack -> PDF/HTML). TC03 is also checked on its revision 3 dataset. No live AI.
Expected values are the engine's own figures for the synthetic datasets, never the answer keys.
"""
import copy
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import tests.test_relationship_register as R
from tests.final_pack_support import openai_investigator, raw, review_for
from tests.renderer_v3_support import audit_integrity, norm, pdf_text, render_all
from uc042lib.final_pack import (AnalystReview, ClosingSummaryOutput, FinalPackInputError, GenerationInfo, Selection,
                                 assemble_final_pack, build_review_snapshot, closing_summary_input, generate_closing_summary,
                                 render_pdf, validate_closing_summary)
from uc042lib.final_pack.model import GroupAssessment, ReviewRecord
from uc042lib.final_pack.sources import list_investigations
from uc042lib.final_pack.validate import validate_final_pack
from uc042lib.investigation.packet import build_case, build_packet, build_scope, retrieve
from uc042lib.investigation.retrieval import EvidenceStore, load_pack
from uc042lib.investigation.routing import route_for
from uc042lib.pack.generate import generate
from uc042lib.pack.relationships import NO_PROOF_LIMITATION, build_relationship_register
from uc042lib.validate import ENRICHED_RULES

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SNAP04 = "IN-03:CBS-20260917-C0004-GBP"
TC03_REV3 = Path(os.environ.get("UC042_TC03_REV3",
                                r"C:\Users\artlptp263user\Downloads\UC042_RECONCILIATION_TEST_SUITE_V2_TC03_REV3"))
ANALYST = {"user_id": "analyst-7", "display_name": "Dana Analyst"}
REV3 = {}


def setUpModule():
    R.setUpModule()
    if (TC03_REV3 / "TC03_TIMING_DIFFERENCE" / "initial_submission").is_dir():
        root = R.TMP / "tc03_rev3"
        case = root / "datasets" / "tc03_timing_difference"
        shutil.copytree(TC03_REV3 / "TC03_TIMING_DIFFERENCE" / "initial_submission", case)
        (root / "packs").mkdir()
        generate(case, root / "packs", rules=ENRICHED_RULES)
        pid = next(p.name for p in (root / "packs").iterdir() if p.name.startswith("PACK-"))
        REV3.update(pack=load_pack(pid, root / "packs"), datasets=root / "datasets")


def tearDownModule():
    R.tearDownModule()


def B(tc):
    return R.BUILT[tc]


def rel(tc, a, b, status=None):
    return R.rel(tc, a, b, status)


def errors_for(tc, edit, si=None):
    si = si or B(tc)["si"]
    return validate_closing_summary(R.scripted(si, edit), si)


def packet(pack, datasets, exc):
    case = build_case(pack, exc)
    route = route_for(case["exception"], case["candidates"], case["results"])
    return build_packet(case, build_scope(case), route, retrieve(route, case, EvidenceStore(pack, datasets)))


def tc_packet(tc, exc):
    return packet(B(tc)["pack"], B(tc)["datasets"], exc)


def ids_of(pk):
    return {r["evidence_id"] for r in pk["source_records"]}


def inv_id(tc, exc):
    return list_investigations(B(tc)["pack"], exc, R.TMP / "inv")["published"][0]["investigation_id"]


def findings_path(tc, exc):
    info = next(i for i in list_investigations(B(tc)["pack"], exc, R.TMP / "inv")["published"])
    return Path(info["path"]) / "findings.json"


def reviewed_snapshot(tc, plan, explanations=None, skip=()):
    """Snapshot with the analyst's decisions: plan {exception_id: ACCEPT|REJECT}; explanations {exception_id: text};
    skip: INCLUDED investigations left PENDING (no decision)."""
    b, explanations = B(tc), explanations or {}
    sels, reviews = [], {}
    for x in b["pack"]["exception_register"]["exceptions"]:
        e = x["exception_id"]
        i = inv_id(tc, e)
        sels.append(Selection(exception_id=e, inclusion="INCLUDED", investigation_id=i))
        if e in skip:
            continue
        d = plan.get(e, "ACCEPT")
        text = explanations.get(e, "")
        reviews[i] = AnalystReview(
            analyst_review_id=f"AR-{e}", investigation_id=i, exception_id=e, decision=d,
            findings_sha256=hashlib.sha256(findings_path(tc, e).read_bytes()).hexdigest(), reviewer=ANALYST,
            decided_at="2026-11-23T14:05:00+00:00", comment=text if d == "ACCEPT" else "",
            rejection_reason=(text or "Rejected by the analyst in Ringfence (fixed wording)") if d == "REJECT" else "")
    return build_review_snapshot(b["pack_id"], sels, packs_root=b["packs"], investigations_root=R.TMP / "inv", analyst_reviews=reviews)


def final_for(snap):
    si = closing_summary_input(snap)
    out = R.scripted(si)
    summary = generate_closing_summary(snap, openai_investigator(lambda kw, o=out: raw(o)))
    review = review_for(snap, summary, reviewer=ANALYST)
    return assemble_final_pack(snap, summary, review, GenerationInfo(generated_at="2026-11-23T14:10:00+00:00")), summary, review


# ============================================================================================================ engine proofs
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
        self.assertEqual(n, 17)          # 12 TC01 + 1 TC02 + 1 TC04 + 3 TC06

    def test_tc06_01_03_proof_explains_the_90_and_keeps_the_reason_open(self):
        [r] = rel("TC06", "EXC-TC06-01", "EXC-TC06-03", "CONFIRMED")
        p = r["proof"]
        self.assertEqual((r["relationship_type"], p["result"], p["faulty_record"]), ("CAUSAL_PROPAGATION", "EQUAL", SNAP04))
        q = {x["name"]: x["value"] for x in p["quantities"]}
        self.assertEqual(q["C0004 snapshot balance 2026-09-17 (reported)"], "40682.24")
        self.assertEqual(q["C0004 roll-forward balance 2026-09-17 (previous snapshot + movements)"], "40592.24")
        self.assertEqual(q["snapshot error (snapshot - roll-forward)"], "90.00")
        self.assertEqual(q["internal difference 2026-09-17 (resource - requirement)"], "-90.00")
        self.assertIn("341484.46", p["requirement_effect"])
        self.assertTrue(any(c.startswith("EXC-TC06-04") and "reverses by 90.00" in c for c in p["corroboration"]))
        self.assertTrue(any("C0007" in c and "transaction-side" in c for c in p["corroboration"]))
        self.assertTrue(any("why the faulty record is wrong" in n for n in p["not_established"]))

    def test_tc06_other_relationships_and_coincidences(self):
        self.assertEqual(rel("TC06", "EXC-TC06-03", "EXC-TC06-04", "CONFIRMED")[0]["proof"]["result"], "EQUAL_AND_OPPOSITE")
        self.assertEqual(rel("TC06", "EXC-TC06-05", "EXC-TC06-06", "CONFIRMED")[0]["proof"]["faulty_record"], "IN-11:TX-0917-00002")
        r15 = rel("TC06", "EXC-TC06-01", "EXC-TC06-05")
        self.assertTrue(r15 and all(r["status"] == "REJECTED" for r in r15))
        coinc = [r for r in B("TC06")["reg"]["relationships"] if r["relationship_type"] == "COINCIDENCE"]
        self.assertTrue(coinc and all(r["status"] == "REJECTED" for r in coinc))
        self.assertFalse([r for r in B("TC06")["reg"]["relationships"] if "EXC-TC06-02" in r["exception_ids"] and r["status"] != "REJECTED"])

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
        [r] = build_relationship_register(V(), lambda text, owner: [])["relationships"]
        self.assertEqual((r["status"], r["engine_status"]), ("CANDIDATE", "CONFIRMED"))
        self.assertIn(NO_PROOF_LIMITATION, r["limitations"])


# ============================================================================================================ TC01-TC06: what the AI receives
class InvestigationEvidence(unittest.TestCase):
    """The evidence each scenario's AI investigation receives (the packet), from the real retrieval."""

    def test_tc01_duplicate_posting_and_its_evidence(self):
        pk = tc_packet("TC01", "EXC-TC01-06")
        self.assertIn("IN-10:LE-GBP-0928-0007", ids_of(pk))                                        # the duplicate row
        rels = pk["engine_relationships"]["relationships"]
        dup = [r for r in rels if r["relationship_type"] == "DUPLICATE_LINEAGE" and r["status"] == "CONFIRMED"]
        self.assertTrue(dup and all(r["proof"]["faulty_record"] == "IN-10:LE-GBP-0928-0007" for r in dup))
        self.assertTrue(all("1246.80" in r["proof"]["calculation"] for r in dup))

    def test_tc02_amount_discrepancy_and_its_impact(self):
        pk = tc_packet("TC02", "EXC-TC02-02")
        self.assertIn("IN-11:TX-0908-00002", ids_of(pk))
        [r] = [r for r in pk["engine_relationships"]["relationships"] if r["status"] == "CONFIRMED"]
        self.assertIn("18.00", r["proof"]["calculation"])                                           # the GBP 18 mismatch
        self.assertIn("C0006", r["proof"]["calculation"])                                           # its client impact

    @unittest.skipUnless(TC03_REV3.is_dir(), "TC03 revision 3 dataset not available")
    def test_tc03_revision_3_timing_difference(self):
        [x] = REV3["pack"]["exception_register"]["exceptions"]
        self.assertEqual((x["root_cause"], x["evidence_status"]), ("BANK_LEDGER_DIFFERENCE|SGA-GBP-01|2026-09-24|-5495.05",
                                                                    "TIMING_EVIDENCED"))
        pk = packet(REV3["pack"], REV3["datasets"], x["exception_id"])
        self.assertIn("AQ-GBP-20260924", json.dumps(pk))                                             # the timing item reaches the AI
        self.assertFalse([r for r in REV3["pack"]["investigation_group_register"]["relationship_register"]["relationships"]
                          if r["status"] == "CONFIRMED"])

    def test_tc04_unmatched_bank_credit(self):
        pk = tc_packet("TC04", "EXC-TC04-02")
        self.assertIn("IN-09:BE-EUR-0930-U01", ids_of(pk))
        [r] = [r for r in pk["engine_relationships"]["relationships"] if r["status"] == "CONFIRMED"]
        self.assertEqual((r["relationship_type"], r["proof"]["result"]), ("BALANCE_LINEAGE", "EQUAL"))   # 650.00 = difference

    def test_tc05_missing_settlement_transactions_without_client_attribution(self):
        pk = tc_packet("TC05", "EXC-TC05-02")
        self.assertIn("IN-12:SB-EUR-20260924", ids_of(pk))
        self.assertFalse([r for r in B("TC05")["reg"]["relationships"] if r["status"] == "CONFIRMED"])  # amounts only
        [c] = B("TC05")["reg"]["common_causes"]
        self.assertEqual(c["status"], "SUSPECTED")
        self.assertTrue(any("client of each missing transaction" in m for m in c["missing_evidence"]))
        gas = B("TC05")["final"]["closing_summary"]["output"]["group_assessments"]
        self.assertFalse([a for a in gas if a["relationship_verdict"] == "EVIDENCE_BACKED" or a["common_cause_status"] == "EVIDENCE_BACKED"])

    def test_tc06_01_investigation_receives_the_c0004_proof(self):
        pk = tc_packet("TC06", "EXC-TC06-01")
        self.assertIn(SNAP04, ids_of(pk))
        r = next(r for r in pk["engine_relationships"]["relationships"]
                 if r["status"] == "CONFIRMED" and set(r["exception_ids"]) == {"EXC-TC06-01", "EXC-TC06-03"})
        self.assertIn("341484.46", r["proof"]["requirement_effect"])
        self.assertTrue(any("reverses by 90.00" in c for c in r["proof"]["corroboration"]))
        self.assertTrue(any("why the faulty record is wrong" in n for n in r["proof"]["not_established"]))
        self.assertIn("REJECTED", {x["status"] for x in pk["engine_relationships"]["relationships"]
                                   if set(x["exception_ids"]) == {"EXC-TC06-01", "EXC-TC06-05"}})


# ============================================================================================================ AI contract (no AI decisions)
class AIContract(unittest.TestCase):
    def test_input_carries_the_proofs_and_no_disposition_list(self):
        reg = B("TC06")["si"]["relationship_register"]
        self.assertEqual(reg["schema"], "uc042-relationship-register/1.1")
        self.assertNotIn("confirmed_relationship_ids", reg)
        r = next(x for x in reg["relationships"] if set(x["exception_ids"]) == {"EXC-TC06-01", "EXC-TC06-03"})
        self.assertEqual(r["proof"]["faulty_record"], SNAP04)
        self.assertLessEqual(set(r["proof"]["records"]), set(B("TC06")["si"]["allowed_source_refs"]))

    def test_output_schema_has_no_ai_decision_on_engine_relationships(self):
        self.assertNotIn("relationship_dispositions", ClosingSummaryOutput.model_fields)
        from uc042lib.final_pack.summary import SUMMARY_INSTRUCTIONS
        flat = " ".join(SUMMARY_INSTRUCTIONS.split())
        self.assertNotIn("ACKNOWLEDGED", flat)
        self.assertNotIn("CHALLENGED", flat)
        self.assertIn("you never confirm, acknowledge, challenge or reject an engine relationship", flat)

    def test_tc06_related_while_the_reason_stays_open(self):
        gas = B("TC06")["final"]["closing_summary"]["output"]["group_assessments"]
        a = next(x for x in gas if {"EXC-TC06-01", "EXC-TC06-03"} <= set(x["exception_ids"]))
        self.assertEqual((a["relationship_verdict"], a["common_cause_status"]), ("EVIDENCE_BACKED", "NOT_ESTABLISHED"))
        self.assertFalse([x for x in gas if {"EXC-TC06-01", "EXC-TC06-05"} <= set(x["exception_ids"])])

    def test_live_prompt_1_7_tc06_assessments_satisfy_the_simplified_rules(self):
        live = json.loads((FIXTURES / "tc06_live_prompt17_group_assessments_20261123.json").read_text(encoding="utf-8"))
        self.assertEqual(errors_for("TC06", lambda d: d.update(group_assessments=live["group_assessments"])), [])

    def test_the_four_representations(self):
        def tc02(d):
            for a in d["group_assessments"]:
                a["common_cause_status"] = "EVIDENCE_BACKED"
                a["common_cause_hypothesis"] = "Both come from transaction TX-0908-00002; why it was recorded wrongly is not established."
        self.assertEqual(errors_for("TC02", tc02), [])                                             # related + cause backed
        self.assertEqual(errors_for("TC06", None), [])                                             # related + cause open
        gas = B("TC05")["final"]["closing_summary"]["output"]["group_assessments"]
        self.assertTrue(all(a["relationship_verdict"] == "UNVERIFIED" for a in gas))              # candidate
        self.assertTrue(rel("TC06", "EXC-TC06-01", "EXC-TC06-05", "REJECTED"))                     # rejected


class ValidationRules(unittest.TestCase):
    def refused(self, tc, edit, needle, si=None):
        errs = errors_for(tc, edit, si)
        self.assertTrue(any(needle in e for e in errs), (needle, errs))

    def test_e1_confirmed_without_proof_in_the_input(self):
        si = copy.deepcopy(B("TC06")["si"])
        next(x for x in si["relationship_register"]["relationships"] if x["status"] == "CONFIRMED")["proof"] = None
        self.refused("TC06", None, "carries no engine proof", si=si)

    def test_e2_live_prompt_1_6_silent_split_is_refused(self):
        live = json.loads((FIXTURES / "tc06_live_relreg_group_assessments_20261123.json").read_text(encoding="utf-8"))
        self.refused("TC06", lambda d: d.update(group_assessments=[dict(a, common_cause_status="NOT_ESTABLISHED")
                                                                   for a in live["group_assessments"]]),
                     "splits the engine-CONFIRMED relationship")

    def test_e2_engine_relationship_cannot_be_rejected_or_downgraded(self):
        def under(d):
            next(x for x in d["group_assessments"] if x["group_id"] == "GRP-TC06-01").update(
                relationship_verdict="UNVERIFIED", confidence="LOW", common_cause_status="UNVERIFIED")
        self.refused("TC06", under, "the engine owns relationship status")

        def coincidence(d):
            next(x for x in d["group_assessments"] if x["group_id"] == "GRP-TC06-01").update(
                relationship_verdict="COINCIDENCE_REJECTED", common_cause_status="NOT_ESTABLISHED", supporting_evidence=[],
                contradicting_evidence=["IN-11:TX-0917-00002"])
        self.refused("TC06", coincidence, "the engine owns relationship status")

    def test_e2_tc01_persistence_cannot_be_split_off(self):
        pair = next(r["exception_ids"] for r in B("TC01")["reg"]["relationships"] if r["link_type"] == "L2 PERSISTENCE")

        def split(d):
            g = next(x for x in d["group_assessments"] if set(pair) <= set(x["exception_ids"]))
            d["group_assessments"].append(dict(copy.deepcopy(g), exception_ids=[pair[1]], relationship_verdict="UNVERIFIED",
                                               confidence="LOW", common_cause_status="UNVERIFIED"))
            g["exception_ids"] = [e for e in g["exception_ids"] if e != pair[1]]
        self.refused("TC01", split, "splits the engine-CONFIRMED relationship")

    def test_c1_common_cause_status_is_required(self):
        self.refused("TC06", lambda d: d["group_assessments"][0].pop("common_cause_status"), "common_cause_status is required")

    def test_c2_unverified_common_cause_is_never_promoted(self):
        def cc(d):
            next(x for x in d["group_assessments"] if x["group_id"] == "CC-TC05-01")["common_cause_status"] = "EVIDENCE_BACKED"
        self.refused("TC05", cc, "never promoted")

        def cand(d):
            next(x for x in d["group_assessments"] if x["group_id"] == "CAND-TC05-01")["common_cause_status"] = "EVIDENCE_BACKED"
        self.refused("TC05", cand, "requires relationship_verdict EVIDENCE_BACKED")

    def test_c3_rejected_or_unconnected_cannot_back_a_common_cause(self):
        si = copy.deepcopy(B("TC06")["si"])
        si["investigation_groups"].append({"group_id": "GRP-TC06-99", "exception_ids": "EXC-TC06-01; EXC-TC06-05", "link_types": "",
                                           "links": "", "statement": "", "source_evidence_ids": []})
        si["investigation_groups"].append({"group_id": "GRP-TC06-98", "exception_ids": "EXC-TC06-02; EXC-TC06-03", "link_types": "",
                                           "links": "", "statement": "", "source_evidence_ids": []})

        def add(gid, excs):
            return {"group_id": gid, "exception_ids": excs, "related_exception_ids": [], "relationship_verdict": "EVIDENCE_BACKED",
                    "common_cause_status": "EVIDENCE_BACKED", "confidence": "MEDIUM",
                    "common_cause_hypothesis": "These may share a cause; it is not established.",
                    "supporting_evidence": [SNAP04], "contradicting_evidence": [], "missing_evidence": [],
                    "analyst_action": "Check the two exceptions together.", "rationale": "Scripted negative test."}

        def e(d):
            d["group_assessments"] += [add("GRP-TC06-99", ["EXC-TC06-01", "EXC-TC06-05"]),
                                       add("GRP-TC06-98", ["EXC-TC06-02", "EXC-TC06-03"])]
        errs = errors_for("TC06", e, si)
        self.assertTrue(any("a rejected relationship cannot support an evidence-backed common cause" in x for x in errs), errs)
        self.assertTrue(any("connected through CONFIRMED engine relationships" in x for x in errs), errs)

    def test_citations_must_be_source_records(self):
        def bad(d):
            next(x for x in d["group_assessments"] if x["group_id"] == "GRP-TC06-01")["supporting_evidence"].append("REL-TC06-04")
        self.refused("TC06", bad, "must be source evidence record IDs")


# ============================================================================================================ analyst review
class AnalystReviewWorkflow(unittest.TestCase):
    """ACCEPT / REJECT with optional explanation, identity and timestamp; pending review; audit history; engine untouched."""

    @classmethod
    def setUpClass(cls):
        cls.before = {e: hashlib.sha256(findings_path("TC06", e).read_bytes()).hexdigest()
                      for e in ("EXC-TC06-01", "EXC-TC06-02")}
        cls.explain = {"EXC-TC06-01": "Agreed: the C0004 snapshot of 17 Sep explains the 90.00; cause still to be confirmed.",
                       "EXC-TC06-02": "Rejected: the acquirer-report finding needs the acquirer's own settlement file first."}
        cls.snap = reviewed_snapshot("TC06", {"EXC-TC06-02": "REJECT"}, cls.explain)
        cls.final, cls.summary, cls.review = final_for(cls.snap)
        cls.all_accept, *_ = final_for(reviewed_snapshot("TC06", {}))

    def entry(self, exc):
        return next(e for e in self.final["exception_register"] if e["exception"]["exception_id"] == exc)

    def test_accept_with_explanation_identity_and_time_in_the_final_pack(self):
        r = self.entry("EXC-TC06-01")["investigation"]["analyst_review"]
        self.assertEqual((r["decision"], r["comment"], r["reviewer"], r["decided_at"]),
                         ("ACCEPT", self.explain["EXC-TC06-01"], ANALYST, "2026-11-23T14:05:00+00:00"))
        self.assertIn(inv_id("TC06", "EXC-TC06-01"), {i["investigation_id"] for i in self.final["ai_investigations"]})

    def test_reject_with_explanation_keeps_the_reference_and_excludes_the_ai_content(self):
        e = self.entry("EXC-TC06-02")["investigation"]
        r = e["analyst_review"]
        self.assertEqual((r["decision"], r["rejection_reason"], r["disposition"]),
                         ("REJECT", self.explain["EXC-TC06-02"], "REJECTED_BY_ANALYST"))
        self.assertEqual(e["investigation_id"], inv_id("TC06", "EXC-TC06-02"))                    # reference kept
        self.assertNotIn(e["investigation_id"], {i["investigation_id"] for i in self.final["ai_investigations"]})

    def test_reject_without_explanation_uses_the_fixed_wording(self):
        f, *_ = final_for(reviewed_snapshot("TC06", {"EXC-TC06-02": "REJECT"}))
        r = next(e for e in f["exception_register"] if e["exception"]["exception_id"] == "EXC-TC06-02")["investigation"]["analyst_review"]
        self.assertEqual(r["rejection_reason"], "Rejected by the analyst in Ringfence (fixed wording)")

    def test_pending_review_is_never_treated_as_accepted(self):
        with self.assertRaises(FinalPackInputError) as cm:
            reviewed_snapshot("TC06", {}, skip=("EXC-TC06-03",))
        self.assertIn("pending analyst review", str(cm.exception))
        self.assertIn("never treated as accepted", str(cm.exception))

    def test_original_ai_findings_stay_unchanged_in_the_audit_history(self):
        for e, digest in self.before.items():
            self.assertEqual(hashlib.sha256(findings_path("TC06", e).read_bytes()).hexdigest(), digest)

    def test_decisions_never_change_the_engine_result(self):
        pack = B("TC06")["pack"]
        for f in (self.final, self.all_accept):
            self.assertEqual([e["exception"] for e in f["exception_register"]], pack["exception_register"]["exceptions"])
            self.assertEqual(f["relationships"]["relationship_register"], pack["investigation_group_register"]["relationship_register"])
            self.assertTrue(all(e["resolution_status"] == "UNRESOLVED" for e in f["exception_register"]))
        for k in ("reconciliation_results", "relationships", "source_inventory"):
            self.assertEqual(self.final[k], self.all_accept[k], k)
        self.assertEqual(validate_final_pack(self.final, self.snap, self.summary, self.review), [])

    def test_tampered_engine_relationship_is_refused(self):
        f = copy.deepcopy(self.final)
        f["relationships"]["relationship_register"]["relationships"][0]["status"] = "REJECTED"
        errs = validate_final_pack(f, self.snap, self.summary, self.review)
        self.assertTrue(any("never changed" in e for e in errs), errs)

    def test_pdf_shows_the_decisions_the_engine_relationships_and_no_ai_verdicts(self):
        pdf, html = render_all(self.final)
        self.assertEqual(audit_integrity(self.final, B("TC06")["pack"], pdf, html, self.snap), [])
        t = norm(pdf_text(pdf))
        for s in ("REJECTED BY ANALYST", self.explain["EXC-TC06-02"], self.explain["EXC-TC06-01"], "Dana Analyst (analyst-7)",
                  "2026-11-23T14:05:00+00:00", "Related exceptions: engine relationship evidence", "ENGINE: CONFIRMED",
                  "Related exceptions (engine relationships)", "341484.46", "NOT established"):
            self.assertIn(norm(s), t, s)
        for s in ("ACKNOWLEDGED", "CHALLENGED", "AI challenge"):
            self.assertNotIn(norm(s), t, s)

    def test_every_tc_publishes_and_renders(self):
        for tc, b in R.BUILT.items():
            pdf, html = render_all(b["final"])
            self.assertEqual(audit_integrity(b["final"], b["pack"], pdf, html, b["snap"]), [], tc)
            self.assertIn(norm("Related exceptions: engine relationship evidence"), norm(pdf_text(pdf)), tc)


# ============================================================================================================ compatibility
class BackwardCompatibility(unittest.TestCase):
    def test_absent_new_fields_are_not_serialised(self):
        a = GroupAssessment(group_id="GRP-X-01", exception_ids=["EXC-X-01"], related_exception_ids=[], relationship_verdict="UNVERIFIED",
                            common_cause_hypothesis="The cause may be shared; not established.", supporting_evidence=[],
                            contradicting_evidence=[], missing_evidence=["x"], analyst_action="Check the records.", confidence="LOW",
                            rationale="Scripted test.")
        self.assertNotIn("common_cause_status", a.model_dump())
        self.assertNotIn("relationship_challenge_reviews", ReviewRecord.model_fields)

    def test_withdrawn_draft_output_is_refused_by_the_schema(self):
        out = copy.deepcopy(B("TC06")["final"]["closing_summary"]["output"])
        out["relationship_dispositions"] = []
        with self.assertRaises(Exception):
            ClosingSummaryOutput.model_validate(out)

    def test_register_1_0_input_and_1_2_output_validate_as_before(self):
        si = copy.deepcopy(B("TC06")["si"])
        reg = si["relationship_register"]
        reg.pop("schema")
        for r in reg["relationships"]:
            for k in ("relationship_type", "engine_status", "proof", "limitations"):
                r.pop(k)

        def old_output(d):
            for a in d["group_assessments"]:
                a.pop("common_cause_status", None)
        self.assertEqual(validate_closing_summary(R.scripted(si, old_output), si), [])


# ============================================================================================================ investigation prompt 1.9
class InvestigationPrompt(unittest.TestCase):
    """Prompt 1.9 / 2.9-tools: individual investigations examine and use the engine's relationships (root cause of the
    live TC06-01 weakness: the prompt never mentioned them, so an engine-CONFIRMED link was reported as merely possible)."""

    def test_versions_and_reusable_instruction(self):
        from uc042lib.investigation import config
        from uc042lib.investigation.prompts import SYSTEM_PROMPT, TOOLS_SYSTEM_PROMPT
        self.assertEqual((config.PROMPT_VERSION, config.TOOLS_PROMPT_VERSION),
                         ("uc042-investigator-prompt/1.12", "uc042-investigator-prompt/2.12-tools"))
        for p in (SYSTEM_PROMPT, TOOLS_SYSTEM_PROMPT):
            flat = " ".join(p.split())
            for s in ("engine_relationships", "status CONFIRMED: an engine result",
                      'Do not describe a CONFIRMED relationship as possible, potential or "may be related"',
                      "A relationship is not a cause", "never invent the reason behind a faulty record",
                      "status CANDIDATE", "status REJECTED", "Relationship IDs (REL-...) are not citable"):
                self.assertIn(s, flat)
            for s in ("TC06", "C0004", "EXC-", "90.00"):            # reusable: nothing scenario-specific
                self.assertNotIn(s, flat)

    def test_model_view_carries_the_proof_losslessly(self):
        from uc042lib.investigation.packet_view import render_model_view
        pk = tc_packet("TC06", "EXC-TC06-01")
        view = render_model_view(pk)                                   # raises unless the view reconstructs the packet
        rels = view["packet_extras"]["engine_relationships"]["relationships"]
        r = next(r for r in rels if r["status"] == "CONFIRMED" and set(r["exception_ids"]) == {"EXC-TC06-01", "EXC-TC06-03"})
        self.assertEqual(r["proof"]["faulty_record"], SNAP04)
        self.assertLessEqual(set(r["proof"]["records"]), set(pk["allowed_citation_ids"]))   # every proof record is citable

    def test_a_confirmed_relationship_finding_passes_investigation_validation(self):
        from tests.final_pack_support import OFFLINE
        from uc042lib.investigation.models import LLMInvestigationOutput
        from uc042lib.investigation.validation import validate_output
        b = B("TC06")
        case = build_case(b["pack"], "EXC-TC06-01")
        pk = tc_packet("TC06", "EXC-TC06-01")
        out = OFFLINE.investigate(pk)[0].model_dump()
        recs = [SNAP04, "IN-03:CBS-20260916-C0004-GBP", "IN-05:IRR-EMONEY-GBP-20260917"]
        out["confirmed_findings"].append({
            "finding_id": f"F-{len(out['confirmed_findings']) + 1:02d}", "evidence_basis": "SOURCE_EVIDENCE",
            "claim": "EXC-TC06-01 and EXC-TC06-03 are connected through the C0004 GBP snapshot of 2026-09-17, which is 90.00 "
                     "above its roll-forward; the GBP requirement of 341574.46 includes it and exceeds the resource of 341484.46 "
                     "by the same 90.00.",
            "explanation": "The engine's confirmed relationship proof compares the snapshot (40682.24) with its roll-forward "
                           "(40592.24) and the requirement with the resource; the next roll-forward reverses by 90.00.",
            "evidence_ids": recs, "supporting_records": recs, "title": "One out-of-line snapshot behind two exceptions",
            "audit_relevance": "It connects the internal difference to the client-balance roll-forward failures.",
            "establishes": "The 17 September C0004 snapshot is 90.00 above its roll-forward, equal to the requirement excess.",
            "does_not_establish": "Why the 17 September C0004 snapshot is wrong is not established by the records."})
        errors, notes, refs = validate_output(LLMInvestigationOutput.model_validate(out), pk, case)
        self.assertEqual(errors, [])


# ============================================================================================================ zero LLM after investigation
class ZeroLLMFinalisation(unittest.TestCase):
    """Analyst review and finalisation are deterministic: with every model entry point instrumented (OpenAI client class,
    investigator factories), snapshot, pending check, decisions, final pack, PDF, HTML, publication and re-opening make ZERO
    model calls. The AI stages (investigations, the closing summary) run before and are persisted."""

    def test_review_and_finalisation_make_no_model_call(self):
        from unittest import mock
        from uc042lib.final_pack import ClosingSummary, publish_final_pack, render_html, verify_final_pack
        snap0 = reviewed_snapshot("TC06", {"EXC-TC06-02": "REJECT"}, {"EXC-TC06-02": "Rejected: needs the acquirer file."})
        _, summary, _ = final_for(snap0)                       # AI stage (closing summary), persisted below
        persisted = json.loads(json.dumps(summary.model_dump()))
        calls = []

        def trip(name):
            def f(*a, **k):
                calls.append(name)
                raise AssertionError(f"model entry point called during finalisation: {name}")
            return f
        with mock.patch("openai.OpenAI", side_effect=trip("openai.OpenAI")), \
                mock.patch("uc042lib.investigation.llm.investigator_from_env", side_effect=trip("investigator_from_env")), \
                mock.patch("uc042lib.final_pack.summary.investigator_from_env", side_effect=trip("summary.investigator_from_env")):
            with self.assertRaises(FinalPackInputError):        # pending investigation: refused, no model call
                reviewed_snapshot("TC06", {}, skip=("EXC-TC06-04",))
            snap = reviewed_snapshot("TC06", {"EXC-TC06-02": "REJECT"}, {"EXC-TC06-02": "Rejected: needs the acquirer file."})
            self.assertEqual(snap.sha256, snap0.sha256)
            stored = ClosingSummary.model_validate(persisted)  # the persisted AI output is reused, never regenerated
            review = review_for(snap, stored, reviewer=ANALYST)
            final = assemble_final_pack(snap, stored, review, GenerationInfo(generated_at="2026-11-23T14:10:00+00:00"))
            pdf, html = render_pdf(final), render_html(final)
            root = Path(tempfile.mkdtemp(prefix="zero_llm_"))
            path = publish_final_pack(final, root)
            self.assertEqual(verify_final_pack(path), [])       # re-opening the published pack
            again = json.loads((Path(path) / "final_pack.json").read_text(encoding="utf-8"))
            self.assertEqual(render_html(again), html)
            shutil.rmtree(root, ignore_errors=True)
        self.assertEqual(calls, [])
        t = norm(pdf_text(pdf))
        self.assertIn(norm("Rejected: needs the acquirer file."), t)
        self.assertIn(norm(summary.output.overall_position), t)  # the persisted AI summary is what the PDF shows


if __name__ == "__main__":
    unittest.main()
