"""File contract for the UC-042 baseline: shared by the generator, validator and data dictionary.

Each column: (name, type, requiredness, description). Requiredness: M mandatory, C conditional, O optional.
Types: id, str, date, ts (ISO 8601 with offset), bool, int, amount (unsigned 2dp), signed (signed 2dp), ccy, enum.
"""

# The constants below describe the BASELINE reporting period (September 2026): its period ID, canonical file names
# and reporting-period rules. The engine itself is period-configurable: uc042lib.period.PeriodConfig derives the same
# values for any month (file names from period.FILE_PATTERNS, rules from PERIOD_RULES with the month's own values), and
# every case is processed with its own period. The dataset generator (generate.py, scenarios.py) uses these values.
PERIOD_ID = "PER-2026-09"
POOL_ID = "POOL-EMONEY"
TZ = "Europe/London"

CSV_FILES = {
    "IN-01": ("recon_calendar_2026-09.csv", "Reconciliation-day calendar", [
        ("calendar_date", "date", "M", "Every calendar date in the period (primary key)"),
        ("period_id", "id", "M", "Reporting period"),
        ("is_recon_day", "bool", "M", "true if reconciliation is required"),
        ("non_recon_reason", "enum", "C", "WEEKEND / UK_BANK_HOLIDAY / FOREIGN_MARKET_CLOSED; required when false"),
        ("calendar_basis", "str", "M", "Synthetic basis statement"),
    ]),
    "IN-02": ("account_inventory.csv", "Institution and account inventory", [
        ("account_id", "id", "M", "Account key"),
        ("account_class", "enum", "M", "RELEVANT_FUNDS_BANK or OWN_FUNDS"),
        ("currency", "ccy", "M", "Account currency"),
        ("asset_pool_id", "id", "C", "Required for RELEVANT_FUNDS_BANK"),
        ("account_number_masked", "str", "M", "Masked synthetic number"),
        ("designation_name", "str", "C", "Account name as designated; required for safeguarding accounts"),
        ("acknowledgement_letter_ref", "str", "C", "Reference printed on the acknowledgement letter PDF"),
        ("institution_id", "id", "M", "Institution key"),
        ("institution_full_name", "str", "M", "Fictional institution name"),
        ("institution_postal_address", "str", "M", "Fictional address"),
        ("institution_email", "str", "M", "Fictional email"),
        ("institution_phone", "str", "M", "Fictional phone"),
        ("institution_role", "enum", "M", "RELEVANT_FUNDS_BANK"),
        ("open_date", "date", "M", "Account opening date"),
        ("close_date", "date", "O", "Blank if open"),
    ]),
    "IN-03": ("client_balance_snapshots_2026-09.csv", "Client balance snapshots at each 17:00 point", [
        ("snapshot_id", "id", "M", "Key"),
        ("recon_date", "date", "M", "Reconciliation day"),
        ("as_at_ts", "ts", "M", "Snapshot time; must equal the reconciliation point"),
        ("client_id", "id", "M", "Client"),
        ("asset_pool_id", "id", "M", "Pool"),
        ("currency", "ccy", "M", "Currency"),
        ("balance", "signed", "M", "Individual safeguarding balance as per client ledger"),
    ]),
    "IN-04": ("unallocated_register_2026-09.csv", "Unallocated receipts register", [
        ("receipt_id", "id", "M", "Key"),
        ("bank_reference", "str", "M", "end_to_end_ref of the bank credit"),
        ("receipt_date", "date", "M", "Day received"),
        ("receipt_ts", "ts", "M", "Time received"),
        ("amount", "amount", "M", "Amount received"),
        ("currency", "ccy", "M", "Currency"),
        ("classification", "enum", "M", "UNALLOCATED or UNIDENTIFIED"),
        ("identified_date", "date", "C", "If first unidentified"),
        ("allocated_date", "date", "C", "Blank while open"),
        ("allocated_ts", "ts", "C", "Blank while open"),
        ("client_id", "id", "C", "Client once allocated"),
    ]),
    "IN-05": ("internal_recon_records_2026-09.csv", "Internal reconciliation records (as reported by the firm)", [
        ("recon_run_id", "id", "M", "Key"),
        ("recon_date", "date", "M", "Reconciliation day"),
        ("reconciliation_point_ts", "ts", "M", "Point the records were taken at"),
        ("performed_at_ts", "ts", "M", "When the reconciliation was carried out"),
        ("asset_pool_id", "id", "M", "Pool"),
        ("currency", "ccy", "M", "Currency (per-currency convention)"),
        ("method", "enum", "M", "STANDARD"),
        ("requirement_reported", "signed", "M", "Reported safeguarding requirement"),
        ("resource_reported", "signed", "M", "Reported safeguarding resource"),
        ("item_a", "signed", "M", "Reported item A (relevant funds bank accounts, ledger values)"),
        ("item_b", "signed", "M", "Reported item B"),
        ("item_c", "signed", "M", "Reported item C"),
        ("item_d", "signed", "M", "Reported item D"),
        ("difference_reported", "signed", "M", "Reported resource minus requirement"),
        ("d1_requirement", "signed", "C", "Blank: D+1 comparison excluded (CASS 15.8.13R basis, see gaps G-R05)"),
        ("d1_resource", "signed", "C", "Blank, as above"),
        ("actions_taken_text", "str", "M", "Actions taken"),
        ("preparer_id", "id", "M", "Preparer"),
        ("reviewer_id", "id", "O", "Reviewer"),
    ]),
    "IN-06": ("external_recon_records_2026-09.csv", "External reconciliation records (as reported by the firm)", [
        ("ext_recon_id", "id", "M", "Key"),
        ("recon_date", "date", "M", "Reconciliation day"),
        ("performed_at_ts", "ts", "M", "When carried out"),
        ("account_id", "id", "M", "Safeguarding account"),
        ("currency", "ccy", "M", "Currency"),
        ("ledger_balance_reported", "signed", "M", "Firm's ledger balance as reported"),
        ("bank_statement_id", "id", "M", "Statement the firm says it used (IN-07)"),
        ("bank_balance_reported", "signed", "M", "Bank balance as reported"),
        ("difference_reported", "signed", "M", "Bank minus ledger as reported"),
        ("timing_difference_claimed", "bool", "M", "Preparer's claim"),
        ("preparer_id", "id", "M", "Preparer"),
    ]),
    "IN-07": ("bank_balance_confirmations_2026-09.csv", "Bank balance confirmations at 17:00", [
        ("statement_id", "id", "M", "Key"),
        ("account_id", "id", "M", "Safeguarding account"),
        ("as_at_ts", "ts", "M", "17:00 point"),
        ("currency", "ccy", "M", "Currency"),
        ("balance_amount", "amount", "M", "Balance as stated by the bank (unsigned)"),
        ("balance_dc_indicator", "enum", "M", "C = in credit to account holder (bank perspective)"),
        ("bank_statement_ref", "str", "O", "Bank's reference"),
    ]),
    "IN-08": ("bank_statements_eod_2026-09.csv", "End-of-day bank statement headers", [
        ("statement_id", "id", "M", "Key"),
        ("account_id", "id", "M", "Account"),
        ("statement_date", "date", "M", "Statement date"),
        ("as_at_ts", "ts", "M", "End of day"),
        ("currency", "ccy", "M", "Currency"),
        ("opening_balance_amount", "amount", "M", "Opening balance (unsigned)"),
        ("opening_balance_dc", "enum", "M", "C / D, bank perspective"),
        ("closing_balance_amount", "amount", "M", "Closing balance (unsigned)"),
        ("closing_balance_dc", "enum", "M", "C / D, bank perspective"),
        ("entry_count", "int", "M", "Number of entries in IN-09 for this statement"),
        ("bank_statement_ref", "str", "O", "Bank's reference"),
    ]),
    "IN-09": ("bank_statement_entries_2026-09.csv", "Bank statement entries", [
        ("bank_entry_id", "id", "M", "Key"),
        ("statement_id", "id", "M", "Parent EOD statement"),
        ("account_id", "id", "M", "Account"),
        ("booking_date", "date", "M", "Booking date"),
        ("booking_ts", "ts", "M", "Booking time"),
        ("value_date", "date", "M", "Value date"),
        ("amount", "amount", "M", "Unsigned amount"),
        ("dc_indicator", "enum", "M", "C = money in, D = money out (bank perspective)"),
        ("currency", "ccy", "M", "Currency"),
        ("bank_reference", "str", "M", "Reference carried by the bank"),
        ("end_to_end_ref", "str", "C", "Required for bank loads and redemptions"),
        ("counterparty_name", "str", "O", "Fictional"),
        ("narrative_text", "str", "O", "Free text, never authoritative"),
    ]),
    "IN-10": ("sga_cashbook_entries_2026-09.csv", "Safeguarding-account cash book (firm ledger)", [
        ("ledger_entry_id", "id", "M", "Key"),
        ("account_id", "id", "M", "Safeguarding account"),
        ("posted_ts", "ts", "M", "Posting time; entries at or before 17:00 count for that day"),
        ("entry_type", "enum", "M", "OPENING_BALANCE / BANK_LOAD / UNALLOCATED_RECEIPT / ACQUIRER_SETTLEMENT / OWN_FUNDS_TOPUP / SCHEME_SETTLEMENT / REDEMPTION"),
        ("amount", "amount", "M", "Unsigned amount"),
        ("dc_indicator", "enum", "M", "D = money in, C = money out (firm asset-ledger perspective)"),
        ("currency", "ccy", "M", "Currency"),
        ("payment_reference", "str", "M", "Equals the bank entry's bank_reference or end_to_end_ref; OPENING for opening rows"),
    ]),
    "IN-11": ("transactions_2026-09.csv", "Client transactions", [
        ("txn_id", "id", "M", "Key"),
        ("client_id", "id", "M", "Client"),
        ("txn_type", "enum", "M", "LOAD_BANK / LOAD_CARD / SPEND / REDEMPTION / REFUND"),
        ("status", "enum", "M", "SETTLED / EXECUTED"),
        ("auth_ts", "ts", "C", "Card authorisation time"),
        ("clearing_date", "date", "C", "Card clearing date"),
        ("executed_ts", "ts", "M", "When the client balance changed (convention D8)"),
        ("amount", "amount", "M", "Unsigned amount"),
        ("direction", "enum", "M", "CR increases client balance, DR decreases"),
        ("currency", "ccy", "M", "Currency"),
        ("settlement_batch_id", "id", "C", "Required for LOAD_CARD, SPEND, REFUND"),
        ("payment_reference", "str", "C", "Required for LOAD_BANK and REDEMPTION; equals bank end_to_end_ref"),
        ("original_txn_id", "id", "C", "Required for REFUND"),
    ]),
    "IN-12": ("settlement_batches_2026-09.csv", "Settlement batch headers (generic synthetic format)", [
        ("batch_id", "id", "M", "Key"),
        ("counterparty_type", "enum", "M", "SCHEME or ACQUIRER"),
        ("cycle_date", "date", "M", "Cycle date per report"),
        ("settlement_date", "date", "M", "Settlement date per report"),
        ("account_id", "id", "M", "Settlement account"),
        ("currency", "ccy", "M", "Currency"),
        ("direction", "enum", "M", "TO_FIRM or FROM_FIRM"),
        ("gross_amount", "amount", "M", "Reported gross (unsigned)"),
        ("total_fees", "amount", "M", "Reported fees (unsigned)"),
        ("total_adjustments", "amount", "M", "Reported refunds/adjustments (unsigned)"),
        ("net_amount_reported", "amount", "M", "Reported net (unsigned)"),
        ("expected_bank_reference", "str", "M", "Reference the bank entry should carry"),
    ]),
    "IN-13": ("settlement_lines_2026-09.csv", "Settlement batch lines", [
        ("line_id", "id", "M", "Key"),
        ("batch_id", "id", "M", "Parent batch"),
        ("line_type", "enum", "M", "TXN / FEE / REFUND"),
        ("txn_id", "id", "C", "Required for TXN and REFUND"),
        ("fee_code", "str", "C", "Required for FEE: ACQ_FEE or SCHEME_FEE"),
        ("amount", "amount", "M", "Unsigned amount"),
        ("dc_indicator", "enum", "M", "C = money to the firm, D = money from the firm"),
        ("currency", "ccy", "M", "Currency"),
    ]),
    "IN-14": ("discrepancy_log_2026-09.csv", "Discrepancy and corrective-action log", [
        ("discrepancy_id", "id", "M", "Key"),
        ("logged_ts", "ts", "M", "When logged"),
        ("recon_ref", "id", "M", "IN-05 or IN-06 record"),
        ("account_id", "id", "M", "Account"),
        ("currency", "ccy", "M", "Currency"),
        ("amount", "signed", "M", "Difference amount"),
        ("description", "str", "M", "Description"),
        ("cause_category", "enum", "O", "Cause, if evidenced"),
        ("cause_evidence_ref", "str", "O", "Evidence for the cause"),
        ("funding_reference", "str", "O", "Own-funds transfer reference"),
        ("status", "enum", "M", "OPEN / RESOLVED"),
        ("resolved_ts", "ts", "O", "When resolved"),
        ("approver_id", "id", "O", "Approver"),
    ]),
}

PDF_FILES = {
    "IN-15": ("ack_letter_SGA-GBP-01.pdf", "Acknowledgement letter, SGA-GBP-01", "REQUIRED",
              ["Letter reference", "Institution", "Account name", "Account number", "Currency", "Letter date"]),
    "IN-16": ("ack_letter_SGA-EUR-01.pdf", "Acknowledgement letter, SGA-EUR-01", "REQUIRED",
              ["Letter reference", "Institution", "Account name", "Account number", "Currency", "Letter date"]),
    "IN-17": ("safeguarding_reconciliation_policy_v1.2.pdf", "Safeguarding reconciliation policy v1.2", "REQUIRED",
              ["Document version", "Effective date", "Safeguarding method", "Reconciliation method",
               "Reconciliation point", "Frequency", "Internal reconciliation basis"]),
    "IN-18": ("governance_register_2026-09.pdf", "Governance register", "OPTIONAL",
              ["Accountable person", "Role", "Allocated from"]),
    "IN-19": ("rep027_submission_receipt_2026-08.pdf", "Monthly safeguarding return receipt (August)", "OPTIONAL",
              ["Return", "Period", "Due date", "Submitted at", "Submission reference"]),
}

CSV_REQUIRED = {fid: "REQUIRED" for fid in CSV_FILES}


def columns(file_id):
    return [c[0] for c in CSV_FILES[file_id][2]]


def mandatory(file_id):
    return [c[0] for c in CSV_FILES[file_id][2] if c[2] == "M"]


def coltypes(file_id):
    return {c[0]: c[1] for c in CSV_FILES[file_id][2]}


# --- Structural rules (used by uc042lib.structure; one place only) -------------------------------
# Allowed values for enum-like columns. Anything else makes the row invalid.
ENUMS = {
    ("IN-01", "non_recon_reason"): {"WEEKEND", "UK_BANK_HOLIDAY", "FOREIGN_MARKET_CLOSED"},
    ("IN-02", "account_class"): {"RELEVANT_FUNDS_BANK", "OWN_FUNDS"},
    ("IN-02", "institution_role"): {"RELEVANT_FUNDS_BANK"},
    ("IN-04", "classification"): {"UNALLOCATED", "UNIDENTIFIED"},
    ("IN-05", "method"): {"STANDARD", "NON_STANDARD"},
    ("IN-07", "balance_dc_indicator"): {"C", "D"},
    ("IN-08", "opening_balance_dc"): {"C", "D"},
    ("IN-08", "closing_balance_dc"): {"C", "D"},
    ("IN-09", "dc_indicator"): {"C", "D"},
    ("IN-10", "entry_type"): {"OPENING_BALANCE", "BANK_LOAD", "UNALLOCATED_RECEIPT", "ACQUIRER_SETTLEMENT",
                              "OWN_FUNDS_TOPUP", "SCHEME_SETTLEMENT", "REDEMPTION"},
    ("IN-10", "dc_indicator"): {"D", "C"},
    ("IN-11", "txn_type"): {"LOAD_BANK", "LOAD_CARD", "SPEND", "REDEMPTION", "REFUND"},
    ("IN-11", "status"): {"SETTLED", "EXECUTED"},
    ("IN-11", "direction"): {"CR", "DR"},
    ("IN-12", "counterparty_type"): {"SCHEME", "ACQUIRER"},
    ("IN-12", "direction"): {"TO_FIRM", "FROM_FIRM"},
    ("IN-13", "line_type"): {"TXN", "FEE", "REFUND"},
    ("IN-13", "dc_indicator"): {"C", "D"},
    ("IN-13", "fee_code"): {"ACQ_FEE", "SCHEME_FEE"},
    ("IN-14", "status"): {"OPEN", "RESOLVED"},
}

# Conditional requiredness the calculations rely on: (file, field, condition on the row, description).
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

# Files that may legitimately contain no data rows.
EMPTY_ALLOWED = {"IN-04", "IN-14"}

# Files that define the expected scope: any invalid row makes the whole file unusable,
# because a partial calendar or account list would silently shrink what is checked.
SCOPE_FILES = {"IN-01", "IN-02"}

# Acknowledgement letter slot for each safeguarding account (C10, and PDF identification at intake).
LETTER_SLOTS = {"SGA-GBP-01": "IN-15", "SGA-EUR-01": "IN-16"}

# Evidence each check needs (from docs/UC042_SOURCE_TO_CONTROL_MATRIX.md, sections 1 and 3).
# If any listed file is missing, empty, unusable or ambiguous, the check is not run and returns
# one INSUFFICIENT_EVIDENCE result. Checks that do not list the file keep running.
DEPENDS = {
    "C03-POLICY": ["IN-17"],
    "C03-POINT": ["IN-17"],
    "C01-COVER": ["IN-01", "IN-02", "IN-05"],
    "C07-COVER": ["IN-01", "IN-02", "IN-06"],
    "C14-COVER": ["IN-01", "IN-02"],
    "DQ23-STATEMENT": ["IN-08", "IN-09"],
    "DQ22-CONTINUITY": ["IN-01", "IN-08"],
    "BC-VS-EOD": ["IN-07", "IN-08", "IN-09"],
    "CASH-BANK-LINK": ["IN-02", "IN-07", "IN-08", "IN-09", "IN-10"],
    "BANK-CASH-LINK": ["IN-02", "IN-09", "IN-10"],
    "C04-REQUIREMENT": ["IN-01", "IN-03", "IN-04", "IN-05", "IN-17"],
    "C05-RESOURCE": ["IN-01", "IN-02", "IN-05", "IN-10", "IN-17"],
    "C06-DIFFERENCE": ["IN-01", "IN-02", "IN-03", "IN-04", "IN-05", "IN-10", "IN-17"],
    "C07-BANK-EVIDENCE": ["IN-01", "IN-02", "IN-06", "IN-07"],
    "RC2-LEDGER": ["IN-02", "IN-06", "IN-10", "IN-17"],
    "C08-DIFFERENCE": ["IN-01", "IN-02", "IN-06", "IN-07", "IN-10", "IN-17"],
    "C11-BATCH-ARITH": ["IN-11", "IN-12", "IN-13"],
    "C11-BATCH-BANK": ["IN-02", "IN-07", "IN-08", "IN-09", "IN-12"],
    "C11-TXN-LINE": ["IN-11", "IN-12", "IN-13"],
    "C11-BANK-ENTRY": ["IN-02", "IN-04", "IN-09", "IN-10", "IN-11", "IN-12"],
    "FUND-TOPUP": ["IN-02", "IN-07", "IN-08", "IN-09", "IN-10", "IN-12"],
    "RC4-DIRECT": ["IN-02", "IN-04", "IN-07", "IN-08", "IN-09", "IN-11"],
    "C09-ALLOCATION": ["IN-02", "IN-04", "IN-09", "IN-11"],
    "C12-REFUND": ["IN-11"],
    "CBAL-NONNEG": ["IN-03"],
    "CBAL-ROLLFWD": ["IN-03", "IN-11", "IN-17"],
    "C13-CURRENCY": ["IN-02"],
    "C10-DESIGNATION": ["IN-02"],
    "DISC-LOG": ["IN-14"],
}


# --- Reporting-period rules (U2; one place only) --------------------------------------------------
# Baseline period (U5): September 2026. Other months: uc042lib.period.PeriodConfig.period_rules. Dates are judged as
# Europe/London calendar dates.
from datetime import date as _date  # noqa: E402

PERIOD_START, PERIOD_END = _date(2026, 9, 1), _date(2026, 9, 30)

# For each evidence type: the business-date fields that must fall inside the period, any explicitly
# permitted boundary records, and fields that must not fall after the period end.
# A row that breaks these rules is excluded from all calculations and reported (DQ-PERIOD).
# A file whose rows are all outside the period (permitted boundary rows aside) is WRONG_PERIOD.
PERIOD_RULES = {
    "IN-01": {"in_period": ["calendar_date"], "equals": {"period_id": PERIOD_ID}},
    # D4: the opening client snapshot at the 31 Aug 2026 17:00 point is a permitted boundary record (like the cash-book opening row).
    "IN-03": {"in_period": ["recon_date"],
              "permitted": [{"recon_date": "2026-08-31", "as_at_ts": "2026-08-31T17:00:00+01:00"}]},
    # A1 (decided): a register row belongs to the period if the receipt was open at some point in it, i.e. received on or
    # before the period end and not allocated before the period start. This follows the RC1 formula in the
    # source-to-control matrix (open at point d if receipt_ts <= d and allocated_ts is blank or later than d).
    # Receipt and allocation stay separate facts; a September receipt allocated in October stays open at every
    # later September point. A receipt received after the period end is out of period.
    "IN-04": {"open_during_period": {"start": ["receipt_date", "receipt_ts"], "end": ["allocated_date", "allocated_ts"]}},
    "IN-05": {"in_period": ["recon_date"]},
    "IN-06": {"in_period": ["recon_date"]},
    "IN-07": {"in_period": ["as_at_ts"]},
    "IN-08": {"in_period": ["statement_date"]},
    "IN-09": {"in_period": ["booking_date", "booking_ts"]},
    # Permitted boundary record: the cash-book opening position at the 31 Aug 2026 17:00 reconciliation point
    # (input evidence spec section 4, IN-10: "One OPENING_BALANCE row per safeguarding account, dated 31 Aug 2026 17:00").
    "IN-10": {"in_period": ["posted_ts"],
              "permitted": [{"entry_type": "OPENING_BALANCE", "posted_ts": "2026-08-31T17:00:00+01:00"}]},
    "IN-11": {"in_period": ["executed_ts"]},
    "IN-12": {"in_period": ["settlement_date"]},
    # A2 (decided, synthetic convention P2): a log entry belongs to the period of the reconciliation record it
    # refers to (recon_ref -> IN-05/IN-06 recon_date), not to its log date. It is excluded if that record is not a
    # September record in this case, or if it was logged before that reconciliation. An entry logged after the period
    # end is kept and labelled as subsequently recorded. The log never changes a balance.
    "IN-14": {"event_ref": {"field": "recon_ref", "sources": {"IN-05": "recon_run_id", "IN-06": "ext_recon_id"},
                            "date_field": "recon_date"},
              "not_before_event": ["logged_ts"], "subsequent_after_end": ["logged_ts"]},
}

# Not period-checked, with the reason. These fields are never read by a calculation, so they cannot influence one.
PERIOD_UNCHECKED = {
    "IN-02": "open_date/close_date describe the account, not period activity",
    "IN-03": "as_at_ts is checked against the reconciliation point by C03 instead",
    "IN-04": "identified_date is not used by any calculation; receipt and allocation dates follow the open-during-period rule",
    "IN-05": "reconciliation_point_ts is checked by C03; performed_at_ts is not used",
    "IN-06": "performed_at_ts is not used",
    "IN-08": "as_at_ts is not used",
    "IN-09": "value_date is not used (A3: a 30 Sep booking with an October value date is plausible; the spec is silent)",
    "IN-11": "auth_ts and clearing_date are not used (A4: an August authorisation settled in September is plausible)",
    "IN-12": "cycle_date is not used (A5: a cycle may precede its settlement date)",
    "IN-13": "no date fields; a line follows its batch, and lines of an excluded batch are not used",
    "IN-14": "resolved_ts is not used; the log's period follows the reconciliation it refers to",
    "PDFs": "letter date, policy effective date and return period are document attributes, not period activity",
}
