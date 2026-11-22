"""Phase 7: monthly reports and document management. Period titles (created once, changed only explicitly, never the
period ID), reporting statuses derived from records, pack types, the data-environment indicator, supporting documents
(additional evidence and corrections linked to the document they replace), documents received after publication of a
final audit pack (pending reassessment, nothing published changes) and the final-pack PDF response.

Disposable state only: temporary packs, final-packs, investigations and document-store roots, a temporary SQLite database
(or the disposable PostgreSQL test database with UC042_TEST_REPOSITORIES=postgres). The February 2026 pack and final
audit pack are COPIED from demo_history into the temporary roots; the originals are only read and are checked unchanged.
Offline: no provider is called. ILLUSTRATIVE SYNTHETIC DATA."""
import hashlib
import io
import shutil
from datetime import date

from tests.api_support import ROOT
from tests.final_pack_support import sha_tree
from tests.test_api_monthly import S05_PACK, MonthlyCase

DEMO = ROOT / "demo_history"
FEB_PACK = "PACK-H202602-PER-2026-02-195df2e1f216"
FEB_FINAL = "FAP-H202602-PER-2026-02-v1-b8dd53bd2449"
FEB_DATA = DEMO / "datasets" / "2026-02"


class ReportsCase(MonthlyCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.demo_before = sha_tree(DEMO)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        assert sha_tree(DEMO) == cls.demo_before, "a demo_history file changed"

    def setUp(self):
        super().setUp()
        self.stop_app()
        shutil.copytree(DEMO / "packs" / FEB_PACK, self.packs_root / FEB_PACK)
        shutil.copytree(DEMO / "final_packs" / FEB_FINAL, self.tmp / "final_packs" / FEB_FINAL)
        self.start_app()  # start-up registers the packs in the temporary packs root under their periods

    def periods(self):
        return {p["period_id"]: p for p in self.get("/api/v1/periods").json()}

    def send(self, period_id, files, expect=201, **form):
        r = self.client.post(f"/api/v1/periods/{period_id}/uploads", data=form,
                             files=[("files", (name, io.BytesIO(data), "application/octet-stream")) for name, data in files])
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    @staticmethod
    def codes(doc):
        return {m["code"] for m in doc["checks"]["messages"]}


class PeriodsAndStatuses(ReportsCase):
    def test_periods_group_packs_by_month_with_their_type_and_status(self):
        p = self.periods()
        feb, sep = p["PER-2026-02"], p["PER-2026-09"]
        self.assertEqual([x["pack_kind"] for x in feb["packs"]], ["HISTORICAL_MONTHLY"])
        self.assertEqual(feb["packs"][0]["final_pack_ids"], [FEB_FINAL])
        self.assertEqual((feb["reporting_status"], feb["final_pack_count"], feb["pending_reassessment"]), ("FINAL_PACK_PUBLISHED", 1, False))
        self.assertEqual(feb["latest_final_pack_at"], "2026-11-04T05:47:45+00:00")
        self.assertEqual(sorted(x["pack_kind"] for x in sep["packs"]), ["DEMONSTRATION_SCENARIO", "DEMONSTRATION_SCENARIO"])
        self.assertEqual((sep["reporting_status"], sep["pack_count"]), ("DETERMINISTIC_PACK_AVAILABLE", 2))  # one month, two scenarios
        self.assertNotIn("PER-2026-10", p)  # no record is invented for a month without data
        s = self.get(f"/api/v1/packs/{FEB_PACK}").json()["summary"]
        self.assertEqual((s["pack_kind"], s["scenario_name"]), ("HISTORICAL_MONTHLY", "Historical demonstration month, February 2026"))
        self.assertEqual(self.get(f"/api/v1/packs/{S05_PACK}").json()["summary"]["pack_kind"], "DEMONSTRATION_SCENARIO")

    def test_new_period_title_duplicates_and_explicit_rename(self):
        r = self.post("/api/v1/periods", {"year": 2026, "month": 10, "title": "October 2026 Reconciliation Audit"})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual((r.json()["period_id"], r.json()["title"], r.json()["reporting_status"]), ("PER-2026-10", "October 2026 Reconciliation Audit", "NO_DATA"))
        again = self.post("/api/v1/periods", {"year": 2026, "month": 10, "title": "Another title"})
        self.assertEqual((again.status_code, again.json()["title"]), (200, "October 2026 Reconciliation Audit"))  # never a second period, title kept
        self.assertEqual(len([x for x in self.periods() if x == "PER-2026-10"]), 1)
        renamed = self.patch("/api/v1/periods/PER-2026-10", {"title": "October 2026 Safeguarding Audit"})
        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertEqual((renamed.json()["period_id"], renamed.json()["title"]), ("PER-2026-10", "October 2026 Safeguarding Audit"))
        event = next(a for a in self.get("/api/v1/activity").json() if a["action"] == "PERIOD_RETITLED")
        self.assertEqual(event["details"], {"previous_title": "October 2026 Reconciliation Audit", "title": "October 2026 Safeguarding Audit"})
        before = self.periods()["PER-2026-02"]["packs"]
        self.assertEqual(self.patch("/api/v1/periods/PER-2026-02", {"title": "February 2026 Reconciliation Audit"}).status_code, 200)
        after = self.periods()["PER-2026-02"]
        self.assertEqual((after["title"], [x["pack_id"] for x in after["packs"]]), ("February 2026 Reconciliation Audit", [x["pack_id"] for x in before]))
        self.assertEqual(self.patch("/api/v1/periods/PER-2026-10", {"title": "x"}).status_code, 422)
        future = date.today().replace(day=1)
        y, m = (future.year + 1, 1) if future.month == 12 else (future.year, future.month + 1)
        self.assertEqual(self.post("/api/v1/periods", {"year": y, "month": m, "title": "Future"}).json()["code"], "FUTURE_PERIOD")

    def test_upload_status_and_environment(self):
        self.open_period(2026, 10)
        self.send("PER-2026-10", [("account_inventory.csv", (FEB_DATA / "source_data" / "account_inventory.csv").read_bytes())])
        self.assertEqual(self.periods()["PER-2026-10"]["reporting_status"], "VALIDATION_REQUIRED")
        h = self.get("/health").json()
        env = h["environment"]
        self.assertEqual(env["packs_root"], self.packs_root.name)
        self.assertTrue(env["label"])
        self.assertNotIn("@", str(env))  # never a connection string or credential


class SupportingDocuments(ReportsCase):
    def test_additional_evidence_after_publication_is_pending_reassessment_and_changes_nothing(self):
        final_before, pack_before = sha_tree(self.tmp / "final_packs" / FEB_FINAL), sha_tree(self.packs_root / FEB_PACK)
        self.assertEqual(self.send("PER-2026-02", [("x.csv", b"a,b\n1,2\n")], expect=422, submission_kind="ADDITIONAL_EVIDENCE")["code"], "REASON_REQUIRED")
        confirmations = (FEB_DATA / "source_data" / "bank_balance_confirmations_2026-02.csv").read_bytes()
        b = self.send("PER-2026-02", [("bank_confirmations_feb.csv", confirmations), ("bank_letter.txt", b"Letter from the bank about 16 Feb\n")],
                      submission_kind="ADDITIONAL_EVIDENCE", reason="Bank confirmation for 16 Feb received after publication")
        docs = {d["original_filename"]: d for d in b["documents"]}
        csv_doc, letter = docs["bank_confirmations_feb.csv"], docs["bank_letter.txt"]
        for d in (csv_doc, letter):
            self.assertEqual((d["submission_kind"], d["submission_reason"], d["reporting_period"]),
                             ("ADDITIONAL_EVIDENCE", "Bank confirmation for 16 Feb received after publication", "PER-2026-02"))
            self.assertIn("RECEIVED_AFTER_PUBLICATION", self.codes(d))
        self.assertEqual((csv_doc["evidence_id"], csv_doc["sha256"]), ("IN-07", hashlib.sha256(confirmations).hexdigest()))
        # a readable file that is not a reconciliation input is kept as supporting evidence (a warning, never processed)
        self.assertEqual((letter["evidence_id"], letter["category"], letter["validation_status"]),
                         (None, "Supporting evidence (not a reconciliation input)", "WARNING"))
        self.assertIn("SUPPORTING_EVIDENCE", self.codes(letter))
        feb = self.periods()["PER-2026-02"]
        self.assertEqual((feb["reporting_status"], feb["pending_reassessment"], feb["documents_after_publication"]),
                         ("ADDITIONAL_EVIDENCE_RECEIVED", True, 2))
        self.assertEqual(sha_tree(self.tmp / "final_packs" / FEB_FINAL), final_before)  # the published pack is not changed
        self.assertEqual(sha_tree(self.packs_root / FEB_PACK), pack_before)
        self.assertTrue(self.get(f"/api/v1/final-packs/{FEB_FINAL}/verify").json()["verified"])
        self.assertEqual(self.get(f"/api/v1/final-packs/{FEB_FINAL}").json()["version"], 1)

    def test_unrecognised_initial_upload_keeps_the_existing_error(self):
        self.open_period(2026, 10)
        b = self.send("PER-2026-10", [("notes.txt", b"hello, world\n1,2\n")])
        d = b["documents"][0]
        self.assertEqual((d["validation_status"], d["submission_kind"]), ("ERROR", "INITIAL"))
        self.assertIn("UNRECOGNISED", self.codes(d))

    def test_correction_is_a_new_version_linked_to_the_unchanged_original(self):
        original = (FEB_DATA / "source_data" / "account_inventory.csv").read_bytes()
        first = self.send("PER-2026-02", [("account_inventory.csv", original)])["documents"][0]
        corrected = original.replace(b"Example Bank plc", b"Example Bank plc (corrected)")
        r = self.send("PER-2026-02", [("account_inventory_v2.csv", corrected), ("other.csv", corrected + b"\n")], expect=422,
                      submission_kind="CORRECTION", reason="Corrected bank name", replaces_document_id=first["document_id"])
        self.assertEqual(r["code"], "INVALID_SUBMISSION")  # one file replaces one document
        self.assertEqual(self.send("PER-2026-02", [("account_inventory_v2.csv", corrected)], expect=422, submission_kind="CORRECTION",
                                   reason="Corrected bank name")["code"], "INVALID_ID")  # the replaced document is required
        b = self.send("PER-2026-02", [("account_inventory_v2.csv", corrected)], submission_kind="CORRECTION", reason="Corrected bank name",
                      replaces_document_id=first["document_id"])
        new = b["documents"][0]
        self.assertEqual((new["submission_kind"], new["replaces_document_id"], new["evidence_id"]), ("CORRECTION", first["document_id"], "IN-02"))
        self.assertIn("REPLACES_DOCUMENT", self.codes(new))
        self.assertNotEqual(new["document_id"], first["document_id"])
        # the original is unchanged: same record, same stored bytes and hash
        self.assertEqual(self.get(f"/api/v1/documents/{first['document_id']}").json()["sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(self.get(f"/api/v1/documents/{first['document_id']}/content").content, original)
        self.assertEqual(self.get(f"/api/v1/documents/{new['document_id']}/content").content, corrected)
        ids = {d["document_id"] for d in self.get("/api/v1/periods/PER-2026-02").json()["documents"]}
        self.assertTrue({first["document_id"], new["document_id"]} <= ids)  # both versions stay in the history
        self.open_period(2026, 10)
        other = self.send("PER-2026-10", [("account_inventory.csv", original + b"\n")])["documents"][0]
        self.assertEqual(self.send("PER-2026-02", [("x.csv", corrected)], expect=422, submission_kind="CORRECTION", reason="wrong month",
                                   replaces_document_id=other["document_id"])["code"], "INVALID_SUBMISSION")

    def test_a_supporting_document_can_be_corrected(self):
        # found in the report 19 end-to-end validation: a correction of a supporting document was an UNRECOGNISED error
        b = self.send("PER-2026-02", [("bank_letter.txt", b"Letter from the bank about 16 Feb\n")], submission_kind="ADDITIONAL_EVIDENCE",
                      reason="Bank letter received after publication")
        letter = b["documents"][0]
        b2 = self.send("PER-2026-02", [("bank_letter_v2.txt", b"Re-issued letter from the bank about 16 Feb\n")], submission_kind="CORRECTION",
                       reason="The bank re-issued the letter", replaces_document_id=letter["document_id"])
        new = b2["documents"][0]
        self.assertEqual((new["evidence_id"], new["category"], new["validation_status"], new["replaces_document_id"]),
                         (None, "Supporting evidence (not a reconciliation input)", "WARNING", letter["document_id"]))
        self.assertIn("SUPPORTING_EVIDENCE", self.codes(new))
        self.assertIn("REPLACES_DOCUMENT", self.codes(new))
        self.assertEqual(self.post(f"/api/v1/uploads/{b2['batch']['batch_id']}/confirm").status_code, 200)
        # a correction of a reconciliation input with an unrecognised file is still an error (never a silent downgrade)
        inventory = self.send("PER-2026-02", [("account_inventory.csv", (FEB_DATA / "source_data" / "account_inventory.csv").read_bytes())])
        bad = self.send("PER-2026-02", [("notes.txt", b"hello, world\n1,2\n")], submission_kind="CORRECTION", reason="wrong file",
                        replaces_document_id=inventory["documents"][0]["document_id"])["documents"][0]
        self.assertEqual(bad["validation_status"], "ERROR")
        self.assertIn("UNRECOGNISED", self.codes(bad))

    def test_the_same_document_again_is_flagged_as_a_duplicate(self):
        data = (FEB_DATA / "source_data" / "account_inventory.csv").read_bytes()
        self.send("PER-2026-02", [("account_inventory.csv", data)])
        again = self.send("PER-2026-02", [("account_inventory_copy.csv", data)], submission_kind="ADDITIONAL_EVIDENCE", reason="same file sent again")
        d = again["documents"][0]
        self.assertIn("DUPLICATE_OF_EARLIER_UPLOAD", self.codes(d))
        self.assertTrue(d["checks"].get("decision_required"))


class FinalPackDownloads(ReportsCase):
    def test_pdf_preview_and_downloads_are_the_published_files(self):
        folder = self.tmp / "final_packs" / FEB_FINAL
        pdf = self.get(f"/api/v1/final-packs/{FEB_FINAL}/pdf")
        self.assertEqual((pdf.status_code, pdf.headers["content-type"]), (200, "application/pdf"))
        self.assertTrue(pdf.content.startswith(b"%PDF-"))
        self.assertEqual(pdf.content, (folder / "report.pdf").read_bytes())
        self.assertEqual(self.get(f"/api/v1/final-packs/{FEB_FINAL}/html").content, (folder / "report.html").read_bytes())
        self.assertEqual(self.get(f"/api/v1/final-packs/{FEB_FINAL}/json").content, (folder / "final_pack.json").read_bytes())
        self.assertEqual((folder / "report.pdf").read_bytes(), (DEMO / "final_packs" / FEB_FINAL / "report.pdf").read_bytes())
