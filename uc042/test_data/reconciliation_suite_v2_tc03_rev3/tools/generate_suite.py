"""Stage D: generate the TC01-TC06 scenario datasets from shared_baseline/ (no engine code is imported or run).

Usage (from the suite root):  py -3.11 -I tools/generate_suite.py
Re-running replaces only the directories this script creates (TC0n_*/, expected_results/, corrections/).
"""
import csv
import hashlib
import io
import json
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as contract_mod  # noqa: E402
from scenario_specs import SCENARIOS  # noqa: E402

SUITE = Path(__file__).resolve().parent.parent
BASE = SUITE / "shared_baseline"
C = contract_mod.Contract(contract_mod.load())
NOTICE = ("ILLUSTRATIVE SYNTHETIC DATA - UC-042 RECONCILIATION TEST SUITE V2 - NOT REAL FINANCIAL RECORDS. Derived from "
          "set_01_clean_baseline; all names, accounts, references and amounts are fictional.")
ZIP_TIME = (2026, 10, 2, 9, 0, 0)
GENERATED = "Generated 2026-11-23 by tools/generate_suite.py"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def read_rows(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def csv_bytes(fid, rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=C.columns(fid), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


def src_path(root, fid):
    return Path(root) / "source_data" / C.filename(fid)


def baseline_guard():
    """The baseline copy is intact, and rewriting any baseline CSV with this writer reproduces it byte for byte
    (so a rewritten file differs from the baseline only where an operation changed it)."""
    with open(BASE / "manifest.csv", encoding="utf-8", newline="") as f:
        man = list(csv.DictReader(f))
    for m in man:
        if sha(BASE / m["relative_path"]) != m["sha256"]:
            raise SystemExit(f"shared_baseline changed: {m['relative_path']}")
    for fid in C.csv:
        p = src_path(BASE, fid)
        if csv_bytes(fid, read_rows(p)) != p.read_bytes():
            raise SystemExit(f"round-trip not byte-identical for {fid}")
    return man


def apply_ops(root, ops):
    """scenarios.py operation semantics: fail loudly if a target or old value is not as expected."""
    for op in ops:
        fid = op["file_id"]
        pk = C.pk(fid)
        p = src_path(root, fid)
        rows = read_rows(p)
        idx = {r[pk]: i for i, r in enumerate(rows)}
        if op["op"] == "delete_record":
            if op["key"] not in idx:
                raise ValueError(f"delete target not found: {op}")
            rows.pop(idx[op["key"]])
        elif op["op"] == "set_field":
            r = rows[idx[op["key"]]]
            if r[op["field"]] != op["old"]:
                raise ValueError(f"old value mismatch: {op} (found {r[op['field']]})")
            r[op["field"]] = op["new"]
        elif op["op"] == "add_record":
            rec = op["record"]
            if list(rec) != C.columns(fid):
                raise ValueError(f"record columns differ from the {fid} header: {list(rec)}")
            if rec[pk] in idx:
                raise ValueError(f"record already exists: {rec[pk]}")
            after = op.get("insert_after")
            if after and after not in idx:
                raise ValueError(f"insert_after not found: {after}")
            rows.insert(idx[after] + 1 if after else len(rows), rec)
        else:
            raise ValueError(f"unknown op {op['op']}")
        p.write_bytes(csv_bytes(fid, rows))


def write_manifest(root, base_manifest):
    out = []
    for m in base_manifest:
        p = Path(root) / m["relative_path"]
        n = str(len(read_rows(p))) if m["format"] == "CSV" else m["record_count"]
        out.append(dict(m, record_count=n, sha256=sha(p)))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(base_manifest[0]), lineterminator="\n")
    w.writeheader()
    w.writerows(out)
    (Path(root) / "manifest.csv").write_bytes(buf.getvalue().encode("utf-8"))


def make_case(dst, ops, base_manifest, scen, submission):
    dst = Path(dst)
    dst.mkdir(parents=True)
    shutil.copytree(BASE / "source_data", dst / "source_data")
    shutil.copytree(BASE / "supporting_documents", dst / "supporting_documents")
    apply_ops(dst, ops)
    write_manifest(dst, base_manifest)
    (dst / "scenario.json").write_text(json.dumps({
        "scenario_id": scen["scenario_id"], "name": scen["title"], "customer_label": scen["customer_label"], "submission": submission,
        "reporting_period": "PER-2026-09", "derived_from": "set_01_clean_baseline",
        "baseline_manifest_sha256": sha(BASE / "manifest.csv"), "synthetic_notice": NOTICE}, indent=2) + "\n", encoding="utf-8")


def evidence_files(case):
    case = Path(case)
    return sorted(list((case / "source_data").iterdir()) + list((case / "supporting_documents").iterdir()), key=lambda p: p.name)


def upload_zip(case, out):
    """Flat ZIP of the 19 canonical evidence files only (UC042_ZIP_INPUT_SPECIFICATION section 4: no manifest, README or key)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in evidence_files(case):
            zi = zipfile.ZipInfo(p.name, ZIP_TIME)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, p.read_bytes())


def restore_ops(fid, initial_root):
    """add_record ops that put back baseline rows deleted in the initial submission, at their baseline positions."""
    pk = C.pk(fid)
    base = read_rows(src_path(BASE, fid))
    have = {r[pk] for r in read_rows(src_path(initial_root, fid))}
    ops = []
    for i, r in enumerate(base):
        if r[pk] not in have:
            ops.append({"op": "add_record", "file_id": fid, "record": r, "insert_after": base[i - 1][pk] if i else None,
                        "why": "restored from the complete source export"})
            have.add(r[pk])
    return ops


def fmt_op(op):
    if op["op"] == "set_field":
        return op["file_id"], op["key"], op["field"], op["old"], op["new"]
    if op["op"] == "delete_record":
        return op["file_id"], op["key"], "(record)", "present", "deleted"
    pk = C.pk(op["file_id"])
    vals = ", ".join(f"{k}={v}" for k, v in op["record"].items() if k != pk)
    return op["file_id"], op["record"][pk], "(record)", "absent", f"added{' after ' + op['insert_after'] if op.get('insert_after') else ''}: {vals}"


def mutation_md(scen, ops, title):
    lines = [f"# {scen['scenario_id']} - {title}", "", f"> {NOTICE}", "", f"**Scenario:** {scen['title']}", "",
             f"**Customer label:** {scen['customer_label']}  |  **Period:** PER-2026-09  |  **Baseline:** set_01_clean_baseline", "",
             "| # | Op | File | Record | Field | Old | New / detail | Why |", "|---|---|---|---|---|---|---|---|"]
    for n, op in enumerate(ops, 1):
        fid, key, field, old, new = fmt_op(op)
        lines.append(f"| {n} | {op['op']} | {fid} `{C.filename(fid)}` | `{key}` | {field} | {old} | {new} | {op['why']} |")
    return lines


def table(rows, head):
    return [f"| {' | '.join(head)} |", "|" + "---|" * len(head)] + [f"| {' | '.join(str(c) for c in r)} |" for r in rows]


def expected_md(scen):
    s = scen
    L = [f"# {s['scenario_id']} - Expected results", "", f"> {NOTICE}", "",
         f"**{s['title']}**", "", f"Customer label: {s['customer_label']}. Period PER-2026-09 (1-30 Sep 2026), reconciliation point 17:00 Europe/London.", "",
         "## Business situation", "", s["business"], "",
         "## Evidence files involved", ""]
    files = sorted({op["file_id"] for op in s["ops"]} | ({op["file_id"] for op in s.get("correction", {}).get("ops", [])} if s.get("correction") else set())
                   | set(s.get("correction", {}).get("restore_from_baseline", [])))
    L += [f"- {fid} `{C.filename(fid)}` (mutated)" for fid in files]
    L += [f"- unchanged on purpose: {x}" for x in s["unchanged_on_purpose"]]
    L += ["", "## 1. Deterministic financial expectations (FIN)", "",
          "Calculated from the specification and re-derived from the generated files by `tools/validate_suite.py` (independent of the engine).", ""]
    for k, v in s["fin"]["summary"].items():
        L.append(f"- **{k}:** {json.dumps(v) if not isinstance(v, str) else v}")
    L += ["", "**Key figures**", ""] + table(sorted(s["fin"]["figures"].items()), ["metric | scope", "value"])
    L += ["", "**Complete expected finding set of the independent validator** (anything else is a generation error)", ""]
    L += [f"- `{a}`" for a in sorted(s["fin"]["expected_anomalies"])]
    p = s["engine_predicted"]
    L += ["", "## 2. Current engine: ENGINE-PREDICTED (source reading only; NOT EXECUTED; unverified)", "",
          f"Expected case status: **{p['expected_case_status']}**. Exception IDs assume `scenario.json` scenario_id `{s['scenario_id']}`; "
          "Ringfence-assigned identifiers are PENDING (gap G-20). Root causes are the stable key.", ""]
    L += table(p["non_passing_results"], ["check_id", "scope", "outcome"]) + [""]
    L += table([[x["exception_id"], x["severity"], f"`{x['root_cause']}`", x["affected_results"]] for x in p["exceptions"]],
               ["exception_id (predicted)", "severity", "root_cause", "affected_results"])
    L += ["", f"- Evidence statuses: {p['evidence_statuses'] or 'none'}", f"- Investigation groups: {p['investigation_groups'] or 'none'}",
          f"- Candidate relationships (UNVERIFIED): {p['candidate_relationships'] or 'none'}"]
    L += [f"- Must hold: {m}" for m in p["must_hold"]] + [f"- **Note:** {n}" for n in p["notes"]]
    L += ["", "## 3. Desired future behaviour: FUTURE (PROPOSED, not implemented)", "", f"Root: `{s['future']['root']}`; gaps {', '.join(s['future']['gaps'])}.", ""]
    L += [f"- {x}" for x in s["future"]["expected"]]
    a = s["ai"]
    L += ["", "## 4. AI investigation expectations (separate from FIN)", ""]
    if a.get("group_level"):
        L.append("- Level: **group** (one conclusion across the exceptions); currently investigation runs per exception (gap G-17).")
    L += [f"- Finding: {x}" for x in a["findings"]] + [f"- Connecting evidence: {x}" for x in a.get("connecting_evidence", [])]
    L += [f"- Evidence reference: {x}" for x in a["evidence"]] + [f"- Missing evidence: {x}" for x in a["missing_evidence"]]
    L += [f"- Confidence: {a['confidence']}"] + [f"- Must not: {x}" for x in a["must_not"]]
    L += ["", "## 5. Expected analyst action", "", a["analyst_action"], ""]
    if s.get("correction"):
        c = s["correction"]
        q = s["engine_predicted_after_correction"]
        L += ["## 6. Correction and re-upload", "", f"- What was wrong: {c['what_was_wrong']}", f"- What changed: {c['what_changed']}",
              f"- FIN after correction: validator findings expected = {c['fin']['expected_anomalies'] or 'none'}",
              f"- ENGINE-PREDICTED after correction: **{q['expected_case_status']}**, {len(q['exceptions'])} exceptions (not executed)"]
        L += [f"  - must hold: {m}" for m in q["must_hold"]]
        L += ["- Files: `corrections/replacement_files/` (only the replaced files), `corrections/corrected_case/` (complete corrected case), "
              f"`upload/{s['scenario_id']}_corrected_evidence_upload.zip`", ""]
    else:
        L += ["## 6. Correction and re-upload", "", "None for this scenario (by design).", ""]
    return "\n".join(L) + "\n"


def scenario_readme(s):
    corr = s.get("correction")
    return "\n".join([
        f"# {s['scenario_id']} - {s['title']}", "", f"> {NOTICE}", "", s["business"], "",
        "| Path | Contents |", "|---|---|",
        "| `initial_submission/` | Engine-layout case directory: `source_data/` (14 CSV), `supporting_documents/` (5 PDF), `manifest.csv`, `scenario.json` |",
        "| `mutations.json`, `MUTATION_RECORD.md` | Every intentional change against the clean baseline (with old values) |",
        "| `expected_results/` | FIN answer key, ENGINE-PREDICTED keys, FUTURE (proposed), AI expectations, `EXPECTED_RESULTS.md` |",
        f"| `corrections/` | {'Replacement files, complete corrected case, correction record' if corr else 'not applicable (no correction in this scenario)'} |",
        "| `upload/` | Flat upload ZIPs with the 19 canonical evidence files only |", "",
        "Upload instructions: see `../UPLOAD_INSTRUCTIONS.md`. Nothing in this folder has been executed by the UC-042 engine or application.", ""])


def main():
    base_manifest = baseline_guard()
    # --only TC03 [TC0n ...]: rebuild only the named scenario folders; all other scenario folders are left untouched.
    only = set(sys.argv[sys.argv.index("--only") + 1:]) if "--only" in sys.argv else None
    selected = [s for s in SCENARIOS if only is None or s["scenario_id"] in only]
    if only and len(selected) != len(only):
        raise SystemExit(f"unknown scenario in --only {sorted(only)}")
    for d in [*(SUITE / s["dir"] for s in selected), SUITE / "expected_results", SUITE / "corrections"]:
        if d.exists():
            shutil.rmtree(d)
    log = []
    for s in selected:
        sd = SUITE / s["dir"]
        make_case(sd / "initial_submission", s["ops"], base_manifest, s, "initial")
        (sd / "mutations.json").write_text(json.dumps({"scenario_id": s["scenario_id"], "baseline": "set_01_clean_baseline",
                                                       "operations": s["ops"]}, indent=2) + "\n", encoding="utf-8")
        md = mutation_md(s, s["ops"], "Mutation record (initial submission)") + ["", "**Unchanged on purpose:**", ""] + [f"- {x}" for x in s["unchanged_on_purpose"]]
        er = sd / "expected_results"
        er.mkdir()
        (er / "financial_answer_key.json").write_text(json.dumps({"label": "FIN (deterministic; independent of the engine)",
            "scenario_id": s["scenario_id"], "submission": "initial", **s["fin"]}, indent=2) + "\n", encoding="utf-8")
        (er / "engine_predicted_initial.json").write_text(json.dumps(s["engine_predicted"], indent=2) + "\n", encoding="utf-8")
        (er / "future_behaviour_proposed.json").write_text(json.dumps({"label": "FUTURE (PROPOSED; not implemented; category names PENDING)",
            "scenario_id": s["scenario_id"], **s["future"]}, indent=2) + "\n", encoding="utf-8")
        (er / "ai_investigation_expectations.json").write_text(json.dumps({"label": "AI (expectations for the investigation layer; separate from FIN)",
            "scenario_id": s["scenario_id"], **s["ai"]}, indent=2) + "\n", encoding="utf-8")
        upload_zip(sd / "initial_submission", sd / "upload" / f"{s['scenario_id']}_initial_evidence_upload.zip")
        c = s.get("correction")
        if c:
            cd = sd / "corrections"
            ops = list(c["ops"]) + [op for fid in c.get("restore_from_baseline", []) for op in restore_ops(fid, sd / "initial_submission")]
            # corrected case = initial submission + correction ops
            tmp = cd / "corrected_case"
            tmp.mkdir(parents=True)
            shutil.copytree(sd / "initial_submission" / "source_data", tmp / "source_data")
            shutil.copytree(sd / "initial_submission" / "supporting_documents", tmp / "supporting_documents")
            apply_ops(tmp, ops)
            write_manifest(tmp, base_manifest)
            (tmp / "scenario.json").write_text(json.dumps(dict(json.loads((sd / "initial_submission" / "scenario.json").read_text()),
                                                               submission="corrected"), indent=2) + "\n", encoding="utf-8")
            changed = sorted({op["file_id"] for op in ops})
            for fid in changed:
                (cd / "replacement_files" / "source_data").mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_path(tmp, fid), cd / "replacement_files" / "source_data" / C.filename(fid))
            for fid in c["must_equal_baseline"]:
                if src_path(tmp, fid).read_bytes() != src_path(BASE, fid).read_bytes():
                    raise SystemExit(f"{s['scenario_id']}: corrected {fid} is not byte-identical to the baseline")
            (cd / "correction_mutations.json").write_text(json.dumps({"scenario_id": s["scenario_id"], "applies_to": "initial_submission",
                                                                      "operations": ops}, indent=2) + "\n", encoding="utf-8")
            note = mutation_md(s, ops, "Correction record (applied to the initial submission)")
            note += ["", f"**What was wrong:** {c['what_was_wrong']}", "", f"**What changed:** {c['what_changed']}", "",
                     f"**Replacement files:** {', '.join(f'{f} `{C.filename(f)}`' for f in changed)}", "",
                     "**Expected before correction:** see `../expected_results/engine_predicted_initial.json` and `financial_answer_key.json`.",
                     "**Expected after correction:** see `../expected_results/engine_predicted_after_correction.json` and `financial_answer_key_after_correction.json`.",
                     "", "Re-upload: use `../upload/" + s["scenario_id"] + "_corrected_evidence_upload.zip` (complete set) or the replacement files only, "
                     "as the receiving application requires (see UPLOAD_INSTRUCTIONS.md)."]
            (cd / "CORRECTION_NOTE.md").write_text("\n".join(note) + "\n", encoding="utf-8")
            (er / "financial_answer_key_after_correction.json").write_text(json.dumps({"label": "FIN (deterministic; independent of the engine)",
                "scenario_id": s["scenario_id"], "submission": "corrected", **c["fin"]}, indent=2) + "\n", encoding="utf-8")
            (er / "engine_predicted_after_correction.json").write_text(json.dumps(s["engine_predicted_after_correction"], indent=2) + "\n", encoding="utf-8")
            upload_zip(tmp, sd / "upload" / f"{s['scenario_id']}_corrected_evidence_upload.zip")
            log.append(f"{s['scenario_id']}: correction with {len(ops)} op(s) on {', '.join(changed)}")
        (sd / "MUTATION_RECORD.md").write_text("\n".join(md) + "\n", encoding="utf-8")
        (er / "EXPECTED_RESULTS.md").write_text(expected_md(s), encoding="utf-8")
        (sd / "README.md").write_text(scenario_readme(s), encoding="utf-8")
        log.append(f"{s['scenario_id']}: {len(s['ops'])} op(s) on {', '.join(sorted({o['file_id'] for o in s['ops']}))}")
    # top-level indexes
    (SUITE / "expected_results").mkdir()
    idx = {"label": "Index of expected results; per-scenario files hold the content", "scenarios": []}
    lines = ["# Expected results index", "", "| Scenario | FIN key | ENGINE-PREDICTED (initial) | After correction | FUTURE | AI | Readable |", "|---|---|---|---|---|---|---|"]
    for s in SCENARIOS:
        e = f"../{s['dir']}/expected_results"
        p = s["engine_predicted"]
        q = s.get("engine_predicted_after_correction")
        idx["scenarios"].append({"scenario_id": s["scenario_id"], "dir": f"{s['dir']}/expected_results",
                                 "predicted_status": p["expected_case_status"], "predicted_exceptions": len(p["exceptions"]),
                                 "predicted_after_correction": q["expected_case_status"] if q else None})
        lines.append(f"| {s['scenario_id']} | [{e}/financial_answer_key.json]({e}/financial_answer_key.json) | {p['expected_case_status']}, "
                     f"{len(p['exceptions'])} exc. | {(q['expected_case_status'] if q else 'n/a')} | [future]({e}/future_behaviour_proposed.json) | "
                     f"[ai]({e}/ai_investigation_expectations.json) | [EXPECTED_RESULTS.md]({e}/EXPECTED_RESULTS.md) |")
    lines += ["", "ENGINE-PREDICTED values come from source reading only and have not been executed."]
    (SUITE / "expected_results" / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (SUITE / "expected_results" / "expected_results_index.json").write_text(json.dumps(idx, indent=2) + "\n", encoding="utf-8")
    (SUITE / "corrections").mkdir()
    cl = ["# Corrections index", "", "Correction and re-upload alternatives exist for TC01, TC04 and TC05 only (by design).", "",
          "| Scenario | Replaced files | Note | Corrected upload ZIP |", "|---|---|---|---|"]
    for s in SCENARIOS:
        if s.get("correction"):
            files = sorted(p.name for p in (SUITE / s["dir"] / "corrections" / "replacement_files" / "source_data").iterdir())
            cl.append(f"| {s['scenario_id']} | {', '.join(files)} | [CORRECTION_NOTE.md](../{s['dir']}/corrections/CORRECTION_NOTE.md) | "
                      f"`{s['dir']}/upload/{s['scenario_id']}_corrected_evidence_upload.zip` |")
    (SUITE / "corrections" / "INDEX.md").write_text("\n".join(cl) + "\n", encoding="utf-8")
    (SUITE / "_work" / "generation_log.txt").write_text(GENERATED + "\n" + "\n".join(log) + "\n", encoding="utf-8")
    print("\n".join(log))


if __name__ == "__main__":
    main()
