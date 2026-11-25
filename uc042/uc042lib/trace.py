"""Trace a record ID or exception ID to its source rows and to the check results that cite them.

Usage (from the uc042/ folder):
    python -m uc042lib.trace ERL-SGA-GBP-01-20260917
    python -m uc042lib.trace EXC-S05-01 --set uc042_dataset/scn_S05_unexplained_gbp_difference

Check results cite rows as `IN-xx:file.csv#L<line>` (or a range `#L<a>-L<b>`). A result is shown if it
cites one of the matched rows, or if its scope contains the term.
"""
import argparse
import csv
import re
from pathlib import Path

from .period import resolve
from .validate import DEFAULT_SET

REF = re.compile(r"^(IN-\d\d):([^#\s]+)#L(\d+)(?:-L(\d+))?")


def cites(evidence, refs):
    for token in filter(None, (t.strip() for t in evidence.split(";"))):
        m = REF.match(token)
        if not m:
            continue
        lo = int(m.group(3))
        hi = int(m.group(4) or lo)
        if any(f == m.group(2) and lo <= line <= hi for f, line in refs):
            return True
    return False


def show(r):
    print(f"  {r['outcome']:<22} {r['check_id']:<18} {r['scope']}")
    if r.get("computed") or r.get("reported"):
        print(f"    computed={r['computed']}  reported={r['reported']}")
    if r.get("note"):
        print(f"    note: {r['note']}")
    if r.get("root_cause"):
        print(f"    root cause: {r['root_cause']}")
    print(f"    evidence: {r['evidence']}")


def load(path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def trace(term, root):
    root = Path(root)
    results_path = root / "validation" / "control_results.csv"
    results = load(results_path)
    if term.startswith(("GRP-", "CAND-")):
        fname_, key = ("investigation_groups.csv", "group_id") if term.startswith("GRP-") else ("candidate_relationships.csv", "candidate_id")
        g = next((x for x in load(root / "validation" / fname_) if x[key] == term), None)
        if g is None:
            print(f"{term}: not found (run python -m uc042lib.validate on this dataset first)")
            return
        print(f"{term}" + ("  investigation group (evidence-linked; no cause set)" if key == "group_id"
                           else "  candidate relationship — UNVERIFIED, NOT EVIDENCE-BACKED, not a group"))
        for k, v in g.items():
            if v and k != key:
                print(f"  {k}: {v}")
        print("\nMember exceptions (trace each with its EXC- id):")
        exc = {x["exception_id"]: x for x in load(root / "validation" / "exceptions.csv")}
        for i in g["exception_ids"].split("; "):
            x = exc.get(i, {})
            print(f"  {i}  {x.get('severity', '')}  {x.get('category', '')}  evidence status: {x.get('evidence_status') or '-'}")
        return
    if term.startswith("EXC-"):
        x = next((x for x in load(root / "validation" / "exceptions.csv") if x["exception_id"] == term), None)
        if x is None:
            print(f"{term}: not found (run python -m uc042lib.validate on this dataset first)")
            return
        print(f"{x['exception_id']}  {x['severity']}  {x['category']}  ({x['status']})")
        for k in ("root_cause", "account_id", "first_date", "last_date", "amount", "flags", "related_records", "evidence_status",
                  "evidence_status_detail", "review_status", "investigation_group_id", "evidence"):
            if x.get(k):
                print(f"  {k}: {x[k]}")
        print(f"\nAffected results ({x['affected_results']}):")
        for r in results:
            if r["root_cause"] == x["root_cause"] and r["outcome"] in ("FAIL", "INSUFFICIENT_EVIDENCE"):
                show(r)
        return
    print(f"Source records mentioning {term!r}:")
    refs = []
    for fid, (fname, _, cols) in resolve(root).csv_files.items():  # the case's own period's file names
        for line, row in enumerate(load(root / "source_data" / fname), start=2):
            matched = [c for c, v in row.items() if v == term]
            if matched:
                refs.append((fname, line))
                role = "primary key" if matched[0] == cols[0][0] else "reference in " + ", ".join(matched)
                print(f"  {fid}:{fname}#L{line}  ({role})")
                print("    " + ", ".join(f"{k}={v}" for k, v in row.items() if v))
    if not refs:
        print("  none")
    if not results:
        print("\nNo check results yet (run python -m uc042lib.validate on this dataset first).")
        return
    hits = [r for r in results if term in r["scope"] or cites(r["evidence"], refs)]
    print(f"\nCheck results citing {term!r} or its rows ({len(hits)}):")
    for r in hits[:40]:
        show(r)
    if len(hits) > 40:
        print(f"  ... {len(hits) - 40} more in {results_path}")
    if not hits:
        print("  none")


def main():
    ap = argparse.ArgumentParser(description="Trace an ID to source evidence and check results")
    ap.add_argument("term")
    ap.add_argument("--set", default=str(DEFAULT_SET))
    a = ap.parse_args()
    trace(a.term, a.set)


if __name__ == "__main__":
    main()
