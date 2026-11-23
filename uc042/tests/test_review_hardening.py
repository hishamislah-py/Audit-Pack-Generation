"""V2 review hardening: contradiction vs reconciliation-view vs unexplained-difference classification, and write-once
integrity of persisted artefacts (including legacy CRLF / earlier-schema artefacts). Offline; temporary folders only.
Run from uc042/: python -m unittest -v"""
import copy
import glob
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from uc042lib.investigation import config, tools
from uc042lib.investigation.graph import run_investigation
from uc042lib.investigation.llm import OfflineSimulatedInvestigator, ScriptedInvestigator
from uc042lib.investigation.models import LLMInvestigationOutput
from uc042lib.investigation.packet import build_case, build_ledger, build_packet, build_scope, collector_from_packet, retrieve
from uc042lib.investigation.persistence import ImmutabilityError, investigation_id_from_findings, verify_published
from uc042lib.investigation.prompts import SYSTEM_PROMPT, TOOLS_SYSTEM_PROMPT
from uc042lib.investigation.retrieval import EvidenceStore, load_pack
from uc042lib.investigation.routing import route_for
from uc042lib.investigation.validation import reconciliation_view, validate_output

ROOT = Path(__file__).resolve().parent.parent
PACK = {os.path.basename(p).split("-")[1]: os.path.basename(p) for p in glob.glob(str(ROOT / "packs" / "PACK-*"))}
OFFLINE = OfflineSimulatedInvestigator()
ERL, CONFIRMATION, INTERNAL = "IN-06:ERL-SGA-GBP-01-20260917", "IN-07:ST-SGA-GBP-01-20260917-1700", "IN-05:IRR-EMONEY-GBP-20260917"
C08 = "C08-DIFFERENCE|2026-09-17/SGA-GBP-01"


def setup_case(scenario, exception_id):
    pack = load_pack(PACK[scenario])
    case = build_case(pack, exception_id)
    route = route_for(case["exception"], case["candidates"], case["results"])
    store = EvidenceStore(pack)
    return case, build_packet(case, build_scope(case), route, retrieve(route, case, store)), store


def s05_ledger():
    """The S05 evidence as in the live run: the packet plus the internal reconciliation record retrieved by a tool."""
    case, packet, store = setup_case("S05", "EXC-S05-01")
    col = collector_from_packet(packet)
    args, err = tools.parse_request("get_reconciliation_evidence", {"account_id": "SGA-GBP-01", "currency": "GBP", "date": "2026-09-17"})
    tools.execute("get_reconciliation_evidence", args, store, col)
    return case, packet, build_ledger(packet, case, col)


def contradiction(compared, scope="Both are balances of account SGA-GBP-01 at the 2026-09-17 17:00 reconciliation point.",
                  description="The two records report different values for the same measure."):
    return {"item_id": "C-01", "description": description, "evidence_ids": list(dict.fromkeys(compared)) or [ERL],
            "compared_evidence": compared, "same_measure_and_scope": scope}


def errors_for(output, ledger, case):
    return validate_output(LLMInvestigationOutput.model_validate(output), ledger, case)[0]


class ContradictionClassification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case, cls.packet, cls.ledger = s05_ledger()
        cls.base = OFFLINE.investigate(cls.packet)[0].model_dump()

    def with_contradiction(self, c):
        out = copy.deepcopy(self.base)
        out["contradictory_evidence"] = [c]
        return out

    def test_s05_internal_vs_external_views_are_not_a_contradiction(self):
        fields = {r["evidence_id"]: r["fields"] for r in self.ledger["source_records"]}
        # the live-run evidence: internal difference 0.00 (requirement vs resource) and external -812.40 (ledger vs bank)
        self.assertEqual((fields[INTERNAL]["difference_reported"], fields[ERL]["difference_reported"]), ("0.00", "-812.40"))
        self.assertEqual(fields[INTERNAL]["resource_reported"], fields[ERL]["ledger_balance_reported"])  # same firm ledger figure
        errs = errors_for(self.with_contradiction(contradiction([INTERNAL, ERL], scope="Both are 2026-09-17 GBP reconciliation results "
                                                                                       "for the firm's safeguarding position.")),
                          self.ledger, self.case)
        self.assertTrue(any("different reconciliation views" in e for e in errs), errs)
        errs = errors_for(self.with_contradiction(contradiction(["C06-DIFFERENCE|2026-09-17/GBP", C08])), self.ledger, self.case)
        self.assertTrue(any("different reconciliation views" in e or "not present" in e for e in errs), errs)

    def test_the_original_live_s05_contradiction_shape_is_rejected(self):
        legacy = {"item_id": "C-01", "description": "The internal reconciliation reports a 0.00 GBP difference, while the external "
                  "reconciliation reports -812.40.", "evidence_ids": [INTERNAL, ERL, CONFIRMATION, C08]}
        errs = errors_for(self.with_contradiction(legacy), self.ledger, self.case)
        self.assertTrue(any("exactly two" in e for e in errs), errs)

    def test_same_measure_and_scope_may_be_a_contradiction(self):
        # same account, same 17:00 point, same measure (bank balance): structurally a valid contradiction
        ok = self.with_contradiction(contradiction([ERL, CONFIRMATION]))
        self.assertEqual(errors_for(ok, self.ledger, self.case), [])
        # real disagreeing data: SC5D's deterministic conflict (engine 395594.86 vs firm 395844.86) and SC2's log status
        for scenario, eid in (("SC5D", "EXC-SC5D-01"), ("SC2", "EXC-SC2-01")):
            case, packet, _ = setup_case(scenario, eid)
            out = OFFLINE.investigate(packet)[0]
            self.assertTrue(out.contradictory_evidence, scenario)
            self.assertEqual(validate_output(out, packet, case)[0], [], scenario)

    def test_missing_scope_or_missing_evidence_is_not_proof_of_contradiction(self):
        not_found = next(s["search_id"] for s in self.ledger["searches"] if s["result"] == "NOT_FOUND")
        with self.assertRaises(ValidationError):  # the strict schema already refuses an unexplained scope
            LLMInvestigationOutput.model_validate(self.with_contradiction(contradiction([ERL, CONFIRMATION], scope="Unclear.")))
        for c, expect in ((contradiction([ERL, not_found]), "cannot be one side"),
                          (contradiction([ERL, CONFIRMATION], scope="                         "), "same measure and scope"),
                          (contradiction([ERL, ERL]), "exactly two"),
                          (contradiction([ERL, "IN-07:ST-INVENTED-1700"]), "not present")):
            with self.subTest(expect=expect):
                errs = errors_for(self.with_contradiction(c), self.ledger, self.case)
                self.assertTrue(any(expect in e for e in errs), errs)
        case, packet, _ = setup_case("S02", "EXC-S02-01")
        out = OFFLINE.investigate(packet)[0].model_dump()
        out["contradictory_evidence"] = [contradiction(["IN-06:ERL-SGA-EUR-01-20260915", "MISS-01"])]
        self.assertTrue(any("cannot be one side" in e for e in errors_for(out, packet, case)))
        case, packet, _ = setup_case("SC5A", "EXC-SC5A-01")
        out = OFFLINE.investigate(packet)[0].model_dump()
        out["contradictory_evidence"] = [contradiction(["CBAL-ROLLFWD|GBP/C0002 2026-09-15", "CAND-SC5A-01"])]
        self.assertTrue(any("cannot be one side" in e or "candidate" in e for e in errors_for(out, packet, case)))

    def test_unexplained_difference_stays_unexplained(self):
        out = copy.deepcopy(self.base)
        out["confirmed_findings"].append({"finding_id": "F-09", "claim": "The external reconciliation reports a -812.40 GBP "
                                          "difference on 2026-09-17 that the available evidence does not explain.",
                                          "explanation": "Ledger 341484.46 against bank 340672.06; no record establishes why.",
                                          "evidence_ids": [ERL, C08], "supporting_records": [ERL]})
        self.assertEqual(errors_for(out, self.ledger, self.case), [])
        caused = copy.deepcopy(out)
        caused["confirmed_findings"][-1]["claim"] = "The -812.40 GBP difference was caused by an unrecorded bank debit."
        self.assertTrue(any("cause" in e for e in errors_for(caused, self.ledger, self.case)))
        c = self.with_contradiction(contradiction([ERL, CONFIRMATION], description="The balances disagree because of a misposting."))
        self.assertTrue(any("states a cause in a contradiction" in e for e in errors_for(c, self.ledger, self.case)))

    def test_view_mapping_and_prompt_rules(self):
        self.assertEqual(reconciliation_view(INTERNAL), reconciliation_view("C06-DIFFERENCE|2026-09-17/GBP"))
        self.assertEqual(reconciliation_view(ERL), reconciliation_view(C08))
        self.assertNotEqual(reconciliation_view(INTERNAL), reconciliation_view(ERL))
        self.assertNotEqual(reconciliation_view("IN-03:CBS-20260915-C0002-GBP"), reconciliation_view(ERL))
        for unclassified in ("IN-14:DL-0001", "CONF-01", "EXC-SC2-01", "IN-09:BE-GBP-0917-X01"):
            self.assertIsNone(reconciliation_view(unclassified), unclassified)
        for prompt in (SYSTEM_PROMPT, TOOLS_SYSTEM_PROMPT):
            for phrase in ("Actual contradiction", "Different reconciliation views", "Unexplained difference", "compared_evidence"):
                self.assertIn(phrase, prompt)
        self.assertEqual((config.PROMPT_VERSION, config.TOOLS_PROMPT_VERSION),  # 1.3 / 2.3: 1.2 / 2.2 (schema 1.4, approved) + the full list of refused causal phrases
                         ("uc042-investigator-prompt/1.11", "uc042-investigator-prompt/2.11-tools"))

    def test_rejected_contradiction_is_not_published_through_the_graph(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            def views(packet):
                out = OFFLINE.investigate(packet)[0].model_dump()
                out["contradictory_evidence"] = [contradiction([C08, "C06-DIFFERENCE|2026-09-17/GBP"])]
                return out
            s = run_investigation(PACK["S05"], "EXC-S05-01", ScriptedInvestigator(views), investigations_root=tmp)
            self.assertEqual((s["result"]["validation_status"], s["persist_outcome"]), ("REJECTED", "NOT_PUBLISHED"))
            self.assertEqual(s["result"]["original_exception_status"], "OPEN")
        finally:
            shutil.rmtree(tmp)


# ---------------------------------------------------------------------------------------------------------------
def sha_tree(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(root).rglob("*")) if p.is_file()}


def to_crlf(path):
    """Rewrite a test artefact as a Windows text-mode write would have produced it (the V1-era format)."""
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))


class WriteOnceIntegrity(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def publish(self, investigator=OFFLINE):
        return run_investigation(PACK["SC2"], "EXC-SC2-01", investigator, investigations_root=self.tmp)

    def test_legacy_crlf_artefact_is_never_rewritten_by_an_identical_rerun(self):
        a = self.publish()
        d = Path(a["artefact_path"])
        for name in ("findings.json", "evidence_packet.json", "runs/0001.json"):
            to_crlf(d / name)
        before = sha_tree(d)
        self.assertEqual(verify_published(d), [])
        b = self.publish()
        self.assertEqual(b["persist_outcome"], "ALREADY_PUBLISHED_IDENTICAL")
        after = sha_tree(d)
        self.assertEqual({k: v for k, v in after.items() if k in before}, before)  # every original byte unchanged
        self.assertEqual(sorted(set(after) - set(before)), [os.path.join("runs", "0002.json")])  # only a new run record
        self.assertEqual((d / "findings.json").read_bytes().count(b"\r\n") > 0, True)

    def test_attempted_overwrite_is_refused_and_leaves_bytes_unchanged(self):
        a = self.publish()
        d = Path(a["artefact_path"])
        f = d / "findings.json"
        data = json.loads(f.read_text())
        data["investigation_summary"] = data["investigation_summary"] + " (altered)"
        f.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
        before = sha_tree(d)
        with self.assertRaises(ImmutabilityError):
            self.publish()
        self.assertEqual(sha_tree(d), before)
        self.assertTrue(any("investigation_id" in p for p in verify_published(d)))

    def test_a_new_result_never_touches_existing_artefacts(self):
        a = self.publish()
        before = sha_tree(self.tmp)

        def different(packet):
            out = OFFLINE.investigate(packet)[0].model_dump()
            out["open_questions"] = out["open_questions"] + ["Which bank processing record shows the 16 September booking?"]
            return out
        b = self.publish(ScriptedInvestigator(different))
        self.assertEqual(b["persist_outcome"], "PUBLISHED")
        self.assertNotEqual(a["result"]["investigation_id"], b["result"]["investigation_id"])
        after = sha_tree(self.tmp)
        self.assertEqual({k: v for k, v in after.items() if k in before}, before)

    def test_earlier_schema_artefact_remains_verifiable(self):
        a = self.publish()
        src = Path(a["artefact_path"])
        legacy = json.loads((src / "findings.json").read_text())
        for added_in_v2 in ("investigation_mode", "evidence_ledger_sha256", "tool_summary", "classification_summary"):
            legacy.pop(added_in_v2)
        for c in legacy["contradictory_evidence"]:
            c.pop("compared_evidence"), c.pop("same_measure_and_scope")
        for k in ("investigation_mode", "tool_registry_version"):
            legacy["model_metadata"].pop(k)
        packet = json.loads((src / "evidence_packet.json").read_text())
        legacy["investigation_id"] = investigation_id_from_findings(legacy, packet["packet_sha256"])
        d = self.tmp / "legacy" / legacy["investigation_id"]
        (d / "runs").mkdir(parents=True)
        (d / "findings.json").write_text(json.dumps(legacy, indent=1, sort_keys=True) + "\n")
        shutil.copy(src / "evidence_packet.json", d / "evidence_packet.json")
        shutil.copy(src / "runs" / "0001.json", d / "runs" / "0001.json")
        for name in ("findings.json", "evidence_packet.json"):
            to_crlf(d / name)
        self.assertEqual(verify_published(d), [])
        (d / "evidence_packet.json").write_bytes((d / "evidence_packet.json").read_bytes().replace(b"2868.50", b"2868.51", 1))
        self.assertTrue(any("packet" in p for p in verify_published(d)))

    def test_not_published_records_are_preserved(self):
        s = self.publish(ScriptedInvestigator("not json"))
        rec = Path(s["artefact_path"])
        before = rec.read_bytes()
        self.publish()
        self.publish(ScriptedInvestigator("still not json"))
        self.publish(ScriptedInvestigator("not json"))  # identical failure, possibly in the same second: same base name
        self.assertEqual(rec.read_bytes(), before)
        self.assertEqual(len(list((self.tmp / "_not_published").rglob("*.json"))), 3)
        self.assertEqual(list((self.tmp / "_not_published").rglob(".tmp-*")), [])


if __name__ == "__main__":
    unittest.main()
