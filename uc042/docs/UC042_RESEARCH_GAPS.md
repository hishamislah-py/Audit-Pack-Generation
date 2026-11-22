# UC-042 Research Gaps and Audit of Existing Research — v1

Status: for review. This document audits the parent spec (revision 17) for what matters to the input files and the three demo scenarios. It does not repeat the spec.

Gap IDs:

- **G-R** = regulatory source not fully verified
- **G-S** = gap or inconsistency in the spec itself
- **G-M** = unconfirmed Moorwand-specific detail

"Material" means the item could change an input file, a field or an expected scenario outcome.

---

## 1. Classification of the spec's relevant claims

| Class | Claims relied on by the input spec | Where in the spec |
| --- | --- | --- |
| **Verified regulatory requirements** (primary text inspected) | Daily internal and external reconciliation on reconciliation days (CASS 15.8.19R, 15.8.42R). Record contents: time, date, actions, outcomes (15.8.9R). Requirement and resource formulas, using ledger values (15.8.15R, 15.8.26R, 15.8.30R, 15.8.33R, 15.8.34G). Currency-by-currency external comparison (15.8.47R). Shortfall and discrepancy handling, including own funds (15.8.50R–57R). 5-year retention (15.8.8R(3)). Allocation by the next business day and unallocated/unidentified recording (15.2.5R, 15.2.9R). CASS 10A pack contents, including the institution list with account numbers and acknowledgement letters (10A.2.1R, 10A.2.3R). Monthly return within 15 business days (SUP 16.14A.3R). EMRs regs 20–21 segregation and the card-funds timing rule. | §9 rows marked PRIMARY |
| **Evidence categories derived from requirements** | S01–S16, S18 (calendar, snapshots, register, reconciliation records, statements, inventory, letters, transactions, settlement, log, policy, governance, return, own-funds transfers) | §3 |
| **General industry conventions** | Settlement aggregation and net-of-fee settlement; reversals within batches; bank D/C indicators; MT940 or camt.053 as possible bank formats; transaction lifecycle states | §3 "typical origin", §4 IC fields, §9 INDUSTRY rows |
| **Proposed POC design decisions** | Canonical field names and IDs; sign convention; per-currency internal reconciliation; 17:00 point; balance confirmation plus end-of-day timing model; baseline volumes and flows; exception and DQ severity scheme; 22 reconciliation days with no foreign closures | §2, §4 DP fields, §8 |
| **Unconfirmed Moorwand assumptions** | One pool; segregation only; standard method; any reconciliation point; bank and statement formats; whether fees hit safeguarding accounts; existing tooling (Kani relationship unproven) | §2 "Assumptions to confirm", §10 |
| **Unresolved research questions** | First-audit transitional deadline; REP027 template; Approach Document chapter; current PSRs reg 23 text | §9 "Not accessible", §12 |

## 2. Regulatory references not fully verified (G-R)

None of these is claimed as verified here.

| ID | Reference | State of verification | Material to inputs? | Effect if it changes |
| --- | --- | --- | --- | --- |
| G-R01 | PSRs 2017 reg 23 (current revised text) | Only the as-made text was seen, as a search extract | No for v1 (single e-money pool) | A second asset pool would add rows (IN-03, IN-05) and an account class |
| G-R02 | FCA glossary: "reconciliation day" and "D+1 segregation requirement" | Search extracts only; full entries not opened | **Yes** | IN-01 calendar rules and `d1_*` columns in IN-05 |
| G-R03 | PS25/12 transitional provisions (first safeguarding audit report deadline) | Not opened. SUP 3A.9.7R states 4 months; secondary sources say 6 months for the first report. | No (affects pack timing, not inputs) | — |
| G-R04 | CASS 15.7 acknowledgement letter requirements and template | Not opened; only referenced via CASS 10A.2.1R(3) | **Yes** | Required content of IN-15 and IN-16. v1 uses generic, labelled wording. |
| G-R05 | CASS 15.8.13R conditions for excluding the D+1 comparison when card-funded loads pass through an acquirer before reaching the safeguarding account (with EMRs reg 20(4)) | 15.8.13R text read; its application to this flow is not analysed | **Yes** | Whether `d1_requirement` and `d1_resource` must be populated in IN-05 |
| G-R06 | REP027 monthly return template fields | Not opened | No for v1 (IN-19 is a receipt only) | Needed only if the pack covers return contents |
| G-R07 | FCA Approach Document safeguarding chapter (updated May 2026, per secondary source) | Not opened | Possibly | May clarify executed and redeemed timing (15.8.33R(2)) used in snapshots |

## 3. Gaps and inconsistencies in the spec (G-S)

| ID | Issue | Material? | v1 handling | Needs |
| --- | --- | --- | --- | --- |
| G-S01 | RC1 and C05 use "internal ledger balances of SGA accounts (item A)", but no entity, field set or source category defines that ledger | **Yes** | Proposes IN-10 cash book and entity `sga_ledger_entry` | **Approval before generation** |
| G-S02 | §4 lists `amount_signed` as a stored source field; the frozen decision requires raw amount plus indicator, with signed values derived | **Yes** | Inputs carry `amount` + `dc_indicator`; `amount_signed` is derived only | Approval (refinement, not a rewrite) |
| G-S03 | Date-only fields (`booking_date`, `receipt_date`, `allocated_date`) cannot decide inclusion at a 17:00 point | **Yes** | Adds `booking_ts`, `receipt_ts`, `allocated_ts` | Approval |
| G-S04 | No independent source for resource items B–D | Low for v1 (all 0.00) | Accepted as reported; output says "not independently verified" | Accept |
| G-S05 | No rule for grouping exceptions across days or affected checks | **Yes** (expected counts) | One exception per root cause, listing affected control results | Approval |
| G-S06 | Unclear whether an unlogged external difference is a separate finding | Medium | Recorded inside the main exception, not separately | Approval |
| G-S07 | DQ results vs exceptions not distinguished | Medium | DQ findings attach to the related exception | Approval |
| G-S08 | S05 describes 17 Sep only; an unexplained debit would persist | **Yes** | Persist 17–30 Sep (10 days) | Approval |
| G-S09 | Daily file counts (44, 44, 88) are impractical for manual upload | **Yes** | Monthly files with per-row daily IDs | Approval; reversible |
| G-S10 | Terminology clash: §4 example `evidence_type` values `E14_POLICY` and `E03_BANK_STATEMENT`, while the research catalogue has E07 = policies and E14 = transaction ledger export | Low | v1 uses the research catalogue numbering (E07 policy, E14 transactions) | Correct the spec example |
| G-S11 | IN-02 to letter link: the spec links by `acknowledgement_evidence_id`, which a raw register cannot hold | Medium | `acknowledgement_letter_ref` printed on both the register and the letter | Approval |
| G-S12 | §5 relationship "settlement batch → bank entry: one-to-one in the baseline" leaves split settlements unspecified | Low for v1 | v1 keeps one-to-one | Defer |

## 4. Unconfirmed Moorwand-specific details (G-M)

None of these is known from public sources. All v1 values are synthetic.

| ID | Detail | Material? |
| --- | --- | --- |
| G-M01 | Which system produces internal and external reconciliation records, and in what layout (would IN-05 and IN-06 exist as exports at all?) | **Yes** |
| G-M02 | Whether existing tooling (possibly Kani) already produces an evidence pack | **Yes**: it decides whether the POC is worthwhile |
| G-M03 | Bank statement delivery (daily files or monthly; CSV, MT940, camt.053, PDF, API) and whether 17:00 balances exist | **Yes** |
| G-M04 | Whether a cash book separate from the bank feed is maintained for safeguarding accounts | **Yes** (IN-10) |
| G-M05 | Settlement report formats; whether scheme or acquirer fees are deducted inside safeguarding accounts | **Yes** (IN-12, IN-13) |
| G-M06 | References carried on bank entries for settlements, loads and redemptions | **Yes**: all link keys depend on this |
| G-M07 | Number of asset pools; safeguarding method; reconciliation method and point; per-currency practice | **Yes** |
| G-M08 | Whether transaction exports carry batch IDs | **Yes** |
| G-M09 | When a spend counts as "executed" and a redemption as "redeemed" | Medium |
| G-M10 | Unallocated register location and status values | Medium |
| G-M11 | Foreign-market closures used for reconciliation days | Medium |

## 5. Decisions safe to treat as synthetic POC conventions

These can proceed without Moorwand input, provided every artefact is labelled synthetic:

- Fictional entity, bank, accounts, clients and balances.
- September 2026 with 22 recon days and no foreign closures.
- 17:00 Europe/London point.
- Per-currency internal reconciliation.
- Balance confirmation plus end-of-day statement timing model.
- Monthly consolidated CSV files.
- Generic settlement report structure.
- Same-day settlement in the baseline.
- Scheme fees billed outside safeguarding accounts.
- Acquirer fees with same-day own-funds top-up.
- Sign normalisation table.
- One balance per client.
- PDF "Key details" tables for deterministic extraction.
- The exception grouping rule, subject to approval (G-S05).

## 6. Questions requiring stakeholder confirmation

Priority order. The first three could change the input file set.

1. Which reconciliation records can you export today, and in what layout? Do they include time, actions, requirement, resource and items A–D? (G-M01)
2. How do bank statements and balances arrive for safeguarding accounts, and is a balance available at your reconciliation point? (G-M03)
3. Is there a cash book for safeguarding accounts separate from the bank feed? (G-M04)
4. Do settlement credits or debits in safeguarding accounts carry the batch reference, and are fees deducted inside those accounts? (G-M05, G-M06)
5. Do transaction exports carry the settlement batch ID? (G-M08)
6. One pool or two? Segregation only? Standard method? What is the documented reconciliation point? (G-M07)
7. Do you reconcile internally per currency? (G-M07)
8. When is a spend "executed" and a redemption "redeemed" for safeguarding? (G-M09)
9. Does an existing tool already assemble the auditor's evidence pack? (G-M02)

## 7. Items that could materially change the input specification

If answered differently from the v1 assumptions, these would change files, fields or scenario outcomes:

- G-S01 / G-M04: cash book exists or not.
- G-M01: reconciliation exports exist or not.
- G-M03 / G-S09: daily vs monthly bank files.
- G-M05: fees inside safeguarding accounts.
- G-R05: D+1 required.
- G-R04: letter content.
- G-S08: persistence of the £812.40 difference.
