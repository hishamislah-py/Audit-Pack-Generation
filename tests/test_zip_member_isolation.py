"""One unreadable member of a readable ZIP is isolated, not fatal (20 Nov 2026).

A ZIP member whose CRC-32 (or compressed data) is damaged is recorded on the run as an `unreadable_entries` item with its
central-directory name and size and the exact error. Its bytes are never staged. Every other member goes through the
normal intake, and the run COMPLETES. The missing evidence follows the normal missing-required path (validation blocks
activation) and is listed as outstanding work. The corrected file is uploaded through the existing case upload path; its
category is decided by its content (O7). A whole-archive failure (not a ZIP, unopenable, empty, nothing readable) still
FAILS the run (O6). Retry semantics (O1) and immutability after activation (O5) are unchanged.

ZIPs are built programmatically; the CRC is corrupted the same way as the demo build tool does (XOR of the CRC-32 field
in the local header and the central-directory record)."""
import hashlib
import io
import struct
import zipfile

import pytest

from .test_ringfence_cases import R, SEP, ctx_for, err, events, make_zip, name, new_case, read, settle, upload
from .test_ringfence_owner_decisions import fail_first_validation, started
from .uc042_support import needs_uc042

CORRUPT = "IN-03"
MEMBER = f"submission/{name(CORRUPT)}"


def corrupt_crc(zb: bytes, member: str) -> bytes:
    b = bytearray(zb)
    with zipfile.ZipFile(io.BytesIO(zb)) as z:
        info = z.getinfo(member)
    bad = info.CRC ^ 0xA5A5A5A5
    assert b[info.header_offset:info.header_offset + 4] == b"PK\x03\x04"
    struct.pack_into("<I", b, info.header_offset + 14, bad)
    i, found = b.find(b"PK\x01\x02"), 0
    while i != -1:
        n, = struct.unpack_from("<H", b, i + 28)
        if bytes(b[i + 46:i + 46 + n]) == member.encode():
            struct.pack_into("<I", b, i + 16, bad)
            found += 1
        i = b.find(b"PK\x01\x02", i + 4)
    assert found == 1
    return bytes(b)


def corrupted_zip() -> bytes:
    return corrupt_crc(make_zip(), MEMBER)


def staging_dirs(ctx) -> list:
    return [p for p in ctx.staging.iterdir() if p.is_dir()]


# ----------------------------------------------------------------------------------------------- isolation
def test_one_unreadable_member_is_isolated_and_the_run_completes(tmp_path):
    ctx = ctx_for(tmp_path)
    data = corrupted_zip()
    with pytest.raises(zipfile.BadZipFile, match="Bad CRC-32"):            # the integrity check itself is unchanged
        zipfile.ZipFile(io.BytesIO(data)).read(MEMBER)
    ref, d = started(ctx, data)
    run = d["runs"][0]
    assert d["status"] == "IN_PROGRESS" and run["status"] == "COMPLETED" and run["failure"] is None
    assert d["failed_runs"] == 0 and not d["actions"]["retry_from_beginning"]["enabled"]
    # the run record: accurate counters and the isolated member (central-directory size, exact error)
    assert run["staged_entries"] == 16 and run["skipped_entries"] == []
    [u] = run["unreadable_entries"]
    size = zipfile.ZipFile(io.BytesIO(data)).getinfo(MEMBER).file_size
    assert u["name"] == MEMBER and u["size"] == size and u["error_kind"] == "CRC_FAILURE"
    assert u["error"].startswith("BadZipFile: Bad CRC-32") and MEMBER in u["error"]
    # the other 16 members were classified, mapped and validated through the normal intake
    assert len(run["intake_job"]["files"]) == 16 and all(f["state"] == "done" for f in run["intake_job"]["files"])
    pkg = ctx.svc.load(run["package_id"])
    assert len(pkg.versions) == 16 and pkg.latest(CORRUPT) is None
    assert {v.version_status for v in pkg.versions.values()} == {"VALIDATED"}
    # only fully read members were staged: no orphan, never the unreadable member's bytes
    assert len(staging_dirs(ctx)) == 16
    # the missing evidence follows the normal missing-required path: validation fails, activation is blocked
    p = d["progress"]
    assert [m["category"] for m in p["missing_required"]] == [CORRUPT]
    assert p["validation"]["state"] == "FAILED" and not d["actions"]["activate"]["enabled"]
    assert not R(ctx, "POST", f"cases/{ref}/activate", {"confirm": True})["activated"]
    assert not ctx.svc.load(run["package_id"]).active_snapshot_id
    # the original ZIP is untouched (content-addressed, same bytes and SHA-256)
    stored = (ctx.cases.zips / f"{d['zip']['sha256']}.zip").read_bytes()
    assert stored == data and hashlib.sha256(stored).hexdigest() == d["zip"]["sha256"]
    # audit: the isolation is recorded in CASE_RUN_STARTED (no dedicated event type exists in review/audit.py)
    ev = events(ctx, "CASE_RUN_STARTED")[-1]["details"]
    assert ev["staged_entries"] == 16 and ev["skipped_entries"] == 0
    assert ev["unreadable_members"] == [{"name": MEMBER, "size": size, "error_kind": "CRC_FAILURE", "error": u["error"],
                                         "original_zip_sha256": d["zip"]["sha256"]}]
    assert not events(ctx, "CASE_RUN_FAILED")


def test_unreadable_member_is_listed_as_outstanding_work(tmp_path):
    ctx = ctx_for(tmp_path)
    ref, d = started(ctx, corrupted_zip())
    [o] = d["outstanding"]["unreadable_members"]
    assert o["name"] == MEMBER and o["error"].startswith("BadZipFile: Bad CRC-32") and o["open"] is True
    assert o["original_zip_sha256"] == d["zip"]["sha256"] and o["size"] > 0
    assert o["hint"].startswith("Hint only (not used to accept the file)") and CORRUPT in o["hint"]
    assert "1 file in the original ZIP could not be read (CRC failure): upload a corrected file" in d["progress"]["summary"]
    assert [m["category"] for m in d["outstanding"]["missing_categories"]] == [CORRUPT]
    assert d["actions"]["upload_evidence"]["enabled"]              # no longer blocked by a failed run
    assert R(ctx, "GET", "cases")["items"][0]["progress"]["unreadable_members"][0]["name"] == MEMBER


def test_corrected_upload_goes_through_the_existing_path_and_activation_works(tmp_path):
    ctx = ctx_for(tmp_path)
    ref, d = started(ctx, corrupted_zip())
    pid = d["package"]["package_id"]
    upload(ctx, ref, "corrected_file.csv", read(SEP, CORRUPT), CORRUPT)        # the existing upload_evidence path
    d = settle(ctx, ref)
    v = ctx.svc.load(pid).latest(CORRUPT)
    assert v is not None and v.version_status == "VALIDATED" and v.version_number == 1
    assert d["progress"]["validation"]["state"] == "PASSED" and d["actions"]["activate"]["enabled"]
    [o] = d["outstanding"]["unreadable_members"]
    assert o["open"] is False and o["hint"] is None
    assert any("no required evidence is missing now" in s for s in d["progress"]["summary"])
    up = events(ctx, "ANALYST_EVIDENCE_UPLOADED")[-1]["details"]
    assert up["kind"] == "missing" and up["evidence_category"] == CORRUPT
    out = R(ctx, "POST", f"cases/{ref}/activate", {"confirm": True})
    assert out["activated"] and out["snapshot_id"]
    d = R(ctx, "GET", f"cases/{ref}")
    assert d["outstanding"]["unreadable_members"] == []                         # O5: nothing can be added any more
    assert any("the package is activated" in s for s in d["progress"]["summary"])
    assert err(lambda: upload(ctx, ref, "again.csv", read(SEP, CORRUPT), CORRUPT)) == "PACKAGE_LOCKED"
    assert d["runs"][0]["unreadable_entries"][0]["name"] == MEMBER              # the run record keeps the fact


def test_category_of_the_corrected_file_is_decided_by_content(tmp_path):
    ctx = ctx_for(tmp_path)
    ref, d = started(ctx, corrupted_zip())
    pid = d["package"]["package_id"]
    upload(ctx, ref, name(CORRUPT), read(SEP, "IN-01"), CORRUPT)              # wrong content behind the right name (O7)
    settle(ctx, ref)
    v = ctx.svc.load(pid).latest(CORRUPT)
    assert v is None or v.version_status != "VALIDATED"
    assert R(ctx, "GET", f"cases/{ref}")["progress"]["validation"]["state"] != "PASSED"


@needs_uc042
def test_isolated_run_reconciles_with_the_real_engine_after_the_corrected_upload(tmp_path):
    ctx = ctx_for(tmp_path, engine=True)
    ref, d = started(ctx, corrupted_zip())
    upload(ctx, ref, "corrected_file.csv", read(SEP, CORRUPT), CORRUPT)
    settle(ctx, ref)
    assert R(ctx, "POST", f"cases/{ref}/activate", {"confirm": True})["activated"]
    R(ctx, "POST", f"cases/{ref}/reconcile")
    d = settle(ctx, ref, 600)
    assert d["status"] == "COMPLETED" and d["completed"]["case_status"] == "CLEAN"


# ----------------------------------------------------------------------------------------------- O6 unchanged
def test_whole_archive_failures_still_fail_the_run(tmp_path):
    ctx = ctx_for(tmp_path)
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("submission/", "")
        z.writestr("__MACOSX/._x.csv", "meta")
    one = io.BytesIO()
    with zipfile.ZipFile(one, "w") as z:
        z.writestr("submission/only.csv", read(SEP, "IN-01"))
    cases = {"INVALID_ZIP": b"PK\x03\x04 truncated archive", "EMPTY_ZIP": b.getvalue(),
             "ZIP_UNREADABLE": corrupt_crc(one.getvalue(), "submission/only.csv")}
    for i, (code, data) in enumerate(cases.items()):
        ref = new_case(ctx, f"Customer {i}", data=data)["case_ref"]
        d = R(ctx, "POST", f"cases/{ref}/start")
        assert d["current_run"]["status"] == "FAILED" and d["current_run"]["failure"]["code"] == code, code
        assert d["actions"]["retry_from_beginning"]["enabled"]
        assert not staging_dirs(ctx)                                           # nothing staged, nothing orphaned
        R(ctx, "POST", f"cases/{ref}/defer")
    assert [e["details"]["code"] for e in events(ctx, "CASE_RUN_FAILED")] == list(cases)
    run = R(ctx, "GET", f"cases/{ref}")["runs"][0]
    assert run["staged_entries"] == 0 and run["unreadable_entries"][0]["name"] == "submission/only.csv"


def test_stage_cleans_up_when_staging_fails_part_way(tmp_path, monkeypatch):
    ctx = ctx_for(tmp_path)
    real, n = ctx._stage_one, {"n": 0}

    def flaky(*a, **k):
        n["n"] += 1
        if n["n"] == 5:
            raise OSError("simulated disk failure")
        return real(*a, **k)
    monkeypatch.setattr(ctx, "_stage_one", flaky)
    with pytest.raises(OSError):
        ctx.stage("submission.zip", corrupted_zip())
    assert not staging_dirs(ctx)


def test_damaged_compressed_data_is_isolated_too(tmp_path):
    ctx = ctx_for(tmp_path)
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("a/good.csv", read(SEP, "IN-01"))
        z.writestr("a/bad.csv", read(SEP, "IN-03"))
    raw = bytearray(b.getvalue())
    info = zipfile.ZipFile(io.BytesIO(bytes(raw))).getinfo("a/bad.csv")
    start = info.header_offset + 30 + len(info.filename)
    for k in range(start + 10, start + 40):
        raw[k] ^= 0xFF
    out = ctx.stage("x.zip", bytes(raw))
    good, bad = out
    assert good["staging_id"] and good["name"] == "good.csv"
    assert bad["staging_id"] is None and bad["unreadable"] and bad["error_kind"] in ("DECOMPRESSION_ERROR", "CRC_FAILURE")
    assert len(staging_dirs(ctx)) == 1


# ----------------------------------------------------------------------------------------------- O1 unchanged
def test_o1_retry_semantics_are_unchanged_for_an_isolated_member(tmp_path):
    ctx = ctx_for(tmp_path)
    ref, d = started(ctx, corrupted_zip())
    # an isolated member is not a failed run: there is nothing to retry
    assert err(lambda: R(ctx, "POST", f"cases/{ref}/retry", {"confirm": True})) == "RUN_NOT_FAILED"
    # a technical failure in the same case still fails, and the retry re-reads the ORIGINAL ZIP (no carry-forward)
    ctx2 = ctx_for(tmp_path / "b")
    fail_first_validation(ctx2)
    ref2, d = started(ctx2, corrupted_zip())
    run1 = d["runs"][0]
    assert run1["status"] == "FAILED" and run1["failure"]["code"] == "INTAKE_JOB_FAILED"
    assert run1["unreadable_entries"][0]["name"] == MEMBER
    R(ctx2, "POST", f"cases/{ref2}/retry", {"confirm": True})
    d = settle(ctx2, ref2)
    run2 = d["runs"][1]
    assert run2["retry_of"] == run1["run_id"] and run2["evidence_source"] == "ORIGINAL_ZIP"
    assert run2["status"] == "COMPLETED" and run2["staged_entries"] == 16
    assert [u["name"] for u in run2["unreadable_entries"]] == [MEMBER]        # the same original ZIP, read again
    assert run2["not_carried_forward"] == []
    assert ctx2.svc.load(run2["package_id"]).latest(CORRUPT) is None
    assert [m["category"] for m in d["outstanding"]["missing_categories"]] == [CORRUPT]


def test_case_recorded_before_this_change_keeps_its_history(tmp_path):
    ctx = ctx_for(tmp_path)
    ref, d = started(ctx, corrupted_zip())
    c = ctx.cases.load(ref)                                     # simulate a stale record: no unreadable_entries key
    c["runs"][0].pop("unreadable_entries")
    ctx.cases._save(c)
    d = R(ctx, "GET", f"cases/{ref}")
    assert d["outstanding"]["unreadable_members"] == [] and d["progress"]["unreadable_members"] == []
    assert d["runs"][0]["status"] == "COMPLETED"
