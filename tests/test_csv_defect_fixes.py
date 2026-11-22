"""DEF-E2E-01 (short CSV row) and DIV-E2E-02 (header-only CSV) fixes, plus the 1-based duplicate diagnosis.

DEF-E2E-01: a data row with fewer cells than the header used to raise IndexError in handoff check 12, aborting
PackageService.submit so the OTHER files of the same call got no version. Now check 12 fails (fail-closed), the file is
FAILED_VALIDATION, and every other file in the call is processed normally.
DIV-E2E-02: a canonical header with no data rows used to be VALIDATED. Now handoff check 11 fails unless the registry's
csv.empty_allowed (imported from UC-042 schema.EMPTY_ALLOWED: IN-04, IN-14) allows an empty file."""
import sys
from pathlib import Path

from smartparser.mapping.rule_store import RuleStore
from smartparser.packages import review_api
from smartparser.packages.service import PackageService, Submission
from smartparser.packages.store import PackageStore
from smartparser.review.authority import AuthorityPolicy
from smartparser.schemas import SchemaRegistry

from .phase3b_support import ANALYST, TEST_POLICY, dump, tbl
from .uc042_support import SEP, read

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from reconcile_3b11 import service as base_service  # noqa: E402


def svc_for(tmp_path) -> PackageService:
    ws = tmp_path / "ws"
    ws.mkdir()
    RuleStore.initialise(ws / "rules", SchemaRegistry.from_directory())
    s = base_service(ws)
    return PackageService(s.store, s.o, AuthorityPolicy.load(TEST_POLICY))


def short_row(fid):
    lines = read(SEP, fid).split(b"\n")
    return b"\n".join(lines[:2] + [lines[2][: lines[2].rfind(b",")]] + lines[3:])


def test_short_row_is_failed_validation_and_the_rest_of_the_batch_is_processed(tmp_path):
    svc = svc_for(tmp_path)
    pid = svc.create_package("2026-09", ["IN-01", "IN-02", "IN-03"]).package_id
    out = svc.submit(pid, [Submission(short_row("IN-01"), "a.csv", "IN-01"), Submission(read(SEP, "IN-02"), "b.csv"),
                           Submission(read(SEP, "IN-03"), "c.csv")])
    st = {o.evidence_category: o.file_version.version_status for o in out}
    assert st == {"IN-01": "FAILED_VALIDATION", "IN-02": "VALIDATED", "IN-03": "VALIDATED"}
    v = out[0].file_version
    c12 = next(c for c in v.handoff.checks if c["id"] == 12)
    assert not c12["passed"] and "row 2 has" in c12["detail"] and "not repaired" in c12["detail"]
    assert v.handoff.preview_csv is None                                   # fail-closed: no preview
    assert svc.evidence.read_original(v.source_sha256) == short_row("IN-01")  # source kept byte-for-byte
    assert svc.pending_resubmissions(pid) == {"IN-01": v.file_version_id}


def test_header_only_file_is_refused_unless_the_contract_allows_empty(tmp_path):
    svc = svc_for(tmp_path)
    pid = svc.create_package("2026-09", ["IN-11", "IN-14"]).package_id
    hdr = lambda fid: read(SEP, fid).split(b"\n")[0] + b"\n"            # noqa: E731
    out = {o.evidence_category: o.file_version for o in
           svc.submit(pid, [Submission(hdr("IN-11"), "t.csv", "IN-11"), Submission(hdr("IN-14"), "d.csv", "IN-14")])}
    assert out["IN-11"].version_status == "FAILED_VALIDATION"
    c11 = next(c for c in out["IN-11"].handoff.checks if c["id"] == 11)
    assert not c11["passed"] and "EMPTY_FILE" in c11["detail"]
    assert out["IN-14"].version_status == "VALIDATED"                      # IN-14 may be empty (UC-042 EMPTY_ALLOWED)
    reg = SchemaRegistry.from_directory()
    assert {c for c in [f"IN-{i:02d}" for i in range(1, 15)] if reg.get(c).csv.empty_allowed} == {"IN-04", "IN-14"}
    a = svc.activate(pid)
    assert not a.activated and "PV-03" in [c.check_id for c in a.validation.checks if not c.passed]


def test_duplicate_source_reason_and_queue_use_1_based_positions(tmp_path):
    svc = svc_for(tmp_path)
    r = tbl("IN-03")
    pid = svc.create_package("2026-09", ["IN-03"]).package_id
    v = svc.submit(pid, [Submission(dump([r[0] + ["balance"]] + [x + [x[6]] for x in r[1:]]), "dup.csv", "IN-03")])[0].file_version
    q = review_api.list_reviews(svc)
    assert q[0]["duplicate_headers"] == {"balance": [7, 8]} and q[0]["review_kind"] == "HEADER_COUNT_MISMATCH"
    d = review_api.decide(svc, ANALYST, pid, v.file_version_id, "CHOOSE_DUPLICATE_SOURCE", 6, "booked column",
                          "balance", "duplicate export column")
    ignored = next(x for x in d["rows"] if x["source_index"] == 7)["decision"]
    assert ignored["action"] == "IGNORE_COLUMN" and "authoritative column is #7 (balance)" in ignored["reason"]
