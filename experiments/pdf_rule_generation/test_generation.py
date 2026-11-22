"""Experiment A2 tests (isolated; run explicitly):
    py -3.11 -m pytest experiments/pdf_rule_generation/test_generation.py -q
Uses a temporary COPY of the UC-042 files the generator reads for the drift/failure tests; the real tree is only read."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
import generate_rules as GR  # noqa: E402
import generated_rules_adapter as G  # noqa: E402

UC042 = Path(r"C:\Users\artlptp263user\p10\uc042_token_optimisation")
needs_uc042 = pytest.mark.skipif(not (UC042 / "uc042lib" / "validate.py").is_file(), reason="UC-042 tree not available")


def _copy_tree(tmp: Path) -> Path:
    root = tmp / "uc042"
    for rel in set(GR.CONSUMER_FILES + GR.DATA_FILES + list(GR.HELPER_FILES.values())) | {"uc042lib/__init__.py", "uc042lib/period.py"}:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(UC042 / rel, root / rel)
    return root


@needs_uc042
def test_generation_is_deterministic_and_matches_the_stored_artefact():
    a, b = GR.render(GR.generate(UC042)), GR.render(GR.generate(UC042))
    assert a == b == (HERE / "generated_pdf_rules.json").read_text(encoding="utf-8")


@needs_uc042
def test_every_label_use_is_classified_or_reported():
    doc = GR.generate(UC042)
    assert doc["unrecognised"] == []
    labels = {l for c in doc["pdf_categories"].values() for l in c["labels"]}
    accounted = {s["label"] for s in doc["sites"]} | set(doc["labels_without_consumer"]) | \
                {m["label"] for m in doc["needs_manual_resolution"]}
    assert labels <= accounted


@needs_uc042
def test_every_site_is_traceable_to_a_source_line():
    doc = GR.generate(UC042)
    for s in doc["sites"]:
        line = (UC042 / s["file"]).read_text(encoding="utf-8").splitlines()[s["line"] - 1].strip()
        assert line == s["source_line"] and s["label"] in line


@needs_uc042
def test_changed_source_is_detected(tmp_path):
    root = _copy_tree(tmp_path)
    before = GR.render(GR.generate(root))
    v = root / "uc042lib/validate.py"
    v.write_text(v.read_text(encoding="utf-8").replace(r'r"^(\d{2}):(\d{2}) Europe/London$"', r'r"^(\d{1,2}):(\d{2}) Europe/London$"'),
                 encoding="utf-8")
    after = GR.render(GR.generate(root))
    assert before != after
    assert r"^(\\d{1,2}):(\\d{2}) Europe/London$" in after


@needs_uc042
def test_missing_source_fails_visibly(tmp_path):
    root = _copy_tree(tmp_path)
    (root / "uc042lib/validate.py").unlink()
    with pytest.raises(GR.GenerationError, match="missing"):
        GR.generate(root)


@needs_uc042
def test_consumer_in_an_unconfigured_function_fails_visibly(tmp_path):
    root = _copy_tree(tmp_path)
    v = root / "uc042lib/validate.py"
    v.write_text(v.read_text(encoding="utf-8") + '\n\ndef new_check(p):\n    return p.get("Role") == "CFO"\n', encoding="utf-8")
    with pytest.raises(GR.GenerationError, match="no configured consequence"):
        GR.generate(root)


@needs_uc042
def test_check_mode_reports_drift(tmp_path):
    out = tmp_path / "rules.json"
    assert GR.main(["--uc042-root", str(UC042), "--out", str(out)]) == 0
    assert GR.main(["--uc042-root", str(UC042), "--out", str(out), "--check"]) == 0
    out.write_text(out.read_text(encoding="utf-8").replace("Europe/London", "Europe/Paris"), encoding="utf-8")
    assert GR.main(["--uc042-root", str(UC042), "--out", str(out), "--check"]) == 1


def test_changed_helper_is_refused_until_re_pinned(tmp_path):
    doc = json.loads((HERE / "generated_pdf_rules.json").read_text(encoding="utf-8"))
    doc["helpers"]["_date_or_none"]["source_sha256"] = "0" * 64
    art = tmp_path / "a.json"
    art.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(G.AdapterError, match="not pinned or changed"):
        G.load(art)


def test_business_level_sites_never_become_extraction_rules():
    rules, no_rule, doc_rules = G.build(G.load())
    ids = {r.rule_id for cat in rules.values() for rs in cat.values() for r in rs}
    assert not any(p in i for i in ids for p in ("CONST_EQUALS", "CROSS_DOC_EQUALS", "NON_EMPTY", "COMPUTED_EQUALS"))
    assert doc_rules("IN-19", {"Submitted at": "2026-09-17T11:02:00+01:00", "Due date": "2026-09-21"}) == []
    assert no_rule[("IN-15", "Currency")].startswith("downstream UC-042 control only")


def test_generated_syntax_rules_match_uc042_on_the_oracle_values():
    oracle = json.loads((Path(r"C:\Users\artlptp263user\p10\pdfx_experiment_a2") / "uc042_helper_oracle.json").read_text(encoding="utf-8"))
    rules, _, _ = G.build(G.load())
    from smartparser.pdf_extraction.rules import Context
    ctx = Context(period_id="PER-2026-09")
    pick = {"date": ("IN-15", "Letter date"), "timestamp": ("IN-19", "Submitted at"), "point": ("IN-17", "Reconciliation point")}
    for kind, (cat, label) in pick.items():
        rs = [r for r in rules[cat][label] if r.rule_id.startswith("GEN:" + label)]
        for value, readable in oracle[kind].items():
            if value:
                ok = all(not (res == "FAIL" and d.startswith("FORMAT:")) for r in rs for res, d in [r.check(value, ctx)])
                assert ok == readable, (label, value)
