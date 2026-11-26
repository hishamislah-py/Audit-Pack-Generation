"""Reporting period configuration (one immutable value per month) and the England and Wales calendar.

The engine processes exactly one reporting period per case. Everything that depends on the month is derived here from
`PeriodConfig(year, month)`: the period identifier, first and last calendar day, the previous month (its last day is the
opening-position boundary, its identifier is the monthly-return period), the canonical source-file names, the reporting
period rules (uc042lib.schema.PERIOD_RULES with the month's own values) and the expected reconciliation calendar.

Nothing here holds mutable state; two periods can be processed in the same process without interfering.

Calendar: dates are judged as Europe/London calendar dates (zoneinfo, so British Summer Time is applied per instant,
never as a fixed +01:00). Bank holidays are the England and Wales rules (New Year's Day, Good Friday, Easter Monday,
early May, spring and summer bank holidays, Christmas Day and Boxing Day, each moved to the next weekday when it falls on
a weekend). One-off proclaimed holidays are not modelled; the supplied reconciliation calendar (IN-01) stays the record
of which days were reconciliation days.
"""
import calendar
import csv
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from . import schema

TZ_NAME = schema.TZ  # "Europe/London"
LONDON = ZoneInfo(TZ_NAME)
PERIOD_ID_RE = re.compile(r"^PER-(\d{4})-(\d{2})$")
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
               "November", "December"]
# Opening positions are taken at the reconciliation point of the previous month's last day (decision D4). The policy
# (IN-17) states the point for each period; 17:00 is the point the opening boundary records are expected at.
OPENING_POINT = time(17, 0)
# The reconciliation policy (IN-17) is a versioned standing document. The baseline period uses v1.2; another version is
# used only when the case supplies exactly that version or the caller selects it (PeriodConfig.policy_version, resolve).
DEFAULT_POLICY_VERSION = "1.2"
POLICY_VERSION_RE = re.compile(r"^\d+\.\d+$")
POLICY_FILE_RE = re.compile(r"^safeguarding_reconciliation_policy_v(\d+\.\d+)\.pdf$")

# Canonical file names. {period} is the reporting month (YYYY-MM); {previous} the month before it; {policy} the policy
# version. Standing documents (account inventory, acknowledgement letters, policy) carry no month.
# uc042lib.schema.CSV_FILES / PDF_FILES hold the same names resolved for the baseline period (September 2026, policy v1.2).
FILE_PATTERNS = {
    "IN-01": "recon_calendar_{period}.csv",
    "IN-02": "account_inventory.csv",
    "IN-03": "client_balance_snapshots_{period}.csv",
    "IN-04": "unallocated_register_{period}.csv",
    "IN-05": "internal_recon_records_{period}.csv",
    "IN-06": "external_recon_records_{period}.csv",
    "IN-07": "bank_balance_confirmations_{period}.csv",
    "IN-08": "bank_statements_eod_{period}.csv",
    "IN-09": "bank_statement_entries_{period}.csv",
    "IN-10": "sga_cashbook_entries_{period}.csv",
    "IN-11": "transactions_{period}.csv",
    "IN-12": "settlement_batches_{period}.csv",
    "IN-13": "settlement_lines_{period}.csv",
    "IN-14": "discrepancy_log_{period}.csv",
    "IN-15": "ack_letter_SGA-GBP-01.pdf",
    "IN-16": "ack_letter_SGA-EUR-01.pdf",
    "IN-17": "safeguarding_reconciliation_policy_v{policy}.pdf",
    "IN-18": "governance_register_{period}.pdf",
    "IN-19": "rep027_submission_receipt_{previous}.pdf",
}
MONTH_TOKEN = re.compile(r"_(\d{4}-\d{2})\.(?:csv|pdf)$")


class PeriodError(ValueError):
    """The reporting period is invalid, cannot be determined, or does not match the case."""


# --------------------------------------------------------------------------------------- England and Wales calendar
def _easter_sunday(year):
    """Gregorian Easter (anonymous algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = ((h + l_ - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _first_monday(year, month):
    d = date(year, month, 1)
    return d + timedelta(days=(7 - d.weekday()) % 7)


def _last_monday(year, month):
    d = date(year, month, calendar.monthrange(year, month)[1])
    return d - timedelta(days=d.weekday())


@lru_cache(maxsize=None)
def bank_holidays(year):
    """England and Wales bank holidays of a year (frozenset of dates), with weekend substitution."""
    out = set()
    ny = date(year, 1, 1)
    out.add(ny + timedelta(days={5: 2, 6: 1}.get(ny.weekday(), 0)))
    easter = _easter_sunday(year)
    out |= {easter - timedelta(days=2), easter + timedelta(days=1)}
    out |= {_first_monday(year, 5), _last_monday(year, 5), _last_monday(year, 8)}
    xmas, boxing = date(year, 12, 25), date(year, 12, 26)
    if xmas.weekday() == 5:      # Saturday: Christmas -> Mon 27, Boxing Day -> Tue 28
        out |= {date(year, 12, 27), date(year, 12, 28)}
    elif xmas.weekday() == 6:    # Sunday: Christmas -> Tue 27, Boxing Day Mon 26
        out |= {date(year, 12, 26), date(year, 12, 27)}
    elif boxing.weekday() == 5:  # Friday Christmas, Saturday Boxing Day -> Mon 28
        out |= {xmas, date(year, 12, 28)}
    else:
        out |= {xmas, boxing}
    return frozenset(out)


def is_business_day(d):
    return d.weekday() < 5 and d not in bank_holidays(d.year)


def business_day_after(d, n=1):
    """The n-th England and Wales business day after d."""
    while n:
        d += timedelta(days=1)
        if is_business_day(d):
            n -= 1
    return d


def london_offset(d, at=OPENING_POINT):
    """UTC offset of Europe/London at a local date and time, e.g. '+01:00' in summer, '+00:00' in winter."""
    off = datetime.combine(d, at, tzinfo=LONDON).utcoffset()
    sign = "-" if off < timedelta(0) else "+"
    minutes = abs(int(off.total_seconds())) // 60
    return f"{sign}{minutes // 60:02d}:{minutes % 60:02d}"


# ----------------------------------------------------------------------------------------------- the period itself
@dataclass(frozen=True)
class PeriodConfig:
    year: int
    month: int
    # Version of the reconciliation policy document (IN-17) used for this run; None: the version the case supplies
    # (resolve), else DEFAULT_POLICY_VERSION. A document selection, not part of the period's identity (compare=False).
    policy_version: str = field(default=None, compare=False)

    def __post_init__(self):
        if not isinstance(self.year, int) or not isinstance(self.month, int) or not 1 <= self.month <= 12 \
                or not 2000 <= self.year <= 2100:
            raise PeriodError(f"invalid reporting period {self.year!r}-{self.month!r}")
        if self.policy_version is not None and not POLICY_VERSION_RE.match(str(self.policy_version)):
            raise PeriodError(f"invalid policy version {self.policy_version!r} (expected N.N)")

    # -- construction --------------------------------------------------------------------------------------------
    @classmethod
    def from_id(cls, period_id, policy_version=None):
        m = PERIOD_ID_RE.match(str(period_id or ""))
        if not m:
            raise PeriodError(f"invalid period id {period_id!r} (expected PER-YYYY-MM)")
        return cls(int(m.group(1)), int(m.group(2)), policy_version)

    @property
    def policy(self):
        """The policy version whose document (IN-17) this run reads."""
        return self.policy_version or DEFAULT_POLICY_VERSION

    # -- identity and range --------------------------------------------------------------------------------------
    @property
    def period_id(self):
        return f"PER-{self.year:04d}-{self.month:02d}"

    @property
    def token(self):
        """The month as used in file names: YYYY-MM."""
        return f"{self.year:04d}-{self.month:02d}"

    @property
    def start(self):
        return date(self.year, self.month, 1)

    @property
    def end(self):
        return date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])

    @property
    def days(self):
        return (self.end - self.start).days + 1

    @property
    def month_name(self):
        return MONTH_NAMES[self.month - 1]

    @property
    def label(self):
        return f"{self.month_name} {self.year}"

    @property
    def timezone(self):
        return TZ_NAME

    def dates(self):
        return [self.start + timedelta(days=i) for i in range(self.days)]

    def contains(self, d):
        return self.start <= d <= self.end

    # -- neighbours ----------------------------------------------------------------------------------------------
    @property
    def previous(self):
        return PeriodConfig(self.year - 1, 12) if self.month == 1 else PeriodConfig(self.year, self.month - 1)

    @property
    def next(self):
        return PeriodConfig(self.year + 1, 1) if self.month == 12 else PeriodConfig(self.year, self.month + 1)

    @property
    def previous_end(self):
        """The previous month's last day: the date of the opening-position boundary records."""
        return self.start - timedelta(days=1)

    def opening_point(self):
        """The opening-position instant: the previous month-end reconciliation point, Europe/London (DST-aware)."""
        return datetime.combine(self.previous_end, OPENING_POINT, tzinfo=LONDON)

    def opening_point_iso(self):
        return f"{self.previous_end.isoformat()}T{OPENING_POINT:%H:%M:%S}{london_offset(self.previous_end)}"

    # -- source documents ----------------------------------------------------------------------------------------
    def filename(self, fid):
        return FILE_PATTERNS[fid].format(period=self.token, previous=self.previous.token, policy=self.policy)

    @property
    def csv_files(self):
        """Same shape as uc042lib.schema.CSV_FILES, with this period's file names."""
        return {fid: (self.filename(fid), desc, cols) for fid, (_, desc, cols) in schema.CSV_FILES.items()}

    @property
    def pdf_files(self):
        """Same shape as uc042lib.schema.PDF_FILES, with this period's file names (IN-19 is the previous month's return)."""
        out = {}
        for fid, (_, desc, req, labels) in schema.PDF_FILES.items():
            if fid == "IN-19":
                desc = f"Monthly safeguarding return receipt ({self.previous.month_name})"
            elif fid == "IN-17":
                desc = f"Safeguarding reconciliation policy v{self.policy}"
            out[fid] = (self.filename(fid), desc, req, labels)
        return out

    def requirement(self, fid):
        """REQUIRED or OPTIONAL (the upload contract; no category is added or removed per month)."""
        return "REQUIRED" if fid in schema.CSV_FILES else schema.PDF_FILES[fid][2]

    @property
    def required_ids(self):
        return [fid for fid in list(schema.CSV_FILES) + list(schema.PDF_FILES) if self.requirement(fid) == "REQUIRED"]

    @property
    def optional_ids(self):
        return [fid for fid in schema.PDF_FILES if self.requirement(fid) == "OPTIONAL"]

    def file_id_of(self, name):
        """The evidence ID whose canonical name (for this period) is `name`, or None."""
        return next((fid for fid in FILE_PATTERNS if self.filename(fid) == name), None)

    # -- reporting-period rules ----------------------------------------------------------------------------------
    @property
    def period_rules(self):
        """uc042lib.schema.PERIOD_RULES with this period's values: the calendar must carry this period's ID, and the
        permitted boundary records are the opening positions at the previous month-end point."""
        point = self.opening_point_iso()
        rules = {fid: dict(rule) for fid, rule in schema.PERIOD_RULES.items()}
        rules["IN-01"]["equals"] = {"period_id": self.period_id}
        rules["IN-03"]["permitted"] = [{"recon_date": self.previous_end.isoformat(), "as_at_ts": point}]
        rules["IN-10"]["permitted"] = [{"entry_type": "OPENING_BALANCE", "posted_ts": point}]
        return rules

    # -- calendar ------------------------------------------------------------------------------------------------
    def expected_calendar(self):
        """[(date, is_business_day, reason)] for every day of the month (reason: WEEKEND / UK_BANK_HOLIDAY / '')."""
        out = []
        for d in self.dates():
            reason = "WEEKEND" if d.weekday() >= 5 else "UK_BANK_HOLIDAY" if d in bank_holidays(d.year) else ""
            out.append((d, not reason, reason))
        return out

    def calendar_findings(self, rows):
        """Compare a supplied reconciliation calendar (IN-01 rows) with the month: missing or duplicate dates, dates
        outside the month, and reconciliation days that fall on a weekend or bank holiday. A business day marked as a
        non-reconciliation day (for example FOREIGN_MARKET_CLOSED) is reported for information only."""
        findings, seen = [], {}
        expected = {d: (bd, reason) for d, bd, reason in self.expected_calendar()}
        for r in rows:
            try:
                d = date.fromisoformat(r.get("calendar_date", ""))
            except ValueError:
                findings.append(("ERROR", "INVALID_DATE", f"invalid calendar date {r.get('calendar_date')!r}"))
                continue
            if d not in expected:
                findings.append(("ERROR", "OUTSIDE_PERIOD", f"{d} is not in {self.label}"))
                continue
            if d in seen:
                findings.append(("ERROR", "DUPLICATE_DATE", f"{d} appears more than once"))
            seen[d] = r
            bd, reason = expected[d]
            if r.get("is_recon_day") == "true" and not bd:
                findings.append(("WARNING", "RECON_ON_NON_BUSINESS_DAY", f"{d} is marked as a reconciliation day but is a "
                                 f"{'weekend' if reason == 'WEEKEND' else 'bank holiday'}"))
            elif r.get("is_recon_day") == "false" and bd:
                findings.append(("INFO", "BUSINESS_DAY_NOT_RECONCILED", f"{d} is a business day marked as a non-reconciliation "
                                 f"day ({r.get('non_recon_reason') or 'no reason'})"))
        for d in expected:
            if d not in seen:
                findings.append(("ERROR", "MISSING_DATE", f"{d} is missing from the calendar"))
        return findings


BASELINE = PeriodConfig(2026, 9)  # the established POC period (uc042lib.schema constants describe it)


# ------------------------------------------------------------------------------------------ period of a case folder
def _manifest_periods(case_dir):
    p = Path(case_dir) / "manifest.csv"
    if not p.is_file():
        return set()
    with open(p, encoding="utf-8", newline="") as f:
        return {r.get("reporting_period", "") for r in csv.DictReader(f)} - {""}


def _name_periods(case_dir):
    out = set()
    for sub in ("source_data", "supporting_documents"):
        d = Path(case_dir) / sub
        if not d.is_dir():
            continue
        for p in d.iterdir():
            m = MONTH_TOKEN.search(p.name)
            if not m:
                continue
            prefix = p.name[:m.start()] + "_{period}" + p.name[m.end() - 4:]
            if prefix in FILE_PATTERNS.values():  # only month-of-period files; IN-19 names the previous month
                out.add("PER-" + m.group(1))
    return out


def _calendar_periods(case_dir):
    out = set()
    d = Path(case_dir) / "source_data"
    for p in (d.glob("recon_calendar_*.csv") if d.is_dir() else []):
        try:
            with open(p, encoding="utf-8-sig", newline="") as f:
                out |= {r.get("period_id", "") for r in csv.DictReader(f)} - {""}
        except (OSError, UnicodeDecodeError, csv.Error):
            continue
    return out


def policy_version_of(name):
    """The policy version in a canonical policy file name (…policy_v1.1.pdf -> '1.1'), else None."""
    m = POLICY_FILE_RE.match(Path(str(name)).name)
    return m.group(1) if m else None


def _supplied_policies(case_dir):
    """Policy versions the case supplies: its intake manifest's IN-17 rows, else the policy documents in the folder."""
    p = Path(case_dir) / "manifest.csv"
    if p.is_file():
        with open(p, encoding="utf-8", newline="") as f:
            versions = {policy_version_of(r.get("filename", "")) for r in csv.DictReader(f) if r.get("file_id") == "IN-17"} - {None}
        if versions:
            return versions
    d = Path(case_dir) / "supporting_documents"
    return {policy_version_of(x.name) for x in d.iterdir()} - {None} if d.is_dir() else set()


def _with_policy(case_dir, period):
    """The period with the policy version the case supplies, unless one was selected. A case that supplies more than one
    version needs an explicit selection: the engine never chooses between policy documents."""
    if period.policy_version is not None:
        return period
    supplied = _supplied_policies(case_dir)
    if len(supplied) > 1:
        raise PeriodError(f"the case supplies more than one reconciliation policy version ({', '.join(sorted(supplied))}); "
                          f"select the version that governs {period.period_id} explicitly")
    return replace(period, policy_version=next(iter(supplied))) if supplied else period


def resolve(case_dir, period=None):
    """The reporting period of a case.

    With `period` given (PeriodConfig or period id), it is checked against the case's intake manifest; a different
    period there raises PeriodError (periods are never mixed). Without `period`, the case must declare exactly one period (manifest, else file names, else the
    calendar's period_id); otherwise PeriodError: there is no default month. The policy version (IN-17) is the one the
    case supplies unless the period selects one (_with_policy)."""
    if period is not None and not isinstance(period, PeriodConfig):
        period = PeriodConfig.from_id(period)
    if period is not None:
        # The intake manifest is the case's own declaration: a different period there is a conflict. Canonical files of
        # another month are not a conflict here: the engine reports them and never uses them (Validator).
        manifest = _manifest_periods(case_dir)
        if manifest - {period.period_id}:
            raise PeriodError(f"the case was prepared for {', '.join(sorted(manifest))}, not {period.period_id}; periods are never mixed")
        return _with_policy(case_dir, period)
    declared = _manifest_periods(case_dir) or _name_periods(case_dir) or _calendar_periods(case_dir)
    if len(declared) == 1:
        return _with_policy(case_dir, PeriodConfig.from_id(next(iter(declared))))
    if not declared:
        raise PeriodError("the reporting period of this case cannot be determined; pass the period explicitly")
    raise PeriodError(f"the case mixes reporting periods: {', '.join(sorted(declared))}")
