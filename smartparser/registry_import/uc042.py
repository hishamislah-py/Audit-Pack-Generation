"""Controlled import of the 19 UC-042 evidence definitions into the Smart Parser registry.

The UC-042 code is the single source of truth. Nothing here defines a column, label, type, enumeration or rule of its
own: every value is read from the UC-042 modules at generation time, and every item records the module/symbol it came
from. The generated JSON files (smartparser/schemas/definitions/IN-xx.json) carry the SHA-256 of each source module, so
a later run can prove whether the registry still matches the UC-042 code (see `compare_with_directory`).

The UC-042 tree is only imported (read). It is never written to.

    python -m smartparser import-registry --uc042-root C:\\path\\to\\uc042 [--out DIR] [--check]
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
import sys
from pathlib import Path

GENERATOR_VERSION = "uc042-registry-import/1.0"
SCHEMA_VERSION = "1.0.0"

# Every UC-042 module this import reads, relative to the UC-042 root. Their hashes go into each definition.
SOURCE_FILES = {
    "uc042lib.schema": "uc042lib/schema.py",
    "uc042lib.period": "uc042lib/period.py",
    "uc042lib.structure": "uc042lib/structure.py",
    "uc042lib.money": "uc042lib/money.py",
    "uc042lib.policy": "uc042lib/policy.py",
    "uc042lib.prepare": "uc042lib/prepare.py",
    "uc042app.ingest.analysis": "uc042app/ingest/analysis.py",
}

# UC-042 type code -> Smart Parser FieldType. This is a translation table, not a rule: each UC-042 type keeps its own
# code in `source_type`, and the value rules attached below (pattern / allowed values) are read from UC-042 itself.
TYPE_MAP = {"id": "string", "str": "string", "date": "date", "ts": "datetime", "bool": "boolean", "int": "integer",
            "amount": "decimal", "signed": "decimal", "ccy": "currency_code", "enum": "string"}

# The two literal date/bool checks are written inline in uc042lib.structure.field_error (no named constant exists).
# They are re-read from the source text below and the import fails if they are no longer there.
_INLINE_DATE = r"^\d{4}-\d{2}-\d{2}$"
_INLINE_BOOL = ('"true", "false"',)


class Uc042ImportError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_uc042(root: str | Path):
    """Import the UC-042 modules from `root` (read-only). Returns (modules dict, source hashes dict)."""
    root = Path(root).resolve()
    missing = [rel for rel in SOURCE_FILES.values() if not (root / rel).is_file()]
    if missing:
        raise Uc042ImportError(f"{root} is not a UC-042 tree; missing {missing}")
    sys.dont_write_bytecode = True          # never write __pycache__ into the UC-042 tree
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    mods = {}
    for name, rel in SOURCE_FILES.items():
        mod = importlib.import_module(name)
        got = Path(mod.__file__).resolve()
        if got != (root / rel).resolve():
            raise Uc042ImportError(f"{name} was imported from {got}, not from {root / rel}; "
                                   "use a fresh interpreter for each UC-042 root")
        mods[name] = mod
    hashes = {rel: _sha256(root / rel) for rel in SOURCE_FILES.values()}
    return mods, hashes, root


def _inline_rules(structure_source: str) -> dict:
    if f'r"{_INLINE_DATE}"' not in structure_source:
        raise Uc042ImportError("uc042lib.structure.field_error no longer contains the inline date pattern")
    if not all(token in structure_source for token in _INLINE_BOOL):
        raise Uc042ImportError("uc042lib.structure.field_error no longer contains the inline true/false rule")
    return {"date": _INLINE_DATE, "bool": r"^(true|false)$"}


def _value_rules(mods, inline) -> dict:
    """Per UC-042 type: (pattern, allowed_values, provenance). Read from uc042lib.structure / uc042lib.money."""
    st, money = mods["uc042lib.structure"], mods["uc042lib.money"]
    return {
        "id": (st.ID_RE.pattern, None, "uc042lib.structure.ID_RE"),
        "str": (None, None, "uc042lib.structure.field_error (no rule for str)"),
        "date": (inline["date"], None, "uc042lib.structure.field_error (inline date check + date.fromisoformat)"),
        "ts": (None, None, "uc042lib.structure.parse_ts (datetime.fromisoformat, offset required)"),
        "bool": (inline["bool"], None, "uc042lib.structure.field_error (value in true/false)"),
        "int": (st.INT_RE.pattern, None, "uc042lib.structure.INT_RE"),
        "amount": (money.UNSIGNED_RE.pattern, None, "uc042lib.money.UNSIGNED_RE"),
        "signed": (money.SIGNED_RE.pattern, None, "uc042lib.money.SIGNED_RE"),
        "ccy": (None, sorted(st.CURRENCIES), "uc042lib.structure.CURRENCIES"),
        "enum": (None, None, "uc042lib.schema.ENUMS"),
    }


def _relationships_csv(fid, cols, schema) -> list[dict]:
    """Cross-document relationships the UC-042 definitions state explicitly. Recorded only (Phase 1)."""
    out = []
    rule = schema.PERIOD_RULES.get(fid, {})
    ev = rule.get("event_ref")
    if ev:
        out.append({"field": ev["field"], "target_category": sorted(ev["sources"]),
                    "target_field": " / ".join(f"{k}.{v}" for k, v in sorted(ev["sources"].items())),
                    "kind": "period_event_reference",
                    "description": f"{ev['field']} refers to a reconciliation record; the entry's period follows that "
                                   f"record's {ev['date_field']}",
                    "provenance": f"uc042lib.schema.PERIOD_RULES['{fid}']['event_ref']"})
    if fid == "IN-02":
        for acct, slot in sorted(schema.LETTER_SLOTS.items()):
            out.append({"field": "acknowledgement_letter_ref", "target_category": slot, "target_field": "Letter reference",
                        "kind": "letter_slot_resolution",
                        "description": f"the {acct} row's acknowledgement_letter_ref identifies the {slot} letter by its "
                                       "'Letter reference' label",
                        "provenance": "uc042lib.schema.LETTER_SLOTS + uc042lib.prepare.prepare_case"})
    for name, _t, _r, desc in cols:
        for target in sorted(set(re.findall(r"\bIN-\d{2}\b", desc)) - {fid}):
            out.append({"field": name, "target_category": target, "target_field": None, "kind": "documented_reference",
                        "description": desc, "provenance": f"uc042lib.schema.CSV_FILES['{fid}'] column description"})
    return out


def build_definitions(mods, hashes, root) -> dict[str, dict]:
    schema, period, policy = mods["uc042lib.schema"], mods["uc042lib.period"], mods["uc042lib.policy"]
    prepare, analysis = mods["uc042lib.prepare"], mods["uc042app.ingest.analysis"]
    structure_src = (Path(root) / SOURCE_FILES["uc042lib.structure"]).read_text(encoding="utf-8")
    rules = _value_rules(mods, _inline_rules(structure_src))
    prov_header = {"generator": GENERATOR_VERSION, "source_system": "UC-042", "uc042_root": str(root),
                   "source_sha256": hashes}
    depends = {}
    for check, fids in schema.DEPENDS.items():
        for f in fids:
            depends.setdefault(f, []).append(check)
    letter_slot_of = {slot: acct for acct, slot in schema.LETTER_SLOTS.items()}
    # PDF label regex as written in uc042lib.prepare._pdf_details.
    pdf_src = (Path(root) / SOURCE_FILES["uc042lib.prepare"]).read_text(encoding="utf-8")
    m = re.search(r're\.search\(rf"(\^\{re\.escape\(lbl\)\}: \(\.\+\)\$)", text, re\.M\)', pdf_src)
    if not m:
        raise Uc042ImportError("uc042lib.prepare._pdf_details no longer uses the documented 'Label: value' regex")
    label_pattern = "^{label}: (.+)$"
    out = {}

    for fid, (filename, name, cols) in schema.CSV_FILES.items():
        fields = []
        for pos, (col, ctype, req, desc) in enumerate(cols):
            if ctype not in TYPE_MAP:
                raise Uc042ImportError(f"{fid}.{col}: UC-042 type {ctype!r} has no Smart Parser translation")
            pattern, allowed, vprov = rules[ctype]
            # An enum column without listed values (e.g. IN-14 cause_category) is recorded as unresolved below.
            enum = schema.ENUMS.get((fid, col))
            cond = [d for f, c, _fn, d in schema.CONDITIONAL if f == fid and c == col]
            fields.append({
                "name": col, "type": TYPE_MAP[ctype], "required": True, "nullable": req != "M",
                "description": desc, "position": pos, "source_type": ctype, "requiredness": req,
                "condition": cond[0] if cond else None,
                "constraints": {"pattern": pattern, "allowed_values": sorted(enum) if enum else allowed},
                "provenance": [f"uc042lib.schema.CSV_FILES['{fid}'][2][{pos}]", vprov]
                + ([f"uc042lib.schema.ENUMS[('{fid}', '{col}')]"] if enum else [])
                + ([f"uc042lib.schema.CONDITIONAL ('{fid}', '{col}')"] if cond else []),
            })
        unresolved = [f"{f['name']}: declared enum with no allowed values in uc042lib.schema.ENUMS"
                      for f in fields if f["source_type"] == "enum" and not f["constraints"]["allowed_values"]]
        rule = schema.PERIOD_RULES.get(fid)
        out[fid] = {
            "category": fid, "title": None, "official_name": name, "evidence_format": "csv",
            "optional_evidence": False, "requirement": "REQUIRED" if fid in analysis.REQUIRED_IDS else "OPTIONAL",
            "schema_version": SCHEMA_VERSION, "verification_status": "verified",
            "definition_source": "UC-042 uc042lib.schema.CSV_FILES (generated by " + GENERATOR_VERSION + ")",
            "notes": "Generated from the UC-042 code. Do not edit by hand: re-run the import.",
            "canonical_filename_pattern": period.FILE_PATTERNS[fid],
            "fields": fields, "unique_key": [cols[0][0]], "null_tokens": [""],
            "classification": {"signature_fields": [], "match_policy": "exact_header"},
            "csv": {"header": [c[0] for c in cols], "encoding": "utf-8 (optional BOM)", "delimiter": ",",
                    "primary_key": [cols[0][0]], "empty_allowed": fid in schema.EMPTY_ALLOWED,
                    "scope_file": fid in schema.SCOPE_FILES,
                    "provenance": ["uc042lib.prepare.identify (header == schema.columns(fid))",
                                   "uc042lib.structure.read_csv (utf-8-sig, csv.DictReader)",
                                   "uc042lib.structure.check_rows (primary key = first column)",
                                   "uc042lib.schema.EMPTY_ALLOWED", "uc042lib.schema.SCOPE_FILES"]},
            "period_rule": json.loads(json.dumps(rule, default=str)) if rule else None,
            "period_rule_note": schema.PERIOD_UNCHECKED.get(fid),
            "relationships": _relationships_csv(fid, cols, schema),
            "consumed_by_checks": sorted(depends.get(fid, [])),
            "recurring_document": fid in analysis.RECURRING_IDS,
            "unresolved": unresolved,
            "provenance": dict(prov_header, definition=f"uc042lib.schema.CSV_FILES['{fid}']"),
        }

    for fid, (filename, name, req, labels) in schema.PDF_FILES.items():
        shared = sorted(f for f, v in schema.PDF_FILES.items() if f != fid and set(v[3]) == set(labels))
        pdf = {
            "labels": [{"label": lbl, "role": analysis.PDF_DATE_ROLES.get(lbl), "value_type": None} for lbl in labels],
            "label_pattern": label_pattern,
            "identification_rule": "readable PDF (starts with %PDF-) whose extracted text contains every label of exactly "
                                   "this category, each as a line 'Label: value'",
            "shared_label_group": shared,
            "provenance": [f"uc042lib.schema.PDF_FILES['{fid}']", "uc042lib.prepare._pdf_details", "uc042lib.prepare.identify",
                           "uc042app.ingest.analysis.PDF_DATE_ROLES"],
        }
        unresolved = ["PDF label value types are not defined by UC-042 (labels only); value_type left undefined"]
        relationships = []
        if fid in letter_slot_of:
            acct = letter_slot_of[fid]
            pdf["slot_account_id"] = acct
            pdf["slot_resolution"] = ("labels are shared with " + ", ".join(shared) + "; the slot is the one whose account "
                                      f"({acct}) has acknowledgement_letter_ref equal to the letter's 'Letter reference' in "
                                      "the account inventory (IN-02). Without that match the letter is ambiguous.")
            pdf["provenance"] += ["uc042lib.schema.LETTER_SLOTS", "uc042lib.prepare.prepare_case (letter_ref_to_slot)"]
            relationships.append({"field": "Letter reference", "target_category": "IN-02",
                                  "target_field": "acknowledgement_letter_ref", "kind": "letter_slot_resolution",
                                  "description": f"matched to the IN-02 row of {acct}",
                                  "provenance": "uc042lib.schema.LETTER_SLOTS + uc042lib.prepare.prepare_case"})
        if fid == "IN-17":
            pdf["policy_versions"] = [
                {"version": v.version, "effective": v.effective.isoformat(), "classification": v.classification,
                 "required_markings": list(v.required_markings), "description": v.description, "decision": v.decision}
                for v in policy.POLICY_VERSIONS.values()]
            pdf["policy_recognition_rule"] = (
                "'Document version' must be a registered version; 'Effective date' must equal its registered effective "
                "date; the whitespace-normalised document text must contain every required marking. Otherwise the PDF "
                "is not a usable policy.")
            pdf["text_normalisation"] = "whitespace runs -> one space; '\u2014' and '\ufffd' -> '-' (uc042lib.policy.normalise)"
            pdf["provenance"] += ["uc042lib.policy.POLICY_VERSIONS", "uc042lib.policy.recognise",
                                  "uc042lib.policy.normalise", "uc042lib.policy.document_text"]
            unresolved.append("Which recognised version governs a period is a period-level selection "
                              "(uc042lib.policy.select / APPROVED_SELECTIONS), not a file classification; not applied here")
        if fid == "IN-19":
            pdf["period_note"] = "the receipt is for the PREVIOUS month's return (uc042app.ingest.analysis.analyse_pdf)"
        out[fid] = {
            "category": fid, "title": None, "official_name": name, "evidence_format": "pdf",
            "optional_evidence": req == "OPTIONAL", "requirement": req,
            "schema_version": SCHEMA_VERSION, "verification_status": "verified",
            "definition_source": "UC-042 uc042lib.schema.PDF_FILES (generated by " + GENERATOR_VERSION + ")",
            "notes": "Generated from the UC-042 code. Do not edit by hand: re-run the import.",
            "canonical_filename_pattern": period.FILE_PATTERNS[fid],
            "fields": [], "unique_key": [], "null_tokens": [""],
            "pdf": pdf, "period_rule": None,
            "period_rule_note": schema.PERIOD_UNCHECKED.get("PDFs"),
            "relationships": relationships,
            "consumed_by_checks": sorted(depends.get(fid, [])),
            "recurring_document": fid in analysis.RECURRING_IDS,
            "unresolved": unresolved,
            "provenance": dict(prov_header, definition=f"uc042lib.schema.PDF_FILES['{fid}']"),
        }
    return out


def _with_titles(defs: dict[str, dict]) -> dict[str, dict]:
    from ..schemas.categories import OFFICIAL_CATEGORIES
    for fid, d in defs.items():
        info = OFFICIAL_CATEGORIES[fid]
        if info.evidence_format != d["evidence_format"] or info.optional != d["optional_evidence"]:
            raise Uc042ImportError(f"{fid}: UC-042 format/optionality differs from the Smart Parser category list")
        d["title"] = info.title
    if sorted(defs) != sorted(OFFICIAL_CATEGORIES):
        raise Uc042ImportError(f"UC-042 defines {sorted(defs)}, Smart Parser expects {sorted(OFFICIAL_CATEGORIES)}")
    return defs


def generate(root: str | Path) -> dict[str, dict]:
    mods, hashes, root = load_uc042(root)
    return _with_titles(build_definitions(mods, hashes, root))


def render(defn: dict) -> str:
    return json.dumps(defn, indent=2, ensure_ascii=False) + "\n"


def write_directory(defs: dict[str, dict], out_dir: str | Path) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for fid, d in sorted(defs.items()):
        p = out_dir / f"{fid}.json"
        p.write_bytes(render(d).encode("utf-8"))   # LF on every platform: byte-identical output
        written.append(p)
    return written


def compare_with_directory(defs: dict[str, dict], out_dir: str | Path) -> list[str]:
    """Differences between freshly generated definitions and the files on disk (empty: in sync)."""
    out_dir = Path(out_dir)
    diffs = []
    for fid, d in sorted(defs.items()):
        p = out_dir / f"{fid}.json"
        if not p.is_file():
            diffs.append(f"{fid}: missing file")
            continue
        on_disk = json.loads(p.read_text(encoding="utf-8"))
        fresh = json.loads(render(d))
        for key in sorted(set(on_disk) | set(fresh)):
            if key == "provenance":
                a, b = dict(on_disk.get(key) or {}), dict(fresh.get(key) or {})
                a.pop("uc042_root", None), b.pop("uc042_root", None)   # location may differ; hashes may not
                if a != b:
                    diffs.append(f"{fid}: provenance/source hashes differ")
            elif on_disk.get(key) != fresh.get(key):
                diffs.append(f"{fid}: '{key}' differs")
    return diffs
