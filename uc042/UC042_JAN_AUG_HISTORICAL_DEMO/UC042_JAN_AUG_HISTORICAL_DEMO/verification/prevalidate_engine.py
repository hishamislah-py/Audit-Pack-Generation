"""PRE-VALIDATION ONLY: run the existing UC-042 engine on each generated month, with the reporting period patched
in memory (module attributes) in a separate process. No project file is edited; nothing is written to the project.

This is NOT the period-aware engine Claude Code must build. It exists to show that the generated data is processable
and that the planted scenarios produce the expected engine behaviour. Results are written to verification/.

    python verification/prevalidate_engine.py --project /path/to/uc042
"""
import argparse
import json
import shutil
import sys
import tempfile
from calendar import monthrange
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
LON = ZoneInfo("Europe/London")
HOLIDAYS = {date(2025, 12, 25), date(2025, 12, 26), date(2026, 1, 1), date(2026, 4, 3), date(2026, 4, 6), date(2026, 5, 4),
            date(2026, 5, 25), date(2026, 8, 31)}


def patch_period(schema, validate, period, policy_file):
    y, m = map(int, period.split("-"))
    start, end = date(y, m, 1), date(y, m, monthrange(y, m)[1])
    prev = start - timedelta(days=1)
    pid = f"PER-{period}"
    prev_point = datetime.combine(prev, time(17, 0), tzinfo=LON).isoformat()
    schema.PERIOD_ID, schema.PERIOD_START, schema.PERIOD_END = pid, start, end
    for fid, (fname, desc, cols) in list(schema.CSV_FILES.items()):
        schema.CSV_FILES[fid] = (fname.replace("_2026-09", f"_{period}"), desc, cols)
    f17 = schema.PDF_FILES["IN-17"]
    schema.PDF_FILES["IN-17"] = (policy_file, f17[1], f17[2], f17[3])
    schema.PERIOD_RULES["IN-01"]["equals"]["period_id"] = pid
    schema.PERIOD_RULES["IN-03"]["permitted"] = [{"recon_date": prev.isoformat(), "as_at_ts": prev_point}]
    schema.PERIOD_RULES["IN-10"]["permitted"] = [{"entry_type": "OPENING_BALANCE", "posted_ts": prev_point}]
    validate.UK_BANK_HOLIDAYS |= HOLIDAYS


def run_month(project, period, policy_file):
    sys.path.insert(0, str(project))
    from uc042lib import schema, validate  # fresh process per month: patches never leak
    patch_period(schema, validate, period, policy_file)
    case = Path(tempfile.mkdtemp()) / period
    shutil.copytree(PKG / period / "source_documents", case)
    v = validate.Validator(case)
    v.run()
    res = [{k: r[k] for k in ("check_id", "scope", "outcome", "computed", "reported", "root_cause", "evidence_status")} for r in v.results]
    out = {"period": period, "policy_file_used": policy_file, "case_status": validate.case_status(v),
           "results_by_outcome": dict(Counter(r["outcome"] for r in v.results)),
           "non_passing": [r for r in res if r["outcome"] in ("FAIL", "INSUFFICIENT_EVIDENCE")],
           "exceptions": [{k: x[k] for k in ("exception_id", "severity", "category", "root_cause", "amount", "first_date", "last_date",
                                              "affected_results", "evidence_status", "investigation_group_id")} for x in v.exceptions],
           "groups": [{k: g[k] for k in ("group_id", "exception_ids", "link_types")} for g in v.groups],
           "candidates": [c["exception_ids"] for c in v.candidates]}
    shutil.rmtree(case.parent)
    print(json.dumps(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--month")
    ap.add_argument("--policy")
    a = ap.parse_args()
    if a.month:
        return run_month(Path(a.project), a.month, a.policy)
    import subprocess
    results = {}
    for period in [f"2026-{m:02d}" for m in range(1, 9)]:
        docs = sorted(p.name for p in (PKG / period / "source_documents" / "supporting_documents").glob("safeguarding_reconciliation_policy_v*.pdf"))
        policy = docs[-1]  # policy in force at the period end (May: v1.2 from 7 May); see claude_code_handoff.md
        p = subprocess.run([sys.executable, __file__, "--project", a.project, "--month", period, "--policy", policy], capture_output=True, text=True)
        if p.returncode:
            raise SystemExit(p.stderr)
        results[period] = json.loads(p.stdout.strip().splitlines()[-1])
        r = results[period]
        print(f"{period}: {r['case_status']:<20} {r['results_by_outcome']} | exceptions {len(r['exceptions'])} | groups {len(r['groups'])} | policy {policy}")
    (HERE / "engine_prevalidation_results.json").write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
