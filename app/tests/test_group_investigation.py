"""One AI investigation per engine investigation group (owner, 24 Nov 2026): the lead is the causing exception (duplicate /
unmatched entry / transaction against bank), else the engine's primary exception; it covers the group's other exceptions."""
import os

from smartparser.webapp import closure as C


def svc_with(pack):
    s = C.ClosureService.__new__(C.ClosureService)
    s._pack = lambda c: pack
    return s


def pack_of(excs, groups):
    return {"exception_register": {"exceptions": [{"exception_id": e, "root_cause": rc} for e, rc in excs]},
            "investigation_group_register": {"groups": groups}}


HALDEN = pack_of(
    [("EXC-CASE-01", "BANK_LEDGER_DIFFERENCE|SGA-EUR-01|2026-09-30|1275.40"),
     ("EXC-CASE-02", "BANK_LEDGER_DIFFERENCE|SGA-GBP-01|2026-09-30|-1684.33"),
     ("EXC-CASE-03", "INTERNAL_DIFFERENCE|2026-09-30/GBP"), ("EXC-CASE-04", "C05-RESOURCE|2026-09-30/GBP"),
     ("EXC-CASE-05", "DUPLICATE_CASHBOOK_ENTRY|LE-GBP-0930-0007"), ("EXC-CASE-06", "RC2-LEDGER|2026-09-30/SGA-GBP-01"),
     ("EXC-CASE-07", "UNMATCHED_BANK_ENTRY|BE-EUR-0930-U01"), ("EXC-CASE-08", "C11-BATCH-ARITH|AQ-EUR-20260922")],
    [{"group_id": "GRP-CASE-01", "exception_ids": "EXC-CASE-01; EXC-CASE-07", "primary_exception_id": "EXC-CASE-01"},
     {"group_id": "GRP-CASE-02", "exception_ids": "EXC-CASE-02; EXC-CASE-03; EXC-CASE-04; EXC-CASE-05; EXC-CASE-06",
      "primary_exception_id": "EXC-CASE-02"}])


def test_lead_is_the_cause_not_the_engine_primary():
    groups = svc_with(HALDEN)._build_ai_groups({})
    assert groups == [
        {"group_id": "GRP-CASE-01", "lead_exception_id": "EXC-CASE-07", "covers": ["EXC-CASE-01"]},
        {"group_id": "GRP-CASE-02", "lead_exception_id": "EXC-CASE-05",
         "covers": ["EXC-CASE-02", "EXC-CASE-03", "EXC-CASE-04", "EXC-CASE-06"]}]
    cover = C.ClosureService._cover({"ai_groups": groups})
    assert "EXC-CASE-08" not in cover and "EXC-CASE-05" not in cover and cover["EXC-CASE-06"] == "EXC-CASE-05"
    # ungrouped + leads are investigated: 3 AI calls instead of 8
    assert [e for e, _ in [(x["exception_id"], 0) for x in HALDEN["exception_register"]["exceptions"]] if e not in cover] == \
        ["EXC-CASE-05", "EXC-CASE-07", "EXC-CASE-08"]


def test_no_cause_falls_back_to_engine_primary_and_singletons_are_ignored():
    p = pack_of([("EXC-CASE-01", "INTERNAL_DIFFERENCE|2026-09-17/GBP"), ("EXC-CASE-02", "CBAL-ROLLFWD|GBP/C0004 2026-09-17"),
                 ("EXC-CASE-03", "C11-BATCH-ARITH|X")],
                [{"group_id": "G1", "exception_ids": "EXC-CASE-01; EXC-CASE-02", "primary_exception_id": "EXC-CASE-02"},
                 {"group_id": "G2", "exception_ids": "EXC-CASE-03", "primary_exception_id": "EXC-CASE-03"}])
    assert svc_with(p)._build_ai_groups({}) == [{"group_id": "G1", "lead_exception_id": "EXC-CASE-02", "covers": ["EXC-CASE-01"]}]


def test_switch_defaults_on_and_can_be_turned_off(monkeypatch):
    monkeypatch.delenv("RINGFENCE_AI_GROUP_INVESTIGATION", raising=False)
    assert C.ai_group_investigation() is True
    monkeypatch.setenv("RINGFENCE_AI_GROUP_INVESTIGATION", "off")
    assert C.ai_group_investigation() is False
    assert os.environ["RINGFENCE_AI_GROUP_INVESTIGATION"] == "off"
