"""Session 1 (23 Nov 2026): group assessments in the AI closing summary (summary schema 1.2, input 1.1, prompt 1.3).

Scenario tests run the REAL pipeline on the TC01-TC06 datasets of UC042_RECONCILIATION_TEST_SUITE_V2 (copied to a temp
folder): engine + deterministic pack -> per-exception investigations (real graph, validation, write-once persistence; only
the provider HTTP layer is mocked) -> analyst ACCEPT / REJECT -> review snapshot -> closing summary (real
generate_closing_summary + deterministic validation; the model response is SCRIPTED, not AI analysis) -> final pack ->
PDF and HTML. The scripted group assessments encode each scenario's expected behaviour as TEST DATA; nothing in the
product code is scenario-specific. Negative tests mutate a valid output and require the validator to refuse it.

The suite is read from UC042_TC_SUITE (default: the Downloads copy); the module is skipped when it is not present.
TC03 uses the suite's current (Saturday 26 Sep) version: no weekday revision exists yet.
"""
import copy
import hashlib
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.final_pack_support import (OFFLINE, openai_investigator, raw, review_for, sha_tree, summary_output)
from uc042lib.final_pack import (AnalystReview, ClosingSummaryError, GenerationInfo, Selection, assemble_final_pack,
                                 build_review_snapshot, closing_summary_input, generate_closing_summary, render_html,
                                 render_pdf, validate_closing_summary)
from uc042lib.final_pack.model import ClosingSummaryOutput
from uc042lib.investigation.graph import run_investigation
from uc042lib.investigation.models import LLMInvestigationOutput
from uc042lib.investigation.packet import build_case, build_packet, build_scope, retrieve
from uc042lib.investigation.retrieval import EvidenceStore, load_pack
from uc042lib.investigation.routing import route_for
from uc042lib.pack.generate import generate

SUITE = Path(os.environ.get("UC042_TC_SUITE", r"C:\Users\artlptp263user\Downloads\UC042_RECONCILIATION_TEST_SUITE_V2"))
TCS = {"TC01": "TC01_DUPLICATE_TRANSACTION", "TC02": "TC02_AMOUNT_MISMATCH", "TC03": "TC03_TIMING_DIFFERENCE",
       "TC04": "TC04_UNMATCHED_TRANSACTION", "TC05": "TC05_COMMON_CAUSE", "TC06": "TC06_INDEPENDENT_CAUSES"}
REVIEWER = {"user_id": "analyst-tc", "display_name": "TC Analyst"}
REJECT = {"TC01": {"EXC-TC01-05"}, "TC06": {"EXC-TC06-02"}}     # analyst REJECTs these findings; every other one is ACCEPTed
TMP, BUILT = None, {}


def norm(s):
    return "".join(str(s).split())


def pdf_text(data):
    import io
    from pypdf import PdfReader
    return "".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)


def _ids(v):
    return [i.strip() for i in str(v).split(";") if i.strip()]


def scripted_investigation(pack_id, exc, packs, datasets, invs):
    """Publish a scripted (offline stub) investigation for one exception through the real graph; returns its ID."""
    pack = load_pack(pack_id, packs)
    case = build_case(pack, exc)
    route = route_for(case["exception"], case["candidates"], case["results"])
    packet = build_packet(case, build_scope(case), route, retrieve(route, case, EvidenceStore(pack, datasets)))
    out = OFFLINE.investigate(packet)[0].model_dump()
    out["investigation_summary"] = (f"SCRIPTED TEST OUTPUT for {exc}: the records show the engine's reported difference; the "
                                    "evidence examined does not establish why it arose.")
    for f in out["confirmed_findings"]:
        f.update(audit_relevance="The engine result is one of the results that make up this exception.",
                 establishes="The engine reported this outcome with the quoted computed and reported values.",
                 does_not_establish="Why the difference arose or how it will be resolved is not established.")
    for h in out["hypotheses"]:
        h["rationale"] = "The engine recorded a relationship between the exceptions that is not verified."
    parsed = LLMInvestigationOutput.model_validate(out)
    s = run_investigation(pack_id, exc, openai_investigator(lambda kw: raw(parsed)), packs_root=packs, datasets_root=datasets,
                          investigations_root=invs, mode="fixed")
    assert s["persist_outcome"] == "PUBLISHED", (exc, s["result"]["failure_reason"], s["result"]["validation_findings"])
    return s["result"]["investigation_id"]


# ---------------------------------------------------------------------------------------- scripted group assessments
def _src(si, excs):
    return [i for x in si["exceptions"] if x["exception_id"] in excs for i in x["source_evidence_ids"]]


def _group(si, gid):
    return next(g for g in si["investigation_groups"] + si["candidate_relationships"]
                if g.get("group_id", g.get("candidate_id")) == gid)


def scripted_assessments(tc, si):
    """Scenario behaviour as test data (what a correct AI answer looks like), built from the IDs in the summary input."""
    if tc == "TC01":
        g = si["investigation_groups"][0]
        return [dict(group_id=g["group_id"], exception_ids=_ids(g["exception_ids"]), related_exception_ids=[],
                     relationship_verdict="EVIDENCE_BACKED", confidence="MEDIUM",
                     common_cause_hypothesis="These exceptions may share one cause: the same transaction appears to have been "
                                             "posted twice to the cash book (a possible duplicate posting, not established).",
                     supporting_evidence=list(dict.fromkeys(g["source_evidence_ids"] + _src(si, _ids(g["exception_ids"]))))[:4],
                     contradicting_evidence=[], missing_evidence=["The posting audit trail for the repeated cash-book entry."],
                     analyst_action="Compare the two cash-book entries with the single bank credit and the export audit trail.",
                     rationale="The cited records carry the same reference and amount on the same day; one bank credit exists.")]
    if tc in ("TC02", "TC03"):
        return []
    if tc == "TC04":
        g = si["investigation_groups"][0]
        return [dict(group_id=g["group_id"], exception_ids=_ids(g["exception_ids"]), related_exception_ids=[],
                     relationship_verdict="UNVERIFIED", confidence="MEDIUM",
                     common_cause_hypothesis="The EUR 650.00 credit may be a receipt that was not recorded in the ledger; "
                                             "this is a possible explanation, not a confirmed cause.",
                     supporting_evidence=list(dict.fromkeys(g["source_evidence_ids"] + _src(si, _ids(g["exception_ids"]))))[:3],
                     contradicting_evidence=[], missing_evidence=["The remittance details identifying the payer of the credit."],
                     analyst_action="Obtain the remittance advice for the EUR 650.00 credit and check the unallocated register.",
                     rationale="The bank shows a credit with no matching ledger entry; nothing identifies the payer.")]
    if tc == "TC05":
        c = si["candidate_relationships"][0]
        members = _ids(c["exception_ids"])
        others = [x["exception_id"] for x in si["exceptions"] if x["exception_id"] not in members]
        return [dict(group_id=c["candidate_id"], exception_ids=members, related_exception_ids=others,
                     relationship_verdict="UNVERIFIED", confidence="MEDIUM",
                     common_cause_hypothesis="All three exceptions may share a common cause: transactions of one settlement "
                                             "batch could be missing from the transaction export (not established).",
                     supporting_evidence=list(dict.fromkeys(c["source_evidence_ids"] + _src(si, members + others)))[:4],
                     contradicting_evidence=[], missing_evidence=["The full export for the batch, to confirm the missing transactions."],
                     analyst_action="Request a re-export of the batch's transactions and compare it with the settlement lines.",
                     rationale="The settlement lines reference transactions absent from the export; the link is a candidate only.")]
    if tc == "TC06":
        g = si["investigation_groups"][0]
        members = _ids(g["exception_ids"])                                # EXC-TC06-01, -03, -05
        backed, decoy = [e for e in members if e != "EXC-TC06-05"], ["EXC-TC06-05"]
        sup = [i for i in dict.fromkeys(g["source_evidence_ids"] + _src(si, backed)) if i not in _src(si, decoy)]
        return [dict(group_id=g["group_id"], exception_ids=backed, related_exception_ids=["EXC-TC06-04"],
                     relationship_verdict="EVIDENCE_BACKED", confidence="MEDIUM",
                     common_cause_hypothesis="The reported shortfall may be driven by C0004's 17 Sep balance snapshot, which "
                                             "fails the roll-forward; a snapshot-side cause is possible, not established.",
                     supporting_evidence=sup[:4], contradicting_evidence=[],
                     missing_evidence=["The client-ledger postings behind C0004's 17 Sep balance."],
                     analyst_action="Investigate the client-ledger posting behind C0004's 17 Sep snapshot.",
                     rationale="The snapshot record is an input to the requirement on the same day (lineage)."),
                dict(group_id=g["group_id"], exception_ids=decoy, related_exception_ids=[],
                     relationship_verdict="COINCIDENCE_REJECTED", confidence="MEDIUM",
                     common_cause_hypothesis="The same date and amount look like a link, but this is a coincidence: no "
                                             "common cause with the snapshot-side exceptions is supported.",
                     supporting_evidence=[], contradicting_evidence=_src(si, decoy)[:3],
                     missing_evidence=["The export audit trail for the transaction-side difference."],
                     analyst_action="Treat this as a separate, transaction-side issue and request a corrected export.",
                     rationale="Its records show a transaction-side difference unrelated to C0004's snapshot.")]
    raise KeyError(tc)


def scripted_summary(tc, si, edit=None):
    def put(d):
        d["group_assessments"] = scripted_assessments(tc, si)
        if edit:
            edit(d)
    return summary_output(si, put)


# ---------------------------------------------------------------------------------------------- module fixture
def setUpModule():
    global TMP
    if not SUITE.is_dir():
        raise unittest.SkipTest(f"TC suite not found: {SUITE}")
    TMP = Path(tempfile.mkdtemp(prefix="s1ga_"))
    datasets, packs, invs = TMP / "datasets", TMP / "packs", TMP / "inv"
    datasets.mkdir(); packs.mkdir(); invs.mkdir()
    for tc, folder in TCS.items():
        case = datasets / folder.lower()
        shutil.copytree(SUITE / folder / "initial_submission", case)
        before = set(p.name for p in packs.iterdir())
        generate(case, packs)
        pack_id = next(p for p in (set(q.name for q in packs.iterdir()) - before) if p.startswith("PACK-"))
        pack = load_pack(pack_id, packs)
        inv, sels, reviews = {}, [], {}
        for x in pack["exception_register"]["exceptions"]:
            e = x["exception_id"]
            inv[e] = scripted_investigation(pack_id, e, packs, datasets, invs)
            sels.append(Selection(exception_id=e, inclusion="INCLUDED", investigation_id=inv[e]))
            from tests.renderer_v3_support import findings_sha
            dec = "REJECT" if e in REJECT.get(tc, set()) else "ACCEPT"
            reviews[inv[e]] = AnalystReview(
                analyst_review_id=f"AR-{e}", investigation_id=inv[e], exception_id=e, decision=dec,
                findings_sha256=findings_sha(invs, pack, e, inv[e]), reviewer=REVIEWER, decided_at="2026-11-23T09:00:00+00:00",
                comment="", rejection_reason="The analyst's own review disagrees with the AI finding." if dec == "REJECT" else "")
        inv_digest_before = sha_tree(invs)
        snap = build_review_snapshot(pack_id, sels, packs_root=packs, investigations_root=invs, analyst_reviews=reviews)
        si = closing_summary_input(snap)
        out = scripted_summary(tc, si)
        summary = generate_closing_summary(snap, openai_investigator(lambda kw, o=out: raw(o)))
        final = assemble_final_pack(snap, summary, review_for(snap, summary, reviewer=REVIEWER),
                                    GenerationInfo(generated_at="2026-11-23T10:00:00+00:00"))
        pdf, html = render_pdf(final), render_html(final)
        BUILT[tc] = dict(pack=pack, pack_id=pack_id, inv=inv, snap=snap, si=si, out=out, summary=summary, final=final,
                         pdf=norm(pdf_text(pdf)), html=html, reviews=reviews, invs=invs,
                         inv_digest_before=inv_digest_before, inv_digest_after=sha_tree(invs))


def tearDownModule():
    if TMP:
        shutil.rmtree(TMP, ignore_errors=True)


# ------------------------------------------------------------------------------------------------- scenario tests
class Scenarios(unittest.TestCase):
    def ga(self, tc):
        return BUILT[tc]["final"]["closing_summary"]["output"]["group_assessments"]

    def rendered(self, tc, a):
        b = BUILT[tc]
        for t in (a["group_id"], a["relationship_verdict"], a["common_cause_hypothesis"], a["analyst_action"],
                  *a["supporting_evidence"], *a["contradicting_evidence"], *a["exception_ids"]):
            self.assertIn(norm(t), b["pdf"], (tc, t))
            self.assertIn(t, b["html"].replace("&#x27;", "'").replace("&amp;", "&"), (tc, t))
        self.assertIn(norm("Likely common cause (HYPOTHESIS - NOT ESTABLISHED)"), b["pdf"])

    def test_every_tc_passes_the_renderer_audit_integrity_checks(self):
        from tests.renderer_v3_support import audit_integrity, render_all
        for tc, b in BUILT.items():
            pdf, html = render_all(b["final"])
            self.assertEqual(render_pdf(b["final"]), pdf, f"{tc}: PDF not byte-reproducible")
            self.assertEqual(audit_integrity(b["final"], b["pack"], pdf, html, b["snap"]), [], tc)

    def test_every_tc_publishes_a_final_pack_with_validated_group_assessments(self):
        for tc, b in BUILT.items():
            self.assertEqual(b["summary"].status, "GENERATED", tc)
            self.assertEqual(validate_closing_summary(b["summary"].output, b["si"]), [], tc)
            self.assertEqual(b["final"]["metadata"]["status"], "GENERATED", tc)
            self.assertIsNotNone(b["final"]["closing_summary"]["output"].get("group_assessments"), tc)
            self.assertIn(norm("Group assessments (related exceptions"), b["pdf"], tc)

    def test_tc01_duplicate_group_assessed_together_with_source_evidence(self):
        [a] = self.ga("TC01")
        self.assertEqual(a["relationship_verdict"], "EVIDENCE_BACKED")
        self.assertEqual(sorted(a["exception_ids"]), ["EXC-TC01-02", "EXC-TC01-03", "EXC-TC01-04"])
        self.assertTrue(a["supporting_evidence"])
        self.assertLessEqual(set(a["supporting_evidence"]), set(BUILT["TC01"]["si"]["allowed_source_refs"]))
        self.assertTrue(all(i.startswith("IN-") and "|" not in i for i in a["supporting_evidence"]))
        self.rendered("TC01", a)

    def test_tc02_tc03_no_relationship_is_invented_and_the_empty_case_is_explicit(self):
        for tc in ("TC02", "TC03"):
            self.assertEqual(self.ga(tc), [], tc)
            self.assertIn(norm("No investigation group or candidate relationship was supplied for this pack"), BUILT[tc]["pdf"], tc)
            bad = scripted_summary(tc, BUILT[tc]["si"], lambda d: d["group_assessments"].append(dict(
                scripted_assessments("TC04", BUILT["TC04"]["si"])[0], group_id="GRP-TC02-99")))
            self.assertTrue(any("unknown relationship ID" in e for e in validate_closing_summary(bad, BUILT[tc]["si"])), tc)

    def test_tc04_unmatched_receipt_is_a_possible_cause_never_confirmed(self):
        [a] = self.ga("TC04")
        self.assertEqual(a["relationship_verdict"], "UNVERIFIED")
        self.assertIn("may be a receipt that was not recorded", a["common_cause_hypothesis"])
        self.rendered("TC04", a)
        si = BUILT["TC04"]["si"]
        bad = scripted_summary("TC04", si, lambda d: d["group_assessments"][0].update(
            common_cause_hypothesis="The EUR 650.00 credit is an unrecorded receipt of the firm."))
        self.assertTrue(any("worded as an unverified hypothesis" in e for e in validate_closing_summary(bad, si)))

    def test_tc05_common_cause_across_three_exceptions_with_uncertainty(self):
        [a] = self.ga("TC05")
        self.assertEqual(a["group_id"], "CAND-TC05-01")
        self.assertEqual(a["relationship_verdict"], "UNVERIFIED")
        self.assertEqual(sorted(a["exception_ids"] + a["related_exception_ids"]), ["EXC-TC05-01", "EXC-TC05-02", "EXC-TC05-03"])
        self.assertTrue(a["missing_evidence"])
        self.rendered("TC05", a)
        si = BUILT["TC05"]["si"]
        bad = scripted_summary("TC05", si, lambda d: d["group_assessments"][0].update(relationship_verdict="EVIDENCE_BACKED"))
        self.assertTrue(any("candidate relationship" in e and "EVIDENCE_BACKED" in e for e in validate_closing_summary(bad, si)))

    def test_tc06_genuine_causes_stay_separate_and_the_coincidence_is_rejected(self):
        gas = self.ga("TC06")
        self.assertEqual(len(gas), 2)
        backed = next(a for a in gas if a["relationship_verdict"] == "EVIDENCE_BACKED")
        decoy = next(a for a in gas if a["relationship_verdict"] == "COINCIDENCE_REJECTED")
        self.assertEqual(sorted(backed["exception_ids"]), ["EXC-TC06-01", "EXC-TC06-03"])
        self.assertEqual(decoy["exception_ids"], ["EXC-TC06-05"])
        self.assertTrue(decoy["contradicting_evidence"])
        self.assertFalse(set(backed["supporting_evidence"]) & set(decoy["contradicting_evidence"]))
        for a in gas:
            self.rendered("TC06", a)
        self.assertIn(norm("COINCIDENCE - RELATIONSHIP REJECTED"), BUILT["TC06"]["pdf"])

    def test_individual_investigations_unchanged_and_decisions_reflected(self):
        for tc, b in BUILT.items():
            self.assertEqual(b["inv_digest_before"], b["inv_digest_after"], tc)        # artefacts never rewritten
            sel = {s.exception_id: s.investigation_id for s in b["snap"].selections}
            self.assertEqual(sel, b["inv"], tc)
        for tc, rejected in REJECT.items():
            t = BUILT[tc]["pdf"].lower()
            self.assertIn(norm("rejected by analyst"), t, tc)
            self.assertIn(norm("accepted by the analyst"), t, tc)
            acc = set(BUILT[tc]["snap"].accepted_ids)
            for e in rejected:
                self.assertNotIn(BUILT[tc]["inv"][e], acc, tc)


# ------------------------------------------------------------------------------------------------- negative tests
class Refused(unittest.TestCase):
    """A valid TC05 / TC06 output, mutated: the deterministic validator must refuse each mutation."""

    def refuse(self, tc, edit, needle):
        si = BUILT[tc]["si"]
        errors = validate_closing_summary(scripted_summary(tc, si, edit), si)
        self.assertTrue(any(needle in e for e in errors), (needle, errors))
        with self.assertRaises(ClosingSummaryError):   # and generation refuses to publish it
            out = scripted_summary(tc, si, edit)
            generate_closing_summary(BUILT[tc]["snap"], openai_investigator(lambda kw: raw(out)))

    def test_missing_group_assessments(self):
        self.refuse("TC05", lambda d: d.pop("group_assessments"), "group_assessments is required")

    def test_empty_group_assessments_when_relationships_exist(self):
        self.refuse("TC06", lambda d: d.update(group_assessments=[]), "missing an assessment for")

    def test_unknown_relationship_id(self):
        self.refuse("TC06", lambda d: d["group_assessments"][0].update(group_id="GRP-TC06-77"), "unknown relationship ID")

    def test_engine_result_id_cited_as_source_evidence(self):
        self.refuse("TC05", lambda d: d["group_assessments"][0]["supporting_evidence"].append("C06-DIFFERENCE|2026-09-24/EUR"),
                    "must be source evidence record IDs")

    def test_exception_candidate_and_missing_ids_are_not_source_evidence(self):
        for bad in ("EXC-TC05-02", "CAND-TC05-01", "MISS-01"):
            self.refuse("TC05", lambda d, b=bad: d["group_assessments"][0]["supporting_evidence"].append(b),
                        "must be source evidence record IDs")

    def test_invented_record_id(self):
        self.refuse("TC06", lambda d: d["group_assessments"][1]["contradicting_evidence"].append("IN-11:TX-0917-99999"),
                    "must be source evidence record IDs")

    def test_unsupported_hypothesis_stated_as_confirmed(self):
        self.refuse("TC06", lambda d: d["group_assessments"][0].update(
            common_cause_hypothesis="C0004's 17 Sep snapshot is the cause of the shortfall."), "worded as an unverified hypothesis")

    def test_unverified_with_high_confidence(self):
        self.refuse("TC05", lambda d: d["group_assessments"][0].update(confidence="HIGH"), "cannot have HIGH confidence")

    def test_no_support_and_no_missing_evidence(self):
        self.refuse("TC05", lambda d: d["group_assessments"][0].update(supporting_evidence=[], missing_evidence=[]),
                    "missing_evidence must say what is needed")

    def test_coincidence_without_contradicting_evidence(self):
        self.refuse("TC06", lambda d: d["group_assessments"][1].update(contradicting_evidence=[]),
                    "COINCIDENCE_REJECTED requires contradicting source evidence")

    def test_evidence_backed_with_contradicting_evidence(self):
        def e(d):
            d["group_assessments"][0]["contradicting_evidence"] = list(d["group_assessments"][1]["contradicting_evidence"][:1])
        self.refuse("TC06", e, "cannot be EVIDENCE_BACKED")

    def test_rejected_relationship_cited_as_support(self):
        def e(d):
            d["group_assessments"][0].update(relationship_verdict="COINCIDENCE_REJECTED", confidence="LOW",
                                             contradicting_evidence=list(d["group_assessments"][0]["supporting_evidence"][:1]),
                                             supporting_evidence=[])
            d["key_observations"][0]["source_refs"].append("CAND-TC05-01")
        self.refuse("TC05", e, "cites a relationship rejected as coincidence")

    def test_split_assessments_must_not_overlap_or_leave_out_an_exception(self):
        self.refuse("TC06", lambda d: d["group_assessments"][1].update(exception_ids=["EXC-TC06-05", "EXC-TC06-03"]), "overlap")
        self.refuse("TC06", lambda d: d["group_assessments"].pop(1), "must cover exactly its exceptions")

    def test_resolution_claim_in_an_assessment(self):
        self.refuse("TC05", lambda d: d["group_assessments"][0].update(
            analyst_action="Note that the discrepancy has been resolved by the batch re-export."), "resolved")

    def test_contradictory_evidence_is_rendered_separately(self):
        b = BUILT["TC06"]
        decoy = b["final"]["closing_summary"]["output"]["group_assessments"][1]
        self.assertIn(norm("Contradicting evidence (source records)" + ", ".join(decoy["contradicting_evidence"])), b["pdf"])


class BackwardCompatible(unittest.TestCase):
    def test_a_stored_summary_without_group_assessments_keeps_its_bytes_and_renders_no_section(self):
        out = scripted_summary("TC02", BUILT["TC02"]["si"])
        d = out.model_dump()
        d.pop("group_assessments")
        old = ClosingSummaryOutput.model_validate(d)
        self.assertNotIn("group_assessments", old.model_dump())          # omitted, so stored hashes are unchanged
        from uc042lib.final_pack.report_v3 import _group_assessment_blocks
        self.assertEqual(_group_assessment_blocks(old.model_dump()), [])

    def test_input_1_0_without_source_refs_needs_no_group_assessments(self):
        si = copy.deepcopy(BUILT["TC05"]["si"])
        si.pop("allowed_source_refs")
        d = scripted_summary("TC05", BUILT["TC05"]["si"]).model_dump()
        d.pop("group_assessments")
        self.assertEqual([e for e in validate_closing_summary(ClosingSummaryOutput.model_validate(d), si) if "group" in e], [])


if __name__ == "__main__":
    unittest.main()
