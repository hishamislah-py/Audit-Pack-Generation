"""Phase 3B-9: evidence packages, file versioning, controlled resubmission, all-or-nothing snapshot activation and the
reconciliation-ready manifest (offline; recorded stubs only; sockets blocked; synthetic UC-042 data; tmp stores only).

Package used by most scenarios (the agreed business example): account inventory IN-02, client balances IN-03,
reconciliation records IN-05, bank statements IN-08, transactions IN-11.
"""
import csv
import hashlib
import io
import json
import socket
from pathlib import Path

import pytest

from smartparser.ai.config import AIConfig
from smartparser.ai.gateway import ProposalGateway
from smartparser.ai.proposer import RecordedResponseStub
from smartparser.handoff import writer
from smartparser.intake.store import EvidenceStore
from smartparser.mapping.rule_store import RuleStore
from smartparser.orchestration.orchestrator import MappingOrchestrator
from smartparser.orchestration.policy import PocAutoAcceptPolicy
from smartparser.packages.models import EvidencePackage
from smartparser.packages.service import PackageError, PackageService, Submission
from smartparser.packages.store import PackageStore, PackageStoreError
from smartparser.review.audit import AuditLog
from smartparser.review.session import ReviewError

from .phase3b_support import ANALYST, OWNER, SEP, dump, make_env, read, tbl

FX = Path(__file__).parent / "fixtures" / "recorded_llm"
POLICY_ON = Path(__file__).parent / "fixtures" / "orchestration" / "poc_auto_accept_enabled.json"
STUB_ON = AIConfig(enabled=True, provider="recorded_stub")
CATS = ["IN-02", "IN-03", "IN-05", "IN-08", "IN-11"]


@pytest.fixture
def env(tmp_path, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)

    def no_submission(*a, **k):
        raise AssertionError("UC-042 submission attempted")
    monkeypatch.setattr(writer, "submit_to_uc042", no_submission)
    return make_env(tmp_path)


def service(env, fixtures=(), policy=None, config=STUB_ON):
    stub = RecordedResponseStub([json.loads((FX / f"{f}.json").read_text(encoding="utf-8")) for f in fixtures])
    gw = ProposalGateway(proposer=stub, config=config, log=env.log)
    o = MappingOrchestrator(env.reg, env.store, env.evidence, gw,
                            PocAutoAcceptPolicy.load(policy) if policy else PocAutoAcceptPolicy.load(), env.log)
    return PackageService(PackageStore(env.root / "pk"), o, env.policy), stub


# ------------------------------------------------------------------------------------------------ data builders
def canon(fid):
    return read(SEP, fid)


def drop(fid, col):
    r = tbl(fid)
    i = r[0].index(col)
    return dump([[c for j, c in enumerate(x) if j != i] for x in r])


def add(fid, header, value="free text", pos=None):
    r = tbl(fid)
    pos = len(r[0]) if pos is None else pos
    return dump([r[0][:pos] + [header] + r[0][pos:]] + [x[:pos] + [value] + x[pos:] for x in r[1:]])


def rename(fid, m):
    r = tbl(fid)
    return dump([[m.get(c, c) for c in r[0]]] + r[1:])


def set_cell(fid, col, value, row=1):
    r = tbl(fid)
    r[row][r[0].index(col)] = value
    return dump(r)


def full(service_, cats=CATS, overrides=None, declared=None):
    overrides = overrides or {}
    # a modified file is uploaded INTO its slot (the analyst's declaration; verified against the content, never trusted)
    declared = {**{c: c for c in overrides}, **(declared or {})}
    pkg = service_.create_package("2026-09", cats)
    subs = [Submission(overrides.get(c, canon(c)), f"upload_{c}.csv", declared.get(c)) for c in cats]
    return pkg.package_id, service_.submit(pkg.package_id, subs)


def by_cat(outcomes):
    return {o.evidence_category: o for o in outcomes}


def events(env, *t):
    env.log.verify()
    return [e for e in env.log.events() if not t or e.event_type in t]


def fms(env):
    return env.store.read("file_mappings")["file_mappings"]


def stored(env, v):
    return env.evidence.read_original(v.source_sha256)


def resolve_all(svc, pid, vid, ignore=None, change=None, leave=None):
    """MAP every suggested column; IGNORE / CHANGE / LEAVE_UNRESOLVED where listed (through the package service)."""
    case, _ = svc.review_case(pid, vid)
    ignore, change, leave = ignore or {}, change or {}, leave or set()
    for c in case.columns:
        i = c.source_index
        if i in case.effective():
            continue
        if i in ignore:
            svc.decide(pid, vid, "IGNORE_COLUMN", ANALYST, ignore[i], i)
        elif i in change:
            svc.decide(pid, vid, "CHANGE", ANALYST, "mapped by the reviewer", i, change[i])
        elif i in leave:
            svc.decide(pid, vid, "LEAVE_UNRESOLVED", ANALYST, "unsure", i)
        elif c.suggested_field:
            svc.decide(pid, vid, "MAP", ANALYST, "canonical name", i)


def snapshot_versions(svc, pid):
    p = svc.load(pid)
    snap = svc.store.load_snapshot(pid, p.active_snapshot_id)
    return {e.evidence_category: e.version_number for e in snap.entries}


# ============================================================================================ store / persistence basics
def test_store_create_once_revision_and_immutable_snapshot(env):
    svc, _ = service(env)
    pkg = svc.create_package("2026-09", CATS)
    with pytest.raises(PackageStoreError):
        svc.store.create(pkg)                                                     # created exactly once
    stale = svc.load(pkg.package_id)
    svc.store.save(svc.load(pkg.package_id))
    with pytest.raises(PackageStoreError, match="changed"):
        svc.store.save(stale)                                                     # stale copy refused
    assert [e.event_type for e in events(env)] == ["PACKAGE_CREATED"]
    with pytest.raises(PackageError):
        svc.create_package("2026-9", CATS)
    with pytest.raises(PackageError):
        svc.create_package("2026-09", ["IN-99"])
    assert svc.create_package("2026-09").required_evidence_categories == [f"IN-{i:02d}" for i in range(1, 18)]


# ============================================================================================ 1-7 initial package intake
def test_01_all_valid_files(env):
    svc, stub = service(env)
    pid, out = full(svc)
    assert all(o.file_version.version_status == "VALIDATED" for o in out) and stub.calls == []
    assert all(o.file_version.version_number == 1 and o.file_version.content_category == o.evidence_category
               for o in out)                                                       # categories from content
    p = svc.load(pid)
    assert p.package_status == "READY_FOR_VALIDATION" and svc.pending_resubmissions(pid) == {}
    for o in out:
        v = o.file_version
        assert stored(env, v) == canon(v.evidence_category)
        assert v.handoff.eligible and (svc.store.root / v.handoff.preview_csv).read_bytes() == canon(v.evidence_category)
    assert len(events(env, "PACKAGE_FILE_RECEIVED", "FILE_VERSION_VALIDATED")) == 10


def test_01b_complete_uc042_contract_with_pdfs(env):
    """All 17 REQUIRED UC-042 categories (14 CSV + 3 PDF), no category declared: CSVs classify by header, the
    acknowledgement letters resolve through the package's own account inventory (IN-02)."""
    svc, _ = service(env)
    pkg = svc.create_package("2026-09")
    subs = [Submission(read(SEP, c), f"file_{n:02d}" + (".pdf" if c in ("IN-15", "IN-16", "IN-17") else ".csv"))
            for n, c in enumerate(reversed(pkg.required_evidence_categories))]          # PDFs first in the list
    out = svc.submit(pkg.package_id, subs)
    assert sorted(o.evidence_category for o in out) == pkg.required_evidence_categories
    assert all(o.file_version.version_status == "VALIDATED" for o in out), \
        [(o.evidence_category, o.file_version.reasons) for o in out if o.file_version.version_status != "VALIDATED"]
    pdfs = [o.file_version for o in out if o.evidence_category in ("IN-15", "IN-16", "IN-17")]
    assert all(v.handoff.basis == "PDF_CONTENT_CLASSIFICATION_ONLY" for v in pdfs)
    a = svc.activate(pkg.package_id)
    assert a.activated and svc.load(pkg.package_id).package_status == "RECONCILIATION_READY"
    assert len(a.snapshot.entries) == 17


def test_02_one_file_with_missing_columns(env):
    svc, stub = service(env)
    pid, out = full(svc, overrides={"IN-03": drop("IN-03", "balance")})
    v = by_cat(out)["IN-03"].file_version
    assert v.version_status == "RESUBMISSION_REQUIRED" and v.missing_fields == ["balance"] and stub.calls == []
    assert "never filled or inferred" in " ".join(v.reasons) and v.review_case_id     # history kept
    assert svc.pending_resubmissions(pid) == {"IN-03": v.file_version_id}
    assert svc.load(pid).package_status == "RESUBMISSION_REQUIRED" and fms(env) == []
    rr = events(env, "RESUBMISSION_REQUESTED")
    assert len(rr) == 1 and rr[0].details["missing_fields"] == ["balance"]


def test_03_two_files_with_missing_columns(env):
    svc, _ = service(env)
    pid, out = full(svc, overrides={"IN-03": drop("IN-03", "balance"), "IN-08": drop("IN-08", "entry_count")})
    assert sorted(svc.pending_resubmissions(pid)) == ["IN-03", "IN-08"]
    assert {c: o.file_version.version_status for c, o in by_cat(out).items()} == {
        "IN-02": "VALIDATED", "IN-03": "RESUBMISSION_REQUIRED", "IN-05": "VALIDATED",
        "IN-08": "RESUBMISSION_REQUIRED", "IN-11": "VALIDATED"}


def test_04_extra_column_file_routes_to_mapping_review_not_resubmission(env):
    svc, stub = service(env)
    pid, out = full(svc, overrides={"IN-05": add("IN-05", "memo")})
    v = by_cat(out)["IN-05"].file_version
    assert v.version_status == "REVIEW_REQUIRED" and v.processing_status == "HEADER_COUNT_GATE:HUMAN_REVIEW"
    assert stub.calls == [] and svc.pending_resubmissions(pid) == {} and fms(env) == []
    case, _ = svc.review_case(pid, v.file_version_id)
    assert case.extra_headers_diagnostic == [{"source_index": 19, "source_header": "memo"}]
    assert svc.load(pid).package_status == "REVIEW_REQUIRED"
    assert not events(env, "INTAKE_DECISION")                                        # nothing ignored automatically


def test_05_same_count_unfamiliar_headers_existing_workflow(env):
    """IN-02 with acct_id / bank_name: deterministic -> proposal (only the 2 unresolved headers) -> CLEAR -> (test POC
    policy) AUTO_ACCEPT -> reprocess -> VALIDATED."""
    svc, stub = service(env, ["in02_auto_clear"], policy=POLICY_ON)
    data = rename("IN-02", {"account_id": "acct_id", "institution_full_name": "bank_name"})
    pid, out = full(svc, overrides={"IN-02": data}, declared={"IN-02": "IN-02"})
    v = by_cat(out)["IN-02"].file_version
    assert v.version_status == "VALIDATED" and v.processing_status == "PROPOSAL:AUTO_ACCEPT"
    assert [u.source_header for u in stub.calls[0].unresolved_columns] == ["acct_id", "bank_name"]
    assert v.confirmation.approval_kind == "POC_AUTO" and v.mapping_rule_refs
    assert (svc.store.root / v.handoff.preview_csv).read_bytes() == canon("IN-02")


def test_05b_same_count_unfamiliar_headers_through_proposal_review(env):
    """Shipped (disabled) POC policy -> HUMAN_REVIEW session -> reviewer approves -> complete_session -> VALIDATED."""
    svc, stub = service(env, ["in02_auto_clear"])
    data = rename("IN-02", {"account_id": "acct_id", "institution_full_name": "bank_name"})
    pid, out = full(svc, overrides={"IN-02": data}, declared={"IN-02": "IN-02"})
    v = by_cat(out)["IN-02"].file_version
    assert v.version_status == "REVIEW_REQUIRED" and v.review_session_id and len(stub.calls) == 1
    s = svc.review_session(pid, v.file_version_id, ANALYST, "checked against the bank list",
                           [(0, "APPROVE", None), (8, "APPROVE", None)])
    assert s.state == "APPROVED"
    v = svc.complete_review(pid, v.file_version_id, [ANALYST], "file-specific")
    assert v.version_status == "VALIDATED" and v.processing_status == "SESSION_RESOLVED:HUMAN_REVIEW"
    assert (svc.store.root / v.handoff.preview_csv).read_bytes() == canon("IN-02") and len(stub.calls) == 1


def test_06_duplicate_evidence_category_in_one_package(env):
    svc, _ = service(env)
    pkg = svc.create_package("2026-09", CATS)
    out = svc.submit(pkg.package_id, [Submission(canon("IN-11"), "tx_a.csv"),
                                      Submission(set_cell("IN-11", "status", "SETTLED", 2), "tx_b.csv")])
    assert out[0].file_version.version_number == 1 and out[1].file_version is None
    assert "second active file for one category is not allowed" in out[1].refused_reason
    p = svc.load(pkg.package_id)
    assert len(p.evidence_files["IN-11"].version_ids) == 1 and p.unassigned_uploads[0]["filename"] == "tx_b.csv"
    assert [e.details["outcome"] for e in events(env, "PACKAGE_FILE_RECEIVED")] == ["ACCEPTED", "REFUSED"]


def test_07_missing_required_category(env):
    svc, _ = service(env)
    pkg = svc.create_package("2026-09", CATS)
    svc.submit(pkg.package_id, [Submission(canon(c), f"{c}.csv") for c in CATS if c != "IN-08"])
    assert svc.load(pkg.package_id).package_status == "INCOMPLETE"
    a = svc.activate(pkg.package_id)
    assert not a.activated and not a.validation.checks[0].passed and "IN-08" in a.validation.checks[0].detail
    svc.submit(pkg.package_id, [Submission(canon("IN-08"), "late.csv")])               # first file for the empty slot
    assert svc.activate(pkg.package_id).activated


# ============================================================================================ 8-12 mapping review
def test_08_extra_column_successfully_mapped(env):
    """IN-11 exported with txn_ref (unrecognised) + an extra memo column: 14 vs 13 -> review; txn_ref is mapped to
    txn_id (CHANGE), memo ignored -> VALIDATED, preview = canonical IN-11."""
    svc, _ = service(env)
    data = add("IN-11", "memo", pos=13)
    data = data.replace(b"txn_id,", b"txn_ref,", 1)
    pid, out = full(svc, overrides={"IN-11": data}, declared={"IN-11": "IN-11"})
    vid = by_cat(out)["IN-11"].file_version.file_version_id
    resolve_all(svc, pid, vid, ignore={13: "operator memo"}, change={0: "txn_id"})
    v = svc.complete_review(pid, vid, [ANALYST], "reviewed")
    assert v.version_status == "VALIDATED" and (svc.store.root / v.handoff.preview_csv).read_bytes() == canon("IN-11")
    assert any(r["rule_id"].startswith("FM-CRC-") for r in v.mapping_rule_refs)


def test_09_extra_column_ignored_with_reason(env):
    svc, _ = service(env)
    pid, out = full(svc, overrides={"IN-05": add("IN-05", "memo")})
    vid = by_cat(out)["IN-05"].file_version.file_version_id
    resolve_all(svc, pid, vid, ignore={19: "free-text memo, not evidence"})
    v = svc.complete_review(pid, vid, [ANALYST], "reviewed")
    side = json.loads((svc.store.root / v.handoff.provenance).read_text(encoding="utf-8"))
    assert v.version_status == "VALIDATED" and side["ignored_columns"][0]["reason"] == "free-text memo, not evidence"
    assert stored(env, v) == add("IN-05", "memo")                                    # source kept, incl. the column


def test_10_extra_column_left_unresolved(env):
    svc, _ = service(env)
    pid, out = full(svc, overrides={"IN-05": add("IN-05", "memo")})
    vid = by_cat(out)["IN-05"].file_version.file_version_id
    resolve_all(svc, pid, vid, leave={19})
    v = svc.complete_review(pid, vid, [ANALYST], "reviewed")
    assert v.version_status == "REVIEW_REQUIRED" and svc.load(pid).package_status == "REVIEW_REQUIRED"
    assert not svc.activate(pid).activated
    svc.decide(pid, vid, "IGNORE_COLUMN", ANALYST, "confirmed irrelevant", 19)          # held case revisited
    assert svc.complete_review(pid, vid, [ANALYST], "reviewed").version_status == "VALIDATED"


def test_11_duplicate_source_columns_resolved(env):
    svc, _ = service(env)
    r = tbl("IN-03")
    data = dump([r[0] + ["BALANCE"]] + [x + [x[6]] for x in r[1:]])
    pid, out = full(svc, overrides={"IN-03": data})
    vid = by_cat(out)["IN-03"].file_version.file_version_id
    case, _ = svc.review_case(pid, vid)
    assert case.potential_duplicate_claims == {"balance": [6, 7]}
    svc.decide(pid, vid, "CHOOSE_DUPLICATE_SOURCE", ANALYST, "booked balance", 6, others_reason="export copy")
    resolve_all(svc, pid, vid)
    v = svc.complete_review(pid, vid, [ANALYST], "reviewed")
    assert v.version_status == "VALIDATED" and (svc.store.root / v.handoff.preview_csv).read_bytes() == canon("IN-03")


def test_12_required_field_still_uncovered_after_mapping(env):
    svc, _ = service(env)
    r = tbl("IN-03")
    data = dump([r[0][:6] + ["memo", "note"]] + [x[:6] + ["a", "b"] for x in r[1:]])         # balance gone, 2 extras
    pid, out = full(svc, overrides={"IN-03": data}, declared={"IN-03": "IN-03"})
    vid = by_cat(out)["IN-03"].file_version.file_version_id
    assert by_cat(out)["IN-03"].file_version.version_status == "REVIEW_REQUIRED"         # 8 > 7: review first
    resolve_all(svc, pid, vid, ignore={6: "memo", 7: "note"})
    v = svc.complete_review(pid, vid, [ANALYST], "reviewed")
    assert v.version_status == "RESUBMISSION_REQUIRED" and v.missing_fields == ["balance"] and fms(env) == []
    assert svc.pending_resubmissions(pid) == {"IN-03": vid}


# ============================================================================================ 13-22 resubmission
def test_13_resubmit_one_file_only(env):
    svc, _ = service(env)
    pid, out = full(svc, overrides={"IN-03": drop("IN-03", "balance")})
    before = {c: o.file_version.file_version_id for c, o in by_cat(out).items()}
    oc = svc.resubmit(pid, "IN-03", canon("IN-03"), "client_balances_corrected.csv", "balance column restored")
    v = oc.file_version
    assert (v.version_number, v.version_status, v.previous_version_id) == (2, "VALIDATED", before["IN-03"])
    assert v.intake_id != by_cat(out)["IN-03"].file_version.intake_id and v.replacement_reason
    p = svc.load(pid)
    assert all(len(p.evidence_files[c].version_ids) == 1 for c in CATS if c != "IN-03")
    assert svc.activate(pid).activated and snapshot_versions(svc, pid) == {
        "IN-02": 1, "IN-03": 2, "IN-05": 1, "IN-08": 1, "IN-11": 1}
    ev = events(env, "RESUBMISSION_RECEIVED")
    assert ev[0].details["previous_file_version_id"] == before["IN-03"]


def test_14_resubmit_two_different_files_only(env):
    svc, _ = service(env)
    pid, _ = full(svc, overrides={"IN-03": drop("IN-03", "balance"), "IN-08": drop("IN-08", "entry_count")})
    svc.resubmit(pid, "IN-03", canon("IN-03"), "cb.csv", "fixed")
    assert svc.pending_resubmissions(pid) == {"IN-08": svc.load(pid).latest("IN-08").file_version_id}
    svc.resubmit(pid, "IN-08", canon("IN-08"), "bs.csv", "fixed")
    assert svc.activate(pid).activated
    assert snapshot_versions(svc, pid) == {"IN-02": 1, "IN-03": 2, "IN-05": 1, "IN-08": 2, "IN-11": 1}


def test_15_resubmission_with_valid_corrected_structure_runs_the_full_pipeline(env):
    svc, stub = service(env)
    pid, _ = full(svc, overrides={"IN-03": drop("IN-03", "balance")})
    oc = svc.resubmit(pid, "IN-03", canon("IN-03"), "cb.csv", "fixed")
    wr = oc.workflow
    assert wr.route == "DETERMINISTIC" and wr.reprocessed.provider_calls == 0 and wr.eligibility.eligible
    assert len(wr.eligibility.checks) == 14 and stub.calls == []
    t = [e.event_type for e in events(env) if e.intake_id == wr.intake_id]
    assert t[:2] == ["REPROCESSED", "HANDOFF_EVALUATED"] and "FILE_VERSION_VALIDATED" in t


def test_16_resubmission_that_still_has_missing_columns(env):
    svc, _ = service(env)
    pid, _ = full(svc, overrides={"IN-03": drop("IN-03", "balance")})
    oc = svc.resubmit(pid, "IN-03", drop("IN-03", "currency"), "cb2.csv", "attempt 2")
    assert oc.file_version.version_status == "RESUBMISSION_REQUIRED" and oc.file_version.missing_fields == ["currency"]
    assert oc.file_version.version_number == 2 and svc.load(pid).package_status == "RESUBMISSION_REQUIRED"
    assert not svc.activate(pid).activated


def test_17_resubmission_with_incorrect_evidence_category(env):
    svc, stub = service(env)
    pid, _ = full(svc, overrides={"IN-03": drop("IN-03", "balance")})
    oc = svc.resubmit(pid, "IN-03", canon("IN-11"), "wrong.csv", "oops")
    v = oc.file_version
    assert v.version_status == "REJECTED" and v.content_category == "IN-11" and "not a replacement for IN-03" in v.reasons[0]
    assert stub.calls == [] and svc.pending_resubmissions(pid) == {"IN-03": v.file_version_id}
    assert stored(env, v) == canon("IN-11")                                          # kept for traceability
    assert events(env, "FILE_VERSION_REJECTED")
    with pytest.raises(PackageError, match="not an evidence category"):
        svc.resubmit(pid, "IN-14", canon("IN-14"), "x.csv", "r")


def test_18_resubmission_modified_after_review(env):
    svc, _ = service(env)
    pid, _ = full(svc, overrides={"IN-03": drop("IN-03", "balance")})
    v2 = svc.resubmit(pid, "IN-03", add("IN-03", "memo"), "cb2.csv", "fixed + memo").file_version
    assert v2.version_status == "REVIEW_REQUIRED"
    resolve_all(svc, pid, v2.file_version_id, ignore={7: "memo"})
    p = env.evidence.root / "originals" / v2.source_sha256[:2] / v2.source_sha256
    p.write_bytes(p.read_bytes() + b"X,2026-09-01,2026-09-01T17:00:00+01:00,C,P,GBP,1.00,extra\n")
    with pytest.raises(ReviewError, match="SHA-256"):
        svc.complete_review(pid, v2.file_version_id, [ANALYST], "reviewed")
    assert svc.load(pid).versions[v2.file_version_id].version_status == "REVIEW_REQUIRED" and fms(env) == []
    assert not svc.activate(pid).activated


def test_18b_validated_version_tampered_before_activation(env):
    svc, _ = service(env)
    pid, out = full(svc)
    v = by_cat(out)["IN-05"].file_version
    p = env.evidence.root / "originals" / v.source_sha256[:2] / v.source_sha256
    p.write_bytes(p.read_bytes().replace(b"STANDARD", b"STANDARX", 1))
    a = svc.activate(pid)
    failed = {c.check_id for c in a.validation.checks if not c.passed}
    assert not a.activated and {"PV-05", "PV-08"} <= failed and svc.load(pid).active_snapshot_id is None


def test_19_repeated_upload_of_identical_corrected_bytes(env):
    svc, _ = service(env)
    pid, out = full(svc, overrides={"IN-03": drop("IN-03", "balance")})
    first = svc.resubmit(pid, "IN-03", canon("IN-03"), "cb.csv", "fixed")
    again = svc.resubmit(pid, "IN-03", canon("IN-03"), "cb.csv", "fixed")              # e.g. a double click
    assert again.file_version is None and "already uploaded as IN-03 v2" in again.refused_reason
    same_as_v1 = svc.resubmit(pid, "IN-03", drop("IN-03", "balance"), "cb.csv", "retry")
    assert same_as_v1.file_version is None and "v1" in same_as_v1.refused_reason
    p = svc.load(pid)
    assert len(p.evidence_files["IN-03"].version_ids) == 2 and first.file_version.version_status == "VALIDATED"
    assert [e.details["outcome"] for e in events(env, "RESUBMISSION_RECEIVED")] == ["ACCEPTED", "REFUSED", "REFUSED"]


def test_20_multiple_attempts_v1_missing_v2_failed_v3_valid(env):
    svc, _ = service(env)
    pid, _ = full(svc, overrides={"IN-03": drop("IN-03", "balance")})
    v2 = svc.resubmit(pid, "IN-03", set_cell("IN-03", "balance", "12,50"), "cb2.csv", "column restored").file_version
    assert v2.version_status == "FAILED_VALIDATION" and 10 in v2.handoff.failed_checks           # data error
    assert not svc.activate(pid).activated
    v3 = svc.resubmit(pid, "IN-03", canon("IN-03"), "cb3.csv", "value fixed").file_version
    assert (v3.version_number, v3.version_status, v3.previous_version_id) == (3, "VALIDATED", v2.file_version_id)
    assert svc.activate(pid).activated
    hist = svc.load(pid).history("IN-03")
    assert [(v.version_number, v.version_status) for v in hist] == [(1, "SUPERSEDED"), (2, "SUPERSEDED"), (3, "ACTIVE")]
    assert [s.status for s in hist[1].status_history] == ["RECEIVED", "FAILED_VALIDATION", "SUPERSEDED"]


def test_21_unchanged_files_are_not_requested_again(env):
    svc, _ = service(env)
    pid, out = full(svc, overrides={"IN-03": drop("IN-03", "balance")})
    assert list(svc.pending_resubmissions(pid)) == ["IN-03"]
    svc.resubmit(pid, "IN-03", canon("IN-03"), "cb.csv", "fixed")
    assert svc.pending_resubmissions(pid) == {}
    p = svc.load(pid)
    for c in ("IN-02", "IN-05", "IN-08", "IN-11"):
        assert p.evidence_files[c].version_ids == [by_cat(out)[c].file_version.file_version_id]
    assert len(events(env, "PACKAGE_FILE_RECEIVED")) == 5 and len(events(env, "RESUBMISSION_RECEIVED")) == 1


def test_22_original_files_remain_unchanged(env):
    svc, _ = service(env)
    v1_data = drop("IN-03", "balance")
    pid, out = full(svc, overrides={"IN-03": v1_data})
    v1 = by_cat(out)["IN-03"].file_version
    svc.resubmit(pid, "IN-03", canon("IN-03"), "cb.csv", "fixed")
    svc.activate(pid)
    assert stored(env, v1) == v1_data and hashlib.sha256(stored(env, v1)).hexdigest() == v1.source_sha256
    v2 = svc.load(pid).latest("IN-03")
    assert v2.source_sha256 != v1.source_sha256 and stored(env, v2) == canon("IN-03")
    assert env.evidence.find(v1.intake_id).sha256 == v1.source_sha256


# ============================================================================================ 23-30 activation
def test_23_all_replacements_valid_activate_new_snapshot(env):
    """3B-10 update (voluntary replacement of an ACTIVE file is now refused): both corrected files validate -> SNAP-001;
    a later first file for an empty OPTIONAL slot (IN-10 is not required in this test package) -> SNAP-002 that
    references SNAP-001."""
    svc, _ = service(env)
    pid, _ = full(svc, overrides={"IN-03": drop("IN-03", "balance"), "IN-08": drop("IN-08", "entry_count")})
    svc.resubmit(pid, "IN-03", canon("IN-03"), "cb_fix.csv", "balance column restored")
    svc.resubmit(pid, "IN-08", canon("IN-08"), "bs_fix.csv", "entry_count restored")
    assert svc.load(pid).package_status == "READY_FOR_VALIDATION"
    first = svc.activate(pid)
    assert first.activated and first.snapshot.sequence == 1
    assert snapshot_versions(svc, pid) == {"IN-02": 1, "IN-03": 2, "IN-05": 1, "IN-08": 2, "IN-11": 1}
    sup = events(env, "FILE_VERSION_SUPERSEDED")
    assert sorted(e.details["evidence_category"] for e in sup) == ["IN-03", "IN-08"]
    svc.submit(pid, [Submission(canon("IN-10"), "cashbook.csv")])                        # optional slot, first file
    second = svc.activate(pid)
    assert second.activated and second.snapshot.previous_snapshot_id == first.snapshot.snapshot_id
    assert snapshot_versions(svc, pid) == {"IN-02": 1, "IN-03": 2, "IN-05": 1, "IN-08": 2, "IN-10": 1, "IN-11": 1}


def test_24_25_one_of_two_replacements_fails_no_partial_activation(env):
    """3B-10 update. 24: two corrections pending, one valid and one still failing -> no snapshot at all (no partial
    package). 25: with an active snapshot, a failing new (optional) file blocks activation and the active snapshot
    and its ACTIVE versions are preserved unchanged."""
    svc, _ = service(env)
    pid, _ = full(svc, overrides={"IN-03": drop("IN-03", "balance"), "IN-08": drop("IN-08", "entry_count")})
    svc.resubmit(pid, "IN-03", canon("IN-03"), "cb_fix.csv", "balance restored")
    bad = svc.resubmit(pid, "IN-08", drop("IN-08", "bank_statement_ref"), "bs_fix.csv", "attempted fix").file_version
    assert bad.version_status == "RESUBMISSION_REQUIRED"
    a = svc.activate(pid)
    assert not a.activated and a.snapshot is None and svc.load(pid).active_snapshot_id is None          # 24
    assert svc.load(pid).latest("IN-03").version_status == "VALIDATED"                                  # waits
    assert events(env, "PACKAGE_VALIDATION_FAILED")
    svc.resubmit(pid, "IN-08", canon("IN-08"), "bs_fix2.csv", "fixed")
    first = svc.activate(pid).snapshot
    svc.submit(pid, [Submission(drop("IN-10", "currency"), "cashbook.csv", "IN-10")])                  # 25
    a = svc.activate(pid)
    assert not a.activated and a.snapshot is None
    p = svc.load(pid)
    assert p.active_snapshot_id == first.snapshot_id and p.snapshot_ids == [first.snapshot_id]
    assert snapshot_versions(svc, pid) == {"IN-02": 1, "IN-03": 2, "IN-05": 1, "IN-08": 3, "IN-11": 1}
    assert all(p.versions[p.evidence_files[c].active_version_id].version_status == "ACTIVE" for c in CATS)
    assert svc.store.load_snapshot(pid, first.snapshot_id) == first


def test_26_27_final_snapshot_mixes_unchanged_v1_and_corrected_v2(env):
    svc, _ = service(env)
    pid, out = full(svc, overrides={"IN-03": drop("IN-03", "balance"), "IN-08": drop("IN-08", "entry_count")})
    svc.resubmit(pid, "IN-03", canon("IN-03"), "cb.csv", "fixed")
    svc.resubmit(pid, "IN-08", canon("IN-08"), "bs.csv", "fixed")
    snap = svc.activate(pid).snapshot
    cats = [e.evidence_category for e in snap.entries]
    assert sorted(cats) == sorted(CATS) and len(cats) == len(set(cats))                             # 27
    p = svc.load(pid)
    for e in snap.entries:
        v = p.versions[e.file_version_id]
        assert (v.version_status, v.source_sha256, v.intake_id) == ("ACTIVE", e.source_sha256, e.intake_id)
        corrected = e.evidence_category in ("IN-03", "IN-08")
        assert e.version_number == (2 if corrected else 1)
        v1_id = by_cat(out)[e.evidence_category].file_version.file_version_id
        if corrected:
            assert v.previous_version_id == v1_id and p.versions[v1_id].version_status == "SUPERSEDED"
        else:
            assert e.file_version_id == v1_id                         # unchanged files keep their original v1


def test_28_reporting_period_consistency(env):
    svc, _ = service(env)
    pid, out = full(svc)
    assert all(env.evidence.find(o.file_version.intake_id).reporting_period == "2026-09" for o in out)
    p = svc.load(pid)
    vid = by_cat(out)["IN-05"].file_version.file_version_id
    p.versions[vid].reporting_period = "2026-08"                     # simulate an inconsistent record
    svc.store.save(p)
    a = svc.activate(pid)
    assert not a.activated and next(c for c in a.validation.checks if c.check_id == "PV-06").passed is False


def test_29_cannot_become_reconciliation_ready_with_unresolved_files(env):
    svc, _ = service(env)
    pid, _ = full(svc, overrides={"IN-05": add("IN-05", "memo"), "IN-03": drop("IN-03", "balance")})
    a = svc.activate(pid)
    failed = {c.check_id for c in a.validation.checks if not c.passed}
    assert not a.activated and {"PV-03", "PV-04"} <= failed
    assert svc.load(pid).package_status == "RESUBMISSION_REQUIRED" and svc.load(pid).active_snapshot_id is None


def test_30_superseded_versions_remain_retrievable(env):
    """3B-10 update: v1 (missing column) superseded by v2 on activation stays retrievable (record, bytes, review case,
    history); SNAP-001 stays retrievable and verifiable after SNAP-002 (optional file added)."""
    svc, _ = service(env)
    v1_data = drop("IN-03", "balance")
    pid, out = full(svc, overrides={"IN-03": v1_data})
    old = by_cat(out)["IN-03"].file_version
    svc.resubmit(pid, "IN-03", canon("IN-03"), "cb_fix.csv", "corrected")
    s1 = svc.activate(pid).snapshot
    svc.submit(pid, [Submission(canon("IN-10"), "cashbook.csv")])
    s2 = svc.activate(pid).snapshot
    p = svc.load(pid)
    v1 = p.versions[old.file_version_id]
    assert v1.version_status == "SUPERSEDED" and [h.status for h in v1.status_history] == [
        "RECEIVED", "RESUBMISSION_REQUIRED", "SUPERSEDED"]
    assert stored(env, v1) == v1_data and svc.store.load_case(pid, v1.review_case_id).case_id == v1.review_case_id
    hist = svc.store.load_snapshot(pid, s1.snapshot_id)
    assert next(e for e in hist.entries if e.evidence_category == "IN-03").version_number == 2
    assert all(c.passed for c in svc.verify_snapshot(pid, s1.snapshot_id))               # historical snapshot intact
    assert p.snapshot_ids == [s1.snapshot_id, s2.snapshot_id]


# ============================================================================================ 31-36 output
def _ready(svc):
    pid, _ = full(svc, overrides={"IN-03": drop("IN-03", "balance")})
    svc.resubmit(pid, "IN-03", canon("IN-03"), "client_balances_v2.csv", "balance column restored")
    return pid, svc.activate(pid)


def test_31_manifest_generated(env):
    svc, _ = service(env)
    pid, a = _ready(svc)
    m = json.loads(a.manifest_path.read_text(encoding="utf-8"))
    assert m["status"] == "RECONCILIATION_READY_NOT_SUBMITTED" and m["reconciliation_status"] == "NOT_RUN"
    assert m["submission_authorised"] is False and m["package_id"] == pid
    assert m["snapshot_id"] == a.snapshot.snapshot_id and m["reporting_period"] == "2026-09"
    assert m["package_validation"]["passed"] and m["validation_id"] == a.validation.validation_id
    assert sorted(m["selected_evidence_categories"]) == sorted(CATS)
    f3 = next(f for f in m["files"] if f["evidence_category"] == "IN-03")
    assert f3["version_number"] == 2 and f3["previous_version_id"] and f3["replacement_reason"]
    assert len(m["superseded_versions"]) == 1
    assert {f.keys() >= {"file_version_id", "intake_id", "original_filename", "source_sha256", "canonical_preview",
                         "provenance", "file_level"} for f in m["files"]} == {True}


def test_32_selected_sha256_values(env):
    svc, _ = service(env)
    pid, a = _ready(svc)
    m = json.loads(a.manifest_path.read_text(encoding="utf-8"))
    for f in m["files"]:
        data = env.evidence.read_original(f["source_sha256"])
        assert hashlib.sha256(data).hexdigest() == f["source_sha256"]
        assert env.evidence.find(f["intake_id"]).sha256 == f["source_sha256"]
        assert data == canon(f["evidence_category"])


def test_33_34_preview_and_provenance_references(env):
    svc, _ = service(env)
    pid, a = _ready(svc)
    m = json.loads(a.manifest_path.read_text(encoding="utf-8"))
    for f in m["files"]:
        pv = svc.store.root / f["canonical_preview"]["path"]
        assert hashlib.sha256(pv.read_bytes()).hexdigest() == f["canonical_preview"]["sha256"]
        assert pv.read_bytes() == canon(f["evidence_category"])
        side = json.loads((svc.store.root / f["provenance"]["path"]).read_text(encoding="utf-8"))
        assert side["source"]["sha256"] == f["source_sha256"] and side["source"]["intake_id"] == f["intake_id"]
        assert side["status"].startswith("PREVIEW_ONLY") and side["output"]["sha256"] == f["canonical_preview"]["sha256"]


def test_35_snapshot_reproducible_and_inspectable_after_restart(env):
    svc, _ = service(env)
    pid, a = _ready(svc)
    # "restart": brand-new objects over the same folders
    env2 = make_env.__globals__["Env"](env.root, env.reg, env.policy, AuditLog(env.root / "audit.jsonl"),
                                       RuleStore(env.root / "rules", env.reg), EvidenceStore(env.root / "evidence"))
    svc2, _ = service(env2)
    p = svc2.load(pid)
    assert p.package_status == "RECONCILIATION_READY" and p.active_snapshot_id == a.snapshot.snapshot_id
    assert all(c.passed for c in svc2.verify_snapshot(pid, p.active_snapshot_id))
    again = svc2.activate(pid)                                           # repeated activation: idempotent
    assert not again.activated and again.snapshot.snapshot_id == a.snapshot.snapshot_id
    assert svc2.load(pid).snapshot_ids == [a.snapshot.snapshot_id]
    with pytest.raises(PackageStoreError, match="immutable"):
        svc2.store.write_snapshot(a.snapshot)
    with pytest.raises(PackageStoreError, match="immutable"):
        svc2.store.write_manifest(pid, a.snapshot.snapshot_id, {})
    assert svc2.store.load_snapshot(pid, a.snapshot.snapshot_id) == a.snapshot


def test_35b_review_resumes_after_restart(env):
    svc, _ = service(env)
    pid, out = full(svc, overrides={"IN-05": add("IN-05", "memo")})
    vid = by_cat(out)["IN-05"].file_version.file_version_id
    svc.decide(pid, vid, "IGNORE_COLUMN", ANALYST, "memo", 19)
    env2 = make_env.__globals__["Env"](env.root, env.reg, env.policy, AuditLog(env.root / "audit.jsonl"),
                                       RuleStore(env.root / "rules", env.reg), EvidenceStore(env.root / "evidence"))
    svc2, _ = service(env2)
    case, _ = svc2.review_case(pid, vid)
    assert case.state == "UNDER_REVIEW" and len(case.decisions) == 1
    resolve_all(svc2, pid, vid)
    assert svc2.complete_review(pid, vid, [ANALYST], "reviewed").version_status == "VALIDATED"
    assert svc2.activate(pid).activated


def test_36_no_uc042_submission_or_protected_integration(env):
    svc, _ = service(env)
    pid, a = _ready(svc)                     # writer.submit_to_uc042 is patched to fail the test if ever called
    m = json.loads(a.manifest_path.read_text(encoding="utf-8"))
    assert m["submission_authorised"] is False and a.snapshot.submission_authorised is False
    assert a.snapshot.reconciliation_status == "NOT_RUN"
    root = svc.store.root
    assert "uc042_token_optimisation" not in str(root) and all(
        "uc042_token_optimisation" not in str(p) for p in root.rglob("*"))
    assert PocAutoAcceptPolicy.load().status == "DISABLED" and AIConfig.from_env({}).enabled is False


# ============================================================================================ review rules at package level
def test_rejected_review_requires_a_new_version(env):
    svc, _ = service(env)
    pid, out = full(svc, overrides={"IN-05": add("IN-05", "memo")})
    vid = by_cat(out)["IN-05"].file_version.file_version_id
    with pytest.raises(PackageError, match="complete or reject its review"):
        svc.resubmit(pid, "IN-05", canon("IN-05"), "x.csv", "r")
    v = svc.reject_review(pid, vid, ANALYST, "wrong export")
    assert v.version_status == "REJECTED" and svc.pending_resubmissions(pid) == {"IN-05": vid}
    assert svc.resubmit(pid, "IN-05", canon("IN-05"), "fixed.csv", "clean export").file_version.version_status == \
        "VALIDATED"
    assert svc.activate(pid).activated


def test_declared_slot_contradicted_by_content_is_rejected(env):
    """A file uploaded into the IN-08 slot whose content identifies as IN-07 is rejected for that slot (never switched,
    never processed as IN-08, no rule); the slot then awaits a correct file."""
    svc, _ = service(env)
    pid, out = full(svc, overrides={"IN-08": canon("IN-07")}, declared={"IN-08": "IN-08"})
    v = by_cat(out)["IN-08"].file_version
    assert v.version_status == "REJECTED" and v.content_category == "IN-07" and fms(env) == []


def test_package_audit_answers_the_traceability_questions(env):
    svc, _ = service(env)
    pid, a = _ready(svc)
    ev = [e for e in events(env) if e.details.get("package_id") == pid]
    t = [e.event_type for e in ev]
    for need in ("PACKAGE_CREATED", "PACKAGE_FILE_RECEIVED", "FILE_VERSION_CREATED", "RESUBMISSION_REQUESTED",
                 "RESUBMISSION_RECEIVED", "FILE_VERSION_VALIDATED", "PACKAGE_VALIDATION_STARTED",
                 "PACKAGE_VALIDATED", "PACKAGE_SNAPSHOT_CREATED", "FILE_VERSION_ACTIVATED", "FILE_VERSION_SUPERSEDED",
                 "PACKAGE_SNAPSHOT_ACTIVATED"):
        assert need in t, need
    req = next(e for e in ev if e.event_type == "RESUBMISSION_REQUESTED")
    assert req.details["missing_fields"] == ["balance"] and req.source_sha256                # why + which original
    act = next(e for e in ev if e.event_type == "PACKAGE_SNAPSHOT_ACTIVATED")
    assert act.details["snapshot_id"] == a.snapshot.snapshot_id and len(act.details["superseded_versions"]) == 1
    assert all(e.details.get("reporting_period") == "2026-09" for e in ev)
