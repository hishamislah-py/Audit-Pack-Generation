"""Stage 6, DR-10: exception-history matching of failed jobs and their not-published records.

A failed job now records the name of the not-published record it produced (job result `not_published_record`); the
history merges a record into the job event that names it (exact, reliable). Only for legacy job events that name no record
does a time-based fallback (within 10 s) apply, and then one job event absorbs at most ONE record (the nearest). A merged
record's validation status is assigned when the job's own value is None. Records with no job stay separate events.
Offline. Run: python -m unittest tests.test_stage6_dr10_history -v"""
import unittest

from tests.api_support import ApiCase
from tests.final_pack_support import PACK
from uc042app.services.investigation_reviews import InvestigationReviewService


class _Repo:
    def __init__(self, rows):
        self.rows = rows

    def list(self, **kw):
        return list(self.rows)


class _Runner:
    def __init__(self, jobs):
        self.repo = _Repo(jobs)


class _Packs:
    def load(self, pack_id):
        return {"metadata": {"pack_id": pack_id}}

    def exception(self, pack, exception_id):
        return {"exception_id": exception_id}


class _Investigations:
    def __init__(self, records):
        self.records = records

    def published(self, pack, exception_id):
        return {"published": [], "not_published": list(self.records)}


def job(job_id, completed_at, record=None, validation_status=None, legacy=False):
    result = {"validation_status": validation_status, "investigation_id": None}
    if not legacy:
        result["not_published_record"] = record
    return {"job_id": job_id, "operation": "INVESTIGATION", "submitted_at": completed_at, "started_at": completed_at,
            "completed_at": completed_at, "status": "FAILED", "result": result, "error_summary": f"{job_id} failed",
            "inputs": {}, "submitted_by": "analyst-1"}


def record(stamp, h, validation_status="REJECTED"):
    """A not-published record as list_investigations reports it; its name carries its storage time."""
    return {"record": f"{stamp}+0000-{h}.json", "investigation_status": "COMPLETED", "validation_status": validation_status,
            "failure_reason": f"record {h}"}


def history(jobs, records):
    svc = InvestigationReviewService(settings=None, repo=_Repo([]), packs=_Packs(), investigations=_Investigations(records),
                                     runner=_Runner(jobs), locks=None)
    return svc.exception_history("PACK-X", "EXC-X-01")["events"]


def failed(events):
    return [e for e in events if e["kind"] == "AI_INVESTIGATION_FAILED"]


def unmerged(events):
    return [e for e in events if e["kind"] == "AI_INVESTIGATION_NOT_PUBLISHED"]


class ExactMatching(unittest.TestCase):
    def test_closely_spaced_attempts_each_keep_their_own_record(self):
        r1, r2 = record("2026-11-16T100000", "aaaa1111"), record("2026-11-16T100003", "bbbb2222", "NOT_VALIDATED")
        jobs = [job("JOB-1", "2026-11-16T10:00:00+00:00", r1["record"]), job("JOB-2", "2026-11-16T10:00:03+00:00", r2["record"])]
        ev = history(jobs, [r1, r2])
        self.assertEqual(unmerged(ev), [])
        got = {e["details"]["job_id"]: e["details"] for e in failed(ev)}
        self.assertEqual(got["JOB-1"]["not_published_record"], r1["record"])
        self.assertEqual(got["JOB-2"]["not_published_record"], r2["record"])
        self.assertEqual((got["JOB-1"]["validation_status"], got["JOB-2"]["validation_status"]), ("REJECTED", "NOT_VALIDATED"))

    def test_identified_job_never_absorbs_a_different_record_by_time(self):
        mine, other = record("2026-11-16T100000", "aaaa1111"), record("2026-11-16T100001", "cccc3333")
        ev = history([job("JOB-1", "2026-11-16T10:00:00+00:00", mine["record"])], [mine, other])
        self.assertEqual([e["details"]["failure_reason"] for e in unmerged(ev)], ["record cccc3333"])

    def test_validation_status_assigned_when_none(self):
        r = record("2026-11-16T100000", "aaaa1111", "REJECTED")
        ev = history([job("JOB-1", "2026-11-16T10:00:00+00:00", r["record"], validation_status=None)], [r])
        self.assertEqual(failed(ev)[0]["details"]["validation_status"], "REJECTED")

    def test_existing_validation_status_is_kept(self):
        r = record("2026-11-16T100000", "aaaa1111", "REJECTED")
        ev = history([job("JOB-1", "2026-11-16T10:00:00+00:00", r["record"], validation_status="NOT_VALIDATED")], [r])
        self.assertEqual(failed(ev)[0]["details"]["validation_status"], "NOT_VALIDATED")


class LegacyTimeFallback(unittest.TestCase):
    def test_one_job_event_absorbs_at_most_one_record(self):
        near, far = record("2026-11-16T100001", "aaaa1111"), record("2026-11-16T100005", "bbbb2222")
        ev = history([job("JOB-1", "2026-11-16T10:00:00+00:00", legacy=True)], [near, far])
        self.assertEqual(len(failed(ev)), 1)
        self.assertEqual(failed(ev)[0]["details"]["not_published_record"], near["record"])  # the nearest one
        self.assertEqual([e["details"]["failure_reason"] for e in unmerged(ev)], ["record bbbb2222"])

    def test_two_legacy_jobs_two_records(self):
        r1, r2 = record("2026-11-16T100000", "aaaa1111"), record("2026-11-16T100004", "bbbb2222")
        jobs = [job("JOB-1", "2026-11-16T10:00:01+00:00", legacy=True), job("JOB-2", "2026-11-16T10:00:05+00:00", legacy=True)]
        ev = history(jobs, [r1, r2])
        self.assertEqual(unmerged(ev), [])
        got = {e["details"]["job_id"]: e["details"]["not_published_record"] for e in failed(ev)}
        self.assertEqual(got, {"JOB-1": r1["record"], "JOB-2": r2["record"]})

    def test_records_outside_the_window_and_without_jobs_stay_separate(self):
        late, alone = record("2026-11-16T100030", "aaaa1111"), record("2026-11-16T120000", "bbbb2222")
        ev = history([job("JOB-1", "2026-11-16T10:00:00+00:00", legacy=True)], [late, alone])
        self.assertEqual(len(unmerged(ev)), 2)
        self.assertNotIn("not_published_record", failed(ev)[0]["details"])

    def test_independent_record_with_no_job_at_all(self):
        ev = history([], [record("2026-11-16T100000", "aaaa1111")])
        self.assertEqual(len(unmerged(ev)), 1)


class ThroughTheRealJob(ApiCase):
    def test_failed_job_names_its_record_and_history_merges_it_exactly(self):
        def cite_candidate(d):
            d["confirmed_findings"][0]["evidence_ids"].append("CAND-SC5A-01")
        job_ = self.run_investigation_job("SC5A", "EXC-SC5A-01", edit=cite_candidate)
        self.assertEqual(job_["status"], "FAILED", job_)
        name = job_["result"]["not_published_record"]
        self.assertTrue(name and name.endswith(".json"), job_["result"])
        h = self.get(f"/api/v1/packs/{PACK['SC5A']}/exceptions/EXC-SC5A-01/review-history").json()
        ev = [e for e in h["events"] if e["kind"] == "AI_INVESTIGATION_FAILED"]
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["details"]["not_published_record"], name)
        self.assertNotIn("AI_INVESTIGATION_NOT_PUBLISHED", [e["kind"] for e in h["events"]])


if __name__ == "__main__":
    unittest.main()
