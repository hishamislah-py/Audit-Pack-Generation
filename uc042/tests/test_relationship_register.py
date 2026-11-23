"""TMS relationship register (23 Nov 2026): engine relationship discovery carried as ONE structured contract from the engine
through the audit pack to investigations and the AI closing summary.

Built through the REAL pipeline on TC01-TC06 of UC042_RECONCILIATION_TEST_SUITE_V2 (copied to a temp folder) with the
engine's relationship discovery ON (EngineRules.enrichment_v1): engine -> pack (+ relationship_register) -> per-exception
investigations (real graph and validation; provider HTTP mocked) -> analyst ACCEPT -> review snapshot -> closing summary
(real validation; the model response is SCRIPTED, built generically from the register, not per scenario) -> final pack ->
PDF/HTML -> renderer audit-integrity checks. Expected relationships are checked against the deterministic register, never
taken from the answer keys. Default-rule packs carry no register and are unchanged (covered by the existing suite).
"""
import copy
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.final_pack_support import openai_investigator, raw, review_for, summary_output
from tests.test_s1_group_assessments import REVIEWER, TCS, norm, pdf_text, scripted_investigation
from uc042lib.final_pack import (AnalystReview, ClosingSummaryError, GenerationInfo, Selection, assemble_final_pack,
                                 build_review_snapshot, closing_summary_input, generate_closing_summary, render_html,
                                 render_pdf, validate_closing_summary)
from uc042lib.investigation.packet import build_case, build_packet, build_scope, retrieve
from uc042lib.investigation.retrieval import EvidenceStore, load_pack
from uc042lib.investigation.routing import route_for
from uc042lib.pack.generate import generate
from uc042lib.validate import ENRICHED_RULES

SUITE = Path(os.environ.get("UC042_TC_SUITE", r"C:\Users\artlptp263user\Downloads\UC042_RECONCILIATION_TEST_SUITE_V2"))
TMP, BUILT = None, {}


def _ids(v):
    return [i.strip() for i in str(v).split(";") if i.strip()]


def register_assessments(si):
    """A generic, cautious scripted answer derived ONLY from the input's deterministic register (the behaviour prompt 1.6
    asks for): groups whose pairs the register CONFIRMS are EVIDENCE_BACKED citing those records; a member whose link the
    register REJECTS is split off as COINCIDENCE_REJECTED citing its own records; candidates and common causes are UNVERIFIED
    citing their supporting records, with all common-cause members as related exceptions."""
    reg = si["relationship_register"]
    conf = [r for r in reg["relationships"] if r["status"] == "CONFIRMED"]
    rej = [r for r in reg["relationships"] if r["status"] == "REJECTED"]
    src = {x["exception_id"]: x["source_evidence_ids"] for x in si["exceptions"]}
    cc_members = {e for c in reg["common_causes"] for e in c["exception_ids"]}
    out = []

    def a(gid, excs, verdict, sup, contra, conf_lvl, hyp, missing, related=()):
        out.append({"group_id": gid, "exception_ids": excs, "related_exception_ids": sorted(set(related) - set(excs)),
                    "relationship_verdict": verdict, "confidence": conf_lvl, "common_cause_hypothesis": hyp,
                    "supporting_evidence": sup, "contradicting_evidence": contra, "missing_evidence": missing,
                    "analyst_action": "SCRIPTED: verify the cited records and the stated missing evidence.",
                    "rationale": "SCRIPTED: derived from the engine's relationship register."})
    for g in si["investigation_groups"]:
        m = _ids(g["exception_ids"])
        linked = {e for r in conf for e in r["exception_ids"] if set(r["exception_ids"]) <= set(m)}
        odd = [e for e in m if e not in linked and any(e in r["exception_ids"] for r in rej)]
        core = [e for e in m if e not in odd]
        sup = sorted({i for r in conf if set(r["exception_ids"]) <= set(core) for i in r["supporting_records"]}) or g["source_evidence_ids"][:2]
        if core:
            a(g["group_id"], core, "EVIDENCE_BACKED" if linked else "UNVERIFIED", sup, [], "MEDIUM" if linked else "LOW",
              "SCRIPTED: these exceptions may share the cited originating record; the cause is not established.",
              ["SCRIPTED: the posting-level records behind the cited record."])
        for e in odd:
            a(g["group_id"], [e], "COINCIDENCE_REJECTED", [], src[e][:2], "MEDIUM",
              "SCRIPTED: the apparent link is a coincidence; no common cause is supported.", ["SCRIPTED: none needed."])
    for c in si["candidate_relationships"]:
        m = _ids(c["exception_ids"])
        a(c["candidate_id"], m, "UNVERIFIED", c["source_evidence_ids"][:3], [], "LOW",
          "SCRIPTED: the link may hold, but it rests on amounts only and is not established.",
          ["SCRIPTED: a record linking the transactions to the client."], related=cc_members if set(m) & cc_members else ())
    for c in reg["common_causes"]:
        a(c["common_cause_id"], list(c["exception_ids"]), "UNVERIFIED", c["supporting_records"][:4], [], "MEDIUM",
          "SCRIPTED: " + c["proposed_common_cause"] + " may be a common cause; it is not established.",
          list(c["missing_evidence"]) or ["SCRIPTED: evidence that would confirm the common cause."])
    return out


def scripted(si, edit=None):
    def put(d):
        d["group_assessments"] = register_assessments(si)
        if edit:
            edit(d)
    return summary_output(si, put)


def setUpModule():
    global TMP
    if not SUITE.is_dir():
        raise unittest.SkipTest(f"TC suite not found: {SUITE}")
    TMP = Path(tempfile.mkdtemp(prefix="relreg_"))
    datasets, packs, invs = TMP / "datasets", TMP / "packs", TMP / "inv"
    datasets.mkdir(); packs.mkdir(); invs.mkdir()
    from tests.renderer_v3_support import findings_sha
    for tc, folder in TCS.items():
        case = datasets / folder.lower()
        shutil.copytree(SUITE / folder / "initial_submission", case)
        before = {p.name for p in packs.iterdir()}
        rec = generate(case, packs, rules=ENRICHED_RULES)
        pack_id = next(p for p in ({q.name for q in packs.iterdir()} - before) if p.startswith("PACK-"))
        pack = load_pack(pack_id, packs)
        sels, reviews, inv = [], {}, {}
        for x in pack["exception_register"]["exceptions"]:
            e = x["exception_id"]
            inv[e] = scripted_investigation(pack_id, e, packs, datasets, invs)
            sels.append(Selection(exception_id=e, inclusion="INCLUDED", investigation_id=inv[e]))
            reviews[inv[e]] = AnalystReview(analyst_review_id=f"AR-{e}", investigation_id=inv[e], exception_id=e, decision="ACCEPT",
                                            findings_sha256=findings_sha(invs, pack, e, inv[e]), reviewer=REVIEWER,
                                            decided_at="2026-11-23T09:00:00+00:00")
        snap = build_review_snapshot(pack_id, sels, packs_root=packs, investigations_root=invs, analyst_reviews=reviews)
        si = closing_summary_input(snap)
        out = scripted(si)
        summary = generate_closing_summary(snap, openai_investigator(lambda kw, o=out: raw(o)))
        final = assemble_final_pack(snap, summary, review_for(snap, summary, reviewer=REVIEWER),
                                    GenerationInfo(generated_at="2026-11-23T10:00:00+00:00"))
        BUILT[tc] = dict(pack=pack, pack_id=pack_id, packs=packs, datasets=datasets, snap=snap, si=si, out=out, final=final,
                         reg=pack["investigation_group_register"]["relationship_register"])


def tearDownModule():
    if TMP:
        shutil.rmtree(TMP, ignore_errors=True)


def rel(tc, a, b, status=None):
    return [r for r in BUILT[tc]["reg"]["relationships"] if set(r["exception_ids"]) == {a, b} and (status is None or r["status"] == status)]


class Discovery(unittest.TestCase):
    def test_tc05_multi_line_combination_links_01_and_02(self):
        [r] = rel("TC05", "EXC-TC05-01", "EXC-TC05-02", "CANDIDATE")
        self.assertEqual(r["link_type"], "LINE-SUM MATCH")
        self.assertEqual({i for i in r["supporting_records"] if i.startswith("IN-13:")},
                         {"IN-13:SL-SB-EUR-20260924-0002", "IN-13:SL-SB-EUR-20260924-0003"})       # two lines combined
        self.assertIn("IN-03:CBS-20260924-C0101-EUR", r["supporting_records"])
        self.assertIn("amounts only", r["basis"])                                                     # never a cause by itself
        self.assertEqual(r["amounts"]["lines_total"], r["amounts"]["roll_forward_difference"])

    def test_tc05_common_cause_is_suspected_with_missing_evidence(self):
        [c] = BUILT["TC05"]["reg"]["common_causes"]
        self.assertEqual((sorted(c["exception_ids"]), c["status"]), (["EXC-TC05-01", "EXC-TC05-02", "EXC-TC05-03"], "SUSPECTED"))
        self.assertTrue(c["all_missing_lines_accounted_for"])
        self.assertTrue(any("client of each missing transaction" in m for m in c["missing_evidence"]))
        self.assertTrue(c["unverified_inferences"] and c["confirmed_facts"])

    def test_tc05_02_investigation_now_receives_the_batch_evidence(self):
        b = BUILT["TC05"]
        pack = load_pack(b["pack_id"], b["packs"])
        case = build_case(pack, "EXC-TC05-02")
        route = route_for(case["exception"], case["candidates"], case["results"])
        packet = build_packet(case, build_scope(case), route, retrieve(route, case, EvidenceStore(pack, b["datasets"])))
        ids = {r["evidence_id"] for r in packet["source_records"]}
        self.assertIn("IN-12:SB-EUR-20260924", ids)
        self.assertTrue({"IN-13:SL-SB-EUR-20260924-0002", "IN-13:SL-SB-EUR-20260924-0003"} <= ids)

    def test_tc06_genuine_lineage_confirmed_and_coincidence_rejected(self):
        self.assertEqual(rel("TC06", "EXC-TC06-05", "EXC-TC06-06", "CONFIRMED")[0]["supporting_records"][0], "IN-11:TX-0917-00002")
        self.assertIn("IN-03:CBS-20260917-C0004-GBP", rel("TC06", "EXC-TC06-03", "EXC-TC06-04", "CONFIRMED")[0]["supporting_records"])
        rejected = rel("TC06", "EXC-TC06-01", "EXC-TC06-05", "REJECTED")
        self.assertTrue(any(r["contradicting_records"] for r in rejected))                           # contradicting evidence
        self.assertTrue(any(r["link_type"] == "DATE_AMOUNT_COINCIDENCE" for r in rejected))          # same date and amount
        groups = sorted(sorted(_ids(g["exception_ids"])) for g in BUILT["TC06"]["pack"]["investigation_group_register"]["groups"])
        self.assertEqual(groups, [["EXC-TC06-01", "EXC-TC06-03", "EXC-TC06-04"], ["EXC-TC06-05", "EXC-TC06-06"]])

    def test_unrelated_exceptions_are_not_linked_and_every_link_is_record_backed(self):
        reg = BUILT["TC06"]["reg"]
        linked = {e for r in reg["relationships"] if r["status"] != "REJECTED" for e in r["exception_ids"]}
        self.assertNotIn("EXC-TC06-02", linked)                                                       # the acquirer-report error
        self.assertFalse([r for r in BUILT["TC03"]["reg"]["relationships"] if r["status"] != "REJECTED"])
        for tc, b in BUILT.items():                    # a link that is not REJECTED always rests on cited source records
            for r in b["reg"]["relationships"]:
                if r["status"] != "REJECTED":
                    self.assertTrue(r["supporting_records"], (tc, r["relationship_id"], r["link_type"]))
                if r["status"] == "CONFIRMED":
                    self.assertNotIn("amounts only", r["basis"], (tc, r["relationship_id"]))

    def test_tc02_exceptions_share_one_transaction_and_reconcile(self):
        conf = [r for r in BUILT["TC02"]["reg"]["relationships"] if r["status"] == "CONFIRMED"]
        self.assertTrue(conf)
        self.assertTrue(all(any(i.startswith("IN-11:") for i in r["supporting_records"]) for r in conf))

    def test_every_register_citation_is_an_evidence_register_record(self):
        for tc, b in BUILT.items():
            recs = {r["evidence_id"] for r in b["pack"]["evidence_register"]["records"]}
            for r in b["reg"]["relationships"]:
                self.assertLessEqual(set(r["supporting_records"]) | set(r["contradicting_records"]), recs, (tc, r["relationship_id"]))
            for c in b["reg"]["common_causes"]:
                self.assertLessEqual(set(c["supporting_records"]), recs, (tc, c["common_cause_id"]))


class AIContract(unittest.TestCase):
    def test_register_reaches_the_summary_input_with_its_records(self):
        si = BUILT["TC05"]["si"]
        self.assertIn("relationship_register", si)
        self.assertIn("CC-TC05-01", si["allowed_refs"])
        self.assertTrue({"IN-13:SL-SB-EUR-20260924-0002", "IN-13:SL-SB-EUR-20260924-0003"} <= set(si["allowed_source_refs"]))

    def test_every_tc_publishes_with_validated_register_based_assessments(self):
        from tests.renderer_v3_support import audit_integrity, render_all
        for tc, b in BUILT.items():
            self.assertEqual(validate_closing_summary(b["final"]["closing_summary"]["output"] and
                                                      __import__("uc042lib.final_pack.model", fromlist=["x"]).ClosingSummaryOutput
                                                      .model_validate(b["final"]["closing_summary"]["output"]), b["si"]), [], tc)
            pdf, html = render_all(b["final"])
            self.assertEqual(audit_integrity(b["final"], b["pack"], pdf, html, b["snap"]), [], tc)

    def test_tc05_assessment_includes_02_and_stays_unverified(self):
        gas = BUILT["TC05"]["final"]["closing_summary"]["output"]["group_assessments"]
        cc = next(a for a in gas if a["group_id"] == "CC-TC05-01")
        self.assertEqual((sorted(cc["exception_ids"]), cc["relationship_verdict"]),
                         (["EXC-TC05-01", "EXC-TC05-02", "EXC-TC05-03"], "UNVERIFIED"))
        self.assertTrue(cc["supporting_evidence"] and set(cc["supporting_evidence"]) <= set(BUILT["TC05"]["si"]["allowed_source_refs"]))
        cand = next(a for a in gas if a["group_id"] == "CAND-TC05-01")
        self.assertIn("EXC-TC05-02", cand["related_exception_ids"])
        t = norm(pdf_text(render_pdf(BUILT["TC05"]["final"])))
        self.assertIn(norm("CC-TC05-01: EXC-TC05-01, EXC-TC05-02, EXC-TC05-03"), t)

    def test_tc06_assessments_keep_the_two_origins_apart(self):
        gas = BUILT["TC06"]["final"]["closing_summary"]["output"]["group_assessments"]
        backed = sorted(sorted(a["exception_ids"]) for a in gas if a["relationship_verdict"] == "EVIDENCE_BACKED")
        self.assertEqual(backed, [["EXC-TC06-01", "EXC-TC06-03", "EXC-TC06-04"], ["EXC-TC06-05", "EXC-TC06-06"]])
        self.assertFalse([a for a in gas if {"EXC-TC06-01", "EXC-TC06-05"} <= set(a["exception_ids"])])


class Refused(unittest.TestCase):
    def refuse(self, tc, edit, needle, si=None):
        si = si or BUILT[tc]["si"]
        errors = validate_closing_summary(scripted(si, edit), si)
        self.assertTrue(any(needle in e for e in errors), (needle, errors))

    def test_suspected_common_cause_cannot_be_evidence_backed(self):
        def e(d):
            a = next(x for x in d["group_assessments"] if x["group_id"] == "CC-TC05-01")
            a.update(relationship_verdict="EVIDENCE_BACKED")
        self.refuse("TC05", e, "unconfirmed common cause")

    def test_missing_common_cause_assessment(self):
        self.refuse("TC05", lambda d: d.update(group_assessments=[x for x in d["group_assessments"] if x["group_id"] != "CC-TC05-01"]),
                    "missing an assessment for")

    def test_register_rejected_pair_cannot_be_one_evidence_backed_relationship(self):
        si = copy.deepcopy(BUILT["TC06"]["si"])           # a group that (wrongly) contains the rejected pair 01-05
        si["investigation_groups"].append({"group_id": "GRP-TC06-99", "exception_ids": "EXC-TC06-01; EXC-TC06-05", "link_types": "",
                                           "links": "", "statement": "", "source_evidence_ids": []})

        def e(d):
            d["group_assessments"].append({"group_id": "GRP-TC06-99", "exception_ids": ["EXC-TC06-01", "EXC-TC06-05"],
                                           "related_exception_ids": [], "relationship_verdict": "EVIDENCE_BACKED", "confidence": "MEDIUM",
                                           "common_cause_hypothesis": "These may share a cause on the same date and amount.",
                                           "supporting_evidence": ["IN-05:IRR-EMONEY-GBP-20260917"], "contradicting_evidence": [],
                                           "missing_evidence": [], "analyst_action": "Check the two exceptions together.",
                                           "rationale": "Same date and the same amount."})
        self.refuse("TC06", e, "relationship register rejects the link", si=si)

    def test_common_cause_only_observation_is_refused(self):
        def e(d):
            d["key_observations"] = [{"text": "The batch transactions are missing from the export.", "source_refs": ["CC-TC05-01"]}]
        self.refuse("TC05", e, "cites only hypotheses")

    def test_invalid_citation_in_a_common_cause_assessment(self):
        def e(d):
            next(x for x in d["group_assessments"] if x["group_id"] == "CC-TC05-01")["supporting_evidence"].append("REL-TC05-01")
        self.refuse("TC05", e, "must be source evidence record IDs")


if __name__ == "__main__":
    unittest.main()
