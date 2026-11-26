"""Command line entry: ``python -m smartparser``.

  python -m smartparser schemas                     # schema coverage report
  python -m smartparser process FILE [--period YYYY-MM] [--category IN-xx]
                                     [--schemas DIR] [--test-schemas] [--summary]
  python -m smartparser classify FILE [FILE ...]    # content-only classification (files classified as one set)
  python -m smartparser import-registry --uc042-root DIR [--out DIR] [--check]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .pipeline import SmartParser
from .schemas.registry import DEFAULT_DEFINITIONS_DIR, SchemaRegistry


def _registry(args) -> SchemaRegistry:
    if args.schemas:
        return SchemaRegistry.from_directory(args.schemas, allow_non_official=args.test_schemas)
    return SchemaRegistry.from_directory()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="smartparser")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("schemas", help="show schema registry coverage")
    s.add_argument("--schemas")
    s.add_argument("--test-schemas", action="store_true")
    pr = sub.add_parser("process", help="process one file and print the result JSON")
    pr.add_argument("file")
    pr.add_argument("--period")
    pr.add_argument("--category")
    pr.add_argument("--schemas", help="schema definitions directory")
    pr.add_argument("--test-schemas", action="store_true", help="allow non-IN category ids")
    pr.add_argument("--summary", action="store_true", help="print a short summary instead of JSON")
    cl = sub.add_parser("classify", help="classify files by content only (one set: letters resolve via IN-02)")
    cl.add_argument("files", nargs="+")
    cl.add_argument("--schemas")
    cl.add_argument("--test-schemas", action="store_true")
    im = sub.add_parser("import-registry", help="generate the 19 definitions from a UC-042 tree (read-only)")
    im.add_argument("--uc042-root", required=True)
    im.add_argument("--out", default=str(DEFAULT_DEFINITIONS_DIR))
    im.add_argument("--check", action="store_true", help="only report differences; write nothing")
    args = p.parse_args(argv)

    if args.cmd == "import-registry":
        from .registry_import import compare_with_directory, generate, write_directory
        defs = generate(args.uc042_root)
        if args.check:
            diffs = compare_with_directory(defs, args.out)
            print("\n".join(diffs) or f"in sync: {len(defs)} definitions match {args.uc042_root}")
            return 1 if diffs else 0
        for path in write_directory(defs, args.out):
            print(f"wrote {path}")
        SchemaRegistry.from_directory(args.out)   # the written registry must load
        return 0

    reg = _registry(args)
    if args.cmd == "schemas":
        rows = reg.coverage_report()
        for r in rows:
            print(f"{r['category']:<8} {r['format']:<4} {r['verification_status']:<12} "
                  f"{r['field_count']:>3} {'labels' if r['format'] == 'pdf' else 'fields'}  "
                  f"{'(optional) ' if r['optional'] else ''}{r['title']}")
        missing = [r["category"] for r in rows if r["verification_status"] == "missing"]
        print(f"\n{len(rows) - len(missing)}/{len(rows)} defined; missing: {', '.join(missing) or 'none'}")
        return 0

    if args.cmd == "classify":
        from .classify.evidence import classify_batch
        items = [(f, Path(f).read_bytes()) for f in args.files]
        for key, fc in classify_batch(items, reg).items():
            r = fc.result
            print(f"{key}: {r.status} {r.category or '-'} ({fc.file_format}) - {r.reason}")
            for w in r.warnings:
                print(f"    warning: {w}")
        return 0

    path = Path(args.file)
    res = SmartParser(schemas=reg).process_bytes(
        path.read_bytes(), path.name, args.period, forced_category=args.category)
    if args.summary:
        m = res.metadata
        print(f"{m.original_filename}: {m.processing_status} | category={m.evidence_category} "
              f"({m.classification_status}) | extraction={m.extraction_status} | "
              f"mapping={m.mapping_status} | validation={m.validation_status}")
        for st in res.steps:
            print(f"  [{st.status:<15}] {st.step}: {st.message}")
        for i in res.all_issues():
            loc = f" row {i.row}" if i.row else ""
            print(f"  {i.severity.upper():<7} {i.code}{loc}: {i.message}")
    else:
        sys.stdout.write(res.model_dump_json(indent=2) + "\n")
    return 0
