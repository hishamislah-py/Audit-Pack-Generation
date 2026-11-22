"""Control names (decision D1): verbatim descriptors from docs/UC042_SOURCE_TO_CONTROL_MATRIX.md, with their line.

No new or conflicting definitions: each name is the matrix's own short descriptor for that control code.
tests/test_audit_pack.py checks that every phrase appears on the stated line of the matrix.
"""
MATRIX = "docs/UC042_SOURCE_TO_CONTROL_MATRIX.md"

# control code -> (name, matrix line, verbatim matrix phrase)
CONTROLS = {
    "C01": ("Internal reconciliation existence", 19, "C01 (R01) existence"),
    "C02": ("Record completeness", 19, "C02 (R02) completeness"),
    "C03": ("Reconciliation point", 19, "C03 (R03) point"),
    "C04": ("Requirement", 83, "C04 requirement"),
    "C05": ("Resource", 84, "C05 resource"),
    "C06": ("Internal difference handling", 19, "C06 (R06) difference handling"),
    "C07": ("External existence and statement agreement", 20, "C07 (R07) existence and statement agreement"),
    "C08": ("External difference handling", 20, "C08 (R08) difference handling"),
    "C09": ("Receipts mapping", 23, "C09 receipts mapping"),
    "C10": ("Designation", 87, "C10 designation"),
    "C11": ("Settlement", 86, "C11 settlement"),
    "C12": ("Reversal validity", 25, "C12 (D07) reversal validity"),
    "C13": ("Currency ownership", 16, "C13 currency ownership"),
    "C14": ("Reporting period and recon-day completeness", 36, "Reporting period and recon-day completeness"),
    "C16": ("Checklist", 31, "C16 (checklist)"),
    "DQ": ("Data-quality checks", 3, "data-quality checks DQ01"),
    "DQ22": ("Cross-day continuity", 22, "DQ22 cross-day continuity"),
    "DQ23": ("Within-statement continuity", 22, "DQ23 within-statement continuity"),
}


def control_name(code):
    """Name for an engine control code; composite codes (for example 'C05/C07') join their parts."""
    parts = code.split("/")
    # Codes the matrix does not name are labelled as such; no name is invented (D1).
    return " / ".join(CONTROLS[p][0] if p in CONTROLS else f"{p} (not named in the source-to-control matrix)" for p in parts)
