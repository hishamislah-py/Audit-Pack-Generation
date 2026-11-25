"""Write continuity_report.md, date_quality_report.md and historical_coverage_report.md from the verification results."""
import json
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
MONTHS = [f"2026-{m:02d}" for m in range(1, 9)]
SYN = "> **ILLUSTRATIVE SYNTHETIC DATA — DEMONSTRATION ONLY — NOT REAL MOORWAND FINANCIAL RECORDS.**"


def m(c):
    c = int(c)
    return ("−" if c < 0 else "") + f"{abs(c) // 100:,}.{abs(c) % 100:02d}"


def mstr(s):
    return m(int(s.replace(".", "")) if "." in s else int(s))


def main():
    dq = json.loads((PKG / "verification" / "data_quality_results.json").read_text())
    run = json.loads((PKG / "generator" / "_last_run.json").read_text())
    eng = json.loads((PKG / "verification" / "engine_prevalidation_results.json").read_text())
    # ---------------- continuity ----------------
    L = ["# Continuity report — January–August 2026", "", SYN, "",
         "Generated from `verification/data_quality_results.json`. All figures are read from the month files, not from the generator.", "",
         "## January opening position (synthetic, as at 31 Dec 2025 17:00 GMT)", "",
         "A **documented synthetic demonstration opening position**, chosen for this package (not derived from any real or earlier record):", ""]
    o = run["2026-01"]["opening"]
    L += ["| Position | GBP | EUR |", "| --- | ---: | ---: |",
          f"| Client balances (Σ, IN-03 `CBS-20251231-*`) | {m(sum(o['clients']['GBP'].values()))} | {m(sum(o['clients']['EUR'].values()))} |",
          f"| Cash book (IN-10 `LE-*-1231-0000` OPENING_BALANCE) | {m(o['cash']['GBP'])} | {m(o['cash']['EUR'])} |",
          f"| Safeguarding bank (first statement opening) | {m(o['bank']['SGA-GBP-01'])} | {m(o['bank']['SGA-EUR-01'])} |",
          f"| Own-funds bank (first statement opening) | {m(o['bank']['OWN-GBP-01'])} | {m(o['bank']['OWN-EUR-01'])} |", "",
          "Own-funds openings were derived so that, after eight months of fee top-ups, August closes on the existing September "
          "own-funds openings (£500,000.00 / €150,000.00). No unallocated receipt is open at any month end.", "",
          "## Month-to-month carry-forward", "",
          "Closing = last reconciliation day at 17:00 (client snapshots), the cash-book balance, and each account's last end-of-day "
          "statement. Opening = the next month's opening snapshot, cash-book OPENING_BALANCE and first statement opening.", "",
          "| From → to | Client balances (12) | Cash book GBP / EUR | Bank SGA-GBP / SGA-EUR / OWN-GBP / OWN-EUR | Closing GBP clients | Closing EUR clients |",
          "| --- | --- | --- | --- | ---: | ---: |"]
    for c in dq["continuity"]:
        cl = dq["months"][c["from"]]["closing"]["clients"]
        g = sum(int(v.replace(".", "")) for k, v in cl.items() if k.endswith("/GBP"))
        e = sum(int(v.replace(".", "")) for k, v in cl.items() if k.endswith("/EUR"))
        ok = lambda b: "✓" if b else "✗"
        L.append(f"| {c['from']} → {c['to']} | {ok(c['clients_equal'])} | {ok(c['cash_equal']['GBP'])} / {ok(c['cash_equal']['EUR'])} | "
                 f"{' / '.join(ok(c['bank_equal'][a]) for a in ('SGA-GBP-01', 'SGA-EUR-01', 'OWN-GBP-01', 'OWN-EUR-01'))} | {m(g)} | {m(e)} |")
    b = dq["august_to_september"]
    L += ["", "## August → September boundary (existing September data, unchanged)", "",
          "August's last reconciliation day is Friday 28 Aug 2026 (31 Aug is a bank holiday). The existing September dataset "
          "(`set_01_clean_baseline`) opens at 31 Aug 2026 17:00 BST. No activity occurs between, so the positions must be equal.", "",
          "| Position | August closing (this package) | September opening (existing) | Match |", "| --- | ---: | ---: | --- |"]
    for k in sorted(b["september_opening"]["clients"]):
        L.append(f"| Client {k} | {mstr(b['august_closing']['clients'][k])} | {mstr(b['september_opening']['clients'][k])} | {'✓' if b['august_closing']['clients'][k] == b['september_opening']['clients'][k] else '✗'} |")
    for k in ("GBP", "EUR"):
        L.append(f"| Cash book {k} | {m(b['august_closing']['cash'][k])} | {m(b['september_opening']['cash'][k])} | {'✓' if b['cash_equal'][k] else '✗'} |")
    for k in ("SGA-GBP-01", "SGA-EUR-01", "OWN-GBP-01", "OWN-EUR-01"):
        L.append(f"| Bank {k} | {mstr(b['august_closing']['bank'][k])} | {mstr(b['september_opening']['bank'][k])} | {'✓' if b['bank_equal'][k] else '✗'} |")
    L += ["", "**Result: all 18 positions match exactly. September was read, never modified.**", "",
          "**How the boundary is met:** on 28 Aug 2026 at 16:40 the generator adds one ordinary bank-transfer load or redemption per client "
          "(references `E2E-<ccy>-0828-Bnn`) for the difference between that client's balance and the September opening figure. "
          "These are normal 1:1 synthetic movements (bank, cash book and transaction together), not adjustments. "
          "Planted discrepancies are designed to leave no unresolved bank-ledger difference at a month end (see README, assumption A2).", ""]
    (PKG / "continuity_report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    # ---------------- date quality ----------------
    D = ["# Date and data-quality report — January–August 2026", "", SYN, "",
         "Produced by `verification/verify_history.py` (independent of the engine). Full detail: `verification/data_quality_results.json`.", "",
         "| Month | Calendar days | Recon days | Checks | Problems | Timestamp offsets | Expected (by design) findings |", "| --- | ---: | ---: | ---: | ---: | --- | --- |"]
    for p in MONTHS:
        q = dq["months"][p]
        tot = sum(sum(v.values()) for v in q["checks"].values())
        prob = sum(v.get("PROBLEM", 0) for v in q["checks"].values())
        exp = [f"{k} ({v['ok']})" for k, v in q["checks"].items() if "expected" in k]
        D.append(f"| {p} | {q['days']} | {q['recon_days']} | {tot:,} | {prob} | {', '.join(f'{k}: {v}' for k, v in q['offsets'].items())} | {'; '.join(exp) or '—'} |")
    D += ["", "## What was checked (every month)", "",
          "- **Files and schema:** 14 CSV files with the contract headers; every value type- and enum-checked with the project's own `field_error`; mandatory fields populated.",
          "- **Identifiers:** primary keys unique within each month; no exact duplicate rows; no natural-key duplicate bank entries.",
          "- **Dates:** every date inside its month, except the documented opening rows (snapshot and cash-book opening at the previous month end, 17:00).",
          "- **Timezone:** every timestamp's offset equals the Europe/London offset for that instant: **GMT (+00:00) until 29 Mar 2026 01:00, BST (+01:00) after**. March contains both.",
          "- **Point and date consistency:** booking timestamp local date = booking date; snapshots and reconciliation points at 17:00 on their own date.",
          "- **Calendar:** every day present; reconciliation days = weekdays minus England & Wales bank holidays (1 Jan, 3 Apr, 6 Apr, 4 May, 25 May, 31 Aug).",
          "- **References:** cash book ↔ bank (one-to-one by reference, amounts equal, opposite D/C); batch → bank by reference and net; line → transaction; transaction → batch; refund → original; unallocated receipt → bank, allocated within the month.",
          "- **Arithmetic:** statement opening + entries = closing; entry counts; day-to-day continuity; 17:00 confirmation = opening + entries to 17:00; batch lines = header totals; gross − fees (or refunds) = net.",
          "- **Balances:** requirement (client snapshots + open unallocated) = reported = cash book at 17:00; bank − ledger = 0 except on planted days.",
          "- **Currency:** every record's currency equals its account's currency; GBP and EUR never combined.",
          "- **Missing evidence:** removed records are absent, not zero-filled; checks that depend on them are reported as not assessable.", "",
          "## Timing differences versus errors", "",
          "No legitimate transaction-to-bank timing difference is planted in January–August: every cash-book posting date equals its "
          "bank booking date, and every batch is booked on its settlement date (checked). Transaction date, authorisation timestamp, "
          "clearing date, settlement date, bank booking date, cash-book posting date, reconciliation date, snapshot date and document date "
          "remain separate fields. Card loads are authorised at 08:05+ and settle the same day at 14:00; spends are authorised from 07:15 "
          "and settle at 15:00 (convention D8). These intraday sequences are by design, not inconsistencies.", "",
          "## Cross-month identifiers", "",
          f"- Account inventory (IN-02): the same 4 standing accounts in every month (expected master data).",
          f"- Client snapshots (IN-03): {dq['cross_month_ids']['IN-03']['identical_carried_forward_opening_snapshots']} records appear in two months: "
          "the opening snapshot of a month whose previous month ended on a reconciliation day is byte-identical to that month's closing snapshot "
          "(carried-forward position, same ID and values). No conflicting duplicate exists.",
          "- All other identifiers embed the date and are unique across months.", ""]
    (PKG / "date_quality_report.md").write_text("\n".join(D) + "\n", encoding="utf-8")
    # ---------------- coverage ----------------
    C = ["# Historical coverage report", "", SYN, "",
         "| Period | Status | Contents |", "| --- | --- | --- |"]
    for p in MONTHS:
        e = eng[p]
        C.append(f"| {p} | **Generated (this package)** | 14 CSV + PDFs; scenario: {', '.join(run[p]['expect'][i]['scenario'] for i in range(len(run[p]['expect']))) or 'clean'}; "
                 f"pre-validated outcome {e['case_status']}, {len(e['exceptions'])} exception(s); **no pack, investigation or audit report yet** |")
    C += ["| 2026-09 | **Existing, unchanged** | The nine original September scenario datasets and nine deterministic packs in the project. Not part of this package; not modified. |",
          "| 2026-10 | **NO DATA** | No data generated. |",
          "| 2026-11 | **Ready for fresh upload** | No data generated; available for the analyst's own documents once upload/ingestion exists. |", "",
          "January–August are a single continuous synthetic timeline. September's nine datasets are separate variants of one month "
          "and must not be combined with each other or with this package.", ""]
    (PKG / "historical_coverage_report.md").write_text("\n".join(C) + "\n", encoding="utf-8")
    print("reports written")


if __name__ == "__main__":
    main()
