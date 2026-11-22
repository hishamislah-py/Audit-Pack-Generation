"""Final audit-pack library: snapshot and selection, assembly, validation (FV rules), write-once publication and
immutability. Offline: investigations and summaries come from the real adapters with a mocked HTTP layer.
Run from uc042/: python -m unittest -v"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.final_pack_support import (PACK, ROOT, make_investigation, resealed, review_for, sha_tree, summary_investigator)
from uc042lib.final_pack import (FinalPackExistsError, FinalPackInputError, FinalPackPublicationError, FinalPackValidationError,
                                 GenerationInfo, Selection, assemble_final_pack, assemble_preview, build_review_snapshot,
                                 default_selections, generate_closing_summary, list_final_packs, list_investigations, load_pack,
                                 next_version, publish_final_pack, unavailable_closing_summary, verify_final_pack)
from uc042lib.final_pack.validate import validate_final_pack
from uc042lib.investigation.retrieval import RetrievalError


class FinalPackCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.inv_root, self.out_root = self.tmp / "investigations", self.tmp / "final_packs"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def snapshot(self, scenario, selections=None):
        pack = load_pack(PACK[scenario])
        return build_review_snapshot(PACK[scenario], selections if selections is not None else default_selections(pack, self.inv_root),
                                     investigations_root=self.inv_root)

    def generated(self, snap, edit=None):
        inv, _ = summary_investigator(snap, edit)
        return generate_closing_summary(snap, inv)

    def final(self, scenario, snap=None, **review):
        snap = snap or self.snapshot(scenario)
        summary = self.generated(snap)
        return snap, summary, assemble_final_pack(snap, summary, review_for(snap, summary, **review), GenerationInfo())


# ---------------------------------------------------------------------------------------------------------------
class Assembly(FinalPackCase):
    def test_clean_baseline_with_zero_exceptions(self):
        snap, summary, final = self.final("S01")
        self.assertEqual((final["exception_register"], final["ai_investigations"], final["executive_summary"]["exceptions"]["total"]), ([], [], 0))
        self.assertEqual(final["executive_summary"]["statement"], "No exceptions were raised by the deterministic engine.")
        self.assertEqual(final["closing_summary"]["output"]["unresolved_items"], [])
        self.assertTrue(final["source_inventory"]["files"] and final["reconciliation_results"]["internal_by_currency_day"])
        path = publish_final_pack(final, self.out_root)
        self.assertEqual(verify_final_pack(path), [])

    def test_unresolved_exceptions_preserved_verbatim(self):
        make_investigation("SC5A", "EXC-SC5A-01", self.inv_root)
        snap, _, final = self.final("SC5A")
        pack = load_pack(PACK["SC5A"])
        self.assertEqual([e["exception"] for e in final["exception_register"]], pack["exception_register"]["exceptions"])
        self.assertEqual({e["resolution_status"] for e in final["exception_register"]}, {"UNRESOLVED"})
        inc = {e["exception"]["exception_id"]: e["investigation"]["inclusion"] for e in final["exception_register"]}
        self.assertEqual(inc, {"EXC-SC5A-01": "INCLUDED", "EXC-SC5A-02": "NOT_INVESTIGATED"})
        self.assertEqual(final["executive_summary"]["exceptions"]["unresolved"], 2)

    def test_ai_content_classes_and_provenance(self):
        make_investigation("SC5A", "EXC-SC5A-01", self.inv_root)
        snap, summary, final = self.final("SC5A")
        inv = final["ai_investigations"][0]
        self.assertEqual({f["class"] for f in inv["confirmed_findings"]}, {"EVIDENCE_CONFIRMED_OBSERVATION"})
        self.assertEqual(inv["assessment"]["class"], "AI_INVESTIGATIVE_ASSESSMENT")
        self.assertNotIn(inv["assessment"]["ref"], {f["ref"] for f in inv["confirmed_findings"]})
        self.assertEqual({h["verification_status"] for h in inv["hypotheses"]}, {"NOT_ESTABLISHED"})
        f = inv["confirmed_findings"][0]
        self.assertTrue(f["title"] and f["audit_relevance"] and f["establishes"] and f["does_not_establish"])
        bundle = snap.bundles[inv["investigation_id"]]
        records = {r["evidence_id"]: r for r in bundle["packet"]["source_records"]}
        for a in f["amounts_and_dates"]:  # copied byte-for-byte from the cited evidence
            src = records[a["evidence_id"]]["fields"][a["field"]] if a["evidence_id"] in records else \
                next(r for r in bundle["packet"]["control_results"] if r["result_id"] == a["evidence_id"])[a["field"]]
            self.assertEqual(a["value"], src)
        for eid, e in final["evidence_index"].items():
            self.assertEqual((e["source_line"], e["file_sha256"]), (records[eid]["source_line"], records[eid]["file_sha256"]))
        trail = final["audit_trail"]["investigations"][0]
        self.assertEqual((trail["findings_sha256"], trail["evidence_packet_sha256"]),
                         (bundle["findings_sha256"], bundle["findings"]["evidence_packet_sha256"]))
        self.assertEqual(final["metadata"]["source_pack"]["pack_content_sha256"], load_pack(PACK["SC5A"])["audit_trail"]["pack_content_sha256"])
        self.assertEqual(final["human_review"]["review_decision_id"], "RD-0001")

    def test_multiple_investigations_for_one_exception(self):
        older = make_investigation("SC5A", "EXC-SC5A-01", self.inv_root)
        newer = make_investigation("SC5A", "EXC-SC5A-01", self.inv_root,
                                   edit=lambda o: o["open_questions"].append("Which export contains the missing transaction?"))
        self.assertNotEqual(older, newer)
        found = list_investigations(load_pack(PACK["SC5A"]), "EXC-SC5A-01", self.inv_root)["published"]
        self.assertEqual({i["investigation_id"] for i in found if i["eligible"]}, {older, newer})
        a = self.snapshot("SC5A", [Selection(exception_id="EXC-SC5A-01", inclusion="INCLUDED", investigation_id=older),
                                   Selection(exception_id="EXC-SC5A-02", inclusion="NOT_INVESTIGATED")])
        b = self.snapshot("SC5A", [Selection(exception_id="EXC-SC5A-01", inclusion="INCLUDED", investigation_id=newer),
                                   Selection(exception_id="EXC-SC5A-02", inclusion="NOT_INVESTIGATED")])
        self.assertNotEqual(a.sha256, b.sha256)
        _, _, final = self.final("SC5A", a)
        other = final["exception_register"][0]["investigation"]["other_attempts"]
        self.assertEqual((final["ai_investigations"][0]["investigation_id"], other["published_not_selected"]), (older, [newer]))

    def test_selection_rules(self):
        iid = make_investigation("SC5A", "EXC-SC5A-01", self.inv_root)
        bad = [([Selection(exception_id="EXC-SC5A-01", inclusion="INCLUDED", investigation_id=iid)], "no selection for exceptions"),
               ([Selection(exception_id="EXC-SC5A-01", inclusion="NOT_INVESTIGATED"),
                 Selection(exception_id="EXC-SC5A-02", inclusion="NOT_INVESTIGATED")], "eligible investigations exist"),
               ([Selection(exception_id="EXC-SC5A-01", inclusion="INCLUDED", investigation_id="INV-EXC-SC5A-01-000000000000"),
                 Selection(exception_id="EXC-SC5A-02", inclusion="NOT_INVESTIGATED")], "not a published investigation"),
               ([Selection(exception_id="EXC-SC5A-99", inclusion="NOT_INVESTIGATED")], "not in the pack")]
        for sels, expect in bad:
            with self.subTest(expect=expect), self.assertRaises(FinalPackInputError) as cm:
                self.snapshot("SC5A", sels)
            self.assertIn(expect, str(cm.exception))
        with self.assertRaises(ValueError):
            Selection(exception_id="EXC-SC5A-01", inclusion="EXCLUDED_BY_ANALYST")  # a reason is required
        ok = self.snapshot("SC5A", [Selection(exception_id="EXC-SC5A-01", inclusion="EXCLUDED_BY_ANALYST", reason="Out of scope for this review."),
                                    Selection(exception_id="EXC-SC5A-02", inclusion="NOT_INVESTIGATED")])
        self.assertEqual(ok.content["selections"][0]["inclusion"], "EXCLUDED_BY_ANALYST")

    def test_ineligible_investigations_are_never_selectable(self):
        from tests.final_pack_support import OFFLINE
        from uc042lib.investigation.graph import run_investigation
        s = run_investigation(PACK["SC5A"], "EXC-SC5A-01", OFFLINE, investigations_root=self.inv_root)  # simulated: VALID but not AI
        sim = s["result"]["investigation_id"]
        real = make_investigation("SC5A", "EXC-SC5A-01", self.inv_root)
        found = {i["investigation_id"]: i for i in list_investigations(load_pack(PACK["SC5A"]), "EXC-SC5A-01", self.inv_root)["published"]}
        self.assertFalse(found[sim]["eligible"])
        self.assertIn("simulated", found[sim]["reasons"][0])
        self.assertEqual(default_selections(load_pack(PACK["SC5A"]), self.inv_root)[0].investigation_id, real)
        with self.assertRaises(FinalPackInputError):
            self.snapshot("SC5A", [Selection(exception_id="EXC-SC5A-01", inclusion="INCLUDED", investigation_id=sim),
                                   Selection(exception_id="EXC-SC5A-02", inclusion="NOT_INVESTIGATED")])
        with mock.patch("uc042lib.final_pack.sources.validate_output", return_value=(["C-01: contradiction rule"], [], [])):
            info = list_investigations(load_pack(PACK["SC5A"]), "EXC-SC5A-01", self.inv_root)["published"]
        self.assertTrue(all(not i["eligible"] and "fails current validation rules" in " ".join(i["reasons"]) for i in info if i["investigation_id"] == real))
        d = next(self.inv_root.rglob(real))  # a tampered artefact fails verification
        f = d / "findings.json"
        f.write_text(f.read_text().replace("engine", "Engine", 1))
        info = {i["investigation_id"]: i for i in list_investigations(load_pack(PACK["SC5A"]), "EXC-SC5A-01", self.inv_root)["published"]}
        self.assertIn("artefact verification failed", info[real]["reasons"][0])

    def test_invalid_source_pack_hash(self):
        packs = self.tmp / "packs"
        shutil.copytree(ROOT / "packs" / PACK["SC2"], packs / PACK["SC2"])
        p = packs / PACK["SC2"] / "pack.json"
        p.write_text(p.read_text().replace("2868.50", "2868.51", 1))
        with self.assertRaises(RetrievalError):
            build_review_snapshot(PACK["SC2"], [Selection(exception_id="EXC-SC2-01", inclusion="NOT_INVESTIGATED")], packs_root=packs,
                                  investigations_root=self.inv_root)


class Validation(FinalPackCase):
    def setUp(self):
        super().setUp()
        make_investigation("SC5A", "EXC-SC5A-01", self.inv_root)
        self.snap, self.summary, self.fp = self.final("SC5A")
        self.review = review_for(self.snap, self.summary)

    def errors(self, mutate):
        return validate_final_pack(resealed(self.fp, mutate), self.snap, self.summary, self.review)

    def assertRejected(self, mutate, expect):
        errs = self.errors(mutate)
        self.assertTrue(any(expect in e for e in errs), errs)

    def test_unmodified_pack_is_valid(self):
        self.assertEqual(validate_final_pack(self.fp, self.snap, self.summary, self.review), [])

    def test_tampering_is_rejected_with_specific_errors(self):
        inv = lambda f: f["ai_investigations"][0]
        cases = [
            (lambda f: f["exception_register"][0]["exception"].update(status="CLOSED"), "statuses must not change"),
            (lambda f: f["exception_register"][0].update(resolution_status="RESOLVED"), "must be UNRESOLVED"),
            (lambda f: f["exception_register"].pop(), "exactly the pack's exceptions"),
            (lambda f: f["reconciliation_results"]["internal_by_currency_day"][0].update(difference="1.00"), "values must be copied"),
            (lambda f: inv(f)["confirmed_findings"][0]["evidence_refs"].append("IN-09:BE-INVENTED-1"), "not in the selected investigation"),
            (lambda f: inv(f)["confirmed_findings"][0].update(evidence_refs=["H-01"], supporting_records=[]), "no supporting source record"),
            (lambda f: f["evidence_index"].clear(), "missing from the evidence index"),
            (lambda f: inv(f)["confirmed_findings"].append(dict(inv(f)["confirmed_findings"][0], finding_id="H-01",
                                                                description=inv(f)["hypotheses"][0]["description"])),
             "not a validated confirmed finding"),
            (lambda f: inv(f)["hypotheses"][0].update(verification_status="ESTABLISHED"), "hypotheses must stay hypotheses"),
            (lambda f: inv(f)["assessment"].update(summary="The evidence proves the transaction was omitted."), "kept distinct and verbatim"),
            (lambda f: inv(f)["confirmed_findings"][0].update(does_not_establish=None), "never rewritten or back-filled"),
            (lambda f: inv(f)["confirmed_findings"][0].update(title="A new, better title written later"), "never rewritten or back-filled"),
            (lambda f: f["metadata"]["source_pack"].update(pack_content_sha256="0" * 64), "content hash does not match"),
            (lambda f: f["metadata"]["source_pack"].update(pack_schema_version="uc042-pack/9.9"), "unsupported original pack schema"),
        ]
        for mutate, expect in cases:
            with self.subTest(expect=expect):
                self.assertRejected(mutate, expect)

    def test_content_hash_mismatch(self):
        f = json.loads(json.dumps(self.fp))
        f["executive_summary"]["statement"] = "edited after assembly"
        self.assertTrue(any("final_content_sha256" in e for e in validate_final_pack(f, self.snap, self.summary, self.review)))

    def test_human_review_requirements(self):
        for overrides, expect in (({"decision": "HOLD"}, "only GENERATE authorises"), ({"acknowledgement_accepted": False}, "acknowledgement"),
                                  ({"snapshot_sha256": "a" * 64}, "different snapshot"), ({"closing_summary_sha256": "b" * 64}, "different closing summary")):
            with self.subTest(expect=expect):
                errs = validate_final_pack(self.fp, self.snap, self.summary, review_for(self.snap, self.summary, **overrides))
                self.assertTrue(any(expect in e for e in errs), errs)
        with self.assertRaises(FinalPackValidationError):
            assemble_final_pack(self.snap, self.summary, None)

    def test_pack_changed_on_disk_after_review(self):
        packs = self.tmp / "packs"
        shutil.copytree(ROOT / "packs" / PACK["SC5A"], packs / PACK["SC5A"])
        self.snap.packs_root = packs
        p = packs / PACK["SC5A"] / "pack.json"
        p.write_text(p.read_text().replace("443.55", "443.56", 1))
        self.assertTrue(any("cannot be loaded and verified" in e for e in validate_final_pack(self.fp, self.snap, self.summary, self.review)))


class PersistenceAndImmutability(FinalPackCase):
    def test_publish_verify_write_once_and_version_chain(self):
        snap, summary, final = self.final("S01")
        path = publish_final_pack(final, self.out_root)
        self.assertEqual(sorted(p.name for p in path.iterdir()), ["final_pack.json", "manifest.json", "report.html", "report.pdf"])
        self.assertEqual(verify_final_pack(path), [])
        before = sha_tree(path)
        with self.assertRaises(FinalPackExistsError):
            publish_final_pack(final, self.out_root)  # same decision / same ID
        self.assertEqual(sha_tree(path), before)
        v2_wrong = assemble_final_pack(snap, summary, review_for(snap, summary, review_decision_id="RD-0002"), GenerationInfo())
        with self.assertRaises(FinalPackExistsError):
            publish_final_pack(v2_wrong, self.out_root)  # version 1 again
        version, supersedes = next_version(PACK["S01"], self.out_root)
        self.assertEqual((version, supersedes), (2, final["metadata"]["final_pack_id"]))
        v2 = assemble_final_pack(snap, summary, review_for(snap, summary, review_decision_id="RD-0002"),
                                 GenerationInfo(version=2, supersedes_final_pack_id=supersedes))
        p2 = publish_final_pack(v2, self.out_root)
        self.assertEqual([m["generation_record"]["version"] for m in list_final_packs(self.out_root, PACK["S01"])], [1, 2])
        self.assertEqual((verify_final_pack(p2), sha_tree(path)), ([], before))

    def test_atomic_failure_leaves_nothing(self):
        _, _, final = self.final("S01")
        with mock.patch("uc042lib.final_pack.persistence.render_pdf", side_effect=RuntimeError("renderer crashed")):
            with self.assertRaises(RuntimeError):
                publish_final_pack(final, self.out_root)
        with mock.patch("uc042lib.final_pack.persistence.os.replace", side_effect=PermissionError("disk")):
            with self.assertRaises(PermissionError):
                publish_final_pack(final, self.out_root)
        self.assertEqual([p for p in self.out_root.rglob("*")] if self.out_root.exists() else [], [])

    def test_previews_and_tampering(self):
        snap = self.snapshot("S01")
        summary = self.generated(snap)
        preview = assemble_preview(snap, summary)
        self.assertTrue(preview["metadata"]["final_pack_id"].startswith("PREVIEW-"))
        self.assertEqual(preview["human_review"]["status"], "PENDING_DECISION")
        with self.assertRaises(FinalPackPublicationError):
            publish_final_pack(preview, self.out_root)
        final = assemble_final_pack(snap, summary, review_for(snap, summary), GenerationInfo())
        path = publish_final_pack(final, self.out_root)
        (path / "report.html").write_text((path / "report.html").read_text(encoding="utf-8") + "<!-- edited -->", encoding="utf-8")
        self.assertTrue(any("report.html" in p for p in verify_final_pack(path)))

    def test_assembly_never_calls_a_model_and_never_writes_sources(self):
        make_investigation("SC5A", "EXC-SC5A-01", self.inv_root)
        snap = self.snapshot("SC5A")
        summary = self.generated(snap)
        protected = sha_tree(ROOT / "packs", ROOT / "uc042_dataset", self.inv_root)
        with mock.patch("openai.OpenAI", side_effect=AssertionError("no model calls during assembly")), \
                mock.patch("uc042lib.investigation.llm.OpenAIInvestigator.structured_request", side_effect=AssertionError("no AI")), \
                mock.patch("uc042lib.investigation.llm.OpenAIInvestigator.investigate", side_effect=AssertionError("no AI")):
            final = assemble_final_pack(snap, summary, review_for(snap, summary), GenerationInfo())
            publish_final_pack(final, self.out_root)
        self.assertEqual(sha_tree(ROOT / "packs", ROOT / "uc042_dataset", self.inv_root), protected)

    def test_unavailable_summary_requires_explicit_acknowledgement(self):
        snap = self.snapshot("S01")
        unavailable = unavailable_closing_summary(snap, "provider error [rate_limit]")
        self.assertEqual(assemble_preview(snap, unavailable)["closing_summary"]["status"], "UNAVAILABLE")
        with self.assertRaises(FinalPackValidationError) as cm:
            assemble_final_pack(snap, unavailable, review_for(snap, unavailable), GenerationInfo())
        self.assertIn("explicit acknowledgement", str(cm.exception))
        final = assemble_final_pack(snap, unavailable, review_for(snap, unavailable, acknowledged_summary_unavailable=True), GenerationInfo())
        self.assertEqual((final["closing_summary"]["output"], final["metadata"]["completeness"]["closing_summary"]), (None, "UNAVAILABLE"))
        self.assertEqual(verify_final_pack(publish_final_pack(final, self.out_root)), [])


if __name__ == "__main__":
    unittest.main()
