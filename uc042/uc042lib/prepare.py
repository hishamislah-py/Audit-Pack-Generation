"""Prepare a case directory from arbitrary evidence files (no generator involved).

Usage (from the uc042/ folder):
    python -m uc042lib.prepare <input_dir> <case_dir>
    python -m uc042lib.validate <case_dir>

Identification is by content only:
  CSV  the exact header row must equal one schema file's column list (UTF-8, optional BOM).
  PDF  the file must be a readable PDF whose text contains every key-details label of one supporting
       document type. Acknowledgement letters (IN-15/IN-16) share labels, so the slot is chosen by
       matching the letter reference to the account inventory (IN-02); without that match the letter
       is reported as ambiguous.
File names, extensions and any manifest found in the input are never trusted.

Decisions recorded in <case_dir>/intake.csv:
  ACCEPTED   copied byte-for-byte to its canonical path
  DUPLICATE  same SHA-256 as an earlier file; not copied
  REJECTED   not a supported CSV/PDF evidence type; not copied
  AMBIGUOUS  two or more different files claim the same evidence slot; none of them is copied
  MISSING    a required evidence type was not supplied (no input file)
Policy documents (IN-17) are versioned (uc042lib.policy): a policy PDF is accepted only as a recognised version with its
registered effective date and markings, and is copied under its own versioned name. The version that governs the period
is selected by uc042lib.policy.select (the single applicable version, or the period's approved selection); another
applicable version is kept in the case and manifest as supplied, not selected. The selection is stated in the intake
reasons (and so in the pack's audit trail) and in <case_dir>/policy_selection.json; read it with selected_policy().
The manifest written to <case_dir>/manifest.csv is case metadata (identity, hash, counts). It is not
proof of validity: the validator checks every file's content independently.
"""
import argparse
import csv
import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

from . import policy, schema
from .period import FILE_PATTERNS, PeriodConfig, PeriodError
from .structure import diagnose_header, read_csv

INTAKE_COLS = ["original_path", "sha256", "decision", "file_id", "canonical_name", "reason",
               "probable_file_id", "missing_columns", "extra_columns", "misordered_columns", "case_or_spacing",
               "expected_header", "received_header"]
MANIFEST_COLS = ["file_id", "filename", "relative_path", "format", "evidence_kind", "requirement", "description",
                 "reporting_period", "record_count", "record_unit", "sha256", "synthetic"]


def _pdf_details(path):
    """Return ({label: value}, page_count) for a readable PDF, or raise."""
    import re
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    text = "\n".join(p.extract_text() or "" for p in reader.pages)
    labels = {lbl for v in schema.PDF_FILES.values() for lbl in v[3]}
    found = {}
    for lbl in labels:
        m = re.search(rf"^{re.escape(lbl)}: (.+)$", text, re.M)
        if m:
            found[lbl] = m.group(1).strip()
    return found, len(reader.pages)


def identify(path):
    """Identify one file by content. Returns (kind, value, info):
    ('CSV', file_id, rows) | ('PDF', [candidate file_ids], (details, pages)) | ('REJECT', reason, None)."""
    raw = Path(path).read_bytes()
    if raw.startswith(b"%PDF-"):
        try:
            details, pages = _pdf_details(path)
        except Exception as e:  # damaged PDFs raise several error types
            return "REJECT", f"PDF not readable ({type(e).__name__})", None
        cands = [fid for fid, v in schema.PDF_FILES.items() if all(lbl in details for lbl in v[3])]
        if not cands:
            return "REJECT", "PDF without the key details of any supported document type", None
        return "PDF", cands, (details, pages)
    if raw.startswith(b"PK\x03\x04"):
        return "REJECT", "XLSX/ZIP content is not supported in this phase (export as CSV)", None
    try:
        header, rows = read_csv(path)
    except (UnicodeDecodeError, csv.Error) as e:
        return "REJECT", f"not a UTF-8 CSV or supported PDF ({type(e).__name__})", None
    matches = [fid for fid in schema.CSV_FILES if header == schema.columns(fid)]
    if not matches:
        return "REJECT", diagnose_header(header), None
    return "CSV", matches[0], rows


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _calendar_period(claims):
    """The period an identified reconciliation calendar (IN-01) declares, or None."""
    cal = claims.get("IN-01", [])
    ids = {r.get("period_id", "") for _, _, rows in cal for r in rows} - {""}
    if len(cal) == 1 and len(ids) == 1:
        try:
            return PeriodConfig.from_id(next(iter(ids)))
        except PeriodError:
            return None
    return None


def prepare_case(input_dir, case_dir, period=None):
    """Build case_dir from the files under input_dir for one reporting period (PeriodConfig or PER-YYYY-MM): canonical
    file names and the manifest's reporting_period are the period's. Without `period`, the period declared by the one
    identified reconciliation calendar (IN-01 period_id) is used; if that cannot be established, PeriodError (there is
    no default month). Returns the intake rows."""
    input_dir, case_dir = Path(input_dir), Path(case_dir)
    if period is not None and not isinstance(period, PeriodConfig):
        period = PeriodConfig.from_id(period)
    if case_dir.exists():
        shutil.rmtree(case_dir)
    (case_dir / "source_data").mkdir(parents=True)
    (case_dir / "supporting_documents").mkdir(parents=True)
    files = sorted(p for p in input_dir.rglob("*") if p.is_file())
    intake, seen, claims, pdfs, policies = [], {}, {}, [], {}

    def record(p, digest, decision, fid="", reason="", diag=None, name=None):
        row = {"original_path": str(p.relative_to(input_dir)) if p else "", "sha256": digest, "decision": decision,
               "file_id": fid, "canonical_name": name or (period.filename(fid) if fid in FILE_PATTERNS else ""),
               "reason": reason}
        row.update({k: "" for k in INTAKE_COLS[6:]})
        if diag:  # header diagnosis (U3): explains the rejection; the file is still rejected
            row.update({"reason": diag["message"], "probable_file_id": diag["file_id"] or "/".join(diag["candidates"]),
                        "missing_columns": ",".join(diag["missing"]), "extra_columns": ",".join(diag["extra"]),
                        "misordered_columns": ",".join(diag["misordered"]), "case_or_spacing": ",".join(diag["case_or_spacing"]),
                        "expected_header": ",".join(diag["expected"]), "received_header": ",".join(diag["received"])})
        intake.append(row)

    for p in files:
        digest = sha256(p)
        if digest in seen:
            record(p, digest, "DUPLICATE", reason=f"same content as {seen[digest].relative_to(input_dir)}")
            continue
        seen[digest] = p
        kind, value, info = identify(p)
        if kind == "REJECT":
            if isinstance(value, dict):
                record(p, digest, "REJECTED", diag=value)
            else:
                record(p, digest, "REJECTED", reason=value)
        elif kind == "CSV":
            claims.setdefault(value, []).append((p, digest, info))
        else:
            pdfs.append((p, digest, value, info))

    if period is None:
        period = _calendar_period(claims)
        if period is None:
            raise PeriodError("the reporting period cannot be established from the evidence (no single reconciliation "
                              "calendar with one period_id); pass the period explicitly")

    # Resolve acknowledgement-letter slots using the account inventory, if one unambiguous inventory exists.
    letter_ref_to_slot = {}
    inv = claims.get("IN-02", [])
    if len(inv) == 1:
        for r in inv[0][2]:
            if r.get("account_id") in schema.LETTER_SLOTS and r.get("acknowledgement_letter_ref"):
                letter_ref_to_slot[r["acknowledgement_letter_ref"]] = schema.LETTER_SLOTS[r["account_id"]]
    for p, digest, cands, (details, pages) in pdfs:
        slot = None
        if len(cands) == 1:
            slot = cands[0]
        else:
            slot = letter_ref_to_slot.get(details.get("Letter reference", ""))
            if slot not in cands:
                record(p, digest, "AMBIGUOUS", "/".join(cands),
                       "acknowledgement letter could not be matched to an account in the inventory (IN-02)")
                continue
        if slot == "IN-17":  # versioned: only a recognised policy version with its markings is a policy document
            version, problems = policy.recognise(details, policy.document_text(p))
            if problems:
                record(p, digest, "REJECTED", "IN-17", "; ".join(problems))
            else:
                policies.setdefault(version, []).append((p, digest, pages))
            continue
        claims.setdefault(slot, []).append((p, digest, pages))

    manifest = []
    for fid in list(schema.CSV_FILES) + list(schema.PDF_FILES):
        if fid == "IN-17":
            manifest += _policy_documents(period, policies, case_dir, record)
            continue
        cands = claims.get(fid, [])
        is_csv = fid in schema.CSV_FILES
        name = period.filename(fid)
        if len(cands) > 1:
            for p, digest, _ in cands:
                record(p, digest, "AMBIGUOUS", fid, f"{len(cands)} different files identify as {fid}; none selected")
            continue
        if not cands:
            if is_csv or schema.PDF_FILES[fid][2] == "REQUIRED":
                near = [r["original_path"] for r in intake if r["decision"] == "REJECTED" and fid in r["probable_file_id"].split("/")]
                record(None, "", "MISSING", fid, "required evidence type not supplied" +
                       (f"; rejected file(s) that look like this type: {', '.join(near)}" if near else ""))
            continue
        p, digest, info = cands[0]
        sub = "source_data" if is_csv else "supporting_documents"
        shutil.copyfile(p, case_dir / sub / name)
        record(p, digest, "ACCEPTED", fid, "identified by CSV header" if is_csv else "identified by PDF key details")
        manifest.append([fid, name, f"{sub}/{name}", "CSV" if is_csv else "PDF", "RAW_SOURCE" if is_csv else "SUPPORTING_DOCUMENT",
                         "REQUIRED" if is_csv else schema.PDF_FILES[fid][2],
                         period.csv_files[fid][1] if is_csv else period.pdf_files[fid][1], period.period_id,
                         len(info) if is_csv else info, "data_rows" if is_csv else "pages", digest, "UNKNOWN"])
    with open(case_dir / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(MANIFEST_COLS)
        w.writerows(manifest)
    intake.sort(key=lambda r: (r["decision"] != "ACCEPTED", r["file_id"], r["original_path"]))
    with open(case_dir / "intake.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=INTAKE_COLS, lineterminator="\n")
        w.writeheader()
        w.writerows(intake)
    return intake


def _policy_documents(period, policies, case_dir, record):
    """Select the governing policy version and copy every usable policy document under its versioned name. Returns the
    manifest rows; writes policy_selection.json. A caller-selected version (period.policy_version) takes precedence."""
    chosen, basis, status = policy.select(period, {v: len(items) for v, items in policies.items()},
                                          override=period.policy_version)
    rows, documents = [], []
    for version, items in sorted(policies.items()):
        st, why = status[version]
        name = replace(period, policy_version=version).filename("IN-17")
        for p, digest, pages in items:
            documents.append({"version": version, "sha256": digest, "status": st, "reason": why,
                              "classification": policy.POLICY_VERSIONS[version].classification})
            if st == policy.AMBIGUOUS:
                record(p, digest, "AMBIGUOUS", "IN-17", why, name=name)
            elif st == policy.NOT_APPLICABLE:
                record(p, digest, "REJECTED", "IN-17", why, name=name)
            else:
                shutil.copyfile(p, case_dir / "supporting_documents" / name)
                record(p, digest, "ACCEPTED", "IN-17", f"identified by PDF key details; policy v{version} "
                       f"({policy.POLICY_VERSIONS[version].classification}) {st} for reconciliation: {why}", name=name)
                rows.append(["IN-17", name, f"supporting_documents/{name}", "PDF", "SUPPORTING_DOCUMENT", "REQUIRED",
                             f"Safeguarding reconciliation policy v{version}", period.period_id, pages, "pages", digest, "UNKNOWN"])
    if chosen is None:
        record(None, "", "MISSING", "IN-17", f"no policy document selected: {basis}")
    (case_dir / "policy_selection.json").write_text(json.dumps(
        {"period_id": period.period_id, "selected_version": chosen, "basis": basis, "documents": documents},
        indent=1) + "\n", encoding="utf-8")
    return rows


def selected_policy(case_dir):
    """The policy version prepare_case selected for a case (None if none, or the case was not prepared by intake)."""
    p = Path(case_dir) / "policy_selection.json"
    return json.loads(p.read_text(encoding="utf-8"))["selected_version"] if p.is_file() else None


def main():
    ap = argparse.ArgumentParser(description="Prepare a case directory from evidence files, identified by content")
    ap.add_argument("input_dir")
    ap.add_argument("case_dir")
    ap.add_argument("--period", help="reporting period PER-YYYY-MM (default: the period the calendar IN-01 declares)")
    a = ap.parse_args()
    intake = prepare_case(a.input_dir, a.case_dir, a.period)
    counts = {}
    for r in intake:
        counts[r["decision"]] = counts.get(r["decision"], 0) + 1
    print(f"Prepared {a.case_dir}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    for r in intake:
        if r["decision"] != "ACCEPTED":
            print(f"  {r['decision']:<10} {r['file_id'] or '-':<8} {r['original_path'] or '-'}: {r['reason']}")
    print(f"Next: python -m uc042lib.validate {a.case_dir}")


if __name__ == "__main__":
    main()
