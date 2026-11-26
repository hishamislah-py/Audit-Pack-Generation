"""Analyst-review timestamps are one canonical UTC instant (B4): whatever offset a decision arrives with and whatever time
zone the database session or the process uses, the stored decision reads back identically and the review snapshot hash is
stable. Offline; the PostgreSQL cases use the disposable UC042_TEST_DATABASE_URL (skipped when it is not set).
Run from uc042/: python -m unittest tests.test_timestamps_utc -v"""
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import event

from tests import TEST_DATABASE_URL
from uc042app.clock import utc_iso
from uc042lib.final_pack import AnalystReview

KOLKATA = timezone(timedelta(hours=5, minutes=30))
DECIDED_KOLKATA = "2026-11-05T11:50:04+05:30"
DECIDED_UTC = "2026-11-05T06:20:04+00:00"


def record(investigation_id="INV-EXC-SC5A-01-000000000001", decided_at=DECIDED_KOLKATA, **kw):
    r = {"analyst_review_id": "AR-" + "0" * 23 + "1", "period_id": "PER-2026-09", "pack_id": "PACK-SC5A-PER-2026-09-ae391170b93a",
         "exception_id": "EXC-SC5A-01", "investigation_id": investigation_id, "findings_sha256": "a" * 64,
         "findings_schema_version": "uc042-investigation-findings/1.4", "decision": "REJECT", "comment": "",
         "rejection_reason": "The investigation did not consider Łódź's additional evidence.", "reviewer_id": "analyst-1",
         "reviewer_name": "Test Analyst", "decided_at": decided_at, "revision": 1, "supersedes_review_id": None}
    r.update(kw)
    return r


class Canonical(unittest.TestCase):
    def test_utc_iso_is_the_same_instant_in_one_form(self):
        self.assertEqual(utc_iso(DECIDED_KOLKATA), DECIDED_UTC)
        self.assertEqual(utc_iso("2026-11-05T01:20:04-05:00"), DECIDED_UTC)
        self.assertEqual(utc_iso(datetime(2026, 11, 5, 11, 50, 4, tzinfo=KOLKATA)), DECIDED_UTC)
        self.assertEqual(utc_iso("2026-11-05T11:50:04.123456+05:30"), "2026-11-05T06:20:04.123456+00:00")  # precision kept
        with self.assertRaises(ValueError):
            utc_iso("2026-11-05T11:50:04")  # naive: ambiguous, refused

    def test_library_review_normalises_before_it_enters_the_snapshot(self):
        base = {"analyst_review_id": "AR-1", "investigation_id": "INV-1", "exception_id": "EXC-1", "decision": "ACCEPT",
                "findings_sha256": "a" * 64, "reviewer": {"user_id": "u", "display_name": "U"}}
        a = AnalystReview.model_validate(dict(base, decided_at=DECIDED_KOLKATA))
        b = AnalystReview.model_validate(dict(base, decided_at=DECIDED_UTC))
        self.assertEqual((a.decided_at, a.model_dump()), (DECIDED_UTC, b.model_dump()))
        with self.assertRaises(ValueError):
            AnalystReview.model_validate(dict(base, decided_at="2026-11-05T11:50:04"))


class FileAndSqlite(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_file_repository(self):
        from uc042app.repositories.files import FileInvestigationReviewRepository
        repo = FileInvestigationReviewRepository(self.tmp / "reviews")
        self.assertEqual(repo.append(record(), 0)["decided_at"], DECIDED_UTC)
        self.assertEqual(repo.list()[0]["decided_at"], DECIDED_UTC)

    def test_sqlite_repository_keeps_the_instant(self):
        from uc042app.db import create_all_for_tests, make_engine, make_sessions
        from uc042app.db.repositories import SqlInvestigationReviewRepository
        engine = make_engine(f"sqlite:///{(self.tmp / 's.db').as_posix()}")
        try:
            create_all_for_tests(engine)
            repo = SqlInvestigationReviewRepository(make_sessions(engine))
            self.assertEqual(repo.append(record(), 0)["decided_at"], DECIDED_UTC)
            self.assertEqual(repo.list()[0]["decided_at"], DECIDED_UTC)  # SQLite stores no offset: stored as UTC
        finally:
            engine.dispose()


@unittest.skipUnless(TEST_DATABASE_URL, "PostgreSQL session time zones (UC042_TEST_DATABASE_URL, disposable)")
class PostgresSessionTimeZones(unittest.TestCase):
    """A decision made in Asia/Kolkata, read back by sessions in UTC, Asia/Kolkata and America/New_York."""

    def engine(self, tz):
        from uc042app.db import make_engine
        e = make_engine(TEST_DATABASE_URL)

        @event.listens_for(e, "connect")
        def _tz(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute(f"SET TIME ZONE '{tz}'")
            cur.close()
        self.engines.append(e)
        return e

    def setUp(self):
        from tests.api_support import reset_test_database
        reset_test_database(TEST_DATABASE_URL)
        self.engines = []

    def tearDown(self):
        for e in self.engines:
            e.dispose()

    def test_same_instant_same_decision_and_snapshot_input(self):
        from uc042app.db import make_sessions
        from uc042app.db.repositories import SqlInvestigationReviewRepository
        from uc042app.services.investigation_reviews import InvestigationReviewService
        writer = SqlInvestigationReviewRepository(make_sessions(self.engine("Asia/Kolkata")))
        writer.append(record(), 0)
        seen = {}
        for tz in ("UTC", "Asia/Kolkata", "America/New_York"):
            rows = SqlInvestigationReviewRepository(make_sessions(self.engine(tz))).list()
            view = InvestigationReviewService.view(rows[0], active=True)
            seen[tz] = (rows[0]["decided_at"], AnalystReview.model_validate(InvestigationReviewService.library_review(view)).model_dump())
        self.assertEqual({v[0] for v in seen.values()}, {DECIDED_UTC})
        self.assertEqual(len({repr(v[1]) for v in seen.values()}), 1)  # identical snapshot input, so an identical snapshot hash
        with self.engine("UTC").connect() as c:  # the stored value is the instant, not a wall-clock string
            from sqlalchemy import text
            stored = c.execute(text("select decided_at from audit.investigation_reviews")).scalar()
        self.assertEqual(stored, datetime(2026, 11, 5, 6, 20, 4, tzinfo=timezone.utc))


class SnapshotStability(unittest.TestCase):
    """The review snapshot (what GENERATE must match) is identical for the same decision read with different offsets."""

    def test_snapshot_hash_is_offset_independent(self):
        from tests.final_pack_support import PACK, make_investigation
        from uc042lib.final_pack import build_review_snapshot
        tmp = Path(tempfile.mkdtemp())
        try:
            root = tmp / "investigations"
            inv = make_investigation("SC5A", "EXC-SC5A-01", root)
            import hashlib
            sha = hashlib.sha256(next(root.glob(f"*/EXC-SC5A-01/{inv}")).joinpath("findings.json").read_bytes()).hexdigest()
            sel = [{"exception_id": "EXC-SC5A-01", "inclusion": "INCLUDED", "investigation_id": inv},
                   {"exception_id": "EXC-SC5A-02", "inclusion": "NOT_INVESTIGATED"}]

            def review(decided_at):
                return {"analyst_review_id": "AR-1", "investigation_id": inv, "exception_id": "EXC-SC5A-01", "decision": "ACCEPT",
                        "findings_sha256": sha, "reviewer": {"user_id": "u", "display_name": "U"}, "decided_at": decided_at}
            hashes = {build_review_snapshot(PACK["SC5A"], sel, investigations_root=root, analyst_reviews=[review(t)]).sha256
                      for t in (DECIDED_KOLKATA, DECIDED_UTC, "2026-11-05T01:20:04-05:00")}
            self.assertEqual(len(hashes), 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
