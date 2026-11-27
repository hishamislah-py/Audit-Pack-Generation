"""Experiment A2 - generate a PDF value-rule artefact from the authoritative UC-042 source (feasibility experiment).

Isolated: nothing in the smartparser package imports this module; it is not run at start-up or intake. It never writes
to the UC-042 tree (bytecode writing disabled; the consumer code is parsed with `ast`, not executed).

What it reads
  data   uc042lib.schema.PDF_FILES (labels), uc042lib.schema.LETTER_SLOTS, uc042lib.policy.POLICY_VERSIONS
         (imported, as smartparser.registry_import.uc042 already does for the registry);
  code   every use of a PDF key-detail label in the UC-042 consumers (validate.py, policy.py, ingest/analysis.py,
         prepare.py), found syntactically as `<x>.get("<label>" ...)` or `<x>["<label>"]`.

What it produces (generated_pdf_rules.json)
  * one entry per consumer SITE: label, categories (from PDF_FILES), file, enclosing function, line, exact source line,
    the recognised pattern and its parameters, and its derivability group (A..E);
  * the policy registry and letter slots (data, with source lines);
  * `unrecognised`: label uses whose code shape matches no known pattern (never guessed);
  * `labels_without_consumer`: labels no consumer reads;
  * SHA-256 of every source file, so `--check` detects any change.

Patterns recognised (closed list; anything else is reported, not interpreted):
  DATE_PARSE        _date_or_none(<label value>)           -> syntax: UC-042 lenient ISO date (first 10 characters)
  TIMESTAMP_PARSE   parse_ts(<label value>)                -> syntax: ISO 8601 with offset
  REGEX_MATCH       re.match(<literal>, <label value>)     -> syntax: the regex literal
  CONST_EQUALS      <label value> == "<literal>"           -> business value (control)
  CROSS_DOC_EQUALS  <label value> == <other>["<column>"]   -> cross-document comparison (control)
  NON_EMPTY         bool(<label value>)                    -> business presence (control)
  COMPUTED_EQUALS   <label value> ==/!= <computed expr>    -> compared with a value UC-042 computes (business)
  REGISTRY_EQUALS   <label value> !=/== reg.<attr>...       -> compared with POLICY_VERSIONS data
  LOOKUP_KEY        <dict>.get(<label value>, ...)          -> the value is a lookup key (slot / registry)
  READ_ONLY         read and only displayed/propagated (an argument to self.add, f-string, dict build, return)
  ASSIGNED          stored in a variable: its later use is NOT followed (reported as needing manual resolution)

The consequence of a site (does UC-042 make the document unusable, or is it a control result?) is NOT in the source as
data. It is supplied by CONSEQUENCE_BY_FUNCTION below - explicit configuration, applied by function name, and the
generator fails if a consumer appears in a function that is not configured.

Usage:  py -3.11 experiments/pdf_rule_generation/generate_rules.py --uc042-root <root> --out <file> [--check]
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import json
import sys
from pathlib import Path

GENERATOR_VERSION = "pdf-rule-generation/0.1-experiment"
CONSUMER_FILES = ["uc042lib/validate.py", "uc042lib/policy.py", "uc042app/ingest/analysis.py", "uc042lib/prepare.py"]
DATA_FILES = ["uc042lib/schema.py", "uc042lib/policy.py"]
HELPER_FILES = {"_date_or_none": "uc042lib/validate.py", "parse_ts": "uc042lib/structure.py"}

# EXPLICIT CONFIGURATION (not derivable from the source as data). What failing a check in each consumer function means.
CONSEQUENCE_BY_FUNCTION = {
    "setup": "PARSE: Validator.setup marks IN-17 unusable (V01-PDF FAIL) or drops it",
    "recognise": "PARSE: policy.recognise refuses the document as a policy (POLICY_NOT_RECOGNISED)",
    "check_designation": "CONTROL: C10-DESIGNATION result",
    "check_policy_and_points": "CONTROL: C03-POLICY result",
    "check_checklist": "CONTROL: C16-GOVERNANCE / C16-RETURN result",
    "analyse_pdf": "INTAKE WARNING: ingest.analysis WRONG_PERIOD message",
    "prepare_case": "IDENTIFICATION: letter slot chosen by IN-02 acknowledgement_letter_ref",
    "_resolve_letters": "IDENTIFICATION: letter slot chosen by IN-02 acknowledgement_letter_ref",
    "load_pdf": "PARSE: label extraction (V01-PDF)",
    "_pdf_details": "PARSE: label extraction",
}
# Derivability group per pattern (the experiment's classification, see the report):
#   A directly derivable, B derivable with a deterministic transformation, C partially (needs explicit configuration),
#   D not derivable, E business-level (belongs to UC-042, not to extraction validation).
GROUP_BY_PATTERN = {"REGEX_MATCH": "B", "TIMESTAMP_PARSE": "C", "DATE_PARSE": "C", "REGISTRY_EQUALS": "A",
                    "LOOKUP_KEY": "A", "CONST_EQUALS": "E", "CROSS_DOC_EQUALS": "E", "NON_EMPTY": "E",
                    "COMPUTED_EQUALS": "E", "READ_ONLY": "-", "ASSIGNED": "D"}
EXTRACTION_USE = {"REGEX_MATCH", "TIMESTAMP_PARSE", "DATE_PARSE", "REGISTRY_EQUALS", "LOOKUP_KEY"}


class GenerationError(RuntimeError):
    pass


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _import(root: Path, name: str):
    sys.dont_write_bytecode = True
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return importlib.import_module(name)


def _label_of(node, labels):
    """The PDF label a node reads: <x>.get("<label>", ...) or <x>["<label>"]."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args:
        a = node.args[0]
        if isinstance(a, ast.Constant) and a.value in labels:
            return a.value
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and node.slice.value in labels:
        return node.slice.value
    return None


def _climb(node, parents):
    """Step over value-preserving wrappers: `(x or "")`, `.strip()`, `x or y or None`. Returns the outermost wrapper."""
    while True:
        parent = parents.get(node)
        if isinstance(parent, ast.BoolOp):
            node = parent
            continue
        if isinstance(parent, ast.Attribute) and parent.attr == "strip" and isinstance(parents.get(parent), ast.Call):
            node = parents[parent]
            continue
        return node


def _classify(site, parents, labels):
    """(pattern, parameters) for one label read, from its syntactic context. None: unrecognised."""
    site = _climb(site, parents)
    parent = parents.get(site)
    if isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name):
        if parent.func.id == "_date_or_none":
            return "DATE_PARSE", {"helper": "uc042lib.validate._date_or_none"}
        if parent.func.id == "parse_ts":
            return "TIMESTAMP_PARSE", {"helper": "uc042lib.structure.parse_ts"}
        if parent.func.id == "bool":
            return "NON_EMPTY", {}
    if isinstance(parent, ast.Call) and isinstance(parent.func, ast.Attribute):
        f = parent.func
        if f.attr == "match" and isinstance(f.value, ast.Name) and f.value.id == "re" and parent.args                 and isinstance(parent.args[0], ast.Constant) and site is not parent.args[0]:
            return "REGEX_MATCH", {"regex": parent.args[0].value}
        if f.attr == "get" and site in parent.args:
            return "LOOKUP_KEY", {"lookup": ast.unparse(f.value)}
        if f.attr == "add" and isinstance(f.value, ast.Name) and f.value.id == "self":
            return "READ_ONLY", {"use": "result evidence (self.add)"}
    if isinstance(parent, ast.Compare) and len(parent.ops) == 1 and isinstance(parent.ops[0], (ast.Eq, ast.NotEq)):
        other = parent.comparators[0] if parent.left is site else parent.left
        if isinstance(other, ast.Constant) and isinstance(other.value, str):
            return "CONST_EQUALS", {"value": other.value, "op": type(parent.ops[0]).__name__}
        if isinstance(other, ast.Subscript) and isinstance(other.slice, ast.Constant):
            return "CROSS_DOC_EQUALS", {"other": ast.unparse(other), "column": other.slice.value}
        text = ast.unparse(other)
        if text.startswith("reg.") or "POLICY_VERSIONS" in text:
            return "REGISTRY_EQUALS", {"registry_expr": text}
        return "COMPUTED_EQUALS", {"expr": text, "op": type(parent.ops[0]).__name__}
    if isinstance(parent, ast.Assign):
        # The value flows into a variable; what is done with it is not visible syntactically (no data-flow analysis).
        return "ASSIGNED", {"variable": ast.unparse(parent.targets[0])}
    if isinstance(parent, ast.Return):
        return "READ_ONLY", {"use": "returned to the caller"}
    if isinstance(parent, (ast.FormattedValue, ast.JoinedStr, ast.Dict, ast.Tuple, ast.keyword, ast.List)) or             (isinstance(parent, ast.Call) and site in getattr(parent, "args", [])):
        return "READ_ONLY", {"use": type(parent).__name__}
    return None


def scan(root: Path, labels: set[str]) -> tuple[list[dict], list[dict]]:
    sites, unknown = [], []
    for rel in CONSUMER_FILES:
        text = (root / rel).read_text(encoding="utf-8")
        tree = ast.parse(text)
        lines = text.splitlines()
        parents, funcs = {}, {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            for n in ast.walk(fn):
                funcs.setdefault(n, fn.name)   # innermost wins for nested defs because ast.walk is breadth-first
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            for n in ast.walk(fn):
                funcs[n] = fn.name if funcs.get(n) is None else funcs[n]
        for node in ast.walk(tree):
            label = _label_of(node, labels)
            if label is None:
                continue
            fn = funcs.get(node, "<module>")
            rec = {"label": label, "file": rel, "function": fn, "line": node.lineno,
                   "source_line": lines[node.lineno - 1].strip()}
            cls = _classify(node, parents, labels)
            if cls is None:
                unknown.append(dict(rec, reason=f"unrecognised code shape: {ast.unparse(parents.get(node))[:120]}"))
                continue
            pattern, params = cls
            if pattern not in ("READ_ONLY", "ASSIGNED") and fn not in CONSEQUENCE_BY_FUNCTION:
                raise GenerationError(f"{rel}:{node.lineno} {label!r} is used by {fn}(), which has no configured consequence; "
                                      "add it to CONSEQUENCE_BY_FUNCTION explicitly (no default is assumed)")
            sites.append(dict(rec, pattern=pattern, parameters=params, group=GROUP_BY_PATTERN[pattern],
                              extraction_use=pattern in EXTRACTION_USE,
                              consequence=CONSEQUENCE_BY_FUNCTION.get(fn, "")))
    key = lambda r: (r["file"], r["line"], r["label"], r.get("pattern", ""))
    return sorted(sites, key=key), sorted(unknown, key=key)


def _line_of(text: str, needle: str) -> int:
    hits = [i for i, l in enumerate(text.splitlines(), 1) if needle in l]
    if len(hits) != 1:
        raise GenerationError(f"expected exactly one source line containing {needle!r}, found {len(hits)}")
    return hits[0]


def generate(root: str | Path) -> dict:
    root = Path(root).resolve()
    needed = sorted(set(CONSUMER_FILES + DATA_FILES + list(HELPER_FILES.values())))
    missing = [rel for rel in needed if not (root / rel).is_file()]
    if missing:
        raise GenerationError(f"{root} is not a UC-042 tree; missing {missing}")
    schema = _import(root, "uc042lib.schema")
    policy = _import(root, "uc042lib.policy")
    if not getattr(schema, "PDF_FILES", None):
        raise GenerationError("uc042lib.schema.PDF_FILES not found or empty")
    if not getattr(policy, "POLICY_VERSIONS", None):
        raise GenerationError("uc042lib.policy.POLICY_VERSIONS not found or empty")
    schema_text = (root / "uc042lib/schema.py").read_text(encoding="utf-8")
    policy_text = (root / "uc042lib/policy.py").read_text(encoding="utf-8")
    cats_of: dict[str, list[str]] = {}
    labels_by_cat = {}
    for fid, (_, desc, req, labels) in schema.PDF_FILES.items():
        labels_by_cat[fid] = {"labels": list(labels), "requirement": req,
                              "source": {"file": "uc042lib/schema.py", "line": _line_of(schema_text, f'"{fid}": (')}}
        for lbl in labels:
            cats_of.setdefault(lbl, []).append(fid)
    sites, unknown = scan(root, set(cats_of))
    for s in sites + unknown:
        s["categories"] = cats_of[s["label"]]
    used = {s["label"] for s in sites if s["pattern"] not in ("READ_ONLY", "ASSIGNED")}
    assigned = sorted({s["label"] for s in sites if s["pattern"] == "ASSIGNED"} - used)
    helpers = {}
    for name, rel in HELPER_FILES.items():
        text = (root / rel).read_text(encoding="utf-8")
        fn = next((n for n in ast.walk(ast.parse(text)) if isinstance(n, ast.FunctionDef) and n.name == name), None)
        if fn is None:
            raise GenerationError(f"helper {name} not found in {rel}")
        src = ast.get_source_segment(text, fn)
        helpers[name] = {"file": rel, "line": fn.lineno, "source": src,
                         "source_sha256": hashlib.sha256(src.encode()).hexdigest()}
    versions = [{"version": v.version, "effective": v.effective.isoformat(), "classification": v.classification,
                 "required_markings": list(v.required_markings),
                 "source": {"file": "uc042lib/policy.py", "line": _line_of(policy_text, f'"{v.version}": PolicyVersion(')}}
                for v in sorted(policy.POLICY_VERSIONS.values(), key=lambda v: v.effective)]
    return {
        "generator_version": GENERATOR_VERSION,
        "status": "EXPERIMENTAL - not used by Smart Parser",
        "source_sha256": {rel: _sha(root / rel) for rel in needed},
        "configuration": {"consequence_by_function": CONSEQUENCE_BY_FUNCTION, "group_by_pattern": GROUP_BY_PATTERN},
        "pdf_categories": labels_by_cat,
        "letter_slots": {"value": dict(sorted(schema.LETTER_SLOTS.items())),
                         "source": {"file": "uc042lib/schema.py", "line": _line_of(schema_text, "LETTER_SLOTS = {")}},
        "policy_versions": versions,
        "helpers": helpers,
        "sites": sites,
        "unrecognised": unknown,
        "needs_manual_resolution": [{"label": l, "reason": "value assigned to a variable; its use is not visible "
                                     "syntactically (no data-flow analysis)",
                                     "sites": [f"{x['file']}:{x['line']}" for x in sites if x['label'] == l and x['pattern'] == 'ASSIGNED']}
                                    for l in assigned],
        "labels_without_consumer": sorted(set(cats_of) - used - set(assigned)),
    }


def render(doc: dict) -> str:
    return json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--uc042-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--check", action="store_true", help="fail if the stored artefact differs from a fresh generation")
    a = ap.parse_args(argv)
    try:
        doc = render(generate(a.uc042_root))
    except GenerationError as e:
        print(f"GENERATION FAILED: {e}", file=sys.stderr)
        return 2
    out = Path(a.out)
    if a.check:
        if not out.is_file():
            print(f"CHECK FAILED: {out} does not exist", file=sys.stderr)
            return 3
        if out.read_text(encoding="utf-8") != doc:
            print("CHECK FAILED: the UC-042 source changed since the artefact was generated (or the artefact was edited)",
                  file=sys.stderr)
            return 1
        print("in sync")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    print(f"written {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
