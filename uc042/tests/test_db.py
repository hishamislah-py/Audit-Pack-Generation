"""Database layer (uc042app.db): migrations, the start-up schema check and the SQL repositories.

The repository tests run on a temporary SQLite file and, when UC042_TEST_DATABASE_URL is set, on that disposable
PostgreSQL database as well. The operational database (UC042_DATABASE_URL) is never used (tests/__init__.py)."""
import shutil
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import inspect

from tests import TEST_DATABASE_URL
from tests.api_support import ApiCase, reset_test_database
from uc042app.config import Settings
from uc042app.db import DatabaseNotReady, check_schema, create_all_for_tests, make_engine, make_sessions, upgrade
from uc042app.db import models as m
from uc042app.db.repositories import SqlRepositories
from uc042app.repositories import ConcurrentUpdate, DuplicateRecord
from uc042app.services import Services

ROOT = Path(__file__).resolve().parent.parent
TABLES = sorted(t.name for t in m.Base.metadata.sorted_tables)
NOW = "2026-11-03T10:00:00+00:00"


def needs_postgres(cls):
    return unittest.skipUnless(TEST_DATABASE_URL, "UC042_TEST_DATABASE_URL is not set")(cls)


class RepositoryContract:
    """Behaviour every SQL backend must show. Subclasses provide self.url."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.engine = make_engine(self.make_url())
        self.repos = SqlRepositories(make_sessions(self.engine))

    def tearDown(self):
        self.engine.dispose()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def batch(self, batch_id="UPL-1", period_id="PER-2026-10", **kw):
        return dict(batch_id=batch_id, period_id=period_id, origin="UPLOAD", created_at=NOW, created_by="analyst-1", file_count=1,
                    validation_status="VALID", status="VALIDATED", summary={"files": 1}, error="", **kw)

    def document(self, document_id="DOC-1", batch_id="UPL-1", sha="a" * 64, name="bank.csv", **kw):
        return dict(document_id=document_id, batch_id=batch_id, original_filename=name, evidence_id="IN-01", category="bank_statement",
                    file_format="CSV", size_bytes=10, sha256=sha, reporting_period="PER-2026-10", date_from="2026-10-01",
                    date_to="2026-10-31", record_count=3, validation_status="VALID", checks={"messages": []},
                    storage_ref=f"object:{sha}", created_at=NOW, **kw)

    # ------------------------------------------------------------------ application state
    def test_jobs_round_trip_and_filter(self):
        job = {"job_id": "JOB-1", "operation": "INVESTIGATION", "pack_id": "P1", "exception_id": "E1", "status": "QUEUED",
               "submitted_at": NOW, "nested": {"a": [1, 2]}}
        self.repos.jobs.create(job)
        self.assertEqual(self.repos.jobs.get("JOB-1"), job)
        self.assertEqual(self.repos.jobs.update("JOB-1", {"status": "RUNNING"})["status"], "RUNNING")
        self.assertEqual([j["job_id"] for j in self.repos.jobs.list(pack_id="P1", statuses=["RUNNING"])], ["JOB-1"])
        self.assertEqual(self.repos.jobs.list(pack_id="P2"), [])

    def test_review_optimistic_concurrency_and_append_only_decisions(self):
        session = {"review_id": "REV-1", "pack_id": "P1", "status": "OPEN", "revision": 1, "created_at": NOW}
        self.repos.reviews.create(session)
        saved = self.repos.reviews.save(dict(session, status="ON_HOLD"), expected_revision=1)
        self.assertEqual(saved["revision"], 2)
        with self.assertRaises(ConcurrentUpdate):
            self.repos.reviews.save(dict(session, status="OPEN"), expected_revision=1)
        self.repos.reviews.append_decision("REV-1", {"review_decision_id": "RD-1", "decided_at": NOW, "decision": "HOLD"})
        self.repos.reviews.append_decision("REV-1", {"review_decision_id": "RD-2", "decided_at": NOW, "decision": "GENERATE"})
        self.assertEqual([d["review_decision_id"] for d in self.repos.reviews.decisions("REV-1")], ["RD-1", "RD-2"])

    def test_previews_are_write_once(self):
        self.repos.reviews.create({"review_id": "REV-1", "pack_id": "P1", "status": "OPEN", "revision": 1, "created_at": NOW})
        self.repos.reviews.save_preview("REV-1", "PRV-1", {"sha": "1"}, {"doc": 1})
        with self.assertRaises(FileExistsError):
            self.repos.reviews.save_preview("REV-1", "PRV-1", {"sha": "2"}, {"doc": 2})
        self.assertEqual(self.repos.reviews.get_preview("REV-1", "PRV-1"), ({"sha": "1"}, {"doc": 1}))
        self.assertEqual(self.repos.reviews.get_preview("REV-1", "PRV-X"), (None, None))

    def test_final_pack_record_is_unique_per_decision(self):
        rec = {"review_decision_id": "RD-1", "review_id": "REV-1", "pack_id": "P1", "status": "GENERATING", "created_at": NOW}
        self.repos.final_packs.create(rec)
        with self.assertRaises(DuplicateRecord):
            self.repos.final_packs.create(rec)
        self.assertEqual(self.repos.final_packs.update("RD-1", {"status": "GENERATED"})["status"], "GENERATED")

    def test_registry_is_ordered_and_append_only(self):
        before = self.repos.registry.signature()
        for seq in (1, 2):
            self.repos.registry.append({"seq": seq, "investigation_id": f"INV-{seq}", "record_type": "NEW_PUBLICATION", "recorded_at": NOW})
        with self.assertRaises(DuplicateRecord):
            self.repos.registry.append({"seq": 2, "investigation_id": "INV-X", "record_type": "NEW_PUBLICATION", "recorded_at": NOW})
        self.assertEqual([e["investigation_id"] for e in self.repos.registry.entries()], ["INV-1", "INV-2"])
        self.assertNotEqual(self.repos.registry.signature(), before)

    # ------------------------------------------------------------------ monthly document management
    def test_periods_batches_documents_runs(self):
        p = self.repos.periods.ensure("PER-2026-10", 2026, 10)
        self.assertEqual((p["status"], p["year"], p["month"]), ("EMPTY", 2026, 10))
        self.assertEqual(self.repos.periods.ensure("PER-2026-10", 2026, 10, status="PROCESSED")["status"], "EMPTY")  # never replaced
        self.repos.uploads.create_batch(self.batch(), [self.document(), self.document("DOC-2", sha="b" * 64, name="bank.csv")])
        self.assertEqual(len(self.repos.uploads.documents(batch_id="UPL-1")), 2)
        self.assertEqual([d["document_id"] for d in self.repos.uploads.find_documents(original_filename="bank.csv",
                                                                                      period_id="PER-2026-10")], ["DOC-1", "DOC-2"])
        self.assertEqual(self.repos.uploads.find_documents(sha256="a" * 64, period_id="PER-2026-11"), [])
        d = self.repos.uploads.update_document("DOC-2", {"review_decision": "EXCLUDE", "reviewed_at": NOW, "reviewed_by": "a1"})
        self.assertEqual(d["review_decision"], "EXCLUDE")
        self.assertEqual(self.repos.uploads.document("DOC-1")["checks"], {"messages": []})
        self.repos.runs.create(dict(run_id="RUN-1", period_id="PER-2026-10", batch_id="UPL-1", job_id=None, status="QUEUED",
                                    started_at=None, completed_at=None, error="", result={}, created_at=NOW, created_by="a1"))
        self.repos.runs.update("RUN-1", {"status": "FAILED", "error": "missing IN-02", "completed_at": NOW})
        self.assertEqual([r["status"] for r in self.repos.runs.list(period_id="PER-2026-10")], ["FAILED"])
        self.repos.periods.add_pack(dict(period_id="PER-2026-10", pack_id="PACK-X", origin="UPLOAD_PROCESSING", scenario_id="",
                                         dataset="", processing_run_id="RUN-1", pack_content_sha256="c" * 64, registered_at=NOW))
        self.repos.periods.add_pack(dict(period_id="PER-2026-10", pack_id="PACK-X", origin="POC_SCENARIO", scenario_id="",
                                         dataset="", processing_run_id=None, pack_content_sha256="d" * 64, registered_at=NOW))
        packs = self.repos.periods.packs("PER-2026-10")
        self.assertEqual([(x["pack_id"], x["origin"]) for x in packs], [("PACK-X", "UPLOAD_PROCESSING")])  # first registration kept

    def test_documents_never_share_an_id(self):
        self.repos.periods.ensure("PER-2026-10", 2026, 10)
        self.repos.uploads.create_batch(self.batch(), [self.document()])
        with self.assertRaises(Exception):
            self.repos.uploads.create_batch(self.batch("UPL-2"), [self.document()])
        self.assertIsNone(self.repos.uploads.batch("UPL-2"))  # the failed batch left nothing behind
        self.assertEqual(self.repos.uploads.document("DOC-1")["batch_id"], "UPL-1")

    def test_activity_is_newest_first(self):
        for i, at in enumerate(("2026-11-01T00:00:00+00:00", "2026-11-02T00:00:00+00:00")):
            self.repos.activity.append({"at": at, "actor": "a1", "action": f"A{i}", "entity_type": "period",
                                        "entity_id": "PER-2026-10", "details": {}})
        self.assertEqual([a["action"] for a in self.repos.activity.recent()], ["A1", "A0"])
        self.assertEqual(self.repos.activity.recent(entity_type="batch"), [])


class SqliteRepositories(RepositoryContract, unittest.TestCase):
    def make_url(self):
        url = f"sqlite:///{(self.tmp / 'db.sqlite').as_posix()}"
        engine = make_engine(url)
        create_all_for_tests(engine)
        engine.dispose()
        return url


@needs_postgres
class PostgresRepositories(RepositoryContract, unittest.TestCase):
    def make_url(self):
        reset_test_database(TEST_DATABASE_URL)
        return TEST_DATABASE_URL


@needs_postgres
class PostgresMigrations(unittest.TestCase):
    def setUp(self):
        reset_test_database(TEST_DATABASE_URL)  # empty: the 0003 downgrade refuses to drop tables that still hold records
        self.engine = make_engine(TEST_DATABASE_URL)

    def tearDown(self):
        upgrade(TEST_DATABASE_URL)  # leave the test database at head for the other tests
        self.engine.dispose()

    def tables(self):
        """Application tables in public and in the audit / operations schemas (migration 0003 moves them out of public)."""
        insp = inspect(self.engine)
        found = [t for t in insp.get_table_names() if t != "alembic_version"]
        found += [t for s in m.SCHEMAS if s in insp.get_schema_names() for t in insp.get_table_names(schema=s)]
        return sorted(found)

    def test_upgrade_downgrade_upgrade(self):
        upgrade(TEST_DATABASE_URL)
        self.assertEqual(self.tables(), TABLES)
        check_schema(self.engine)
        from alembic import command
        from uc042app.db import alembic_config
        command.downgrade(alembic_config(TEST_DATABASE_URL), "base")
        self.assertEqual(self.tables(), [])
        with self.assertRaises(DatabaseNotReady):
            check_schema(self.engine)
        upgrade(TEST_DATABASE_URL)
        self.assertEqual(self.tables(), TABLES)

    def test_backend_refuses_an_unmigrated_database(self):
        from alembic import command
        from uc042app.db import alembic_config
        command.downgrade(alembic_config(TEST_DATABASE_URL), "base")
        tmp = Path(tempfile.mkdtemp())
        try:
            settings = Settings.from_env(state_dir=tmp / "state", final_packs_root=tmp / "fp", database_url=TEST_DATABASE_URL)
            with self.assertRaises(DatabaseNotReady):
                Services(settings)
            self.assertEqual(self.tables(), [])  # nothing was created implicitly
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class FileStateImport(unittest.TestCase):
    """import-file-state copies file-backed state into the database, never modifies the source and never overwrites."""

    def setUp(self):
        from uc042app.repositories import FileRepositories
        self.tmp = Path(tempfile.mkdtemp())
        self.state = self.tmp / "state"
        src = FileRepositories(self.state)
        src.jobs.create({"job_id": "JOB-1", "operation": "PREVIEW", "pack_id": "P1", "exception_id": None, "status": "COMPLETED",
                         "submitted_at": NOW})
        src.reviews.create({"review_id": "RS-1", "pack_id": "P1", "status": "ON_HOLD", "revision": 3, "created_at": NOW})
        src.reviews.append_decision("RS-1", {"review_decision_id": "RD-1", "decided_at": NOW, "decision": "HOLD"})
        src.reviews.save_preview("RS-1", "PRV-1", {"fingerprint": "x"}, {"sections": [1]})
        src.final_packs.create({"review_decision_id": "RD-9", "review_id": "RS-1", "pack_id": "P1", "status": "GENERATED",
                                "created_at": NOW})
        src.registry.append({"seq": 1, "investigation_id": "INV-1", "record_type": "LEGACY_BASELINE_IMPORT", "recorded_at": NOW})
        from tests.final_pack_support import sha_tree
        self.sha_tree = sha_tree
        self.before = sha_tree(self.state)
        self.engine = make_engine(f"sqlite:///{(self.tmp / 'db.sqlite').as_posix()}")
        create_all_for_tests(self.engine)
        self.db = SqlRepositories(make_sessions(self.engine))

    def tearDown(self):
        self.engine.dispose()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_import_is_complete_idempotent_and_read_only(self):
        from uc042app.db.importer import import_file_state
        dry = import_file_state(self.state, self.db, dry_run=True)
        self.assertEqual(dry.count("WOULD_IMPORT"), 6)
        self.assertIsNone(self.db.jobs.get("JOB-1"))
        first = import_file_state(self.state, self.db)
        self.assertEqual((first.count("IMPORTED"), first.conflicts), (6, []))
        self.assertEqual(self.db.reviews.get("RS-1")["revision"], 3)
        self.assertEqual(self.db.reviews.get_preview("RS-1", "PRV-1"), ({"fingerprint": "x"}, {"sections": [1]}))
        self.assertEqual(self.db.registry.entries()[0]["record_type"], "LEGACY_BASELINE_IMPORT")
        second = import_file_state(self.state, self.db)
        self.assertEqual((second.count("IMPORTED"), second.count("UNCHANGED")), (0, 6))
        self.assertEqual(self.sha_tree(self.state), self.before)

    def test_differing_database_record_is_a_conflict_not_an_overwrite(self):
        from uc042app.db.importer import import_file_state
        self.db.jobs.create({"job_id": "JOB-1", "operation": "PREVIEW", "pack_id": "P1", "exception_id": None, "status": "FAILED",
                             "submitted_at": NOW})
        report = import_file_state(self.state, self.db)
        self.assertEqual([r[:3] for r in report.conflicts], [("job", "JOB-1", "CONFLICT")])
        self.assertEqual(self.db.jobs.get("JOB-1")["status"], "FAILED")

    def test_refuses_a_folder_that_is_not_application_state(self):
        from uc042app.db.importer import import_file_state
        with self.assertRaises(FileNotFoundError):
            import_file_state(self.tmp / "nowhere", self.db)
        with self.assertRaises(FileNotFoundError):
            import_file_state(ROOT / "packs", self.db)


class SqlRegistryTamper(ApiCase):
    """Database counterpart of the file-format registry tests: a changed registry row no longer matches the files."""

    def setUp(self):
        super().setUp()
        if not self.svc.database:
            self.stop_app()
            self.settings = self.settings.with_(database_url=f"sqlite:///{(self.tmp / 'state.db').as_posix()}")
            self.start_app()

    def test_changed_registry_row_no_longer_matches_the_files(self):
        from tests.test_api_registry import REAL_S05_14, Registry
        d, _, _ = Registry.import_copy(self, REAL_S05_14)
        self.assertTrue(Registry.eligible(self, "S05", "EXC-S05-01", d.name)["eligible"])
        with self.svc.repos.sessions.begin() as s:
            row = s.get(m.RegistryEntryRow, 1)
            row.data = dict(row.data, findings_sha256="f" * 64)
        reasons = " ".join(Registry.eligible(self, "S05", "EXC-S05-01", d.name)["ineligible_reasons"])
        self.assertIn("findings_sha256 differs", reasons)

if __name__ == "__main__":
    unittest.main()
