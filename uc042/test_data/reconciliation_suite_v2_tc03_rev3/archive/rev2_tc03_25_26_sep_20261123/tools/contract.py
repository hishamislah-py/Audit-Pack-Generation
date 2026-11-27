"""Canonical UC-042 file contract, read WITHOUT executing engine code.

`schema.py` of the reference engine is parsed with `ast` and only literal assignments are evaluated
(CSV_FILES, PDF_FILES, ENUMS, EMPTY_ALLOWED, SCOPE_FILES). CONDITIONAL holds lambdas and cannot be read
literally; its eleven rules are transcribed below from schema.py lines 255-267 (reference engine, 23 Nov 2026).
A JSON snapshot (tools/schema_contract_snapshot.json) records what was read and the SHA-256 of schema.py,
so validation can be reproduced without access to the engine path.
"""
import ast
import hashlib
import json
from pathlib import Path

REFERENCE_SCHEMA = Path(r"C:\u42v\e2e_20261122\engine_base\uc042\uc042lib\schema.py")
SNAPSHOT = Path(__file__).resolve().parent / "schema_contract_snapshot.json"
LITERALS = ("CSV_FILES", "PDF_FILES", "ENUMS", "EMPTY_ALLOWED", "SCOPE_FILES")

# Transcribed from schema.CONDITIONAL: (file, field, predicate on the row, description).
CONDITIONAL = [
    ("IN-01", "non_recon_reason", lambda r: r.get("is_recon_day") == "false", "required when is_recon_day is false"),
    ("IN-02", "asset_pool_id", lambda r: r.get("account_class") == "RELEVANT_FUNDS_BANK", "required for safeguarding accounts"),
    ("IN-02", "designation_name", lambda r: r.get("account_class") == "RELEVANT_FUNDS_BANK", "required for safeguarding accounts"),
    ("IN-02", "acknowledgement_letter_ref", lambda r: r.get("account_class") == "RELEVANT_FUNDS_BANK", "required for safeguarding accounts"),
    ("IN-04", "allocated_ts", lambda r: r.get("allocated_date", "") != "", "required when allocated_date is set"),
    ("IN-04", "client_id", lambda r: r.get("allocated_date", "") != "", "required when allocated_date is set"),
    ("IN-11", "settlement_batch_id", lambda r: r.get("txn_type") in ("LOAD_CARD", "SPEND", "REFUND"), "required for card transactions"),
    ("IN-11", "payment_reference", lambda r: r.get("txn_type") in ("LOAD_BANK", "REDEMPTION"), "required for bank loads and redemptions"),
    ("IN-11", "original_txn_id", lambda r: r.get("txn_type") == "REFUND", "required for refunds"),
    ("IN-13", "txn_id", lambda r: r.get("line_type") in ("TXN", "REFUND"), "required for TXN and REFUND lines"),
    ("IN-13", "fee_code", lambda r: r.get("line_type") == "FEE", "required for FEE lines"),
]


def _read_reference():
    raw = REFERENCE_SCHEMA.read_bytes()  # hash the file bytes exactly as stored
    src = raw.decode("utf-8")
    tree = ast.parse(src)
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in LITERALS:
                found[name] = ast.literal_eval(node.value)
    missing = [n for n in LITERALS if n not in found]
    if missing:
        raise RuntimeError(f"schema.py literals not found: {missing}")
    snap = {
        "source": str(REFERENCE_SCHEMA),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "csv_files": {fid: {"filename": v[0], "title": v[1], "columns": [list(c) for c in v[2]]} for fid, v in found["CSV_FILES"].items()},
        "pdf_files": {fid: {"filename": v[0], "title": v[1], "requirement": v[2], "labels": v[3]} for fid, v in found["PDF_FILES"].items()},
        "enums": [[k[0], k[1], sorted(v)] for k, v in found["ENUMS"].items()],
        "empty_allowed": sorted(found["EMPTY_ALLOWED"]),
        "scope_files": sorted(found["SCOPE_FILES"]),
        "conditional_transcribed": [[f, c, d] for f, c, _, d in CONDITIONAL],
    }
    return snap


def load(refresh=False):
    """Return the contract snapshot. With refresh=True (or no snapshot yet) re-read schema.py via ast."""
    if refresh or not SNAPSHOT.exists():
        snap = _read_reference()
        SNAPSHOT.write_text(json.dumps(snap, indent=1) + "\n", encoding="utf-8")
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


class Contract:
    def __init__(self, snap):
        self.snap = snap
        self.csv = snap["csv_files"]
        self.pdf = snap["pdf_files"]
        self.enums = {(f, c): set(v) for f, c, v in snap["enums"]}
        self.empty_allowed = set(snap["empty_allowed"])

    def filename(self, fid):
        return (self.csv.get(fid) or self.pdf.get(fid))["filename"]

    def columns(self, fid):
        return [c[0] for c in self.csv[fid]["columns"]]

    def pk(self, fid):
        return self.columns(fid)[0]

    def types(self, fid):
        return {c[0]: c[1] for c in self.csv[fid]["columns"]}

    def mandatory(self, fid):
        return [c[0] for c in self.csv[fid]["columns"] if c[2] == "M"]

    def fid_of(self, filename):
        for fid in list(self.csv) + list(self.pdf):
            if self.filename(fid) == filename:
                return fid
        return None


if __name__ == "__main__":
    s = load(refresh=True)
    print(f"contract read from {s['source']} (sha256 {s['source_sha256'][:16]}): {len(s['csv_files'])} CSV, {len(s['pdf_files'])} PDF, "
          f"{len(s['enums'])} enums, {len(s['conditional_transcribed'])} conditional rules")
