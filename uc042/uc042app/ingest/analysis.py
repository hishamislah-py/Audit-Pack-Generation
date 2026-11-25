"""Upload analysis: identify one uploaded file by CONTENT (the engine's own intake identification, uc042lib.prepare.identify)
and check its dates and keys against the month the analyst selected. Pure: no database, no file writes.

Date types are kept apart (DATE_ROLES): a booking date is not a settlement date, a snapshot time is not a transaction
time. Only the column(s) that decide which month a record belongs to (GOVERNING, taken from uc042lib.schema.PERIOD_RULES)
are judged against the selected month. Other dates are reported with their range; a value outside the month there is a
legitimate timing difference (for example an October value date on a 30 September booking), never an error.

Nothing is moved between months. A record dated outside the selected month stays in its document; the engine excludes it
from calculations and reports it (DQ-PERIOD) when the period is processed."""
import calendar
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from uc042lib import policy, schema
from uc042lib.period import PeriodConfig
from uc042lib.prepare import identify
from uc042lib.structure import field_error, parse_ts

TZ = ZoneInfo(schema.TZ)

# What each date column means. Values are shown to the analyst; they are never interchangeable.
DATE_ROLES = {
    ("IN-01", "calendar_date"): "Reconciliation calendar date",
    ("IN-02", "open_date"): "Account opening date", ("IN-02", "close_date"): "Account closing date",
    ("IN-03", "recon_date"): "Reconciliation date", ("IN-03", "as_at_ts"): "Snapshot timestamp",
    ("IN-04", "receipt_date"): "Receipt date", ("IN-04", "receipt_ts"): "Receipt timestamp",
    ("IN-04", "identified_date"): "Identification date", ("IN-04", "allocated_date"): "Allocation date",
    ("IN-04", "allocated_ts"): "Allocation timestamp",
    ("IN-05", "recon_date"): "Reconciliation date", ("IN-05", "reconciliation_point_ts"): "Reconciliation point timestamp",
    ("IN-05", "performed_at_ts"): "Performed-at timestamp",
    ("IN-06", "recon_date"): "Reconciliation date", ("IN-06", "performed_at_ts"): "Performed-at timestamp",
    ("IN-07", "as_at_ts"): "Bank confirmation timestamp",
    ("IN-08", "statement_date"): "Statement date", ("IN-08", "as_at_ts"): "Statement end-of-day timestamp",
    ("IN-09", "booking_date"): "Booking date", ("IN-09", "booking_ts"): "Booking timestamp", ("IN-09", "value_date"): "Value date",
    ("IN-10", "posted_ts"): "Cash-book posting timestamp",
    ("IN-11", "auth_ts"): "Card authorisation timestamp", ("IN-11", "clearing_date"): "Clearing date",
    ("IN-11", "executed_ts"): "Transaction execution timestamp",
    ("IN-12", "cycle_date"): "Settlement cycle date", ("IN-12", "settlement_date"): "Settlement date",
    ("IN-14", "logged_ts"): "Discrepancy logged timestamp", ("IN-14", "resolved_ts"): "Discrepancy resolved timestamp",
}
PDF_DATE_ROLES = {"Letter date": "Letter issue date", "Effective date": "Policy effective date",
                  "Allocated from": "Responsibility allocated from", "Period": "Return period",
                  "Due date": "Return due date", "Submitted at": "Return submission timestamp"}

# Dates that describe the record rather than period activity (account open/close; IN-04 follows its own open-during rule).
NOT_PERIOD_DATED = {"IN-02", "IN-04"}
REQUIRED_IDS = [fid for fid in schema.CSV_FILES] + [fid for fid, v in schema.PDF_FILES.items() if v[2] == "REQUIRED"]
OPTIONAL_IDS = [fid for fid, v in schema.PDF_FILES.items() if v[2] == "OPTIONAL"]
# Documents that legitimately recur unchanged from month to month (standing data and standing documents).
RECURRING_IDS = {"IN-02", "IN-15", "IN-16", "IN-17", "IN-18"}


def period_id(year, month):
    return f"PER-{year:04d}-{month:02d}"


def parse_period(pid):
    m = re.fullmatch(r"PER-(\d{4})-(\d{2})", pid or "")
    if not m or not 1 <= int(m.group(2)) <= 12 or not 2000 <= int(m.group(1)) <= 2100:
        raise ValueError(f"invalid period id {pid!r} (expected PER-YYYY-MM)")
    return int(m.group(1)), int(m.group(2))


def month_bounds(year, month):
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def previous_month_end(year, month):
    return date(year, month, 1) - timedelta(days=1)


def evidence_label(fid, period_id=None):
    """The evidence type's description; with a period, as it applies to that month (IN-19 names the previous month)."""
    if period_id:
        cfg = PeriodConfig.from_id(period_id)
        return (cfg.csv_files.get(fid) or cfg.pdf_files.get(fid))[1]
    return (schema.CSV_FILES.get(fid) or schema.PDF_FILES.get(fid))[1]


def _msg(code, level, text, **extra):
    return dict(code=code, level=level, message=text, **extra)


def _local_date(ftype, value):
    return parse_ts(value).astimezone(TZ).date() if ftype == "ts" else date.fromisoformat(value)


def _governing(fid):
    rule = schema.PERIOD_RULES.get(fid, {})
    return rule.get("in_period", []), rule


def _boundary(fid, row, year, month):
    """The engine's permitted boundary records, moved to the selected month: the opening position at the previous
    month-end 17:00 point (client snapshot IN-03; cash-book OPENING_BALANCE IN-10). Reported, never an error."""
    prev = previous_month_end(year, month)
    if fid == "IN-03":
        return row.get("recon_date") == prev.isoformat()
    if fid == "IN-10":
        return row.get("entry_type") == "OPENING_BALANCE" and _safe_date("ts", row.get("posted_ts", "")) == prev
    return False


def _safe_date(ftype, value):
    try:
        return _local_date(ftype, value)
    except (ValueError, TypeError):
        return None


def analyse_csv(fid, rows, year, month):
    """Date analysis, record count and key repetition for one identified CSV."""
    start, end = month_bounds(year, month)
    types = schema.coltypes(fid)
    mandatory = set(schema.mandatory(fid))
    governing, rule = _governing(fid)
    messages, dates = [], {}
    for col, ftype in types.items():
        if ftype not in ("date", "ts"):
            continue
        values, invalid, missing, outside = [], 0, 0, 0
        for r in rows:
            raw = (r.get(col) or "").strip()
            if not raw:
                missing += col in mandatory
                continue
            if field_error(ftype, raw):
                invalid += 1
                continue
            d = _local_date(ftype, raw)
            values.append(d)
            outside += not (start <= d <= end) and not _boundary(fid, r, year, month)
        dates[col] = {"role": DATE_ROLES.get((fid, col), col), "type": "timestamp" if ftype == "ts" else "date",
                      "governing": col in governing, "from": min(values).isoformat() if values else None,
                      "to": max(values).isoformat() if values else None, "invalid": invalid, "missing": missing,
                      "outside_month": outside}
        role = dates[col]["role"]
        if invalid:
            messages.append(_msg("INVALID_DATE", "WARNING", f"{invalid} row(s) with an invalid {role.lower()} ({col}); the engine "
                                 "excludes those rows", column=col, count=invalid))
        if missing:
            messages.append(_msg("MISSING_DATE", "WARNING", f"{missing} row(s) without the mandatory {role.lower()} ({col})",
                                 column=col, count=missing))

    # Period membership, judged on the governing column(s) only.
    in_month = out_month = boundary = 0
    out_examples = []
    if governing:
        for r in rows:
            ds = [_safe_date(types[c], (r.get(c) or "").strip()) for c in governing]
            ds = [d for d in ds if d]
            if not ds:
                continue
            if all(start <= d <= end for d in ds):
                in_month += 1
            elif _boundary(fid, r, year, month):
                boundary += 1
            else:
                out_month += 1
                if len(out_examples) < 5:
                    out_examples.append({"line": r.get("_line"), "dates": {c: r.get(c) for c in governing}})
    elif "open_during_period" in rule:  # IN-04: open at some point in the month (received <= end, not allocated before start)
        for r in rows:
            rec = _safe_date("date", r.get("receipt_date", ""))
            alloc = _safe_date("date", r.get("allocated_date", "")) if r.get("allocated_date") else None
            if rec is None:
                continue
            if rec <= end and (alloc is None or alloc >= start):
                in_month += 1
            else:
                out_month += 1
                if len(out_examples) < 5:
                    out_examples.append({"line": r.get("_line"), "dates": {"receipt_date": r.get("receipt_date"),
                                                                           "allocated_date": r.get("allocated_date")}})
    period = {"basis": ", ".join(DATE_ROLES.get((fid, c), c) for c in governing) if governing else
              ("Receipt open during the month (received on or before month end, not allocated before month start)"
               if "open_during_period" in rule else
               "Follows the reconciliation record it refers to (judged when the period is processed)" if "event_ref" in rule else
               "Standing data: not period-dated"),
              "in_month": in_month, "outside_month": out_month, "boundary_records": boundary, "examples": out_examples}
    if fid == "IN-01":
        pid = period_id(year, month)
        wrong = sorted({r.get("period_id", "") for r in rows} - {pid})
        if wrong:
            messages.append(_msg("WRONG_PERIOD", "ERROR", f"the calendar is for {', '.join(wrong)}, not {pid}"))
        else:  # compared with the month's England and Wales calendar; the supplied calendar stays the record
            for level, code, text in PeriodConfig(year, month).calendar_findings(rows):
                if code != "OUTSIDE_PERIOD":  # already reported by the period checks
                    messages.append(_msg(f"CALENDAR_{code}", "WARNING" if level == "ERROR" else level, text))
    if rows and (governing or "open_during_period" in rule):
        if in_month == 0 and out_month:
            messages.append(_msg("WRONG_PERIOD", "ERROR", f"no record falls in the selected month on {period['basis'].lower()}; "
                                 f"the document appears to belong to another period (records are never moved between months)"))
        elif out_month:
            messages.append(_msg("OUT_OF_PERIOD_RECORDS", "WARNING", f"{out_month} record(s) fall outside the selected month on "
                                 f"{period['basis'].lower()}; they stay in this document and the engine excludes and reports them",
                                 count=out_month))
    if boundary:
        messages.append(_msg("BOUNDARY_RECORDS", "INFO", f"{boundary} opening-position record(s) at the previous month-end "
                             "reconciliation point (permitted boundary records)", count=boundary))
    for col, info in dates.items():
        if not info["governing"] and info["outside_month"] and fid not in NOT_PERIOD_DATED:
            messages.append(_msg("TIMING_DIFFERENCE", "INFO", f"{info['outside_month']} {info['role'].lower()} value(s) outside the "
                                 f"month ({col}); this date does not decide the period, so this is a timing difference, not an error",
                                 column=col, count=info["outside_month"]))

    # Repeated business keys inside the document (first column is the record key, uc042lib.schema).
    key = schema.columns(fid)[0]
    seen, repeated = set(), {}
    for r in rows:
        k = (r.get(key) or "").strip()
        if k in seen:
            repeated[k] = repeated.get(k, 1) + 1
        seen.add(k)
    if repeated:
        messages.append(_msg("REPEATED_RECORD_ID", "WARNING", f"{len(repeated)} {key} value(s) appear more than once in this "
                             f"document (e.g. {', '.join(sorted(repeated)[:3])}); nothing is removed", column=key,
                             count=len(repeated)))
    if not rows:
        level = "INFO" if fid in schema.EMPTY_ALLOWED else "ERROR"
        messages.append(_msg("NO_RECORDS", level, "the file has a valid header but no data rows" +
                             (" (allowed for this evidence type)" if level == "INFO" else "")))
    # Detected date range: the governing column(s); otherwise every date the document carries (except standing data).
    ranged = [i for i in dates.values() if i["governing"]] or ([] if fid in ("IN-02",) else list(dates.values()))
    all_dates = [d for info in ranged for d in (info["from"], info["to"]) if d]
    return {"dates": dates, "period": period, "messages": messages, "key_column": key,
            "date_from": min(all_dates) if all_dates else None, "date_to": max(all_dates) if all_dates else None}


def analyse_pdf(fid, details, year, month):
    messages, dates = [], {}
    for label, role in PDF_DATE_ROLES.items():
        if label in details:
            dates[label] = {"role": role, "value": details[label]}
    if fid == "IN-19":  # the monthly return receipt is for the PREVIOUS month
        prev = previous_month_end(year, month)
        expected = f"{prev.year:04d}-{prev.month:02d}"
        if details.get("Period") != expected:
            messages.append(_msg("WRONG_PERIOD", "WARNING", f"the return receipt is for {details.get('Period') or 'an unknown period'}; "
                                 f"for {period_id(year, month)} the previous month's return ({expected}) is expected"))
    messages.append(_msg("PDF_STORED_AS_ORIGINAL", "INFO", "stored as an original with its key details; PDF content is not "
                         "read by the AI investigation"))
    return {"dates": dates, "messages": messages, "key_details": details}


def analyse_policy(path, details, year, month):
    """A policy PDF (IN-17) is used only as a recognised synthetic version that applies to the month (uc042lib.policy).
    Returns (policy info for the document's checks, messages). An unsupported or non-applicable policy is an ERROR
    document: it is kept, never processed."""
    version, problems = policy.recognise(details, policy.document_text(path))
    if problems:
        return {"version": version, "recognised": False}, [_msg("POLICY_NOT_RECOGNISED", "ERROR", "not used as a policy: "
                                                                + "; ".join(problems))]
    reg, period = policy.POLICY_VERSIONS[version], PeriodConfig(year, month)
    applies, why = policy.applicability(version, period)
    info = {"version": version, "recognised": True, "classification": reg.classification, "effective": str(reg.effective),
            "applies": applies, "applicability": why}
    if not applies:
        return info, [_msg("POLICY_NOT_APPLICABLE", "ERROR", f"{why}; it does not govern this month and is not used")]
    msgs = [_msg("POLICY_VERSION", "INFO", f"{why} ({reg.classification})")]
    if reg.classification == "ILLUSTRATIVE_SYNTHETIC":
        msgs.append(_msg("ILLUSTRATIVE_SYNTHETIC_POLICY", "INFO", "illustrative synthetic document (decision "
                         f"{reg.decision}); not an actual or historical Moorwand policy"))
    approved = policy.APPROVED_SELECTIONS.get(period.period_id)
    if approved is not None:
        info["approved_selection"] = approved.version
        msgs.append(_msg("POLICY_SELECTED" if approved.version == version else "POLICY_SUPPLIED_NOT_SELECTED", "INFO",
                         f"{period.period_id}: approved selection {approved.decision} is v{approved.version}; "
                         + ("this document governs reconciliation" if approved.version == version else
                            "this document is kept in the source inventory and not used for reconciliation")))
    return info, msgs


def analyse_file(path, original_filename, year, month):
    """Identify and analyse one uploaded file. Returns the document fields (without IDs, storage or duplicates)."""
    path = Path(path)
    size = path.stat().st_size
    base = {"original_filename": original_filename, "size_bytes": size, "evidence_id": None, "category": None,
            "file_format": "OTHER", "record_count": None, "date_from": None, "date_to": None, "slot_candidates": []}
    if size == 0:
        return dict(base, checks={"messages": [_msg("EMPTY_FILE", "ERROR", "the file is empty")]})
    kind, value, info = identify(path)
    if kind == "REJECT":
        reason = value["message"] if isinstance(value, dict) else value
        fmt = "PDF" if path.read_bytes()[:5] == b"%PDF-" else ("CSV" if original_filename.lower().endswith(".csv") else "OTHER")
        checks = {"messages": [_msg("UNRECOGNISED", "ERROR", f"not a supported evidence file: {reason}")]}
        if isinstance(value, dict):
            checks["header_diagnosis"] = {k: value.get(k) for k in ("file_id", "candidates", "missing", "extra", "misordered",
                                                                     "case_or_spacing")}
        return dict(base, file_format=fmt, checks=checks)
    if kind == "CSV":
        a = analyse_csv(value, info, year, month)
        return dict(base, evidence_id=value, category=evidence_label(value, period_id(year, month)), file_format="CSV", record_count=len(info),
                    date_from=a["date_from"], date_to=a["date_to"],
                    checks={"messages": a["messages"], "dates": a["dates"], "period": a["period"], "key_column": a["key_column"],
                            "identified_by": "CSV header"})
    details, pages = info
    fid = value[0] if len(value) == 1 else None
    a = analyse_pdf(fid, details, year, month)
    if fid == "IN-17":
        info, msgs = analyse_policy(path, details, year, month)
        a["messages"][:0] = msgs
        a["policy"] = info
    out = dict(base, evidence_id=fid, category=evidence_label(fid, period_id(year, month)) if fid else "Acknowledgement letter (account to be matched)",
               file_format="PDF", record_count=pages, slot_candidates=value,
               checks={"messages": a["messages"], "dates": a["dates"], "key_details": details, "identified_by": "PDF key details"})
    if "policy" in a:
        out["checks"]["policy"] = a["policy"]
    return out


def policy_version(doc):
    """The policy version of an IN-17 document (its analysis, else its key details), or None."""
    if doc.get("evidence_id") != "IN-17":
        return None
    checks = doc.get("checks") or {}
    return (checks.get("policy") or {}).get("version") or (checks.get("key_details") or {}).get("Document version") or None


def slot(doc):
    """The evidence slot of a document: its evidence type, and for policies its version (several policy versions may be
    supplied for one month; each version is its own slot)."""
    v = policy_version(doc)
    return f"IN-17@v{v}" if v else doc.get("evidence_id")


def status_of(messages):
    levels = {m["level"] for m in messages}
    return "ERROR" if "ERROR" in levels else "WARNING" if "WARNING" in levels else "VALID"


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")
