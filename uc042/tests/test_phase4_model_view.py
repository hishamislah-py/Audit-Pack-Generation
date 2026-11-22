"""Phase 4 (token-optimisation copy): the lossless model-facing evidence view.

The stored packet is unchanged; OpenAI requests carry render_model_view(packet) instead of the raw packet JSON and no
longer repeat the output schema (text_format still enforces it). Tested on every exception of every scenario pack, the
historical demonstration packs and (read-only, if present) the 20-exception uploaded CASE pack of Clone E.
Run: python -m unittest tests.test_phase4_model_view -v"""
import csv
import hashlib
import json
import unittest

from tests.test_tool_calling import PACK, Temp, final, offline_output, requests_of
from tests.test_phase1_reliability import make
from tests.view_fixtures import ROOT, all_packets
from uc042lib.investigation.graph import run_investigation
from uc042lib.investigation.models import LLMInvestigationOutput
from uc042lib.investigation.packet import canonical
from uc042lib.investigation.packet_view import MODEL_VIEW_VERSION, model_view_sha256, model_view_text, reconstruct_packet, render_model_view
from uc042lib.investigation.prompts import SYSTEM_PROMPT, TOOLS_SYSTEM_PROMPT, model_user_message

PACKETS = list(all_packets())
SIZES = []


def edges(rel):
    return sorted(json.dumps(e, sort_keys=True) for e in rel)


class Lossless(unittest.TestCase):
    def test_model_view_lossless(self):
        self.assertGreaterEqual(len(PACKETS), 30)
        for label, _, _, p, *_ in PACKETS:
            with self.subTest(label):
                r = reconstruct_packet(render_model_view(p))
                self.assertEqual({e["evidence_id"]: e for e in r["source_records"]}, {e["evidence_id"]: e for e in p["source_records"]})
                self.assertEqual(len(r["source_records"]), len(p["source_records"]))  # no evidence ID lost or duplicated
                self.assertEqual(edges(r["relationships"]), edges(p["relationships"]))
                self.assertEqual(sorted(json.dumps(c, sort_keys=True) for c in r["control_results"]),
                                 sorted(json.dumps(c, sort_keys=True) for c in p["control_results"]))
                for k in p:
                    if k not in ("source_records", "relationships", "control_results"):
                        self.assertEqual(r[k], p[k], k)
                SIZES.append((label, len(json.dumps(p, sort_keys=True, ensure_ascii=False)), len(model_view_text(p))))

    def test_model_view_deterministic(self):
        for label, _, _, p, *_ in PACKETS[:12]:
            with self.subTest(label):
                self.assertEqual(model_view_text(p), model_view_text(json.loads(json.dumps(p))))
                self.assertEqual(model_view_sha256(p), hashlib.sha256(model_view_text(p).encode()).hexdigest())

    def test_stored_packet_unchanged(self):
        for label, _, _, p, *_ in PACKETS:
            with self.subTest(label):
                before = canonical(p)
                render_model_view(p)
                self.assertEqual(canonical(p), before)  # rendering never mutates the packet
                body = {k: v for k, v in p.items() if k != "packet_sha256"}
                self.assertEqual(hashlib.sha256(canonical(body).encode()).hexdigest(), p["packet_sha256"])


class Requests(Temp):
    def test_schema_not_duplicated_and_text_format_unchanged(self):
        out = offline_output("SC2", "EXC-SC2-01")
        s, inv = self.run_tools([final(out)])
        kw = requests_of(inv)[0]
        content = kw["input"][0]["content"]
        self.assertNotIn("OUTPUT JSON SCHEMA", content)
        self.assertNotIn('"$defs"', content)
        self.assertIs(kw["text_format"], LLMInvestigationOutput)
        self.assertIn("<evidence_view>", content)
        self.assertIn(s["packet"]["packet_sha256"], content)
        fixed = make([final(out)])
        fixed.investigate(s["packet"])
        fk = requests_of(fixed)[0]
        self.assertNotIn("OUTPUT JSON SCHEMA", fk["input"][0]["content"])
        self.assertIs(fk["text_format"], LLMInvestigationOutput)

    def test_view_version_and_hash_recorded_and_reproducible(self):
        out = offline_output("SC2", "EXC-SC2-01")
        s, inv = self.run_tools([final(out)])
        m = s["result"]["model_metadata"]
        self.assertEqual(m["model_view_version"], MODEL_VIEW_VERSION)
        self.assertEqual(m["model_view_sha256"], model_view_sha256(s["packet"]))
        self.assertIn(model_view_text(s["packet"]), requests_of(inv)[0]["input"][0]["content"])  # exactly what was sent

    def test_prompt_rules_preserved(self):
        for prompt in (SYSTEM_PROMPT, TOOLS_SYSTEM_PROMPT):
            for phrase in ("Never treat it as zero", "Do not state a cause as fact", "Candidate relationships are UNVERIFIED",
                           "Do not resolve, close, approve", "untrusted data", "Actual contradiction", "Causal wording is refused",
                           "Cite only IDs listed in allowed_citation_ids", "citation_classes", "hypotheses_only_ids"):
                self.assertIn(phrase, prompt)
        msg = model_user_message(offline_packet := PACKETS[0][3])
        self.assertIn("every MISS- item", msg)
        self.assertIn("untrusted data", msg)
        self.assertTrue(offline_packet["packet_sha256"] in msg)


class CandidatesHypothesesOnly(unittest.TestCase):
    def test_candidate_ids_hypothesis_only(self):
        seen = 0
        for label, _, _, p, *_ in PACKETS:
            v = render_model_view(p)
            cands = {c["candidate_id"] for c in p["candidate_relationships"]}
            cc = v["citation_classes"]
            self.assertEqual(set(cc["hypotheses_only_ids"]), cands, label)
            self.assertFalse(cands & set(cc["confirmed_finding_ids"]), label)
            self.assertEqual(sorted(cc["confirmed_finding_ids"] + cc["hypotheses_only_ids"]), p["allowed_citation_ids"], label)  # never broadened
            self.assertEqual(v["candidate_relationships_HYPOTHESES_ONLY"], p["candidate_relationships"])
            seen += bool(cands)
        self.assertGreater(seen, 0)


class IndependentCitationCheck(unittest.TestCase):
    """Every record the view carries is checked against the original source CSV row named by its source_file and
    source_line (independent of the application's own loaders)."""
    def test_view_rows_match_the_source_csv_files(self):
        checked = 0
        for label, pack_id, _, p, store, *_ in PACKETS:
            if not label.startswith("scenario:"):
                continue
            r = reconstruct_packet(render_model_view(p))
            for rec in r["source_records"]:
                if not rec["source_file"].endswith(".csv"):
                    continue
                path = store.dir / rec["source_file"]  # the scenario's own dataset directory
                self.assertTrue(path.is_file(), path)
                with open(path, newline="", encoding="utf-8") as f:
                    rows = list(csv.DictReader(f))
                row = rows[rec["source_line"] - 2]
                self.assertEqual({k: v for k, v in rec["fields"].items() if k in row}, {k: row[k] for k in rec["fields"] if k in row}, rec["evidence_id"])
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), rec["file_sha256"], rec["evidence_id"])
                checked += 1
        self.assertGreater(checked, 100)


def tearDownModule():
    if SIZES:
        old = sum(s[1] for s in SIZES)
        new = sum(s[2] for s in SIZES)
        print(f"\n[phase 4] {len(SIZES)} packets: {old} -> {new} characters ({100 * (old - new) / old:.1f}% smaller)")


if __name__ == "__main__":
    unittest.main()
