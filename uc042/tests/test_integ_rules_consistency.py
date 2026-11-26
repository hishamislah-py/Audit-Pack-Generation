"""Integration fixes I-1..I-3 (engine integration branch, 23 Nov 2026):
  I-1 rules propagate through pack generation (generate -> build -> assemble -> engine);
  I-2 the enrichment module is part of the engine fingerprint of enriched runs only;
  I-3 reconciliation outputs, pack generation and closure use one rule set (recorded rules, correlation version, guard).
Enrichment OFF must leave every pack field other than the code identifiers unchanged."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from uc042lib import validate as V
from uc042lib.pack import config, model
from uc042lib.pack.generate import build, generate
from uc042lib.scenarios import apply, set_op, write_manifest
from uc042lib.validate import (APPROVED_RULES, DEFAULT_SET, ENRICHED_RULES, PUBLISHED_RULES_BEFORE_17_NOV_2026, EngineRules,
                               Validator, case_status, rules_from_recorded, rules_of_reconciliation, write_outputs)

TMP = Path(tempfile.mkdtemp(prefix="integ_rules_"))
SKIP = {"validation", "VALIDATION_REPORT.md"}


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def case(name, ops=()):
    """A copy of the clean baseline with ops applied and its manifest regenerated (packs need a manifest)."""
    dst = TMP / name
    shutil.copytree(DEFAULT_SET, dst, ignore=lambda d, names: [n for n in names if n in SKIP])
    if ops:
        apply(dst, list(ops))
        write_manifest(dst)
    return dst


def reconcile(root, rules):
    """What the application adapter does: run the engine and write its outputs into the case."""
    v = Validator(root, rules=rules)
    results = v.run()
    write_outputs(root, results, v.exceptions, case_status(v), v.groups, v.candidates, v.pdf, v.period, v.rules,
                  enrichment_state=v.enrichment)
    return v


TC02_OP = set_op("IN-11", "TX-0908-00002", "amount", "3035.61", "3053.61", "transposition (TC02-style)")


class RecordedRules(unittest.TestCase):
    def test_round_trip_for_every_named_configuration(self):
        for r in (APPROVED_RULES, ENRICHED_RULES, PUBLISHED_RULES_BEFORE_17_NOV_2026, EngineRules(zero_difference_outcome="NOT_APPLICABLE",
                                                                                                 enrichment_v1=True)):
            self.assertEqual(rules_from_recorded(r.recorded()), r)

    def test_unknown_or_malformed_records_are_refused(self):
        with self.assertRaises(ValueError):
            rules_from_recorded({"something_new": "x"})
        with self.assertRaises(ValueError):
            rules_from_recorded({"reconciliation_enrichment": "v2"})
        with self.assertRaises(ValueError):
            rules_from_recorded({"c06_c08_zero_difference": "FAIL"})


class EngineFingerprint(unittest.TestCase):
    def test_default_fingerprint_is_the_historical_module_set(self):
        import hashlib
        h = hashlib.sha256()
        for name in ["schema.py", "period.py", "structure.py", "money.py", "validate.py"]:
            h.update(name.encode())
            h.update((model.ENGINE_DIR / name).read_bytes())
        self.assertEqual(model.engine_fingerprint(), h.hexdigest())
        self.assertEqual(model.engine_fingerprint(APPROVED_RULES), h.hexdigest())
        self.assertEqual(model.engine_fingerprint(PUBLISHED_RULES_BEFORE_17_NOV_2026), h.hexdigest())
        h.update(b"enrichment.py")
        h.update((model.ENGINE_DIR / "enrichment.py").read_bytes())
        self.assertEqual(model.engine_fingerprint(ENRICHED_RULES), h.hexdigest())
        self.assertEqual(config.ENRICHMENT_MODULES, ["enrichment.py"])


class PackRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tc02 = case("tc02", [TC02_OP])
        cls.clean = case("clean")
        cls.off = build(cls.tc02, rules=None)
        cls.on = build(cls.tc02, rules=ENRICHED_RULES)
        cls.clean_on = build(cls.clean, rules=ENRICHED_RULES)

    def test_both_modes_generate_and_pass_pack_validation(self):
        for status, pack, _, _, findings in (self.off, self.on, self.clean_on):
            self.assertEqual((status, findings), ("GENERATED", []))

    def test_enrichment_off_records_nothing_new(self):
        _, pack, _, outputs, _ = self.off
        at = pack["audit_trail"]
        self.assertNotIn("engine_rules", at)
        self.assertEqual(at["engine_fingerprint"], model.engine_fingerprint())
        self.assertNotIn("enrichment.json", outputs)
        self.assertEqual(len(pack["investigation_group_register"]["groups"]), 0)  # TC02 is ungrouped without enrichment
        self.assertEqual(at["correlation_version"], "deterministic-v1")

    def test_enrichment_on_is_recorded_consistently(self):
        _, pack, _, outputs, _ = self.on
        at = pack["audit_trail"]
        self.assertEqual(at["engine_rules"], ENRICHED_RULES.recorded())
        self.assertEqual(rules_from_recorded(at["engine_rules"]), ENRICHED_RULES)
        self.assertEqual(at["engine_fingerprint"], model.engine_fingerprint(ENRICHED_RULES))
        self.assertNotEqual(at["configuration_fingerprint"], self.off[1]["audit_trail"]["configuration_fingerprint"])
        self.assertEqual(at["correlation_version"], "deterministic-v2-enrichment")
        groups = pack["investigation_group_register"]["groups"]
        self.assertEqual(len(groups), 1)
        self.assertIn("L4 TRANSACTION LINEAGE", groups[0]["link_types"])
        doc = json.loads(outputs["enrichment.json"])
        self.assertEqual(doc["engine_rules"], ENRICHED_RULES.recorded())
        self.assertEqual(at["processing_outputs"]["enrichment.json"], model.sha256_text(outputs["enrichment.json"]))

    def test_correlation_version_follows_the_rules_when_no_group_forms(self):
        _, pack, _, _, _ = self.clean_on
        self.assertEqual(pack["investigation_group_register"]["groups"], [])
        self.assertEqual(pack["audit_trail"]["correlation_version"], "deterministic-v2-enrichment")

    def test_pack_enrichment_document_equals_the_engine_written_one(self):
        root = case("tc02_written", [TC02_OP])
        reconcile(root, ENRICHED_RULES)
        _, _, _, outputs, _ = build(root, rules=ENRICHED_RULES)
        self.assertEqual((root / "validation" / "enrichment.json").read_text(encoding="utf-8"), outputs["enrichment.json"])

    def test_off_pack_content_equals_default_build_apart_from_code_identifiers(self):
        _, explicit, _, out_explicit, _ = build(self.tc02, rules=APPROVED_RULES)
        self.assertEqual(explicit, self.off[1])
        self.assertEqual(out_explicit, self.off[3])


class Propagation(unittest.TestCase):
    def test_generate_forwards_the_rules_to_the_engine(self):
        root = case("gen_tc02", [TC02_OP])
        packs = TMP / "packs_on"
        rec = generate(root, packs, rules=ENRICHED_RULES)
        self.assertEqual(rec["status"], "GENERATED", rec)
        pack = json.loads((packs / rec["pack_id"] / "pack.json").read_text(encoding="utf-8"))
        self.assertEqual(pack["audit_trail"]["engine_rules"], ENRICHED_RULES.recorded())
        rec_off = generate(case("gen_tc02_off", [TC02_OP]), TMP / "packs_off")
        pack_off = json.loads((TMP / "packs_off" / rec_off["pack_id"] / "pack.json").read_text(encoding="utf-8"))
        self.assertNotIn("engine_rules", pack_off["audit_trail"])
        self.assertNotEqual(rec["pack_id"], rec_off["pack_id"])


class Consistency(unittest.TestCase):
    def test_rules_of_reconciliation(self):
        self.assertIsNone(rules_of_reconciliation(case("none")))
        off = case("recon_off")
        reconcile(off, APPROVED_RULES)
        self.assertEqual(rules_of_reconciliation(off), "ENRICHMENT_OFF")
        on = case("recon_on")
        reconcile(on, ENRICHED_RULES)
        self.assertEqual(rules_of_reconciliation(on), ENRICHED_RULES)

    def test_matching_rules_generate(self):
        for name, rules in (("m_off", None), ("m_on", ENRICHED_RULES)):
            root = case(name, [TC02_OP])
            reconcile(root, rules)
            status, _, _, _, findings = build(root, rules=rules)
            self.assertEqual((status, findings), ("GENERATED", []), name)
            status, _, _, _, _ = build(root, rules=rules_of_reconciliation(root) if rules else None)
            self.assertEqual(status, "GENERATED", name)

    def test_mismatched_rules_are_refused(self):
        on = case("mm_on", [TC02_OP])
        reconcile(on, ENRICHED_RULES)
        status, pack, _, _, findings = build(on, rules=None)
        self.assertEqual(status, "FAILED")
        self.assertIsNone(pack)
        self.assertIn("rules mismatch", findings[0])
        off = case("mm_off", [TC02_OP])
        reconcile(off, APPROVED_RULES)
        status, _, _, _, findings = build(off, rules=ENRICHED_RULES)
        self.assertEqual(status, "FAILED")
        self.assertIn("enrichment OFF", findings[0])

    def test_frozen_datasets_build_unchanged_with_their_stored_default_outputs(self):
        # the frozen datasets carry default-mode validation outputs: default and published builds are unaffected
        status, _, _, _, findings = build(V.PROJECT / "uc042_dataset" / "scn_SC2_settlement_timing", rules=PUBLISHED_RULES_BEFORE_17_NOV_2026)
        self.assertEqual((status, findings), ("GENERATED", []))
