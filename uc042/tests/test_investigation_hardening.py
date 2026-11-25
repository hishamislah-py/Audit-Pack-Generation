"""V1 hardening: atomic write-once persistence, run-record numbering, graph error handling and per-exception isolation.
Run from the uc042/ folder: python -m unittest -v. Offline only; artefacts are written to temporary folders."""
import glob
import json
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from uc042lib.investigation import graph, persistence
from uc042lib.investigation.graph import build_graph, run_investigation
from uc042lib.investigation.llm import OfflineSimulatedInvestigator, ScriptedInvestigator
from uc042lib.investigation.persistence import ImmutabilityError, append_run_record
from uc042lib.investigation.run import investigate_pack

ROOT = Path(__file__).resolve().parent.parent
PACK = {os.path.basename(p).split("-")[1]: os.path.basename(p) for p in glob.glob(str(ROOT / "packs" / "PACK-*"))}
OFFLINE = OfflineSimulatedInvestigator()


class TempRoot(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_case(self, scenario="SC2", exception_id="EXC-SC2-01", investigator=OFFLINE):
        return run_investigation(PACK[scenario], exception_id, investigator, investigations_root=self.tmp)

    def leftovers(self):
        return [p for p in self.tmp.rglob(".tmp-*")]


# ---------------------------------------------------------------------------------------------------------------
class AtomicPublication(TempRoot):
    def test_publication_contains_the_run_record(self):
        s = self.run_case()
        d = Path(s["artefact_path"])
        self.assertEqual(s["persist_outcome"], "PUBLISHED")
        self.assertEqual(sorted(p.relative_to(d).as_posix() for p in d.rglob("*")),
                         ["evidence_packet.json", "findings.json", "runs", "runs/0001.json"])
        run = json.loads((d / "runs" / "0001.json").read_text())
        findings = json.loads((d / "findings.json").read_text())
        self.assertEqual((run["outcome"], run["route"]), ("PUBLISHED", findings["investigation_route"]))
        self.assertEqual(json.loads((d / "evidence_packet.json").read_text())["packet_sha256"], findings["evidence_packet_sha256"])
        self.assertEqual(self.leftovers(), [])

    def test_failed_publication_leaves_nothing_and_is_reported(self):
        real_replace = os.replace

        def fail_dir_publish(src, dst):
            if Path(src).is_dir():
                raise PermissionError("simulated storage failure")
            return real_replace(src, dst)
        with mock.patch("uc042lib.investigation.persistence.os.replace", side_effect=fail_dir_publish):
            s = self.run_case()
        self.assertEqual((s["persist_outcome"], s["artefact_path"]), ("PERSIST_FAILED", ""))
        self.assertIn("simulated storage failure", s["persist_error"])
        self.assertEqual(s["result"]["validation_status"], "VALID")  # validated, but not published
        self.assertFalse(list(self.tmp.rglob("findings.json")))
        self.assertEqual(self.leftovers(), [])
        s = self.run_case()  # a later run publishes normally
        self.assertEqual(s["persist_outcome"], "PUBLISHED")

    def test_staging_failure_mid_write_leaves_nothing(self):
        real_write = Path.write_bytes  # artefacts are staged as UTF-8 bytes

        def fail_packet(self_, *a, **k):
            if self_.name == "evidence_packet.json":
                raise OSError("disk full")
            return real_write(self_, *a, **k)
        with mock.patch("pathlib.Path.write_bytes", fail_packet):
            s = self.run_case()
        self.assertEqual(s["persist_outcome"], "PERSIST_FAILED")
        self.assertFalse(list(self.tmp.rglob("findings.json")))
        self.assertEqual(self.leftovers(), [])

    def test_lost_publication_race_is_treated_as_identical_rerun(self):
        first = self.run_case()
        target = Path(first["artefact_path"])
        with mock.patch.object(Path, "exists", lambda p: False if p == target else os.path.exists(p)):
            s = self.run_case()  # believes the target is free; the rename then fails because it exists
        self.assertEqual(s["persist_outcome"], "ALREADY_PUBLISHED_IDENTICAL")
        self.assertEqual(sorted(p.name for p in (target / "runs").iterdir()), ["0001.json", "0002.json"])
        self.assertEqual(self.leftovers(), [])

    def test_identical_rerun_and_immutability(self):
        a, b = self.run_case(), self.run_case()
        self.assertEqual((a["persist_outcome"], b["persist_outcome"]), ("PUBLISHED", "ALREADY_PUBLISHED_IDENTICAL"))
        runs = Path(a["artefact_path"]) / "runs"
        self.assertEqual([json.loads(p.read_text())["outcome"] for p in sorted(runs.glob("*.json"))],
                         ["PUBLISHED", "ALREADY_PUBLISHED_IDENTICAL"])
        f = Path(a["artefact_path"]) / "findings.json"
        f.write_text(f.read_text().replace("COMPLETED", "COMPLETED ", 1))
        with self.assertRaises(ImmutabilityError):
            self.run_case()

    def test_failed_and_rejected_are_never_published_as_valid(self):
        def promoted(packet):
            d = OFFLINE.investigate(packet)[0].model_dump()
            d["confirmed_findings"][0]["evidence_ids"].append("CAND-SC5A-01")
            return d
        s = self.run_case("SC5A", "EXC-SC5A-01", ScriptedInvestigator(promoted))
        self.assertEqual((s["result"]["validation_status"], s["persist_outcome"]), ("REJECTED", "NOT_PUBLISHED"))
        s = self.run_case("SC2", "EXC-SC2-01", ScriptedInvestigator("not json"))
        self.assertEqual((s["result"]["investigation_status"], s["persist_outcome"]), ("FAILED", "NOT_PUBLISHED"))
        self.assertEqual([p.parent.name for p in self.tmp.rglob("findings.json")], [])
        stored = [json.loads(p.read_text())["result"] for p in (self.tmp / "_not_published").rglob("*.json")]
        self.assertEqual(sorted(r["validation_status"] for r in stored), ["NOT_VALIDATED", "REJECTED"])
        self.assertTrue(all(r["investigation_id"] == "" for r in stored))


class RunRecordNumbering(unittest.TestCase):
    def setUp(self):
        self.runs = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.runs)

    def test_gap_or_stale_count_never_overwrites(self):
        (self.runs / "0002.json").write_text("existing")
        p = append_run_record(self.runs, "new")
        self.assertEqual(p.name, "0003.json")
        self.assertEqual((self.runs / "0002.json").read_text(), "existing")

    def test_concurrent_writers_get_distinct_numbers(self):
        barrier = threading.Barrier(8)

        def worker(i):
            barrier.wait()
            append_run_record(self.runs, json.dumps({"writer": i}))
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        files = sorted(self.runs.glob("*.json"))
        self.assertEqual([p.name for p in files], [f"{n:04d}.json" for n in range(1, 9)])
        self.assertEqual(sorted(json.loads(p.read_text())["writer"] for p in files), list(range(8)))
        self.assertEqual(list(self.runs.glob(".tmp-*")), [])


# ---------------------------------------------------------------------------------------------------------------
class GraphErrorHandling(TempRoot):
    def test_error_routes_exist_for_every_pre_model_stage(self):
        edges = {(e.source, e.target) for e in build_graph().get_graph().edges}
        for src in ("load_investigation_case", "identify_investigation_scope", "route_investigation", "build_evidence_packet",
                    "retrieve_bank_ledger_mismatch", "retrieve_generic"):
            self.assertIn((src, "validate_findings"), edges, src)

    def test_unexpected_exceptions_become_failed_results_and_are_logged(self):
        for target, stage in (("build_scope", "identify_investigation_scope"), ("route_for", "route_investigation"),
                              ("build_packet", "build_evidence_packet"), ("retrieve", "retrieve_bank_ledger_mismatch")):
            with self.subTest(stage=stage), mock.patch.object(graph, target, side_effect=ZeroDivisionError("boom")), \
                    self.assertLogs("uc042.investigation", level="ERROR") as logs:
                s = self.run_case()
            r = s["result"]
            self.assertEqual((r["investigation_status"], r["validation_status"], s["persist_outcome"]),
                             ("FAILED", "NOT_VALIDATED", "NOT_PUBLISHED"))
            self.assertEqual(r["failure_reason"], f"{stage}: unexpected error: ZeroDivisionError: boom")
            self.assertEqual((r["original_exception_status"], r["exception_resolution"]), ("OPEN", "NOT_RESOLVED_BY_INVESTIGATION"))
            self.assertTrue(any("Traceback" in line and stage in line for line in logs.output))

    def test_unexpected_investigator_exception(self):
        class Broken:
            provider, model, simulated = "broken", "x", True

            def investigate(self, packet):
                raise RuntimeError("adapter bug")
        with self.assertLogs("uc042.investigation", level="ERROR"):
            s = self.run_case(investigator=Broken())
        self.assertIn("ai_investigation: unexpected error: RuntimeError: adapter bug", s["result"]["failure_reason"])

    def test_unexpected_validation_error_is_contained(self):
        with mock.patch.object(graph, "validate_output", side_effect=KeyError("allowed_citation_ids")), \
                self.assertLogs("uc042.investigation", level="ERROR"):
            s = self.run_case()
        self.assertEqual((s["result"]["investigation_status"], s["persist_outcome"]), ("FAILED", "NOT_PUBLISHED"))


class PerExceptionIsolation(TempRoot):
    def test_one_crashing_exception_does_not_stop_the_others(self):
        real = run_investigation

        def flaky(pack_id, eid, *a, **k):
            if eid == "EXC-SC3C-02":
                raise ImmutabilityError("simulated tampered artefact")
            return real(pack_id, eid, *a, **k)
        with mock.patch("uc042lib.investigation.run.run_investigation", flaky), \
                self.assertLogs("uc042.investigation", level="ERROR"):
            s = investigate_pack(PACK["SC3C"], OFFLINE, investigations_root=self.tmp)
        by = {r["exception_id"]: r for r in s["investigations"]}
        self.assertEqual(sorted(by), ["EXC-SC3C-01", "EXC-SC3C-02", "EXC-SC3C-03"])
        self.assertEqual((by["EXC-SC3C-02"]["investigation_status"], by["EXC-SC3C-02"]["persist_outcome"]), ("FAILED", "NOT_PERSISTED"))
        self.assertIn("ImmutabilityError", by["EXC-SC3C-02"]["failure_reason"])
        for eid in ("EXC-SC3C-01", "EXC-SC3C-03"):
            self.assertEqual((by[eid]["validation_status"], by[eid]["persist_outcome"]), ("VALID", "PUBLISHED"))
        self.assertTrue(all(r["original_exception_status"] == "OPEN" for r in by.values()))

    def test_every_scenario_publishes_offline(self):
        for sc, pid in sorted(PACK.items()):
            for r in investigate_pack(pid, OFFLINE, investigations_root=self.tmp)["investigations"]:
                self.assertEqual((r["validation_status"], r["persist_outcome"], r["simulated"]), ("VALID", "PUBLISHED", True), (sc, r))
        self.assertEqual(self.leftovers(), [])


if __name__ == "__main__":
    unittest.main()
