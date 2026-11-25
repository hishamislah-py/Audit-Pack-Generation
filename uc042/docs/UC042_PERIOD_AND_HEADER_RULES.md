# UC-042 Reporting-Period and Header Rules (U2, U3)

Implemented 29 Oct 2026 under the approved upload contract (`UC042_UPLOAD_CONTRACT.md`, decisions U1–U6). The A1 and A2 date decisions were added the same day (section 1.4).

The rules live in one place each:

| What | Where |
| --- | --- |
| Period rules | `schema.PERIOD_RULES`, `schema.PERIOD_UNCHECKED`, applied by `structure.check_period` |
| Header diagnosis | `structure.diagnose_header` |

Financial calculations contain no date exceptions.

## 1. Reporting period

**Period:** 1–30 September 2026 (U5). Dates are judged as Europe/London calendar dates, so a timestamp's offset is applied before the date is taken.

### Business-date rules

| Type | Fields that must fall inside the period | Permitted boundary records | Must not be after the period end |
| --- | --- | --- | --- |
| IN-01 calendar | `calendar_date`; `period_id` must equal `PER-2026-09` | — | — |
| IN-03 client snapshots | `recon_date` | — | — |
| IN-04 unallocated register | **Open during the period** (A1): received on or before 30 Sep, and not allocated before 1 Sep | — | — |
| IN-05 internal reconciliation | `recon_date` | — | — |
| IN-06 external reconciliation | `recon_date` | — | — |
| IN-07 balance confirmations | `as_at_ts` | — | — |
| IN-08 statement headers | `statement_date` | — | — |
| IN-09 statement entries | `booking_date`, `booking_ts` | — | — |
| IN-10 cash book | `posted_ts` | `OPENING_BALANCE` posted at exactly `2026-08-31T17:00:00+01:00` (input spec §4, IN-10) | — |
| IN-11 transactions | `executed_ts` | — | — |
| IN-12 settlement batches | `settlement_date` | — | — |
| IN-14 discrepancy log | **Follows the referenced reconciliation** (A2): `recon_ref` must be a September IN-05/IN-06 record in the case; `logged_ts` must not be before that reconciliation | Entries logged after 30 Sep are kept and labelled *subsequent-recorded* | — |

**Not period-checked.** These fields are never read by a calculation, so they cannot influence a result. Each is listed with its reason in `schema.PERIOD_UNCHECKED`:

- IN-02 account open and close dates;
- IN-03 `as_at_ts`, IN-05 `reconciliation_point_ts`: checked against the reconciliation point by C03 instead;
- performed-at timestamps;
- IN-09 `value_date`, IN-11 `auth_ts` and `clearing_date`, IN-12 `cycle_date`;
- IN-13 settlement lines: no dates; they follow their batch;
- IN-14 `resolved_ts`;
- all PDF dates.

### Outcomes

The four conditions are kept distinct:

| Condition | Finding | Root cause, severity | Effect |
| --- | --- | --- | --- |
| Malformed date (for example `15/09/2026 17:00`) | `DQ-FIELD` | `INVALID_ROWS\|IN-xx`, High | Row excluded (structure stage, before the period stage) |
| Valid date outside the period, in a file that also has September rows | `DQ-PERIOD` per field, with file, line, field, date and evidence type | `OUT_OF_PERIOD_ROWS\|IN-xx`, High | Row excluded from all calculations. Scopes it could have affected become INSUFFICIENT_EVIDENCE. |
| File with rows, none in the period (permitted boundary rows do not count) | One `DQ-PERIOD` for the file, giving the date range found | `WRONG_PERIOD\|IN-xx`, Critical | File unusable; dependent checks gated (one result each); independent checks run |
| File or record absent | `V00-FILE` or coverage result | `MISSING_FILE` or `MISSING_BANK_EVIDENCE`, Critical | As before |

An excluded row dated **before** the period never taints a September balance roll-forward. The opening balance represents everything before 1 September. If the opening row itself is excluded, item A cannot be computed and the resource checks report insufficient evidence for that cause.

### Verified behaviour

| Input | Result |
| --- | --- |
| August bank-confirmation file | 1 Critical `WRONG_PERIOD\|IN-07` (previously 88 missing-evidence exceptions) |
| One stray August bank entry | 1 High finding; all 44 bank-evidence checks and 88 batch checks still pass |
| Stray August cash-book row worth £5,000.00 | Excluded; all 22 GBP resource checks still pass, so it could not influence the ledger |
| Opening balance moved to 30 Aug | Excluded; GBP resource checks insufficient with that cause; EUR unaffected |
| 30 Sep receipt allocated 1 Oct | Kept; open at the 30 Sep point (requirement includes it); C09 passes, noting a subsequent event; case `CLEAN` |
| Receipt dated 1 Oct | Excluded (received after the period end); September requirement checks unaffected |
| A 30 Sep entry with value date 1 Oct | No finding (`value_date` unchecked); case `CLEAN` |

### 1.4 Decisions A1 and A2

#### A1: September receipts allocated after 30 September (decided)

**What the specification already establishes.** The RC1 requirement formula in the source-to-control matrix (§2) counts a receipt at reconciliation point *d* when `receipt_ts` ≤ *d* and `allocated_ts` is blank or later than *d*. Receipt and allocation are therefore separate facts.

- A receipt received on 30 Sep at 16:30 and allocated on 1 Oct is open at the 30 Sep 17:00 point, and belongs in that day's requirement.
- A later allocation is not evidence that the receipt did not exist in September.
- The same formula means a receipt received before 1 Sep and still open in September belongs in September's requirement.

**Period rule.** A register row is in scope if it was open at some point in the period: received on or before 30 Sep, and not allocated before 1 Sep. Excluded:

- rows received after 30 Sep;
- rows received and allocated before 1 Sep.

**Synthetic convention P1.** The specification does not say how to evidence an allocation that crosses the period boundary. For this POC:

- **Allocation after 30 Sep:** this is a subsequent event. C09 judges timeliness (next business day, CASS 15.2.5R) from the register's `allocated_ts`, and does **not** require the allocating transaction, which belongs to the next period's evidence. If an October allocation transaction is uploaded in the September export, it is still excluded as out of period and reported; C09 is unaffected.
- **Receipt before 1 Sep:** its bank credit is outside the September evidence, so C09 does not require it. RC4 reports the allocating transaction's 1:1 bank link as NOT_APPLICABLE, with that reason.

**Defect fixed with A1.** A receipt with no allocation was previously reported as PASS with the note "allocated by the next business day". It is now:

- **FAIL** if its deadline fell within the period ("not allocated; allocation was due by …");
- **PASS** if it is still within its deadline at the period end ("open at the period end; allocation due by … , after the period").

The three committed datasets are unaffected: both baseline receipts are allocated in September.

#### A2: September discrepancy logged after 30 September (decided)

**What the specification already establishes.** The log is evidence that a difference was investigated (C06/C08, CASS 15.8.56R). Each entry points to the reconciliation record it concerns through `recon_ref` (input spec, IN-14). The log never changes a balance, so it cannot alter September's calculations.

**Synthetic convention P2.** An entry's period is the date of the reconciliation it refers to, not its log date.

| Entry | Effect |
| --- | --- |
| Refers to a September reconciliation, logged in September | Investigation evidence for that difference (`DISC-LOG` PASS) |
| Refers to a September reconciliation, logged after 30 Sep | Investigation evidence, labelled **subsequent-recorded** in the `DISC-LOG` note. The exception gets flag `INVESTIGATION_RECORDED_AFTER_PERIOD_END`. The difference itself stays unexplained and the exception stays open. |
| Logged before the reconciliation it refers to | Excluded (`DQ-PERIOD`). If it concerned an open difference, `DISC-LOG` becomes INSUFFICIENT_EVIDENCE, not "not logged". |
| Refers to a record not in the case, or not in September | Excluded (`DQ-PERIOD`) |
| A log with entries but none usable for September | One `WRONG_PERIOD\|IN-14` exception; `DISC-LOG` gated |

#### Remaining uncertainty

- **P1 and P2 are synthetic conventions, not research findings.**
  - P1: whether a firm or its auditor expects the post-period allocation transaction as September evidence.
  - P2: whether a log entry recorded after the period end is acceptable investigation evidence, given that CASS 15.8.56R requires resolution "without undue delay" and gives no number.

  Both would need confirming with Moorwand's compliance team before real use.
- **A3–A5 are unchanged.** `value_date`, `auth_ts`/`clearing_date` and `cycle_date` are not period-checked because no calculation reads them.

## 2. CSV headers

Matching stays **exact**: same names, same case, same order, no extra or missing columns. A near match is never accepted and columns are never reordered. When a header does not match, `diagnose_header` explains why:

| Status | When | Message |
| --- | --- | --- |
| `LIKELY` | One type is clearly closest (set overlap ≥ 0.5, at least 0.1 ahead of the next) | Names the type and lists missing, extra, misordered and case or spacing differences, as plain-language fixes |
| `AMBIGUOUS` | Two or more types are equally close (for example, IN-08 and IN-09 columns exported together) | Names the candidates and says the type cannot be determined; no guess |
| `UNKNOWN` | Nothing is close | Says the CSV resembles no supported evidence type |

### Where the diagnosis appears

- **`intake.csv`** (from `prepare`): the reason, `probable_file_id`, missing, extra and misordered columns, case or spacing differences, and the expected and received headers.
- **The `MISSING` intake row** for that type points to the rejected file.
- **The validator's missing-file finding** quotes the intake rejection.
- **A file placed directly in a case with a wrong header:** the `V01-SCHEMA` note carries the same diagnosis.

Example, from `intake.csv`:

> This looks like IN-08 (End-of-day bank statement headers) but the header is not exact. To fix it: rename 'Statement_ID' to 'statement_id'. Headers must match exactly, including case and column order.

## 3. Replacement and history (U4)

Each `prepare` run rebuilds the case directory from the current upload set only. It clears the directory first, so a replaced file cannot remain among the inputs. Run history is a future application concern and is not built here.

## 4. Remaining limitations

- The period is fixed to September 2026 (U5). A1 and A2 are decided using synthetic conventions P1 and P2 (section 1.4). A3–A5 remain documented as unchecked fields.
- An excluded row whose account or date is unreadable still taints every scope it might touch (conservative).
- No date-order check (for example allocation before receipt, DQ03) and no general cross-file conflict detection (DQ13).
- Header diagnosis uses column-name overlap. It explains rejections but is never used to accept a file.
