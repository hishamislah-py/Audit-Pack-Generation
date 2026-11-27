r"""Validation tool (not used by the application). Drives one UC-042 demo scenario end to end through the analyst API
(the same calls the React app makes) and saves every output for validation and comparison.

    .venv\Scripts\python.exe deploy\validation\uc042_demo_journey.py --base http://127.0.0.1:8780 \
        --password-file <file holding the account password> --out .runtime\validation \
        --scenario all|clean|dunmore|dunmore_corrected|halden [--decide accept|none]

Scenarios and expected results come from demo_datasets/september_2026/*_STEPS.md.

Steps: register ZIP -> start Smart Parser -> mapping decisions (suggested field, or the scenario's table) -> confirm ->
upload late/refused files -> (auto) validation, activation, reconciliation -> wait for AI operations to settle ->
optional analyst decisions -> one-click audit pack (open review, preview, GENERATE) -> download outputs.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rfclient import ApiError, Client  # noqa: E402

SEP = "september_2026"
DUNMORE_IN12 = {"Settlement Run": "batch_id", "Counterparty": "counterparty_type", "Run Date": "cycle_date",
                "Value Date": "settlement_date", "Receiving Account": "account_id", "Ccy": "currency",
                "Flow": "direction", "Gross Value": "gross_amount", "Fees Deducted": "total_fees",
                "Adjustments": "total_adjustments", "Net Value": "net_amount_reported",
                "Bank Ref": "expected_bank_reference", "Ops Comment": None}
SCENARIOS = {
    "clean": {"customer": "Clean Control Ltd", "zip": "01_Clean_Control_Ltd_September_2026_CONTROL.zip",
              "later": {}, "tables": {}, "expect": {"exceptions": 0, "statement": "Everything checks out"}},
    "dunmore": {"customer": "Dunmore Payments Ltd", "zip": "06_Dunmore_Payments_Ltd_September_2026_TC04_initial_mapping.zip",
                "later": {"IN-12": "06_Dunmore_Payments_Ltd_September_2026_TC04_upload_later/settlement_batches_2026-09.csv"},
                "tables": {"IN-12": DUNMORE_IN12}, "expect": {"exceptions": 2}},
    "dunmore_corrected": {"customer": "Dunmore Payments Ltd", "zip": "07_Dunmore_Payments_Ltd_September_2026_TC04_corrected.zip",
                          "later": {}, "tables": {}, "expect": {"exceptions": 0, "statement": "Everything checks out"}},
    "halden": {"customer": "Halden Brook Payments Ltd", "zip": "15_Halden_Brook_Payments_Ltd_September_2026.zip",
               "later": {"IN-13": "15_Halden_Brook_Payments_Ltd_September_2026_upload_later/settlement_lines_2026-09.csv"},
               "tables": {}, "expect": {"exceptions": 7}},
}
AI_BUSY = {"QUEUED", "RUNNING", "PENDING", "STARTING", "IN_PROGRESS", "INVESTIGATING"}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def _act(c, ref, d, sc, data, trail, uploaded, decided_files):
    acted = False
    out_ = d.get("outstanding") or {}
    for m in out_.get("mapping_decisions") or []:
        fv, cat = m["file_version_id"], m["category"]
        if fv in decided_files:
            continue
        rv = c.get(f"/api/cases/{ref}/review/{fv}")
        table = sc["tables"].get(cat, {})
        for row in rv["rows"]:
            if row.get("decided") or not (row.get("needs_attention") or row["source_header"] in table):
                continue
            h = row["source_header"]
            if h in table:
                tgt = table[h]
            else:
                tgt = row.get("suggested_field")
                if not tgt:
                    raise RuntimeError(f"{cat}: no suggestion and no table entry for column {h!r}")
            acts = row.get("available_actions") or []
            if tgt is None:
                action = "IGNORE"
            elif "MAP" in acts and row.get("suggested_field") == tgt:
                action = "MAP"                      # accept the suggested field
            else:
                action = "CHANGE"                   # choose a different / unsuggested field
            body = {"source_index": row["source_index"], "action": action}
            if tgt:
                body["canonical_field"] = tgt
            c.post(f"/api/cases/{ref}/review/{fv}/decision", body)
            trail["steps"].append({"mapping": cat, "column": h, "decision": body["action"], "field": tgt})
        rv = c.get(f"/api/cases/{ref}/review/{fv}")
        if not rv.get("can_confirm"):
            raise RuntimeError(f"{cat}: review cannot be confirmed: {json.dumps(rv.get('counts'))}")
        c.post(f"/api/cases/{ref}/review/{fv}/confirm", {})
        decided_files.add(fv)
        log("confirmed mapping", cat, f"({rv['counts']['decided']} decisions)")
        acted = True
    for miss in out_.get("missing_categories") or []:
        cat = miss["category"]
        if cat in sc["later"] and cat not in uploaded:
            f = data / SEP / sc["later"][cat]
            s = c.post("/api/staging", {"name": f.name, "data_b64": c.b64(f)})
            sid = [e for e in s["entries"] if e.get("staging_id")][0]["staging_id"]
            c.post(f"/api/cases/{ref}/evidence", {"staging_id": sid, "category": cat})
            uploaded.add(cat)
            trail["steps"].append({"late_upload": cat, "file": f.name})
            log("uploaded late file", cat, f.name)
            acted = True
    return acted


def run(c: Client, sc: dict, data: Path, out: Path, decide: str) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    trail = {"scenario": sc, "steps": []}
    z = data / SEP / sc["zip"]
    d = c.post("/api/cases", {"customer_name": sc["customer"], "reporting_period": "2026-09", "zip_name": z.name,
                              "zip_b64": c.b64(z)})
    ref = d["case_ref"]
    log("registered", ref)
    c.post(f"/api/cases/{ref}/start", {"expected_revision": d.get("revision")})
    uploaded, decided_files, requested = set(), set(), set()
    deadline = time.time() + 900
    while time.time() < deadline:
        d = c.get(f"/api/cases/{ref}")
        steps = {s["key"]: s["state"] for s in d["steps"]}
        if steps.get("reconciliation") == "done":
            break
        if d["status"] in ("FAILED",) or (d.get("current_run") or {}).get("status") == "FAILED":
            raise RuntimeError(f"case failed: {json.dumps(d.get('current_run'))[:500]}")
        busy = (d.get("current_run") or {}).get("status") in ("RUNNING", "QUEUED") or any(
            v == "running" for v in steps.values())
        acted = False
        out_ = d.get("outstanding") or {}
        try:
            acted = _act(c, ref, d, sc, data, trail, uploaded, decided_files)
        except ApiError as e:
            if e.status == 409 and isinstance(e.payload, dict) and e.payload.get("error") in ("OPERATION_RUNNING", "CASE_CHANGED"):
                time.sleep(2)
                continue
            raise
        out_ = {}
        if not acted and not busy:
            acts = d.get("actions") or {}
            if (acts.get("activate") or {}).get("enabled") and "activate" not in requested:
                c.post(f"/api/cases/{ref}/activate", {"confirm": True, "expected_revision": d.get("revision")})
                requested.add("activate")
                trail["steps"].append({"manual": "activate"})
                log("activated package (manual step, as in the walkthrough)")
            elif (acts.get("reconcile") or {}).get("enabled") and "reconcile" not in requested:
                c.post(f"/api/cases/{ref}/reconcile", {"expected_revision": d.get("revision")})
                requested.add("reconcile")
                trail["steps"].append({"manual": "reconcile"})
                log("reconciliation started (manual step, as in the walkthrough)")
        time.sleep(2)
    else:
        raise TimeoutError("reconciliation did not complete")
    log("reconciliation done; case status", d["status"])
    (out / "case.json").write_text(json.dumps(d, indent=1), encoding="utf-8")

    base = f"/api/cases/{ref}/closure"
    v = c.wait(lambda: c.get(base), lambda x: (x.get("pack") or {}).get("status") in ("GENERATED", "FAILED", "UNAVAILABLE"),
               "engine pack", 600)
    # let every AI operation settle (AI off: UNAVAILABLE; capture mode: FAILED after the recorded request)
    v = c.wait(lambda: c.get(base), lambda x: not any((e.get("ai_state") or "") in AI_BUSY for e in x.get("exceptions") or []),
               "AI operations", 900, every=3)
    trail["ai_states"] = {e["exception_id"]: e.get("ai_state") for e in v.get("exceptions") or []}
    log("AI states", trail["ai_states"])
    if decide == "accept":
        for e in v.get("exceptions") or []:
            if e.get("investigation_id") and not e.get("analyst_decision"):
                v = c.get(base)
                c.post(f"{base}/investigations/{e['investigation_id']}/decision",
                       {"decision": "ACCEPT", "expected_revision": v["revision"], "explanation": None})
                trail["steps"].append({"decision": "ACCEPT", "exception": e["exception_id"]})
        v = c.get(base)
    (out / "closure_before_pack.json").write_text(json.dumps(v, indent=1), encoding="utf-8")
    for e in v.get("exceptions") or []:
        (out / "exceptions").mkdir(exist_ok=True)
        (out / "exceptions" / f"{e['exception_id']}.json").write_text(
            json.dumps(c.get(f"{base}/exceptions/{e['exception_id']}"), indent=1), encoding="utf-8")
    (out / "pack_view.json").write_text(json.dumps(c.get(base + "/pack"), indent=1), encoding="utf-8")

    # one-click audit pack (Closing.jsx)
    if not (v.get("review") or {}).get("review_id"):
        c.post(base + "/review", {"expected_revision": v["revision"]})
        v = c.get(base)
    pv = v["review"].get("current_preview")
    if not pv or pv.get("stale"):
        before = pv["preview_id"] if pv else None
        r = c.post(base + "/review/preview", {"confirm_ai": False, "expected_revision": v["revision"]})

        def ok(x):
            c2 = (x.get("review") or {}).get("current_preview")
            f = (x.get("review") or {}).get("last_preview_failure")
            if f and (not c2 or str(f.get("at", "")) > str(c2.get("created_at", ""))):
                raise RuntimeError(f"preview failed: {json.dumps(f)[:600]}")
            return c2 and not c2.get("stale") and (r.get("reused") or c2.get("preview_id") != before)
        v = c.wait(lambda: c.get(base), ok, "preview", 300)
        pv = v["review"]["current_preview"]
    c.post(base + "/review/decision", {"decision": "GENERATE", "acknowledgement_accepted": True,
                                       "acknowledged_summary_unavailable": pv.get("closing_summary_status") == "UNAVAILABLE",
                                       "snapshot_sha256": pv["snapshot_sha256"], "expected_revision": v["revision"]})
    v = c.wait(lambda: c.get(base), lambda x: x.get("frozen") or x.get("last_generation_failure"), "generate", 600)
    if not v.get("frozen"):
        raise RuntimeError(f"generation failed: {json.dumps(v.get('last_generation_failure'))[:600]}")
    (out / "closure_final.json").write_text(json.dumps(v, indent=1), encoding="utf-8")
    fp = c.get(base + "/final-pack")
    (out / "final_pack_view.json").write_text(json.dumps(fp, indent=1), encoding="utf-8")
    (out / "final").mkdir(exist_ok=True)
    for f in fp.get("files") or []:
        (out / "final" / f["name"]).write_bytes(c.get(f["url"], raw=True))
    run_id = (d.get("current_run") or {}).get("run_id")
    trail.update(case_ref=ref, final_pack_id=fp.get("final_pack_id"), integrity=fp.get("integrity"),
                 verified=fp.get("verified"), files=[f["name"] for f in fp.get("files") or []],
                 exceptions=len(v.get("exceptions") or []),
                 statement=((v.get("deterministic_summary") or {}).get("statement") or {}).get("headline"),
                 recon_run_id=v.get("recon_run_id"), smart_parser_run=run_id)
    exp = sc["expect"]
    trail["expect_ok"] = (trail["exceptions"] == exp["exceptions"]
                          and ("statement" not in exp or trail["statement"] == exp["statement"]))
    (out / "journey.json").write_text(json.dumps(trail, indent=1), encoding="utf-8")
    log("DONE", ref, "exceptions", trail["exceptions"], "|", trail["statement"], "| pack", trail["integrity"],
        "| expected:", "OK" if trail["expect_ok"] else "MISMATCH")
    return trail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--password-file", required=True)
    ap.add_argument("--user", default="analyst@ringfence.demo")
    ap.add_argument("--scenario", required=True, choices=list(SCENARIOS) + ["all"])
    ap.add_argument("--data", default=str(Path(__file__).resolve().parents[2] / "demo_datasets"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--decide", choices=["accept", "none"], default="accept")
    a = ap.parse_args()
    c = Client(a.base)
    c.login(a.user, Path(a.password_file).read_text().strip())
    names = list(SCENARIOS) if a.scenario == "all" else [a.scenario]
    results = {}
    for n in names:
        log("=== scenario", n)
        results[n] = run(c, SCENARIOS[n], Path(a.data), Path(a.out) / n, a.decide)
    ok = all(r["expect_ok"] for r in results.values())
    print(json.dumps({n: {k: r[k] for k in ("case_ref", "exceptions", "statement", "integrity", "expect_ok")}
                      for n, r in results.items()}, indent=1))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
