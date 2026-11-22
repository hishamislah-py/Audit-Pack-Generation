"""Monthly document management (Phase 4): reconciliation periods, the archive, uploads with content identification, date
and duplicate checks, analyst decisions, confirmation and processing into a new write-once pack.

Every test runs on temporary folders: a COPY of two real packs as the packs root, an empty document store, a temporary
SQLite database (or the disposable PostgreSQL test database with UC042_TEST_REPOSITORIES=postgres). Uploaded files are
read from uc042_dataset/ (source_data/ and supporting_documents/ only) and sent as uploads; the dataset is never written.
Offline: the AI provider is mocked."""
import io
import shutil
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from tests.api_support import AI_OK, ROOT, TEST_REPOSITORIES, ApiCase, test_database_url
from tests.final_pack_support import OFFLINE, sha_tree
from uc042lib.pack.generate import build as build_pack

DATASETS = ROOT / "uc042_dataset"
S05 = DATASETS / "scn_S05_unexplained_gbp_difference"
S05_PACK = next((ROOT / "packs").glob("PACK-S05-*")).name
SC2_PACK = next((ROOT / "packs").glob("PACK-SC2-*")).name
CONTROLLED = ("answer_key.json", "mutations.json", "SCENARIO_NOTES.md", "scenario.json")


def scenario_files(dataset=S05, skip=()):
    files = sorted((dataset / "source_data").glob("*.csv")) + sorted((dataset / "supporting_documents").glob("*.pdf"))
    return [(p.name, p.read_bytes()) for p in files if p.name not in skip]


class MonthlyCase(ApiCase):
    # The individual-document workflow is retired from active use (ZIP-only operation, 17 Nov 2026); these regression tests
    # keep covering its shared engine path on historical-style data, so they opt in explicitly (never possible from the
    # environment). ZIP submission tests set this to False and prove the retired entry points refuse.
    LEGACY_ENTRY_POINTS = True

    @classmethod
    def setUpClass(cls):
        cls.dataset_before = sha_tree(DATASETS)
        cls.packs_before = sha_tree(ROOT / "packs")

    @classmethod
    def tearDownClass(cls):
        assert sha_tree(DATASETS) == cls.dataset_before, "a dataset file changed"
        assert sha_tree(ROOT / "packs") == cls.packs_before, "a real pack changed"

    def setUp(self):
        super().setUp()
        self.stop_app()
        self.packs_root = self.tmp / "packs"
        for pack in (S05_PACK, SC2_PACK):
            shutil.copytree(ROOT / "packs" / pack, self.packs_root / pack)
        url = test_database_url(self.tmp) if TEST_REPOSITORIES == "postgres" else f"sqlite:///{(self.tmp / 'm.db').as_posix()}"
        self.settings = self.settings.with_(packs_root=self.packs_root, document_store=self.tmp / "docs", database_url=url,
                                            legacy_entry_points=self.LEGACY_ENTRY_POINTS)
        self.start_app()

    # ------------------------------------------------------------------ helpers
    def upload(self, period_id, files, expect=201):
        r = self.client.post(f"/api/v1/periods/{period_id}/uploads",
                             files=[("files", (name, io.BytesIO(data), "application/octet-stream")) for name, data in files])
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    def open_period(self, year, month):
        r = self.post("/api/v1/periods", {"year": year, "month": month})
        self.assertIn(r.status_code, (200, 201), r.text)
        return r.json()

    def docs_by_name(self, batch):
        return {d["original_filename"]: d for d in batch["documents"]}

    def codes(self, doc):
        return {m["code"] for m in doc["checks"]["messages"]}

    def process(self, batch_id, expect=202):
        r = self.post(f"/api/v1/uploads/{batch_id}/process")
        self.assertEqual(r.status_code, expect, r.text)
        run = r.json()
        if run.get("job_id"):
            self.svc.runner.wait(run["job_id"], timeout=180)
            run = self.get(f"/api/v1/processing-runs/{run['run_id']}").json()
        return run


class Archive(MonthlyCase):
    def test_september_is_registered_from_the_packs_as_scenarios_of_one_month(self):
        periods = self.get("/api/v1/periods").json()
        self.assertEqual([p["period_id"] for p in periods], ["PER-2026-09"])  # no other month is invented
        sep = periods[0]
        self.assertEqual(sep["archive_state"], "RESULTS_NO_FINAL_PACK")
        self.assertTrue(sep["scenario_packs"])
        self.assertEqual(sorted(p["pack_id"] for p in sep["packs"]), sorted([S05_PACK, SC2_PACK]))
        self.assertTrue(all(p["origin"] == "POC_SCENARIO" for p in sep["packs"]))
        self.assertEqual(sep["exceptions_total"], sum(p["exceptions_total"] for p in sep["packs"]))

    def test_open_a_month_creates_an_empty_period_only(self):
        today = date.today()
        p = self.open_period(today.year, today.month)
        self.assertEqual((p["archive_state"], p["document_count"], p["pack_count"]), ("AWAITING_UPLOAD", 0, 0))
        again = self.post("/api/v1/periods", {"year": today.year, "month": today.month})
        self.assertEqual(again.status_code, 200)
        future = (today.year + 1, today.month)
        r = self.post("/api/v1/periods", {"year": future[0], "month": future[1]})
        self.assertEqual((r.status_code, r.json()["code"]), (422, "FUTURE_PERIOD"))
        self.assertEqual(self.get("/api/v1/periods/PER-2026-13").json()["code"], "INVALID_ID")
        self.assertEqual(self.get("/api/v1/periods/PER-2025-01").status_code, 404)

    def test_poc_scenario_documents_are_registered_in_place_without_controlled_files(self):
        rows = self.svc.monthly.import_poc_documents()
        self.assertEqual({r["pack_id"] for r in rows}, {S05_PACK, SC2_PACK})
        self.assertFalse(any(r["problems"] for r in rows))
        self.assertEqual(self.svc.monthly.import_poc_documents(), [])  # idempotent
        detail = self.get("/api/v1/periods/PER-2026-09").json()
        self.assertEqual(detail["current_set"], {})  # archive records of the scenarios, never a processing set
        names = {d["original_filename"] for d in detail["documents"]}
        self.assertFalse(names & set(CONTROLLED))
        self.assertTrue(all(d["storage_kind"] == "POC_DATASET" for d in detail["documents"]))
        d = next(d for d in detail["documents"] if d["evidence_id"] == "IN-09")
        content = self.get(f"/api/v1/documents/{d['document_id']}/content")
        self.assertEqual(content.headers["X-Content-SHA256"], d["sha256"])
        text = self.get("/api/v1/periods/PER-2026-09").text
        self.assertNotIn("dataset:", text)
        self.assertNotIn(str(self.tmp).replace("\\", "\\\\"), text)

    def test_monthly_endpoints_need_the_database(self):
        self.stop_app()
        self.settings = self.settings.with_(database_url=None)
        self.start_app()
        r = self.get("/api/v1/periods")
        self.assertEqual((r.status_code, r.json()["code"]), (503, "DATABASE_REQUIRED"))
        self.assertIsNone(self.get("/health").json()["database"])


class Upload(MonthlyCase):
    def test_complete_september_upload_is_identified_and_valid(self):
        b = self.upload("PER-2026-09", scenario_files())
        docs = b["documents"]
        self.assertEqual(len(docs), 19)
        self.assertEqual(sorted(d["evidence_id"] for d in docs), sorted(f"IN-{i:02d}" for i in range(1, 20)))
        letters = [d for d in docs if d["original_filename"].startswith("ack_letter")]
        self.assertTrue(all(d["checks"].get("slot_resolved_by") for d in letters))
        self.assertEqual(b["batch"]["summary"]["missing_required"], [])
        self.assertIn(b["batch"]["validation_status"], ("VALID", "WARNINGS"))
        self.assertFalse([d for d in docs if d["validation_status"] == "ERROR"])
        pdf = next(d for d in docs if d["evidence_id"] == "IN-17")
        self.assertEqual((pdf["file_format"], pdf["storage_kind"]), ("PDF", "UPLOADED_ORIGINAL"))
        self.assertIn("PDF_STORED_AS_ORIGINAL", self.codes(pdf))
        cashbook = next(d for d in docs if d["evidence_id"] == "IN-10")
        self.assertIn("BOUNDARY_RECORDS", self.codes(cashbook))
        self.assertEqual(cashbook["checks"]["dates"]["posted_ts"]["role"], "Cash-book posting timestamp")

    def test_september_documents_uploaded_for_october_are_wrong_period_and_never_moved(self):
        self.open_period(2026, 10)
        b = self.upload("PER-2026-10", scenario_files())
        docs = {d["evidence_id"]: d for d in b["documents"]}
        for fid in ("IN-01", "IN-05", "IN-09", "IN-11"):
            self.assertEqual(docs[fid]["validation_status"], "ERROR", fid)
            self.assertIn("WRONG_PERIOD", self.codes(docs[fid]))
        self.assertEqual(docs["IN-09"]["date_from"][:7], "2026-09")  # the detected range is reported as found
        self.assertIn("IN-01", b["batch"]["summary"]["missing_required"])
        self.assertEqual(b["batch"]["validation_status"], "INCOMPLETE")
        self.assertEqual(self.get("/api/v1/periods/PER-2026-09").json()["documents"], [])  # nothing moved to September
        errors = {d["document_id"] for d in b["documents"] if d["validation_status"] == "ERROR"}
        self.assertFalse(errors & set(b["batch"]["summary"]["decisions_pending"]))  # never processed, so no decision needed

    def test_partial_out_of_period_rows_and_timing_differences(self):
        src = (S05 / "source_data" / "bank_statement_entries_2026-09.csv").read_text(encoding="utf-8").splitlines()
        header, rows = src[0], src[1:]
        cols = header.split(",")
        bi, vi = cols.index("booking_date"), cols.index("value_date")
        r0 = rows[0].split(",")
        r0[bi] = "2026-10-02"
        r1 = rows[1].split(",")
        r1[vi] = "2026-10-01"
        r2 = rows[2].split(",")
        r2[bi] = "2026-02-30"
        dup = rows[3]
        data = "\n".join([header, ",".join(r0), ",".join(r1), ",".join(r2), *rows[3:], dup]) + "\n"
        b = self.upload("PER-2026-09", [("entries.csv", data.encode())])
        d = b["documents"][0]
        codes = self.codes(d)
        self.assertEqual(d["evidence_id"], "IN-09")
        self.assertTrue({"OUT_OF_PERIOD_RECORDS", "INVALID_DATE", "TIMING_DIFFERENCE", "REPEATED_RECORD_ID"} <= codes, codes)
        self.assertEqual(d["validation_status"], "WARNING")
        timing = next(m for m in d["checks"]["messages"] if m["code"] == "TIMING_DIFFERENCE")
        self.assertEqual((timing["level"], timing["column"]), ("INFO", "value_date"))

    def test_invalid_and_empty_files_are_kept_as_error_documents(self):
        b = self.upload("PER-2026-09", [("notes.txt", b"hello, world\n1,2\n"), ("empty.csv", b""),
                                        ("fake.pdf", b"%PDF-1.4 not really"), ("calendar.csv", (S05 / "source_data" / "recon_calendar_2026-09.csv").read_bytes())])
        docs = self.docs_by_name(b)
        self.assertEqual(docs["empty.csv"]["validation_status"], "ERROR")
        self.assertIn("EMPTY_FILE", self.codes(docs["empty.csv"]))
        self.assertIn("UNRECOGNISED", self.codes(docs["notes.txt"]))
        self.assertIn("UNRECOGNISED", self.codes(docs["fake.pdf"]))
        self.assertEqual(docs["calendar.csv"]["evidence_id"], "IN-01")
        self.assertEqual(b["batch"]["validation_status"], "INCOMPLETE")
        for d in b["documents"]:  # no data loss: every original is retrievable, byte for byte
            r = self.get(f"/api/v1/documents/{d['document_id']}/content")
            self.assertEqual((r.status_code, r.headers["X-Content-SHA256"]), (200, d["sha256"]))
        bad = self.upload("PER-2026-09", [("x.txt", b"nothing")])
        self.assertEqual(bad["batch"]["validation_status"], "INVALID")
        self.assertEqual(self.post(f"/api/v1/uploads/{bad['batch']['batch_id']}/confirm").json()["code"], "BATCH_INVALID")
        self.assertEqual(self.client.post("/api/v1/periods/PER-2026-09/uploads").status_code, 422)  # no files

    def test_duplicate_in_batch_needs_a_decision_before_confirmation(self):
        files = scenario_files()
        files.append(("copy_of_" + files[0][0], files[0][1]))
        b = self.upload("PER-2026-09", files)
        copy = self.docs_by_name(b)["copy_of_" + files[0][0]]
        self.assertIn("DUPLICATE_IN_BATCH", self.codes(copy))
        self.assertTrue(copy["checks"]["decision_required"])
        batch_id = b["batch"]["batch_id"]
        r = self.post(f"/api/v1/uploads/{batch_id}/confirm")
        self.assertEqual((r.status_code, r.json()["code"]), (409, "DECISIONS_PENDING"))
        self.assertEqual(self.post(f"/api/v1/uploads/{batch_id}/process").json()["code"], "BATCH_NOT_CONFIRMED")
        r = self.post(f"/api/v1/documents/{copy['document_id']}/review", {"decision": "EXCLUDE", "comment": ""})
        self.assertEqual(r.status_code, 422)
        r = self.post(f"/api/v1/documents/{copy['document_id']}/review", {"decision": "EXCLUDE", "comment": "Same file twice"})
        self.assertEqual((r.json()["review_decision"], r.json()["reviewed_by"]), ("EXCLUDE", "analyst-1"))
        confirmed = self.post(f"/api/v1/uploads/{batch_id}/confirm").json()
        self.assertEqual(confirmed["batch"]["status"], "CONFIRMED")
        self.assertEqual(len(confirmed["documents"]), 20)  # the excluded copy is kept, not deleted
        r = self.post(f"/api/v1/documents/{copy['document_id']}/review", {"decision": "INCLUDE", "comment": "changed my mind"})
        self.assertEqual(r.json()["code"], "BATCH_CONFIRMED")

    def test_repeat_upload_and_same_name_with_different_content(self):
        first = self.upload("PER-2026-09", scenario_files(skip=()))
        self.post(f"/api/v1/uploads/{first['batch']['batch_id']}/confirm")
        name = "transactions_2026-09.csv"
        original = (S05 / "source_data" / name).read_bytes()
        changed = original.rstrip(b"\n") + b"\n"  # identical rows, different bytes: header line ending changed
        changed = changed.replace(b"\n", b"\r\n")
        second = self.upload("PER-2026-09", [(name, changed), ("account_inventory.csv",
                                                               (S05 / "source_data" / "account_inventory.csv").read_bytes())])
        docs = self.docs_by_name(second)
        self.assertIn("SAME_NAME_DIFFERENT_CONTENT", self.codes(docs[name]))
        self.assertIn("NEW_VERSION", self.codes(docs[name]))
        overlap = next(m for m in docs[name]["checks"]["messages"] if m["code"] == "NEW_VERSION")
        self.assertGreater(overlap["overlapping_ids"], 0)
        self.assertIn("DUPLICATE_OF_EARLIER_UPLOAD", self.codes(docs["account_inventory.csv"]))
        first_doc = next(d for d in first["documents"] if d["original_filename"] == name)
        self.assertEqual(self.get(f"/api/v1/documents/{first_doc['document_id']}/content").content, original)  # not overwritten
        self.assertNotEqual(docs[name]["sha256"], first_doc["sha256"])

    def test_missing_categories_block_processing(self):
        b = self.upload("PER-2026-09", scenario_files(skip=("transactions_2026-09.csv", "safeguarding_reconciliation_policy_v1.2.pdf")))
        self.assertEqual(sorted(b["batch"]["summary"]["missing_required"]), ["IN-11", "IN-17"])
        self.assertEqual(b["batch"]["validation_status"], "INCOMPLETE")
        self.post(f"/api/v1/uploads/{b['batch']['batch_id']}/confirm")
        r = self.post(f"/api/v1/uploads/{b['batch']['batch_id']}/process")
        self.assertEqual((r.status_code, r.json()["code"]), (409, "INCOMPLETE"))
        self.assertEqual(self.get(f"/api/v1/uploads/{b['batch']['batch_id']}").json()["runs"], [])


class Processing(MonthlyCase):
    def confirmed_september(self):
        b = self.upload("PER-2026-09", scenario_files())
        self.post(f"/api/v1/uploads/{b['batch']['batch_id']}/confirm")
        return b["batch"]["batch_id"]

    def test_processing_produces_a_new_verified_pack_matching_the_engine(self):
        batch_id = self.confirmed_september()
        run = self.process(batch_id)  # the application always runs the engine under the approved rules
        self.assertEqual(run["status"], "SUCCEEDED", run)
        self.assertEqual(run["result"]["outcome"], "PUBLISHED")
        pack_id = run["result"]["pack_id"]
        self.assertTrue((self.packs_root / pack_id / "pack.json").is_file())
        new = self.get(f"/api/v1/packs/{pack_id}").json()
        original = self.get(f"/api/v1/packs/{S05_PACK}").json()
        self.assertEqual(new["summary"]["exceptions"], original["summary"]["exceptions"])  # the same inputs, the same exceptions
        status, engine_pack, _, _, _ = build_pack(S05)  # the engine's own result for the same inputs (approved rules)
        self.assertEqual(status, "GENERATED")
        self.assertEqual(new["summary"]["outcomes"], self.svc.packs.summary(engine_pack)["outcomes"])
        # the stored S05 pack was published under the pre-17-Nov rule (zero difference NOT_APPLICABLE); the only approved
        # difference is that outcome becoming PASS on zero-difference days: every other value is identical
        def approved(rows):
            return [dict(r, difference_outcome="PASS") if r.get("difference_outcome") == "NOT_APPLICABLE"
                    and r.get("difference") == "0.00" and r.get("difference_reported") == "0.00" else r for r in rows]
        new_rows = self.get(f"/api/v1/packs/{pack_id}/reconciliation").json()["internal_by_currency_day"]
        stored_rows = self.get(f"/api/v1/packs/{S05_PACK}/reconciliation").json()["internal_by_currency_day"]
        self.assertEqual(new_rows, approved(stored_rows))
        self.assertNotEqual(new_rows, stored_rows)  # the approved rule is in effect
        period = self.get("/api/v1/periods/PER-2026-09").json()
        ref = next(p for p in period["period"]["packs"] if p["pack_id"] == pack_id)
        self.assertEqual((ref["origin"], ref["processing_run_id"]), ("UPLOAD_PROCESSING", run["run_id"]))
        self.assertEqual(self.get(f"/api/v1/uploads/{batch_id}").json()["batch"]["status"], "PROCESSED")
        exc = self.get(f"/api/v1/packs/{pack_id}/exceptions").json()
        self.assertTrue(exc and all(x["status"] != "RESOLVED" for x in exc))  # nothing is auto-resolved
        self.assertEqual(self.svc.investigations.datasets_root_for(pack_id), self.tmp / "docs" / "cases")
        case = self.tmp / "docs" / "cases" / run["result"]["case"]
        self.assertFalse([p.name for p in case.rglob("*") if p.name in CONTROLLED])

        # Retry: a new run; the identical pack is left untouched (write-once), the first run's record is unchanged.
        before = sha_tree(self.packs_root / pack_id)
        retry = self.process(batch_id)  # identical inputs and rules: the identical pack
        self.assertNotEqual(retry["run_id"], run["run_id"])
        self.assertEqual((retry["status"], retry["result"]["outcome"], retry["result"]["pack_id"]), ("SUCCEEDED", "ALREADY_EXISTS", pack_id))
        self.assertEqual(sha_tree(self.packs_root / pack_id), before)
        self.assertEqual(self.get(f"/api/v1/processing-runs/{run['run_id']}").json(), run)

    def test_failed_build_is_reported_as_failed_and_publishes_nothing(self):
        batch_id = self.confirmed_september()
        with mock.patch("uc042app.services.monthly.build", return_value=("FAILED", None, None, None, ["ASSEMBLY: simulated"])):
            run = self.process(batch_id)
        self.assertEqual(run["status"], "FAILED")
        self.assertIn("could not be generated", run["error"])
        self.assertEqual(sorted(p.name for p in self.packs_root.iterdir()), sorted([S05_PACK, SC2_PACK]))
        self.assertEqual(self.get(f"/api/v1/uploads/{batch_id}").json()["batch"]["status"], "PROCESSING_FAILED")
        job = self.get(f"/api/v1/jobs/{run['job_id']}").json()
        self.assertEqual((job["operation"], job["status"]), ("PROCESSING", "FAILED"))
        retry = self.process(batch_id)
        self.assertEqual(retry["status"], "SUCCEEDED")
        self.assertEqual(self.get(f"/api/v1/processing-runs/{run['run_id']}").json()["status"], "FAILED")  # history kept

    def test_other_months_use_the_same_engine_subject_to_their_own_inputs(self):
        self.open_period(2026, 10)
        detail = self.get("/api/v1/periods/PER-2026-10").json()
        self.assertTrue(detail["processing_supported"])
        self.assertIsNone(detail["processing_limitation"])
        self.assertIn("(September)", detail["evidence_types"]["IN-19"])  # October's return receipt is September's
        # September's files are wrong-period for October: never used, so October's required evidence is missing
        b = self.upload("PER-2026-10", scenario_files())
        self.post(f"/api/v1/uploads/{b['batch']['batch_id']}/confirm")
        r = self.post(f"/api/v1/uploads/{b['batch']['batch_id']}/process")
        self.assertEqual((r.status_code, r.json()["code"]), (409, "INCOMPLETE"))
        self.assertIn("IN-01", r.json()["missing"])
        self.assertEqual(self.get(f"/api/v1/uploads/{b['batch']['batch_id']}").json()["runs"], [])  # no run, no pack

    def test_the_selected_period_is_passed_to_preparation_and_generation(self):
        from uc042lib.period import PeriodConfig
        import uc042app.services.monthly as monthly
        seen = []
        real_prepare, real_build = monthly.prepare_case, monthly.build
        with mock.patch.object(monthly, "prepare_case", side_effect=lambda i, c, p: seen.append(("prepare", p)) or real_prepare(i, c, p)),                 mock.patch.object(monthly, "build", side_effect=lambda c, p: seen.append(("build", p)) or real_build(c, p)):
            run = self.process(self.confirmed_september())
        self.assertEqual(run["status"], "SUCCEEDED", run)
        self.assertEqual(seen, [("prepare", PeriodConfig(2026, 9)), ("build", PeriodConfig(2026, 9))])
        self.assertEqual(run["result"]["continuity"]["status"], "NOT_VERIFIABLE")  # no August period: nothing assumed
        self.assertEqual(run["result"]["continuity"]["previous_period"], "PER-2026-08")

    def test_interrupted_run_is_marked_on_restart_and_never_rerun(self):
        batch_id = self.confirmed_september()
        repos = self.svc.monthly.repos
        repos.runs.create({"run_id": "RUN-" + "0" * 24, "period_id": "PER-2026-09", "batch_id": batch_id, "job_id": None,
                           "status": "RUNNING", "started_at": "2026-11-03T10:00:00+00:00", "completed_at": None, "error": "",
                           "result": {}, "created_at": "2026-11-03T10:00:00+00:00", "created_by": "analyst-1"})
        self.restart()
        run = self.get("/api/v1/processing-runs/RUN-" + "0" * 24).json()
        self.assertEqual(run["status"], "INTERRUPTED")
        self.assertEqual(self.get(f"/api/v1/uploads/{batch_id}").json()["batch"]["status"], "PROCESSING_FAILED")
        self.assertEqual(sorted(p.name for p in self.packs_root.iterdir()), sorted([S05_PACK, SC2_PACK]))  # not re-run


class AnalystWorkflow(MonthlyCase):
    """The full analyst workflow on uploaded documents, OpenAI mocked: archive -> upload -> validation -> duplicate decision ->
    confirm -> processing -> new pack -> exceptions -> AI investigation -> review -> preview -> HOLD -> preview -> GENERATE."""

    def investigation_output_for(self, pack_id, exc_id):
        from uc042lib.investigation.models import LLMInvestigationOutput
        from uc042lib.investigation.packet import build_case, build_packet, build_scope, retrieve
        from uc042lib.investigation.retrieval import EvidenceStore, load_pack
        from uc042lib.investigation.routing import route_for
        pack = load_pack(pack_id, self.packs_root)
        case = build_case(pack, exc_id)
        route = route_for(case["exception"], case["candidates"], case["results"])
        store = EvidenceStore(pack, self.svc.investigations.datasets_root_for(pack_id))
        out = OFFLINE.investigate(build_packet(case, build_scope(case), route, retrieve(route, case, store)))[0].model_dump()
        out["investigation_summary"] = "The records show the engine's reported difference; the cause is not established."
        for f in out["confirmed_findings"]:
            f.update(audit_relevance="The engine result is part of this exception.",
                     establishes="The engine reported this outcome with the quoted values.",
                     does_not_establish="Why the difference arose is not established.")
        for h in out["hypotheses"]:
            h["rationale"] = "A coincidence of date and amount was recorded."
        return LLMInvestigationOutput.model_validate(out)

    def test_upload_to_final_pack(self):
        # 1-2. The archive shows September (scenarios); the analyst uploads the month's documents (one file twice).
        self.assertEqual([p["period_id"] for p in self.get("/api/v1/periods").json()], ["PER-2026-09"])
        files = scenario_files()
        files.append(("copy_" + files[1][0], files[1][1]))
        b = self.upload("PER-2026-09", files)
        batch_id = b["batch"]["batch_id"]
        # 3. Validation: everything identified, nothing missing, one duplicate awaiting a decision.
        self.assertEqual(b["batch"]["summary"]["missing_required"], [])
        dup = self.docs_by_name(b)["copy_" + files[1][0]]
        self.assertEqual(b["batch"]["summary"]["decisions_pending"], [dup["document_id"]])
        # 4-5. Decision with a comment, then confirmation.
        self.post(f"/api/v1/documents/{dup['document_id']}/review", {"decision": "EXCLUDE", "comment": "Uploaded twice by mistake"})
        self.assertEqual(self.post(f"/api/v1/uploads/{batch_id}/confirm").json()["batch"]["status"], "CONFIRMED")
        # 6-7. Processing produces a new, verified pack (no final pack is published by processing) and, mandatorily,
        # queues an AI investigation of every exception of it (here the provider is unreachable: each attempt fails,
        # with its reason, and is left unpublished).
        import httpx2
        import openai
        self.provider.error = openai.APIConnectionError(request=httpx2.Request("POST", "https://api.openai.com/v1/responses"))
        run = self.process(batch_id)
        self.assertEqual(run["status"], "SUCCEEDED", run)
        pack_id = run["result"]["pack_id"]
        auto = run["result"]["auto_investigation"]
        self.assertEqual(auto["status"], "ENQUEUED", auto)
        for i in auto["items"]:
            self.assertEqual(self.wait_job(i["job_id"])["status"], "FAILED")
        self.provider.error = None
        failed = {i["exception_id"]: i["job_id"] for i in auto["items"]}
        self.assertEqual(list((self.tmp / "final_packs").glob("FAP-*")) if (self.tmp / "final_packs").is_dir() else [], [])
        # 8. The archive shows the period with results and no final pack yet.
        sep = self.get("/api/v1/periods/PER-2026-09").json()["period"]
        self.assertEqual(sep["archive_state"], "RESULTS_NO_FINAL_PACK")
        self.assertIn(pack_id, [p["pack_id"] for p in sep["packs"]])
        # 9. Exceptions of the new pack, all unresolved.
        exc = self.get(f"/api/v1/packs/{pack_id}/exceptions").json()
        self.assertTrue(exc)
        self.assertEqual(sorted(failed), sorted(x["exception_id"] for x in exc))  # every exception was attempted
        exc_id = exc[0]["exception_id"]
        # 10. The explicit retry of one (OpenAI mocked) reads the run's prepared case and is published and eligible.
        self.provider.output = self.investigation_output_for(pack_id, exc_id)
        job = self.post(f"/api/v1/packs/{pack_id}/exceptions/{exc_id}/investigations",
                        {"mode": "tools", "authorization": AI_OK, "retry_of": failed[exc_id]}).json()
        job = self.wait_job(job["job_id"])
        self.assertEqual((job["status"], job["result"]["persist_outcome"]), ("COMPLETED", "PUBLISHED"), job)
        rows = self.get(f"/api/v1/packs/{pack_id}/exceptions/{exc_id}/investigations").json()["published"]
        self.assertTrue(rows[0]["eligible"], rows)
        findings = self.get(f"/api/v1/investigations/{rows[0]['investigation_id']}/findings").json()
        self.assertTrue(all(h.get("status", "HYPOTHESIS") != "CONFIRMED" for h in findings.get("hypotheses", [])))
        self.accept_investigation(rows[0]["investigation_id"])  # the analyst's ACCEPT in the Exception Workspace
        # 11-12. Final review: preview, then HOLD (publishes nothing).
        r = self.post(f"/api/v1/packs/{pack_id}/reviews")
        self.assertIn(r.status_code, (200, 201), r.text)
        s = r.json()
        others = [x["exception_id"] for x in exc[1:]]
        # a failed investigation is never reported as "not investigated": it blocks until retried or excluded with a reason
        self.assertEqual(sorted(b["detail"].split(":")[0] for b in s["readiness"]["blockers"] if b["code"] == "INVESTIGATION_FAILED_NO_DISPOSITION"),
                         sorted(others))
        sel = [x if x["exception_id"] == exc_id else {"exception_id": x["exception_id"], "inclusion": "EXCLUDED_BY_ANALYST",
                                                      "reason": "AI investigation failed: provider unreachable; reported from the deterministic results"}
               for x in s["selections"]]
        r = self.patch(f"/api/v1/reviews/{s['review_id']}/selections", {"selections": sel, "expected_revision": s["revision"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["readiness"]["checklist"]["counts"]["excluded"], len(others))
        s = self.preview(s["review_id"])
        held = self.post(f"/api/v1/reviews/{s['review_id']}/decision", {"decision": "HOLD", "comment": "Waiting for the bank trace."})
        self.assertEqual(held.json()["session_status"], "ON_HOLD")
        self.assertFalse((self.tmp / "final_packs").is_dir() and list((self.tmp / "final_packs").glob("FAP-*")))
        # 13-14. A new preview, then the explicit GENERATE: the only step that publishes a final pack.
        s = self.preview(s["review_id"])
        g = self.post(f"/api/v1/reviews/{s['review_id']}/decision", {"decision": "GENERATE", "acknowledgement_accepted": True,
                                                                     "snapshot_sha256": s["current_preview"]["snapshot_sha256"],
                                                                     "comment": "Reviewed the preview."})
        self.assertEqual(g.status_code, 201, g.text)
        fp = g.json()["final_pack"]
        self.assertEqual(self.get(f"/api/v1/final-packs/{fp['final_pack_id']}/verify").json()["verified"], True)
        final = self.get(f"/api/v1/final-packs/{fp['final_pack_id']}/json").json()
        self.assertTrue(all(x["resolution_status"] == "UNRESOLVED" for x in final["exception_register"]))
        sep = self.get("/api/v1/periods/PER-2026-09").json()["period"]
        self.assertEqual((sep["archive_state"], sep["final_pack_count"]), ("RESULTS_AND_FINAL_PACK", 1))
        actions = [a["action"] for a in self.get("/api/v1/activity").json()]
        for a in ("DOCUMENTS_UPLOADED", "DOCUMENT_EXCLUDED", "BATCH_CONFIRMED", "PROCESSING_STARTED", "PROCESSING_SUCCEEDED"):
            self.assertIn(a, actions)


if __name__ == "__main__":
    unittest.main()
