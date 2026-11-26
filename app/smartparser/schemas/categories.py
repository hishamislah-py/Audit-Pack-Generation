"""The 19 recognised UC-042 evidence categories (from the project brief).

Only identifiers, titles, formats and optionality are recorded here - these are
given in the brief. Field-level contracts live in definitions/*.json.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryInfo:
    category: str
    title: str
    evidence_format: str
    optional: bool = False


OFFICIAL_CATEGORIES: dict[str, CategoryInfo] = {
    c.category: c
    for c in [
        CategoryInfo("IN-01", "Reconciliation calendar", "csv"),
        CategoryInfo("IN-02", "Account inventory", "csv"),
        CategoryInfo("IN-03", "Client balance snapshots", "csv"),
        CategoryInfo("IN-04", "Unallocated receipts", "csv"),
        CategoryInfo("IN-05", "Internal reconciliation records", "csv"),
        CategoryInfo("IN-06", "External reconciliation records", "csv"),
        CategoryInfo("IN-07", "Bank balance confirmations", "csv"),
        CategoryInfo("IN-08", "End-of-day statement headers", "csv"),
        CategoryInfo("IN-09", "Statement entries", "csv"),
        CategoryInfo("IN-10", "Safeguarding cash book", "csv"),
        CategoryInfo("IN-11", "Client transactions", "csv"),
        CategoryInfo("IN-12", "Settlement batches", "csv"),
        CategoryInfo("IN-13", "Settlement lines", "csv"),
        CategoryInfo("IN-14", "Discrepancy log", "csv"),
        CategoryInfo("IN-15", "GBP safeguarding account acknowledgement letter", "pdf"),
        CategoryInfo("IN-16", "EUR safeguarding account acknowledgement letter", "pdf"),
        CategoryInfo("IN-17", "Reconciliation policy", "pdf"),
        CategoryInfo("IN-18", "Governance register", "pdf", optional=True),
        CategoryInfo("IN-19", "Previous month's return receipt", "pdf", optional=True),
    ]
}
