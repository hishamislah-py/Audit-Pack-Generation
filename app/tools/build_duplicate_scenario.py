"""Ringfence demo scenario 5 (RF-DEMO-05): duplicate refund (refund counted twice), built from the canonical UC-042
dataset scn_SC5C_refund_double_posted and its FROZEN answer key. Nothing is generated or invented.

    py -3.11 -B tools/build_duplicate_scenario.py build  [--out <RINGFENCE_DEMO_TEST_DATA>] [--dataset <scn dir>]
    py -3.11 -B tools/build_duplicate_scenario.py verify [--out <RINGFENCE_DEMO_TEST_DATA>] [--ws <workspace>] [--port N]

build
  * copies the BYTES of the 14 CSVs (source_data/) and 5 PDFs (supporting_documents/) listed in the dataset's
    manifest.csv into a ZIP under customer-like member names (the Smart Parser classifies by content, O7). Every member
    is re-read from the ZIP and its sha256 compared with manifest.csv and with the source file. The dataset's
    validation/ folder (a previous engine run) and its answer key are NOT put in the ZIP.
  * writes scenario.json (customer, period, ZIP sha256 + entries, name mapping, source paths + sha256 list, frozen key
    reference) and expected_outcome.json (copied / derived ONLY from the frozen answer_key.json) BEFORE any run.
  * refuses to overwrite an existing verification_result.json's inputs silently: build is idempotent (same bytes).

verify
  * drives the REAL Ringfence backend (smartparser.webapp.server, fresh workspace, random free port, AI disabled,
    --insecure-no-auth test harness) through register -> start -> (review if needed) -> validation -> activation ->
    reconciliation, compares EXACTLY with the frozen key and writes verification_result.json.
    The HTTP helpers (Server / Checks / wait_case / idle / register) are imported read-only from
    RINGFENCE_DEMO_TEST_DATA/tools/verify_demo_zips.py, so the harness is the one used for scenarios 1-4.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import socket
import sys
import time
import zipfile
from pathlib import Path

DATA = Path(r"C:\Users\artlptp263user\p10\RINGFENCE_DEMO_TEST_DATA")
UC = Path(r"C:\u42x\UC042_SMART_PARSER_E2E_TEST_BUNDLE\src\uc042")
SCN = "scn_SC5C_refund_double_posted"
DATASET = UC / "uc042_dataset" / SCN
MIRRORS = {  # read-only copies that must be byte-identical to DATASET (checked and recorded)
    "token_optimisation_dataset": Path(r"C:\Users\artlptp263user\p10\uc042_token_optimisation\uc042_dataset") / SCN,
    "e2e_bundle_ground_truth": Path(r"C:\u42x\UC042_SMART_PARSER_E2E_TEST_BUNDLE\ground_truth\uc042_scenarios") / SCN,
}
FOLDER = "scenario_5_duplicate"
SID = "RF-DEMO-05"
CUSTOMER = "Pellworth Card Services Ltd"          # fictional
PREFIX = "Pellworth_Sep2026"
NAMES = {
    "IN-01": "01_reconciliation_calendar.csv", "IN-02": "02_safeguarding_accounts.csv",
    "IN-03": "03_client_balances_1700.csv", "IN-04": "04_unallocated_receipts.csv",
    "IN-05": "05_internal_reconciliations.csv", "IN-06": "06_external_reconciliations.csv",
    "IN-07": "07_bank_balances_1700.csv", "IN-08": "08_bank_eod_statements.csv",
    "IN-09": "09_bank_statement_lines.csv", "IN-10": "10_safeguarding_cashbook.csv",
    "IN-11": "11_card_transactions.csv", "IN-12": "12_settlement_batches.csv",
    "IN-13": "13_settlement_lines.csv", "IN-14": "14_breaks_log.csv",
    "IN-15": "docs/bank_acknowledgement_GBP.pdf", "IN-16": "docs/bank_acknowledgement_EUR.pdf",
    "IN-17": "docs/Pellworth_safeguarding_recon_policy_v1.2.pdf",
    "IN-18": "docs/Pellworth_governance_register_Sep2026.pdf",
    "IN-19": "docs/Pellworth_REP027_receipt_Aug2026.pdf",
}
SYN = ("ILLUSTRATIVE SYNTHETIC DATA - UC-042 RINGFENCE DEMONSTRATION - NOT REAL FINANCIAL RECORDS "
       "(canonical dataset scn_SC5C_refund_double_posted; fictional customer name)")


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def manifest(ds: Path) -> list[dict]:
    with open(ds / "manifest.csv", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def zip_bytes(entries: list[tuple[str, bytes]], when: tuple) -> bytes:
    """Same deterministic writer as the demo bundle's build_scenarios.zip_bytes (fixed time, deflate, 0644)."""
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries:
            zi = zipfile.ZipInfo(name, date_time=when)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, data)
    return b.getvalue()


def tree_hashes(d: Path) -> dict[str, str]:
    return {p.relative_to(d).as_posix(): sha(p.read_bytes()) for p in sorted(d.rglob("*")) if p.is_file()}


def case_status_from_key(key: dict) -> str:
    """uc042lib.validate.case_status semantics applied to the key's non-passing results: any INSUFFICIENT_EVIDENCE ->
    EVIDENCE_INCOMPLETE, else any FAIL -> EXCEPTIONS_OPEN, else CLEAN. The key has no explicit case_status field."""
    outs = [r[2] for r in key["non_passing_results"]]
    return "EVIDENCE_INCOMPLETE" if "INSUFFICIENT_EVIDENCE" in outs else ("EXCEPTIONS_OPEN" if "FAIL" in outs else "CLEAN")


def expected_from_key(key: dict, key_path: Path) -> dict:
    by_id = {e["exception_id"]: e for e in key["exceptions"]}
    groups = [sorted(by_id[x]["root_cause"] for x in g) for g in key["investigation_groups"]]
    return {
        "source": f"{key_path} (frozen; copied unchanged under frozen_key)",
        "source_sha256": sha(key_path.read_bytes()),
        "written_before_any_run": True,
        "expected_case_status": case_status_from_key(key),
        "expected_case_status_basis": "derived from the key's non_passing_results with uc042lib.validate.case_status "
                                      "semantics (all FAIL, no INSUFFICIENT_EVIDENCE -> EXCEPTIONS_OPEN)",
        "expected_counts": {o: sum(r[2] == o for r in key["non_passing_results"]) for o in ("FAIL", "INSUFFICIENT_EVIDENCE")},
        "expected_non_passing_set": sorted(list(r) for r in key["non_passing_results"]),
        "expected_exception_count": len(key["exceptions"]),
        "expected_exception_root_causes": sorted(e["root_cause"] for e in key["exceptions"]),
        "expected_exceptions": sorted(({"severity": e["severity"], "root_cause": e["root_cause"],
                                        "affected_results": e["affected_results"]} for e in key["exceptions"]),
                                      key=lambda x: x["root_cause"]),
        "expected_investigation_group_count": len(key["investigation_groups"]),
        "expected_investigation_groups_by_root_cause": sorted(groups),
        "expected_review_steps": "none expected (canonical headers; AI disabled) - recorded from the run, not assumed",
        "not_predicted": "PASS / NOT_APPLICABLE totals and engine-assigned exception and group IDs (the key's "
                         "EXC-SC5C-nn IDs are the dataset's own; comparison is by root cause).",
        "frozen_key": key,
    }


# ============================================================================================ build
def build(out: Path, ds: Path) -> dict:
    sdir = out / FOLDER
    rows = manifest(ds)
    assert [r["file_id"] for r in rows] == [f"IN-{i:02d}" for i in range(1, 20)], "manifest must list IN-01..IN-19"
    period = {r["reporting_period"] for r in rows}
    assert period == {"PER-2026-09"}, period
    entries, mapping = [], []
    for r in rows:
        data = (ds / r["relative_path"]).read_bytes()
        if sha(data) != r["sha256"]:
            raise SystemExit(f"{r['relative_path']}: sha256 differs from manifest.csv")
        name = f"{PREFIX}/{NAMES[r['file_id']]}"
        entries.append((name, data))
        mapping.append({"category": r["file_id"], "zip_entry": name, "canonical_file": r["filename"],
                        "canonical_relative_path": r["relative_path"], "requirement": r["requirement"],
                        "bytes": len(data), "sha256": sha(data)})
    zb = zip_bytes(entries, (2026, 10, 4, 9, 30, 0))
    with zipfile.ZipFile(io.BytesIO(zb)) as z:              # corrupt-free: every member reads and equals the source
        assert z.testzip() is None
        listing = []
        for m in mapping:
            d = z.read(m["zip_entry"])
            assert sha(d) == m["sha256"]
            listing.append({"entry": m["zip_entry"], "bytes": len(d), "sha256": sha(d), "category": m["category"],
                            "readable": True, "identical_to_canonical_file": True})
    src_hashes = tree_hashes(ds)
    mirrors = {}
    for label, p in MIRRORS.items():
        h = tree_hashes(p) if p.is_dir() else None
        common = sorted(set(h or {}) & set(src_hashes))
        mirrors[label] = {"path": str(p), "present": h is not None, "files": len(h or {}),
                          "common_files": len(common),
                          "all_common_identical": bool(h) and all(h[k] == src_hashes[k] for k in common),
                          "identical_tree": h == src_hashes}
    key_path = ds / "answer_key.json"
    key = json.loads(key_path.read_text(encoding="utf-8"))
    exp = expected_from_key(key, key_path)
    sdir.mkdir(parents=True, exist_ok=True)
    zname = f"{CUSTOMER.replace(' ', '_')}_2026-09.zip"
    (sdir / zname).write_bytes(zb)
    src_meta = json.loads((ds / "scenario.json").read_text(encoding="utf-8"))
    scen = {
        "scenario_id": SID, "source_scenario": SCN, "customer_name": CUSTOMER, "reporting_period": "2026-09",
        "synthetic_notice": SYN,
        "zip": {"file": zname, "sha256": sha(zb), "bytes": len(zb), "entries": listing},
        "name_mapping": mapping,
        "source_dataset": {"path": str(ds), "scenario": src_meta, "manifest_sha256": sha((ds / "manifest.csv").read_bytes()),
                           "files_sha256": src_hashes, "mirrors": mirrors,
                           "excluded_from_zip": ["answer_key.json", "mutations.json", "manifest.csv", "scenario.json",
                                                 "*.md", "validation/* (a previous engine run)"]},
        "frozen_key": {"path": str(key_path), "sha256": sha(key_path.read_bytes()),
                       "mirror_paths": [str(p / "answer_key.json") for p in MIRRORS.values()]},
        "planted_discrepancy": {"description": key["description"], "mutations": str(ds / "mutations.json"),
                                "mutations_sha256": sha((ds / "mutations.json").read_bytes()),
                                "mutation_operations": len(json.loads((ds / "mutations.json").read_text(encoding="utf-8")))},
        "generator": "tools/build_duplicate_scenario.py (byte copy of the canonical files; nothing generated)",
        "all_csv_canonical_layout": True,
        "expected_outcome": {"case_status": exp["expected_case_status"], "fail": exp["expected_counts"]["FAIL"],
                             "insufficient_evidence": exp["expected_counts"]["INSUFFICIENT_EVIDENCE"],
                             "exceptions": exp["expected_exception_count"],
                             "investigation_groups": exp["expected_investigation_group_count"]},
    }
    (sdir / "scenario.json").write_text(json.dumps(scen, indent=1) + "\n", encoding="utf-8")
    ep = sdir / "expected_outcome.json"
    text = json.dumps(exp, indent=1) + "\n"
    if ep.is_file() and ep.read_text(encoding="utf-8") != text:
        raise SystemExit("expected_outcome.json exists with different content; refusing to rewrite the expectation")
    ep.write_text(text, encoding="utf-8")
    print(f"{FOLDER}/{zname} sha256={sha(zb)} bytes={len(zb)} entries={len(entries)}")
    print("mirrors:", json.dumps({k: v["identical_tree"] for k, v in mirrors.items()}))
    return scen


# ============================================================================================ verify
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def verify(out: Path, ws: Path, port: int) -> int:
    sys.path.insert(0, str(out / "tools"))
    import verify_demo_zips as v                                    # read-only import of the scenario 1-4 harness

    sdir = out / FOLDER
    scen = json.loads((sdir / "scenario.json").read_text(encoding="utf-8"))
    exp = json.loads((sdir / "expected_outcome.json").read_text(encoding="utf-8"))
    key = exp["frozen_key"]
    assert sha((Path(scen["frozen_key"]["path"])).read_bytes()) == exp["source_sha256"], "frozen key changed"
    ws.parent.mkdir(parents=True, exist_ok=True)
    log = ws.parent / f"server_{FOLDER}.log"
    print(f"=== {SID}: {CUSTOMER} 2026-09 (port {port}, ws {ws})", flush=True)
    srv = v.Server(ws, port, log)
    ck = v.Checks("S5")
    ev = {"server": {"port": port, "root": str(ws), "llm": srv.app.get("llm"),
                     "engine_configured": srv.app.get("engine_configured"), "reviewer": srv.app.get("reviewer")}}
    t0, err = time.time(), None
    try:
        c = v.register(srv, sdir, scen, ck)
        ref = c["case_ref"]
        ev["case_ref"] = ref
        srv.post(f"cases/{ref}/start", {"expected_revision": c["revision"]})
        c = v.wait_case(srv, ref, v.idle, "Smart Parser run")
        run = c["current_run"]
        ev["smart_parser_run"] = {"run_id": run["run_id"], "status": run["status"], "failure": run["failure"]}
        ck.check("RUN.completed", "Smart Parser run COMPLETED", run["status"], "COMPLETED")
        o = c["outstanding"]
        ev["outstanding_after_run"] = o
        ev["slots_after_run"] = [{"category": s["evidence_category"], "status": (s["latest"] or {}).get("version_status"),
                                  "file": (s["latest"] or {}).get("original_filename")} for s in c["package"]["slots"]]
        by_cat = {s["category"]: s["file"] for s in ev["slots_after_run"]}
        ck.check("RUN.classified", "every category is filled by the ZIP member mapped to it (content classification)",
                 {m["category"]: by_cat.get(m["category"]) for m in scen["name_mapping"]},
                 {m["category"]: m["zip_entry"].split("/")[-1] for m in scen["name_mapping"]})
        ck.check("RUN.nothing_missing", "no missing category, no file requiring replacement, no refused upload",
                 ([m["category"] for m in o["missing_categories"]], o["files_requiring_replacement"], o["refused_uploads"]),
                 ([], [], []))
        reviews = []
        for md in list(o["mapping_decisions"]):                     # recorded, never assumed
            vid = md["file_version_id"]
            rv = srv.get(f"cases/{ref}/review/{vid}")
            steps = []
            for r in rv["rows"]:
                if r["needs_attention"] and not r["decided"]:
                    act = "MAP" if r.get("suggested_field") and "MAP" in r["available_actions"] else "IGNORE"
                    c = srv.get(f"cases/{ref}")
                    srv.post(f"cases/{ref}/review/{vid}/decision", {"action": act, "source_index": r["source_index"],
                                                                    "expected_revision": c["revision"]})
                    steps.append({"source_header": r["source_header"], "action": act, "field": r.get("suggested_field")})
            c = srv.get(f"cases/{ref}")
            srv.post(f"cases/{ref}/review/{vid}/confirm", {"expected_revision": c["revision"]})
            reviews.append({"category": md["category"], "file": md["file_name"], "review_kind": rv["review_kind"],
                            "decisions": steps})
            v.wait_case(srv, ref, v.idle, "after review")
        ev["review_steps"] = reviews
        c = v.wait_case(srv, ref, lambda x: v.idle(x) and x["progress"]["validation"]["state"] in ("PASSED", "FAILED"),
                        "automatic validation", timeout=300)
        ev["validation"] = c["package"]["latest_validation"]
        ck.check("VAL.passed", "automatic package validation PASSED", c["progress"]["validation"]["state"], "PASSED")
        a = srv.post(f"cases/{ref}/activate", {"confirm": True, "expected_revision": c["revision"]})
        ck.check("ACT.snapshot", "activation created a snapshot", (a["activated"], bool(a["snapshot_id"])), (True, True))
        ev["snapshot_id"] = a["snapshot_id"]
        c = srv.get(f"cases/{ref}")
        srv.post(f"cases/{ref}/reconcile", {"expected_revision": c["revision"]})
        c = v.wait_case(srv, ref, lambda x: x["status"] == "COMPLETED" or x["progress"]["reconciliation"]["state"] == "FAILED",
                        "reconciliation", timeout=1500)
        ck.check("REC.completed", "reconciliation finished and the case is COMPLETED", c["status"], "COMPLETED")
        rid = c["completed"]["reconciliation_run_id"]
        run = srv.get(f"runs/{rid}")
        nonpass = []
        for o_ in ("FAIL", "INSUFFICIENT_EVIDENCE"):
            cr = srv.get(f"runs/{rid}/controls?outcome={o_}")
            assert not cr.get("truncated")
            nonpass += cr["rows"]
        exc = run["exceptions"]
        details = {e["exception_id"]: srv.get(f"runs/{rid}/exceptions/{e['exception_id']}") for e in exc}
        # ---- exact comparison with the frozen key
        ck.check("KEY.case_status", "case_status equals the key-derived status",
                 (c["completed"]["case_status"], run["case_status"]), (exp["expected_case_status"],) * 2)
        ck.check("KEY.counts", "FAIL / INSUFFICIENT_EVIDENCE counts",
                 {o_: sum(r["outcome"] == o_ for r in nonpass) for o_ in ("FAIL", "INSUFFICIENT_EVIDENCE")},
                 exp["expected_counts"])
        ck.check("KEY.non_passing", "non-passing (check_id, scope, outcome) set equals the key exactly",
                 sorted([r["check_id"], r["scope"], r["outcome"]] for r in nonpass),
                 sorted(list(r) for r in key["non_passing_results"]))
        ck.check("KEY.exception_count", "exception count", (len(exc), run["exception_count"]),
                 (len(key["exceptions"]),) * 2)
        ck.check("KEY.exception_root_causes", "exception root causes", sorted(e["root_cause"] for e in exc),
                 sorted(e["root_cause"] for e in key["exceptions"]))
        ck.check("KEY.exception_fields", "exception severity / affected results per root cause",
                 sorted(({"severity": x.get("severity"), "root_cause": x["root_cause"],
                          "affected_results": int(x.get("affected_results") or 0)} for x in exc), key=lambda x: x["root_cause"]),
                 exp["expected_exceptions"])
        gid: dict[str, list] = {}
        for x in exc:
            if x.get("investigation_group_id"):
                gid.setdefault(x["investigation_group_id"], []).append(x["root_cause"])
        ck.check("KEY.groups", "investigation groups (root-cause sets) equal the key",
                 sorted(sorted(g) for g in gid.values()), exp["expected_investigation_groups_by_root_cause"])
        ck.check("API.exception_detail", "every exception detail resolves with evidence rows",
                 all(d["exception"]["exception_id"] == i and isinstance(d["evidence"], list) for i, d in details.items()), True)
        ev["reconciliation"] = {
            "run_id": rid, "case_status": run["case_status"], "outcomes": run["outcomes"],
            "total_results": run["total_results"], "exception_count": run["exception_count"],
            "by_severity": run["by_severity"], "integrity_checks": run["integrity_checks"],
            "investigation_groups": {g: sorted(x) for g, x in gid.items()},
            "exceptions": [{k: e.get(k) for k in ("exception_id", "severity", "root_cause", "affected_results", "amount",
                                                  "first_date", "last_date", "evidence_status", "investigation_group_id")}
                           for e in exc],
            "exception_evidence_rows": {i: len(d["evidence"]) for i, d in details.items()},
            "non_passing": [{k: r[k] for k in ("check_id", "scope", "outcome", "root_cause")} for r in nonpass]}
        # closure / audit pack (BE-CLOSURE's concern): record only, never asserted here
        time.sleep(3)
        st, cl = srv.req("GET", f"cases/{ref}/closure", ok_errors=True)
        ev["closure_observed"] = {"http": st, "state": (cl or {}).get("state") if isinstance(cl, dict) else None,
                                  "pack": (cl or {}).get("pack") if isinstance(cl, dict) else None,
                                  "error": (cl or {}).get("error") if isinstance(cl, dict) else None}
    except Exception as exc_:                                       # recorded, not hidden
        err = f"{type(exc_).__name__}: {exc_}"
        print("  ERROR", err, flush=True)
    finally:
        srv.stop()
    res = {"scenario": FOLDER, "scenario_id": SID, "customer_name": CUSTOMER, "reporting_period": "2026-09",
           "zip_sha256": scen["zip"]["sha256"], "frozen_key": scen["frozen_key"],
           "verdict": "PASS" if not err and all(c_["passed"] for c_ in ck.items) else "FAIL",
           "checks_passed": sum(c_["passed"] for c_ in ck.items), "checks_total": len(ck.items), "error": err,
           "seconds": round(time.time() - t0, 1), "harness": "real smartparser.webapp.server over HTTP; AI disabled; "
           "--insecure-no-auth; TEST authority; uc042-root " + str(v.UC),
           "server_log": str(log), "checks": ck.items, "observed": ev, "post_transcript": srv.transcript}
    (sdir / "verification_result.json").write_text(json.dumps(res, indent=1, default=str) + "\n", encoding="utf-8")
    print(f"=== {SID}: {res['verdict']} {res['checks_passed']}/{res['checks_total']} in {res['seconds']}s", flush=True)
    return 0 if res["verdict"] == "PASS" else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("build", "verify"))
    ap.add_argument("--out", default=str(DATA))
    ap.add_argument("--dataset", default=str(DATASET))
    ap.add_argument("--ws", default=r"C:\u42v\impl_20261120\dup\ws")
    ap.add_argument("--port", type=int, default=0)
    a = ap.parse_args()
    if a.cmd == "build":
        build(Path(a.out), Path(a.dataset))
    else:
        sys.exit(verify(Path(a.out), Path(a.ws), a.port or free_port()))


if __name__ == "__main__":
    main()
