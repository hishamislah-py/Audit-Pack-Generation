"""23 Nov 2026 (owner): the reporting period is worked out from the submission itself; the analyst only names the customer.
Calendar first (the dates being reconciled), then the period written in the file names; refused when neither shows one."""
import io
import zipfile

import pytest

from smartparser.webapp.cases import CaseError, detect_period

from .test_ringfence_cases import ctx_for, make_zip


def zip_of(files):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return b.getvalue()


def test_calendar_decides_even_with_unhelpful_names():
    data = zip_of({"Pack/01_reconciliation_calendar.csv": "calendar_date,period_id\n2026-06-01,P\n2026-06-02,P\n2026-05-29,P\n",
                   "Pack/other.csv": "a,b\n1,2\n"})
    assert detect_period(data) == {"period": "2026-06", "basis": "reconciliation calendar (01_reconciliation_calendar.csv)"}


def test_file_names_when_there_is_no_calendar():
    data = zip_of({"transactions_2026-10.csv": "a\n1\n", "bank_2026-10.csv": "a\n1\n", "governance_register_Oct2026.pdf": b"%PDF-"})
    assert detect_period(data) == {"period": "2026-10", "basis": "file names"}


def test_nothing_to_go_on_is_none():
    assert detect_period(zip_of({"a.csv": "x\n1\n"})) is None
    assert detect_period(b"not a zip") is None


def test_register_without_a_period_uses_the_detected_one(tmp_path):
    ctx = ctx_for(tmp_path)
    c = ctx.cases.create("Harbourline Payments Ltd", "", "submission.zip", make_zip())
    assert c["reporting_period"] == "2026-09" and c["case_ref"].startswith("RF-2026-09-")
    ev = [e for e in ctx.events() if e["event_type"] == "CASE_CREATED"][-1]
    assert ev["details"]["reporting_period_detected_from"].startswith(("reconciliation calendar", "file names"))


def test_register_refuses_when_the_period_cannot_be_read(tmp_path):
    ctx = ctx_for(tmp_path)
    with pytest.raises(CaseError) as e:
        ctx.cases.create("X Ltd", "", "s.zip", zip_of({"a.csv": "x\n1\n"}))
    assert "PERIOD_NOT_DETECTED" in repr(e.value.args) + repr(vars(e.value))


def test_an_explicit_period_still_wins(tmp_path):
    ctx = ctx_for(tmp_path)
    assert ctx.cases.create("Harbourline Payments Ltd", "2026-08", "submission.zip", make_zip())["reporting_period"] == "2026-08"
