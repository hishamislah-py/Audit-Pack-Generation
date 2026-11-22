"""Independent ZIP submissions (approved 17 Nov 2026): safe reading and strict schema membership of one ZIP per period,
the completeness gate, the explicit Submit for Audit action (a new submission and a new run every time, also for an
identical package), no inheritance from earlier uploads, runs or packs, the RUN_IN_PROGRESS guard, analyst decisions and
reviews scoped to one submission (migration 0006), and final-pack traceability (submission -> batch -> run -> final pack)
with earlier final packs unchanged.

Every test runs on temporary folders and a temporary SQLite database (or the disposable PostgreSQL test database with
UC042_TEST_REPOSITORIES=postgres). Documents are read from uc042_dataset/ (never written). Offline: the real
OpenAIInvestigator with its HTTP client mocked; no live provider call is possible.
Run from uc042/: python -m unittest tests.test_zip_submissions -v"""
import io
import json
import stat
import unittest
import zipfile
from unittest import mock

from tests.api_support import AI_OK, MockProvider
from tests.final_pack_support import OFFLINE, raw, sha_tree
from tests.test_api_monthly import MonthlyCase, scenario_files
from tests.view_fixtures import packet_from_message
from uc042app.ingest import zip_package as Z
from uc042lib.investigation.models import LLMInvestigationOutput
from uc042lib.period import PeriodConfig

SEP = PeriodConfig(2026, 9)
FILES = dict(scenario_files())  # the 19 September documents of scenario S05, named by the central schema
IN04, IN11, IN14, IN17, IN19 = (SEP.filename(f) for f in ("IN-04", "IN-11", "IN-14", "IN-17", "IN-19"))


def make_zip(entries, compression=zipfile.ZIP_DEFLATED):
    """entries: {name: bytes} or [(name, bytes | ZipInfo-modifier)]."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as zf:
        for name, data in (entries.items() if isinstance(entries, dict) else entries):
            zf.writestr(name, data)
    return buf.getvalue()


def set_encrypted(data, name):
    """Set the 'encrypted' flag bit of one entry (local header and central directory): zipfile's writer clears it."""
    buf, enc = bytearray(data), name.encode()
    for sig, flag_at, len_at, name_at in ((b"PK\x03\x04", 6, 26, 30), (b"PK\x01\x02", 8, 28, 46)):
        i = buf.find(sig)
        while i != -1:
            n = int.from_bytes(buf[i + len_at:i + len_at + 2], "little")
            if bytes(buf[i + name_at:i + name_at + n]) == enc:
                buf[i + flag_at] |= 0x1
            i = buf.find(sig, i + 4)
    return bytes(buf)


def files(skip=(), extra=None, replace=None):
    out = {k: v for k, v in FILES.items() if k not in skip}
    out.update(replace or {})
    out.update(extra or {})
    return out


def header_only(name):
    return FILES[name].split(b"\n", 1)[0] + b"\n"


# ---------------------------------------------------------------------------------------------- reading (no application)
class Reading(unittest.TestCase):
    def test_a_complete_package_maps_every_file_through_the_central_schema(self):
        inv, got = Z.read_package(make_zip(FILES), SEP)
        self.assertEqual(sorted(f for _, _, f, _ in got), sorted(SEP.required_ids + SEP.optional_ids))
        self.assertEqual((inv["unsafe"], inv["unexpected"], inv["duplicate_names"], inv["duplicate_types"]), ([], [], [], {}))
        self.assertTrue(inv["archive_safe"])
        for name, _, fid, _ in got:  # the mapping IS PeriodConfig's (no second schema)
            self.assertEqual(SEP.file_id_of(name), fid)

    def test_folders_inside_the_zip_are_flattened(self):
        inv, got = Z.read_package(make_zip({f"docs/sep/{k}": v for k, v in FILES.items()}), SEP)
        self.assertEqual(len(got), 19)
        self.assertEqual(inv["unexpected"], [])

    def test_operating_system_metadata_is_listed_and_ignored(self):
        inv, got = Z.read_package(make_zip(files(extra={"__MACOSX/._x.csv": b"x", ".DS_Store": b"x", "docs/Thumbs.db": b"x",
                                                        "desktop.ini": b"x", "._recon.csv": b"x"})), SEP)
        self.assertEqual(sorted(inv["ignored_metadata"]), sorted(["__MACOSX/._x.csv", ".DS_Store", "docs/Thumbs.db", "desktop.ini", "._recon.csv"]))
        self.assertEqual((len(got), inv["unexpected"]), (19, []))

    def test_unexpected_and_wrong_period_files_are_reported_with_the_reason(self):
        inv, _ = Z.read_package(make_zip(files(extra={"notes.txt": b"hello", "transactions_2026-08.csv": FILES[IN11],
                                                      "rep027_submission_receipt_2026-09.pdf": FILES[IN19]})), SEP)
        why = {u["name"]: u["reason"] for u in inv["unexpected"]}
        self.assertIn("not a file of the approved UC-042 schema", why["notes.txt"])
        self.assertIn("another reporting period (2026-08)", why["transactions_2026-08.csv"])
        self.assertIn("receipt for the previous month (2026-08)", why["rep027_submission_receipt_2026-09.pdf"])

    def test_nested_zip_is_unexpected(self):
        inv, _ = Z.read_package(make_zip(files(extra={"inner.zip": make_zip({"a.csv": b"a"}), "disguised.csv": make_zip({"a": b"a"})})), SEP)
        self.assertEqual(sorted(u["name"] for u in inv["unexpected"]), ["disguised.csv", "inner.zip"])
        self.assertTrue(all("nested ZIP" in u["reason"] for u in inv["unexpected"]))

    def test_unsafe_entries_reject_every_file(self):
        for name, reason in (("/etc/x.csv", "absolute path"), ("\\x.csv", "absolute path"), ("../x.csv", "path traversal"),
                             ("a/../../x.csv", "path traversal"), ("C:/x.csv", "Windows drive path"), ("c:x.csv", "Windows drive path")):
            with self.subTest(name=name):
                inv, got = Z.read_package(make_zip(files(extra={name: b"x"})), SEP)
                self.assertEqual(got, [])  # nothing reaches document analysis
                self.assertFalse(inv["archive_safe"])
                stored = name.replace("\\", "/")  # zipfile stores '\' as '/' when writing on Windows
                self.assertIn(reason, next(u["reason"] for u in inv["unsafe"] if u["name"].replace("\\", "/") == stored))

    def test_symlink_and_encrypted_entries_are_unsafe(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for k, v in FILES.items():
                zf.writestr(k, v)
            link = zipfile.ZipInfo("link.csv")
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(link, "/etc/passwd")
            zf.writestr("enc.csv", b"secret")
        inv, got = Z.read_package(set_encrypted(buf.getvalue(), "enc.csv"), SEP)
        self.assertEqual(got, [])
        why = {u["name"]: u["reason"] for u in inv["unsafe"]}
        self.assertEqual((why["link.csv"], why["enc.csv"]), ("symbolic link", "encrypted entry"))

    def test_duplicate_flattened_names_and_duplicate_types(self):
        inv, _ = Z.read_package(make_zip(files(extra={f"a/{IN11}": FILES[IN11], "safeguarding_reconciliation_policy_v1.1.pdf": FILES[IN17]})), SEP)
        self.assertEqual(inv["duplicate_names"], [{"name": IN11, "paths": [IN11, f"a/{IN11}"]}])
        self.assertEqual(sorted(inv["duplicate_types"]["IN-17"]), sorted([IN17, "safeguarding_reconciliation_policy_v1.1.pdf"]))
        inv, _ = Z.read_package(make_zip(files(extra={IN11.upper(): FILES[IN11]})), SEP)  # case-insensitive file systems
        self.assertEqual(len(inv["duplicate_names"]), 1)

    def test_limits_entries_size_total_and_ratio(self):
        data = make_zip(FILES)
        inv, got = Z.read_package(data, SEP, Z.ZipLimits(max_entries=5))
        self.assertIn("at most 5", inv["unsafe"][0]["reason"])
        self.assertEqual(got, [])
        inv, _ = Z.read_package(data, SEP, Z.ZipLimits(max_file_bytes=1000))
        self.assertTrue(any("bytes uncompressed" in u["reason"] for u in inv["unsafe"]))
        inv, _ = Z.read_package(data, SEP, Z.ZipLimits(max_total_bytes=20000))
        self.assertTrue(any("in total" in u["reason"] for u in inv["unsafe"]))
        bomb = make_zip({IN11: b"0" * 2_000_000})
        inv, got = Z.read_package(bomb, SEP)
        self.assertIn("compression ratio", inv["unsafe"][0]["reason"])
        with self.assertRaises(Z.PackageRejected) as e:
            Z.read_package(data, SEP, Z.ZipLimits(max_archive_bytes=100))
        self.assertEqual(e.exception.code, "PACKAGE_TOO_LARGE")

    def test_not_a_zip_and_corrupt_archives_are_rejected(self):
        with self.assertRaises(Z.PackageRejected) as e:
            Z.read_package(b"%PDF-1.7 not a zip", SEP)
        self.assertEqual(e.exception.code, "NOT_A_ZIP")
        with self.assertRaises(Z.PackageRejected) as e:
            Z.read_package(b"PK\x03\x04" + b"\x00" * 50, SEP)
        self.assertEqual(e.exception.code, "PACKAGE_UNREADABLE")

    def test_limits_are_configurable_and_validated(self):
        self.assertEqual(Z.ZipLimits.from_env({"UC042_ZIP_MAX_ENTRIES": "25"}).max_entries, 25)
        self.assertEqual(Z.ZipLimits.from_env({}), Z.ZipLimits())
        for bad in ("0", "-1", "x"):
            with self.assertRaises(ValueError):
                Z.ZipLimits.from_env({"UC042_ZIP_MAX_RATIO": bad})

    def test_no_smart_parser_fallback(self):
        self.assertIsNone(Z.resolve_unexpected("anything.csv", b"x"))
        self.assertEqual(Z.map_filename("txns_sept.csv", SEP)[0], None)


# ---------------------------------------------------------------------------------------------- the API (gate, submissions)
class ZipCase(MonthlyCase):
    LEGACY_ENTRY_POINTS = False  # ZIP-only operation: the retired individual-document entry points must refuse

    def upload_zip(self, data, period_id="PER-2026-09", name="september.zip", expect=201):
        r = self.client.post(f"/api/v1/periods/{period_id}/packages", files=[("file", (name, io.BytesIO(data), "application/zip"))])
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    def submit(self, batch_id, expect=202, body=None):
        r = self.post(f"/api/v1/uploads/{batch_id}/submit", body if body is not None else {"ai_authorization": AI_OK})
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    def finish(self, run):
        self.svc.runner.wait(run["job_id"], timeout=180)
        run = self.get(f"/api/v1/processing-runs/{run['run_id']}").json()
        for i in (run["result"].get("auto_investigation") or {}).get("items") or []:
            if i.get("job_id"):
                self.svc.runner.wait(i["job_id"], 120)
        return run

    def gate(self, detail):
        return detail["batch"]["summary"]["package"]["gate"]

    def runs(self):
        return self.svc.repos.runs.list()

    def assert_rejected(self, detail, status="PACKAGE_REJECTED"):
        self.assertEqual(detail["batch"]["status"], status)
        self.assertFalse(self.gate(detail)["passed"])
        before = len(self.runs())
        r = self.post(f"/api/v1/uploads/{detail['batch']['batch_id']}/submit", {"ai_authorization": AI_OK})
        self.assertEqual((r.status_code, r.json()["code"]), (409, "PACKAGE_NOT_COMPLETE"))
        self.assertEqual(len(self.runs()), before)  # no audit run is created on failure


class Gate(ZipCase):
    def setUp(self):
        super().setUp()
        self.provider.respond = lambda kw: (_ for _ in ()).throw(RuntimeError("no AI in gate tests"))

    def test_complete_package_passes_and_reports_every_document(self):
        d = self.upload_zip(make_zip(files(extra={".DS_Store": b"x"})))
        g = self.gate(d)
        self.assertTrue(g["passed"], g)
        self.assertEqual(d["batch"]["status"], "VALIDATED")
        self.assertEqual(d["batch"]["origin"], "ZIP_SUBMISSION")
        self.assertEqual((g["present_required"], g["missing_required"]), (sorted(SEP.required_ids), []))
        self.assertEqual(g["present_optional"], ["IN-18", "IN-19"])
        self.assertEqual((g["unexpected"], g["mismatches"], g["unusable"], g["duplicate_types"], g["ignored_metadata"]),
                         ([], [], [], {}, [".DS_Store"]))
        self.assertEqual(len(d["documents"]), 19)
        self.assertEqual(self.runs(), [])  # validation never processes
        self.assertEqual(self.get("/api/v1/periods/PER-2026-09").json()["current_set"], {})  # never in the accumulated set

    def test_missing_required_document_fails_and_lists_it(self):
        d = self.upload_zip(make_zip(files(skip=(IN11,))))
        self.assertEqual(self.gate(d)["missing_required"], ["IN-11"])
        self.assert_rejected(d, "PACKAGE_INCOMPLETE")

    def test_optional_documents_may_be_absent(self):
        d = self.upload_zip(make_zip(files(skip=(IN19, SEP.filename("IN-18")))))
        g = self.gate(d)
        self.assertTrue(g["passed"], g)
        self.assertEqual(g["present_optional"], [])

    def test_in04_and_in14_may_be_empty(self):
        d = self.upload_zip(make_zip(files(replace={IN04: header_only(IN04), IN14: header_only(IN14)})))
        self.assertTrue(self.gate(d)["passed"], self.gate(d))

    def test_unexpected_file_rejects_the_whole_package_without_analysis(self):
        d = self.upload_zip(make_zip(files(extra={"notes.txt": b"x"})))
        self.assertEqual([u["name"] for u in self.gate(d)["unexpected"]], ["notes.txt"])
        self.assertEqual(d["documents"], [])  # nothing reached document analysis
        self.assert_rejected(d)

    def test_duplicate_document_type_rejects(self):
        d = self.upload_zip(make_zip(files(extra={"safeguarding_reconciliation_policy_v1.1.pdf": FILES[IN17]})))
        self.assertIn("IN-17", self.gate(d)["duplicate_types"])
        self.assert_rejected(d)

    def test_duplicate_flattened_names_reject(self):
        d = self.upload_zip(make_zip(files(extra={f"copy/{IN11}": FILES[IN11]})))
        self.assertEqual(self.gate(d)["duplicate_names"][0]["name"], IN11)
        self.assert_rejected(d)

    def test_wrong_period_package_is_rejected(self):
        self.open_period(2026, 10)
        d = self.upload_zip(make_zip(FILES), period_id="PER-2026-10")
        self.assertTrue(all("another reporting period" in u["reason"] or "previous month" in u["reason"]
                            for u in self.gate(d)["unexpected"] if u["name"] != "account_inventory.csv"))
        self.assert_rejected(d)

    def test_filename_content_mismatch_fails(self):
        cal = SEP.filename("IN-01")
        d = self.upload_zip(make_zip(files(replace={cal: FILES[IN11], IN11: FILES[cal]})))
        mm = {m["name"]: m for m in self.gate(d)["mismatches"]}
        self.assertEqual((mm[cal]["by_name"], mm[cal]["by_content"]), ("IN-01", "IN-11"))
        self.assert_rejected(d, "PACKAGE_INCOMPLETE")

    def test_unreadable_required_document_fails(self):
        d = self.upload_zip(make_zip(files(replace={SEP.filename("IN-15"): b"%PDF-1.4 garbage, not a readable PDF"})))
        g = self.gate(d)
        self.assertFalse(g["passed"])
        self.assertTrue(g["mismatches"] or g["unusable"], g)
        self.assert_rejected(d, "PACKAGE_INCOMPLETE")

    def test_unsafe_and_nested_packages_are_rejected_with_their_names(self):
        for extra in ({"../evil.csv": b"x"}, {"inner.zip": make_zip({"a.csv": b"a"})}):
            with self.subTest(extra=list(extra)):
                d = self.upload_zip(make_zip(files(extra=extra)))
                g = self.gate(d)
                self.assertIn(list(extra)[0].rsplit("/", 1)[-1], json.dumps(g["unsafe"] + g["unexpected"]))
                self.assertEqual(d["documents"], [])
                self.assert_rejected(d)

    def test_not_a_zip_is_recorded_as_rejected(self):
        d = self.upload_zip(b"plain text, not an archive")
        self.assertEqual(d["batch"]["summary"]["package"]["error"]["code"], "NOT_A_ZIP")
        self.assertEqual(d["batch"]["status"], "PACKAGE_REJECTED")


class Independence(ZipCase):
    def setUp(self):
        super().setUp()
        self.provider.respond = lambda kw: (_ for _ in ()).throw(RuntimeError("provider unreachable (offline test)"))

    def test_each_submit_is_a_new_submission_and_run_identical_packages_included(self):
        data = make_zip(FILES)
        a, b = self.upload_zip(data), self.upload_zip(data)
        self.assertNotEqual(a["batch"]["batch_id"], b["batch"]["batch_id"])
        self.assertEqual(a["batch"]["summary"]["package"]["zip_sha256"], b["batch"]["summary"]["package"]["zip_sha256"])
        r1 = self.finish(self.submit(a["batch"]["batch_id"]))
        r2 = self.finish(self.submit(b["batch"]["batch_id"]))
        r3 = self.finish(self.submit(a["batch"]["batch_id"]))  # the same package again: still a new submission and run
        subs = [r["result"]["submission_id"] for r in (r1, r2, r3)]
        self.assertEqual(len(set(subs)), 3)
        self.assertEqual(len({r["run_id"] for r in (r1, r2, r3)}), 3)
        self.assertTrue(all(r["status"] == "SUCCEEDED" and r["result"]["purpose"] == "SUBMISSION" for r in (r1, r2, r3)))
        # deterministic engine identity is unchanged: identical inputs, identical content-addressed pack
        self.assertEqual(len({r["result"]["pack_id"] for r in (r1, r2, r3)}), 1)
        self.assertEqual(r1["result"]["outcome"], "PUBLISHED")
        self.assertEqual((r2["result"]["outcome"], r3["result"]["outcome"]), ("ALREADY_EXISTS", "ALREADY_EXISTS"))
        # each run processed only its own package's documents
        own = {d["document_id"] for d in a["documents"]}
        self.assertTrue(set(r1["result"]["document_set"].values()) <= own)
        self.assertTrue(set(r2["result"]["document_set"].values()).isdisjoint(own))
        # history: two packages, three separate entries, newest package first
        hist = self.get("/api/v1/periods/PER-2026-09/submissions").json()
        by_batch = {p["batch_id"]: p for p in hist}  # (package order within one second is not asserted: second precision)
        self.assertEqual(set(by_batch), {a["batch"]["batch_id"], b["batch"]["batch_id"]})
        self.assertEqual([s["submission_id"] for s in by_batch[a["batch"]["batch_id"]]["submissions"]], [subs[0], subs[2]])
        self.assertEqual([s["submission_id"] for s in by_batch[b["batch"]["batch_id"]]["submissions"]], [subs[1]])
        self.assertTrue(all(s["status"] == "SUCCEEDED" and s["final_packs"] == [] for p in hist for s in p["submissions"]))
        # fresh per submission: every submission's run queued its own investigations (none skipped as already investigated)
        for r in (r1, r2, r3):
            items = r["result"]["auto_investigation"]["items"]
            self.assertTrue(items and all(i["outcome"] == "QUEUED" for i in items), items)

    def test_run_in_progress_is_refused(self):
        d = self.upload_zip(make_zip(FILES))
        with mock.patch.object(self.svc.runner, "submit"):  # the run stays QUEUED
            first = self.submit(d["batch"]["batch_id"])
            self.assertEqual(first["status"], "QUEUED")
            r = self.post(f"/api/v1/uploads/{d['batch']['batch_id']}/submit", {"ai_authorization": AI_OK})
        self.assertEqual((r.status_code, r.json()["code"]), (409, "RUN_IN_PROGRESS"))
        self.assertEqual(len(self.runs()), 1)



class WithHistoricalLegacyBatches(ZipCase):
    """Individual-document batches can only exist as historical records now (ZIP-only operation): the retired workflow is
    enabled in code here to create them, and the ZIP path must still ignore them."""
    LEGACY_ENTRY_POINTS = True

    def setUp(self):
        super().setUp()
        self.provider.respond = lambda kw: (_ for _ in ()).throw(RuntimeError("provider unreachable (offline test)"))

    def test_only_zip_packages_can_be_submitted(self):
        b = self.upload("PER-2026-09", scenario_files())
        r = self.post(f"/api/v1/uploads/{b['batch']['batch_id']}/submit", {"ai_authorization": AI_OK})
        self.assertEqual((r.status_code, r.json()["code"]), (422, "NOT_A_PACKAGE"))

    def test_no_inheritance_from_earlier_packages_or_uploads(self):
        self.finish(self.submit(self.upload_zip(make_zip(FILES))["batch"]["batch_id"]))
        b = self.upload("PER-2026-09", [(IN11, FILES[IN11])])  # a legacy upload of the missing file is not borrowed either
        self.post(f"/api/v1/uploads/{b['batch']['batch_id']}/confirm")
        d = self.upload_zip(make_zip(files(skip=(IN11,))))
        self.assertEqual(self.gate(d)["missing_required"], ["IN-11"])
        self.assert_rejected(d, "PACKAGE_INCOMPLETE")
        # and the legacy accumulated set never includes a ZIP package's documents
        zip_docs = {x["document_id"] for x in d["documents"]}
        self.assertTrue(zip_docs and zip_docs.isdisjoint(self.get("/api/v1/periods/PER-2026-09").json()["current_set"].values()))

# ---------------------------------------------------------------------------------------------- through to final packs
class Answers:
    """Investigations answered from the request's own evidence packet (the offline stub's content); closing summaries by
    the MockProvider. Controlled fixtures, not provider calls."""

    def __init__(self, provider):
        self.mock, self.calls = MockProvider(), 0
        provider.respond = self.respond

    def respond(self, kw):
        content = kw["input"][0]["content"]
        if "<audit_pack_input>" in content:
            return self.mock.respond(kw)
        self.calls += 1  # a fresh model call words its findings afresh (the offline stub alone would repeat them exactly)
        out = OFFLINE.investigate(packet_from_message(content))[0].model_dump()
        out["investigation_summary"] = f"{out['investigation_summary']} (investigation call {self.calls})"
        return raw(LLMInvestigationOutput.model_validate(out))


class SubmissionReview(ZipCase):
    def setUp(self):
        super().setUp()
        Answers(self.provider)

    def submitted(self, data):
        d = self.upload_zip(data)
        run = self.finish(self.submit(d["batch"]["batch_id"]))
        self.assertEqual(run["status"], "SUCCEEDED", run)
        return d["batch"]["batch_id"], run

    def produced(self, run):
        return self.svc.auto_investigations.submission_investigations(self.svc.repos.runs.get(run["run_id"]))

    def review_to_final_pack(self, run):
        sub, pack_id = run["result"]["submission_id"], run["result"]["pack_id"]
        produced = self.produced(run)
        self.assertTrue(produced)
        r = self.post(f"/api/v1/packs/{pack_id}/reviews", {"submission_id": sub})
        self.assertEqual(r.status_code, 201, r.text)
        s = r.json()
        self.assertEqual((s["submission_id"], s["run_id"], s["batch_id"]), (sub, run["run_id"], run["batch_id"]))
        included = {x["exception_id"]: x["investigation_id"] for x in s["selections"] if x["inclusion"] == "INCLUDED"}
        self.assertEqual(included, produced)  # only this submission's own investigations
        self.assertIn("AI_REVIEW_PENDING", [b["code"] for b in s["readiness"]["blockers"]])  # no decision is inherited
        for inv in produced.values():
            a = self.post(f"/api/v1/investigations/{inv}/analyst-review",
                          {"decision": "ACCEPT", "comment": f"checked for {sub}", "expected_revision": 0, "submission_id": sub})
            self.assertEqual(a.status_code, 201, a.text)
            self.assertEqual(a.json()["submission_id"], sub)
        r = self.post(f"/api/v1/reviews/{s['review_id']}/preview", {"authorization": AI_OK})
        self.assertEqual(r.status_code, 202, r.text)
        self.wait_job(r.json()["job_id"], 120)
        s = self.get(f"/api/v1/reviews/{s['review_id']}").json()
        self.assertTrue(s["readiness"]["ready"], s["readiness"])
        g = self.post(f"/api/v1/reviews/{s['review_id']}/decision", {"decision": "GENERATE", "acknowledgement_accepted": True,
                                                                     "snapshot_sha256": s["current_preview"]["snapshot_sha256"]})
        self.assertEqual(g.status_code, 201, g.text)
        return g.json()["final_pack"]["final_pack_id"], produced

    def test_identical_submissions_get_separate_reviews_decisions_and_final_packs(self):
        data = make_zip(FILES)
        batch_a, run_a = self.submitted(data)
        fp_a, produced_a = self.review_to_final_pack(run_a)
        fp_a_dir = next(r / fp_a for r in self.svc.final_packs.roots() if (r / fp_a).is_dir())
        fp_a_before = sha_tree(fp_a_dir)

        batch_b, run_b = self.submitted(data)  # the identical ZIP, uploaded and submitted again
        self.assertEqual(run_b["result"]["pack_id"], run_a["result"]["pack_id"])
        sub_a, sub_b = run_a["result"]["submission_id"], run_b["result"]["submission_id"]
        self.assertNotEqual(sub_a, sub_b)
        # A's decisions do not count in B's review: B's review opens with every investigation pending
        fp_b, produced_b = self.review_to_final_pack(run_b)
        self.assertNotEqual(fp_a, fp_b)
        self.assertEqual(sha_tree(fp_a_dir), fp_a_before)  # the earlier final pack is unchanged

        listing = {f["final_pack_id"]: f for f in self.get("/api/v1/final-packs").json()}
        self.assertEqual((listing[fp_a]["submission_id"], listing[fp_a]["run_id"], listing[fp_a]["batch_id"]),
                         (sub_a, run_a["run_id"], batch_a))
        self.assertEqual((listing[fp_b]["submission_id"], listing[fp_b]["run_id"], listing[fp_b]["batch_id"]),
                         (sub_b, run_b["run_id"], batch_b))
        self.assertNotEqual(listing[fp_a]["generated_at"], "")
        detail = self.get(f"/api/v1/final-packs/{fp_b}").json()
        self.assertEqual(detail["record"]["submission_id"], sub_b)
        hist = {s["submission_id"]: s for p in self.get("/api/v1/periods/PER-2026-09/submissions").json() for s in p["submissions"]}
        self.assertEqual([f["final_pack_id"] for f in hist[sub_a]["final_packs"]], [fp_a])
        self.assertEqual([f["final_pack_id"] for f in hist[sub_b]["final_packs"]], [fp_b])
        # each submission's decisions are kept in its own scope
        inv = next(iter(produced_b.values()))
        self.assertEqual([x["submission_id"] for x in self.get(f"/api/v1/investigations/{inv}/analyst-reviews?submission_id={sub_b}").json()], [sub_b])
        self.assertEqual(self.get(f"/api/v1/investigations/{inv}/analyst-reviews").json(), [])  # no legacy decision was made

    def test_submission_scoping_is_enforced(self):
        _, run_a = self.submitted(make_zip(FILES))
        sub_a, pack_id = run_a["result"]["submission_id"], run_a["result"]["pack_id"]
        # a pack the submission did not produce
        other = next(p["pack_id"] for p in self.get("/api/v1/periods/PER-2026-09").json()["period"]["packs"] if p["pack_id"] != pack_id)
        r = self.post(f"/api/v1/packs/{other}/reviews", {"submission_id": sub_a})
        self.assertEqual((r.status_code, r.json()["code"]), (409, "SUBMISSION_PACK_MISMATCH"))
        r = self.post(f"/api/v1/packs/{pack_id}/reviews", {"submission_id": "SUB-" + "0" * 24})
        self.assertEqual(r.status_code, 404)
        r = self.post(f"/api/v1/packs/{pack_id}/reviews", {"submission_id": "not-an-id"})
        self.assertEqual(r.status_code, 422)
        # active reviews are keyed by (pack, submission): another submission's review of the same pack opens independently
        ra = self.post(f"/api/v1/packs/{pack_id}/reviews", {"submission_id": sub_a})
        self.assertEqual(ra.status_code, 201)
        _, run_b = self.submitted(make_zip(FILES))
        r = self.post(f"/api/v1/packs/{pack_id}/reviews", {"submission_id": run_b["result"]["submission_id"]})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertNotEqual(r.json()["review_id"], ra.json()["review_id"])
        again = self.post(f"/api/v1/packs/{pack_id}/reviews", {"submission_id": sub_a})  # A's own active review is returned
        self.assertEqual((again.status_code, again.json()["review_id"]), (200, ra.json()["review_id"]))
        # a decision scoped to a submission must concern an investigation produced for it
        inv = next(iter(self.produced(run_a).values()))
        r = self.post(f"/api/v1/investigations/{inv}/analyst-review",
                      {"decision": "ACCEPT", "expected_revision": 0, "submission_id": "SUB-" + "0" * 24})
        self.assertIn(r.status_code, (404, 409, 422), r.text)
        self.assertEqual(self.svc.repos.investigation_reviews.list(investigation_id=inv), [])
class IdenticalAnswers(Answers):
    """A model answering an identical evidence packet with identical findings (no per-call variation). `hold`, when set,
    keeps investigation calls waiting (to have one submission's jobs still running when the next one is submitted)."""
    hold = None

    def respond(self, kw):
        content = kw["input"][0]["content"]
        if "<audit_pack_input>" in content:
            return self.mock.respond(kw)
        if self.hold is not None:
            self.hold.wait(60)
        return raw(LLMInvestigationOutput.model_validate(OFFLINE.investigate(packet_from_message(content))[0].model_dump()))


class IdenticalFindings(SubmissionReview):
    """The audit run is the investigation execution scope (17 Nov 2026): two identical ZIP submissions whose models return
    word-for-word identical findings each execute and persist their own investigations (own artefacts, own execution
    metadata, own analyst decisions); nothing is compared with, rejected because of, or reused from the other submission,
    and nothing earlier is overwritten."""
    # the inherited tests use varying answers (SubmissionReview); only the identical-answer cases run here
    test_identical_submissions_get_separate_reviews_decisions_and_final_packs = None
    test_submission_scoping_is_enforced = None

    def setUp(self):
        super().setUp()
        self.answers = IdenticalAnswers(self.provider)

    def jobs_of(self, run):
        return self.svc.auto_investigations.submission_jobs(self.svc.repos.runs.get(run["run_id"]))

    def artefact(self, inv):
        return next(p for p in self.inv_root.rglob(inv) if p.is_dir())

    def test_identical_submissions_each_execute_and_persist_their_own_investigations(self):
        from uc042lib.investigation.persistence import investigation_id_from_findings, verify_published
        data = make_zip(FILES)
        batch_a, run_a = self.submitted(data)
        produced_a = self.produced(run_a)
        dirs_a = {inv: self.artefact(inv) for inv in produced_a.values()}
        trees_a = {inv: sha_tree(d) for inv, d in dirs_a.items()}
        fp_a, _ = self.review_to_final_pack(run_a)
        fp_a_dir = next(r / fp_a for r in self.svc.final_packs.roots() if (r / fp_a).is_dir())
        fp_before = sha_tree(fp_a_dir)

        batch_b, run_b = self.submitted(data)  # identical ZIP, identical model answers
        produced_b = self.produced(run_b)
        jobs_a, jobs_b = self.jobs_of(run_a), self.jobs_of(run_b)
        self.assertEqual(set(produced_b), set(produced_a))  # every exception investigated again, none skipped or refused
        self.assertTrue(set(produced_a.values()).isdisjoint(produced_b.values()))  # separate artefacts, separate IDs
        self.assertTrue(all(j["status"] == "COMPLETED" and j["result"]["persist_outcome"] == "PUBLISHED" for j in jobs_b.values()), jobs_b)
        self.assertTrue({j["job_id"] for j in jobs_a.values()}.isdisjoint(j["job_id"] for j in jobs_b.values()))
        for e, inv in produced_b.items():
            d = self.artefact(inv)
            self.assertEqual(verify_published(d), [])
            f, f_a = (json.loads((x / "findings.json").read_text(encoding="utf-8")) for x in (d, dirs_a[produced_a[e]]))
            # stored against its originating execution, with its own execution metadata
            self.assertEqual(f["execution"], {"submission_id": run_b["result"]["submission_id"], "run_id": run_b["run_id"],
                                              "authorization_id": run_b["result"]["auto_investigation"]["authorization_id"],
                                              "job_id": jobs_b[e]["job_id"]})
            self.assertEqual(f_a["execution"]["submission_id"], run_a["result"]["submission_id"])
            self.assertTrue(f["model_metadata"]["usage"] and f["model_metadata"]["model"] and f["investigated_at"])
            # the same analysis content; the identity differs only by the execution
            strip = lambda x: {k: v for k, v in x.items() if k not in ("execution", "investigation_id", "investigated_at", "model_metadata")}  # noqa: E731
            self.assertEqual(strip(f), strip(f_a))
            self.assertEqual(investigation_id_from_findings(f, f["evidence_packet_sha256"]), inv)
            self.assertEqual(len(list((d / "runs").glob("*.json"))), 1)  # its own first run record, not appended elsewhere
        # nothing earlier is overwritten or appended to
        self.assertEqual({inv: sha_tree(d) for inv, d in dirs_a.items()}, trees_a)
        self.assertEqual(sha_tree(fp_a_dir), fp_before)
        registered = {e["investigation_id"] for e in self.svc.registry.entries()}
        self.assertTrue(set(produced_a.values()) | set(produced_b.values()) <= registered)

        # analyst decisions are isolated: B starts with every investigation pending and decides its own
        fp_b, _ = self.review_to_final_pack(run_b)
        self.assertNotEqual(fp_a, fp_b)
        sub_a, sub_b = run_a["result"]["submission_id"], run_b["result"]["submission_id"]
        for e in produced_a:
            hist_a = self.get(f"/api/v1/investigations/{produced_a[e]}/analyst-reviews?submission_id={sub_a}").json()
            hist_b = self.get(f"/api/v1/investigations/{produced_b[e]}/analyst-reviews?submission_id={sub_b}").json()
            self.assertEqual(([x["revision"] for x in hist_a], [x["revision"] for x in hist_b]), ([1], [1]))
            self.assertEqual(self.get(f"/api/v1/investigations/{produced_a[e]}/analyst-reviews?submission_id={sub_b}").json(), [])
        final_b = self.get(f"/api/v1/final-packs/{fp_b}/json").json()
        self.assertEqual(sorted(i["investigation_id"] for i in final_b["ai_investigations"]), sorted(produced_b.values()))
        self.assertEqual(sha_tree(fp_a_dir), fp_before)

    def test_a_running_earlier_submission_is_never_reused_by_the_next(self):
        import threading
        self.answers.hold = threading.Event()
        data = make_zip(FILES)
        d_a = self.upload_zip(data)
        run_a = self.submit(d_a["batch"]["batch_id"])
        self.svc.runner.wait(run_a["job_id"], timeout=180)  # A's audit run done; its investigations are held QUEUED / RUNNING
        run_a = self.get(f"/api/v1/processing-runs/{run_a['run_id']}").json()
        d_b = self.upload_zip(data)
        run_b = self.submit(d_b["batch"]["batch_id"])
        self.svc.runner.wait(run_b["job_id"], timeout=180)
        run_b = self.get(f"/api/v1/processing-runs/{run_b['run_id']}").json()
        items_a, items_b = (r["result"]["auto_investigation"]["items"] for r in (run_a, run_b))
        self.assertTrue(all(i["outcome"] == "QUEUED" for i in items_b), items_b)  # not ALREADY_ACTIVE: A's jobs are not reused
        self.assertTrue({i["job_id"] for i in items_a}.isdisjoint(i["job_id"] for i in items_b))
        self.answers.hold.set()
        for i in items_a + items_b:
            self.svc.runner.wait(i["job_id"], 120)
        pa, pb = self.produced(run_a), self.produced(run_b)
        self.assertEqual(set(pa), set(pb))
        self.assertTrue(set(pa.values()).isdisjoint(pb.values()))


class LegacyIdentityUnchanged(unittest.TestCase):
    """Investigations outside a submission run store no execution: their findings bytes and identity are exactly as before."""

    def test_empty_execution_is_omitted_and_identity_is_unchanged(self):
        from uc042lib.investigation.models import InvestigationResult
        from uc042lib.investigation.persistence import investigation_id_from_findings
        base = dict(investigation_id="", pack_id="P", pack_content_sha256="a" * 64, exception_id="EXC-1", original_exception_status="OPEN",
                    original_review_status="", original_evidence_status="", investigation_scope={}, investigation_route="r",
                    investigation_status="COMPLETED", validation_status="VALID", evidence_packet_sha256="b" * 64)
        legacy = InvestigationResult(**base).model_dump()
        self.assertNotIn("execution", legacy)
        self.assertEqual(json.loads(InvestigationResult(**base).model_dump_json()), legacy)
        scoped = InvestigationResult(**base, execution={"submission_id": "SUB-1", "run_id": "RUN-1", "job_id": "JOB-1"}).model_dump()
        self.assertEqual(scoped["execution"]["job_id"], "JOB-1")
        self.assertNotEqual(investigation_id_from_findings(legacy, "b" * 64), investigation_id_from_findings(scoped, "b" * 64))
        other_job = dict(scoped, execution=dict(scoped["execution"], job_id="JOB-2"))
        self.assertNotEqual(investigation_id_from_findings(scoped, "b" * 64), investigation_id_from_findings(other_job, "b" * 64))


if __name__ == "__main__":
    unittest.main()
