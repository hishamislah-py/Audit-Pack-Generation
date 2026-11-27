"""Build four Ringfence / UC-042 Smart Parser demo ZIPs whose CSVs are all in the canonical layout (AI-disabled backend).

    py -3.11 -B tools/build_demo_zips.py --out <RINGFENCE_DEMO_TEST_DATA> [--bundle <UC042_RINGFENCE_DEMO_SCENARIOS>]
                                         [--scratch C:\\u42d]

Reuses, read-only and unmodified, the existing demo bundle's builder (tools/build_scenarios.py): its SCENARIOS design,
`Gen` (seeded month generator + discrepancy planting), `canonical_csv`, `make_pdfs`, `zip_bytes`, FILE_NAMES. Same seeds
and the same generation order as the original, so the planted discrepancies and the frozen answer keys still apply.

Differences from the original customer_submission.zip files:
  * S1: IN-11 in canonical layout (original used a novel layout that needs the LLM).
  * S2: the real IN-08 (canonical) under the scenario's IN-08 file name; the mis-named copy of IN-07 is not included.
  * S3: IN-12 in canonical layout (original used a novel layout that needs the LLM).
  * S4 (new): Thornbury Wallet Ltd, 2026-11, clean data, but the ZIP member for IN-09 carries a wrong CRC-32 so that
    reading it raises zipfile.BadZipFile inside the Smart Parser run (technical failure -> FAILED run).
Every unchanged CSV / PDF is compared byte-for-byte with the corresponding member of the original ZIP.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import struct
import sys
import zipfile
from pathlib import Path

DEFAULT_BUNDLE = Path(r"C:\Users\artlptp263user\Downloads\UC042_RINGFENCE_DEMO_SCENARIOS")

OUT_FOLDERS = {
    "scenario_01_intelligent_mapping": "scenario_1_clean",
    "scenario_02_rejection_correction": "scenario_2_exceptions",
    "scenario_03_human_in_the_loop": "scenario_3_evidence_incomplete",
}

S4 = dict(sid="RF-DEMO-04", customer="Thornbury Wallet Ltd", short="tw", period="2026-11", seed=2026111904,
          client_prefix=(5001, 5101), bank=("INST-WB4", "Westerleigh Bank plc", "9 Ferry Street, Glasgow G0 4WB (fictional)",
                                            "safeguarding@westerleigh-bank.invalid", "+44 141 000 0000"),
          masked={"SGA-GBP-01": "****4416", "SGA-EUR-01": "****4423", "OWN-GBP-01": "****7735", "OWN-EUR-01": "****7742"},
          ack={"SGA-GBP-01": "WLB-SG-4416", "SGA-EUR-01": "WLB-SG-4423"}, letter_date="2025-08-11", open_date="2025-07-28",
          accountable=("T. Thornbury (synthetic)", "Chief Financial Officer (synthetic)", "2026-02-02"),
          optional=("IN-18", "IN-19"), discrepancies=[], parser="TECHNICAL_FAILURE", llm_category=None,
          recon_target="NOT_REACHED")
S4_NAMES = {"IN-01": "Thornbury_Nov2026/01_reconciliation_calendar.csv", "IN-02": "Thornbury_Nov2026/02_safeguarding_accounts.csv",
            "IN-03": "Thornbury_Nov2026/03_client_balances_1700.csv", "IN-04": "Thornbury_Nov2026/04_unallocated_receipts.csv",
            "IN-05": "Thornbury_Nov2026/05_internal_reconciliations.csv", "IN-06": "Thornbury_Nov2026/06_external_reconciliations.csv",
            "IN-07": "Thornbury_Nov2026/07_bank_balances_1700.csv", "IN-08": "Thornbury_Nov2026/08_bank_eod_statements.csv",
            "IN-09": "Thornbury_Nov2026/09_bank_statement_lines.csv", "IN-10": "Thornbury_Nov2026/10_safeguarding_cashbook.csv",
            "IN-11": "Thornbury_Nov2026/11_wallet_transactions.csv", "IN-12": "Thornbury_Nov2026/12_settlement_batches.csv",
            "IN-13": "Thornbury_Nov2026/13_settlement_lines.csv", "IN-14": "Thornbury_Nov2026/14_breaks_log.csv",
            "IN-15": "Thornbury_Nov2026/docs/Westerleigh_acknowledgement_GBP_4416.pdf",
            "IN-16": "Thornbury_Nov2026/docs/Westerleigh_acknowledgement_EUR_4423.pdf",
            "IN-17": "Thornbury_Nov2026/docs/Thornbury_safeguarding_recon_policy_v1.2.pdf",
            "IN-18": "Thornbury_Nov2026/docs/Thornbury_governance_register_Nov2026.pdf",
            "IN-19": "Thornbury_Nov2026/docs/Thornbury_REP027_receipt_Oct2026.pdf"}
S4_CORRUPT_CATEGORY = "IN-09"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def corrupt_crc(zb: bytes, member: str) -> bytes:
    """Flip the CRC-32 of one member in both its local header and its central-directory record. The archive stays
    structurally valid (opens, lists, every other member reads); reading that member raises BadZipFile (Bad CRC-32)."""
    b = bytearray(zb)
    with zipfile.ZipFile(io.BytesIO(zb)) as z:
        info = z.getinfo(member)
    bad = info.CRC ^ 0xA5A5A5A5
    lh = info.header_offset
    assert b[lh:lh + 4] == b"PK\x03\x04"
    struct.pack_into("<I", b, lh + 14, bad)
    name = member.encode()
    i = b.find(b"PK\x01\x02")
    found = 0
    while i != -1:
        n, = struct.unpack_from("<H", b, i + 28)
        if bytes(b[i + 46:i + 46 + n]) == name:
            struct.pack_into("<I", b, i + 16, bad)
            found += 1
        i = b.find(b"PK\x01\x02", i + 4)
    assert found == 1, found
    return bytes(b)


def zip_listing(zb: bytes, names: dict) -> list[dict]:
    rev = {v: k for k, v in names.items() if v}
    out = []
    with zipfile.ZipFile(io.BytesIO(zb)) as z:
        for i in z.infolist():
            try:
                d = z.read(i)
                h, ok = sha(d), True
            except zipfile.BadZipFile as exc:
                h, ok = None, f"UNREADABLE: {exc}"
            out.append({"entry": i.filename, "bytes": i.file_size, "sha256": h, "category": rev.get(i.filename),
                        "readable": ok})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--bundle", default=str(DEFAULT_BUNDLE))
    ap.add_argument("--scratch", default=r"C:\u42d")
    a = ap.parse_args()
    out, bundle = Path(a.out), Path(a.bundle)
    sys.path.insert(0, str(bundle / "tools"))
    import build_scenarios as bs                                   # read-only import of the original builder
    g = bs.Gen(Path(a.scratch))
    schema, P = g.schema, g.P
    cols = {fid: g.proj.columns(fid) for fid in schema.CSV_FILES}
    report = {"source_builder": str(bundle / "tools" / "build_scenarios.py"),
              "source_builder_sha256": sha((bundle / "tools" / "build_scenarios.py").read_bytes()), "scenarios": {}}

    todo = list(bs.SCENARIOS.items()) + [("scenario_04_technical_failure", S4)]   # original order first (same RNG use)
    for folder, cfg in todo:
        m, start = g.month(cfg)
        ops, results, exceptions, groups, planted = g.plant(m, cfg["discrepancies"])
        names = dict(S4_NAMES if folder.startswith("scenario_04") else bs.FILE_NAMES[cfg["short"]])
        if folder == "scenario_02_rejection_correction":
            names["IN-08"] = bs.S2_WRONG_FILE                    # the scenario's own IN-08 file name, now with real IN-08
        canonical = {fid: bs.canonical_csv(cols[fid], m.rows[fid]) for fid in schema.CSV_FILES}
        pdfs: dict[str, bytes] = {}
        bs.make_pdfs(cfg, P, pdfs)
        y, mo = map(int, cfg["period"].split("-"))
        when = (y + (mo == 12), mo % 12 + 1, 4, 9, 30, 0)
        entries = [(names[fid], canonical[fid]) for fid in schema.CSV_FILES if names.get(fid)]
        entries += [(names[fid], pdfs[fid]) for fid in ("IN-15", "IN-16", "IN-17", "IN-18", "IN-19") if fid in pdfs]
        zb = bs.zip_bytes(entries, when)

        # ---- byte comparison with the original ZIP (S1-S3)
        comparison = None
        if folder in bs.SCENARIOS:
            orig = zipfile.ZipFile(bundle / folder / "customer_submission.zip")
            onames = set(orig.namelist())
            rows = []
            for name, data in entries:
                fid = next(f for f, n in names.items() if n == name)
                if name in onames:
                    od = orig.read(name)
                    rows.append({"entry": name, "category": fid, "identical_to_original_member": od == data,
                                 "original_sha256": sha(od), "new_sha256": sha(data),
                                 "note": "layout changed to canonical (expected difference)" if od != data and (
                                     (folder.startswith("scenario_01") and fid == "IN-11") or
                                     (folder.startswith("scenario_03") and fid == "IN-12") or
                                     (folder.startswith("scenario_02") and fid == "IN-08")) else ""})
                else:
                    rows.append({"entry": name, "category": fid, "identical_to_original_member": None,
                                 "new_sha256": sha(data), "note": "not in original ZIP"})
            if folder.startswith("scenario_02"):
                corr = (bundle / folder / "corrected_submission_files" / bs.S2_CORRECTED_FILE).read_bytes()
                c_rows, n_rows = corr.decode().split("\n"), canonical["IN-08"].decode().split("\n")
                rows.append({"entry": bs.S2_CORRECTED_FILE, "category": "IN-08",
                             "data_rows_identical_to_corrected_file": c_rows[1:] == n_rows[1:],
                             "header_identical_ignoring_case": c_rows[0].lower() == n_rows[0],
                             "note": "the corrected file uses UPPER-CASE headers; the demo ZIP uses the canonical header"})
            # semantic check for re-laid-out files: the original novel layout carries the same cell values
            for fid, layout in (("IN-11", bs.S1_IN11_LAYOUT), ("IN-12", bs.S3_IN12_LAYOUT)):
                if cfg["llm_category"] == fid:
                    rows.append({"entry": names[fid], "category": fid, "original_layout_bytes_equal_regenerated_layout":
                                 orig.read(names[fid]) == bs.layout_csv(layout, m.rows[fid]),
                                 "note": "proves the regenerated records equal the original records for this file"})
            unchanged = [r for r in rows if r.get("identical_to_original_member") is not None and not r["note"]]
            comparison = {"members": rows, "unchanged_members": len(unchanged),
                          "unchanged_byte_identical": sum(1 for r in unchanged if r["identical_to_original_member"]),
                          "all_unchanged_identical": all(r["identical_to_original_member"] for r in unchanged),
                          "original_members_not_in_demo_zip": sorted(onames - {n for n, _ in entries})}

        corrupt = None
        if folder.startswith("scenario_04"):
            member = names[S4_CORRUPT_CATEGORY]
            zb_ok = zb
            zb = corrupt_crc(zb, member)
            z = zipfile.ZipFile(io.BytesIO(zb))
            try:
                z.read(member)
                raise SystemExit("corruption did not take effect")
            except zipfile.BadZipFile as exc:
                err = str(exc)
            corrupt = {"member": member, "category": S4_CORRUPT_CATEGORY, "method": "CRC-32 field XOR 0xA5A5A5A5 in the "
                       "local header and the central directory; compressed data untouched", "read_error": err,
                       "zip_opens": True, "testzip_first_bad": z.testzip(), "uncorrupted_zip_sha256": sha(zb_ok),
                       "starts_with_PK0304": zb[:4] == b"PK\x03\x04"}

        sdir = out / OUT_FOLDERS.get(folder, "scenario_4_technical_failure")
        sdir.mkdir(parents=True, exist_ok=True)
        zname = f"{cfg['customer'].replace(' ', '_')}_{cfg['period']}.zip"
        (sdir / zname).write_bytes(zb)
        status = "CLEAN" if not results else ("EVIDENCE_INCOMPLETE" if any(r["outcome"] == "INSUFFICIENT_EVIDENCE"
                                                                         for r in results) else "EXCEPTIONS_OPEN")
        scen = {"scenario_id": cfg["sid"], "source_scenario": folder, "customer_name": cfg["customer"],
                "reporting_period": cfg["period"], "synthetic_notice": bs.SYN,
                "zip": {"file": zname, "sha256": sha(zb), "bytes": len(zb), "entries": zip_listing(zb, names)},
                "source_seed": cfg["seed"], "generator": "build_scenarios.Gen (original bundle, imported read-only) via "
                                                        "tools/build_demo_zips.py",
                "record_counts": {fid: len(v) for fid, v in m.rows.items()},
                "all_csv_canonical_layout": True,
                "planted_discrepancies": planted, "mutation_operations": len(ops),
                "expected_outcome": ({"case_status": status, "fail": sum(r["outcome"] == "FAIL" for r in results),
                                      "insufficient_evidence": sum(r["outcome"] == "INSUFFICIENT_EVIDENCE" for r in results),
                                      "exceptions": len(exceptions), "investigation_groups": len(groups)}
                                     if not corrupt else {"smart_parser_run": "FAILED", "retry_run": "FAILED",
                                                          "runs_kept": 2, "reconciliation": "not reachable"}),
                "byte_comparison_with_original": comparison, "technical_corruption": corrupt}
        (sdir / "scenario.json").write_text(json.dumps(scen, indent=1) + "\n", encoding="utf-8")

        # ---- expected outcome, written before any run
        if folder in bs.SCENARIOS:
            key = json.loads((bundle / "answer_keys" / folder / "expected_reconciliation.json").read_text(encoding="utf-8"))
            exp = {"source": f"answer_keys/{folder}/expected_reconciliation.json (frozen, copied unchanged below)",
                   "source_sha256": sha((bundle / "answer_keys" / folder / "expected_reconciliation.json").read_bytes()),
                   "expected_case_status": key["expected_case_status"],
                   "expected_counts": key["expected_non_passing_counts"],
                   "expected_non_passing_set": sorted([r["check_id"], r["scope"], r["outcome"]]
                                                      for r in key["expected_non_passing_results"]),
                   "expected_exception_count": len(key["expected_exceptions"]),
                   "expected_exception_root_causes": sorted(e["root_cause"] for e in key["expected_exceptions"]),
                   "expected_investigation_group_count": len(key["expected_investigation_groups"]),
                   "expected_review_steps": "none (all CSV headers canonical; AI disabled)",
                   "frozen_key": key}
            # consistency: the regenerated design must reproduce the frozen key's non-passing set
            mine = sorted([r["check_id"], r["scope"], r["outcome"]] for r in results)
            assert mine == exp["expected_non_passing_set"], folder
            assert sorted(e["root_cause"] for e in exceptions) == exp["expected_exception_root_causes"], folder
        else:
            exp = {"source": "derived from the backend code (smartparser/webapp/cases.py _begin_run/retry, context.stage): "
                             "zipfile.ZipFile.read raises BadZipFile('Bad CRC-32 ...') on the corrupted member; the "
                             "exception is caught in _begin_run and the run is recorded FAILED (stage 'read').",
                   "expected_registration": {"http": 200, "status": "WAITING"},
                   "expected_run_1": {"status": "FAILED", "failure_code": "RUN_FAILED",
                                      "failure_message_contains": f"Bad CRC-32 for file '{corrupt['member']}'",
                                      "failure_stage": "read"},
                   "expected_retry": {"http": 200, "run_2_status": "FAILED", "run_2_retry_of": "run 1 run_id",
                                      "run_2_evidence_source": "ORIGINAL_ZIP", "runs_listed": 2, "failed_runs": 2},
                   "expected_case_status_after_retry": "IN_PROGRESS",
                   "expected_actions_after_failure": {"retry_from_beginning": True, "defer": True, "activate": False,
                                                      "reconcile": False},
                   "reconciliation": "not reachable (no package is ever produced)"}
        (sdir / "expected_outcome.json").write_text(json.dumps(exp, indent=1) + "\n", encoding="utf-8")
        report["scenarios"][folder] = {"folder": sdir.name, "zip": zname, "sha256": sha(zb), "entries": len(entries),
                                       "comparison": None if comparison is None else {
                                           k: comparison[k] for k in ("unchanged_members", "unchanged_byte_identical",
                                                                      "all_unchanged_identical",
                                                                      "original_members_not_in_demo_zip")},
                                       "corruption": corrupt}
        print(folder, "->", sdir.name, zname, sha(zb)[:16], len(entries), "entries",
              "" if comparison is None else f"unchanged identical {comparison['unchanged_byte_identical']}/"
                                            f"{comparison['unchanged_members']}")
    (out / "tools" / "build_report.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
