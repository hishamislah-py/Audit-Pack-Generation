# 04 — Configuration Gap Assessment

Assessment date: 30 Oct 2026. No configuration system is designed or implemented here.

**Finding: the implementation is not configuration-driven.** There is no configuration file (no YAML, TOML or JSON config in the project). Every business rule, value and relationship is a Python constant in `uc042lib/`. Changing a rule means changing code.

What *is* data-driven: the validator reads whatever accounts, transactions, batches, lines and entries are in the files, and applies fixed rules to them.

## 1. Hard-coded behaviour (with code references)

| Area | Hard-coded value or rule | Location |
| --- | --- | --- |
| Reporting period | `PERIOD_ID = "PER-2026-09"`; `PERIOD_START`, `PERIOD_END` = 1–30 Sep 2026 | `schema.py` lines 7, 315 |
| Time zone | `TZ = "Europe/London"` | `schema.py` line 9 |
| Supported currencies | `CURRENCIES = {"GBP", "EUR"}` | `structure.py` line 28 |
| Bank holidays | `UK_BANK_HOLIDAYS` (31 Aug, 25 Dec, 28 Dec 2026) duplicated in two files | `validate.py` line 40; `generate.py` line 29 |
| Reconciliation point | Parsed from the policy PDF text matching `HH:MM Europe/London` | `validate.py` line 326 |
| Fee categories | `fee_code` ∈ {`ACQ_FEE`, `SCHEME_FEE`} | `schema.py` line 246 (`ENUMS`) |
| Cash-book entry types and all other enums | Fixed sets | `schema.py` `ENUMS` |
| Fee top-up evidence | Found by the reference pattern `TOPUP-<ccy>-<yyyymmdd>` | `validate.py` line 761 |
| Fee treatment | Acquirer: net = gross − fees. Scheme: net = gross − refunds, fees 0. Fees always belong to a settlement batch. | `validate.py` `check_settlement`; generator |
| Account relationships | One safeguarding account per currency (`acct_of_ccy`; `next(a for a in self.sga if ccy …)`) | `validate.py` lines 564, 812, 835 |
| Letter slots | `LETTER_SLOTS = {"SGA-GBP-01": "IN-15", "SGA-EUR-01": "IN-16"}` | `schema.py` line 273 |
| Matching rules | Exact equality only; matching by reference, never by amount; **no tolerance anywhere** (no "tolerance" in the code) | `validate.py` (multiple comparisons) |
| Control set and evidence dependencies | Each check is a method; `DEPENDS` maps check → required files | `validate.py`; `schema.py` line 278 |
| Severity and categories | `SEVERITY`, `CATEGORY` tables | `validate.py` line 1014 |
| Period rules | `PERIOD_RULES`, `PERIOD_UNCHECKED` | `schema.py` |
| File types and schemas | `CSV_FILES`, `PDF_FILES` | `schema.py` |
| Scenarios | Python functions `s02_definition`, `s05_definition` | `scenarios.py` lines 89, 137 |
| Generator economics | Seed, opening balances, fee rates (0.30%, 0.155%), volumes, timings | `generate.py` lines 25, 38, 52–53 |

**Already semi-configurable** (centralised, but still code): `schema.py` holds the file contract, enums, period rules and dependency map in one place, so a rule change is a one-place edit, not a scattered one.

## 2. The briefed examples: data change or code change?

| Change | Handled by data alone today? | What happens now (verified where marked) | What would be needed |
| --- | --- | --- | --- |
| Add a new bank fee transaction of an existing type inside a settlement batch | **Yes.** Add a FEE line and update the batch totals. | The arithmetic checks include it | — |
| Add a bank fee charged directly to a safeguarding account (not in a batch) | **No** | Probe: a £15.00 `ACCOUNT FEE` debit becomes an `UNMATCHED_BANK_ENTRY` exception (a bank entry with no counterpart) | A concept of "bank charges": fee category, the account it may hit, and whether own funds must replace it |
| Introduce a new fee category | **No** | Rejected as an invalid row (`fee_code` enum) | Fee categories in configuration |
| Change the mapping of a fee category to a bank account | **No** | No such mapping exists; fees inherit the batch's account | Fee category → account mapping in configuration |
| Add a new safeguarding account | **Partly.** A new account in a *new currency* fails the currency check. A *second account in an existing currency* breaks the one-account-per-currency logic. C10 has no letter slot for it. | — | Accounts and their letter slots fully data-driven; per-account (not per-currency) resource and RC4 logic |
| Change a matching rule or tolerance | **No** | Exact match is fixed | Matching rules and tolerances in configuration, with an audit trail of the configuration in force |
| Enable or disable a scenario | **No** (scenarios are generator code and separate datasets) | — | A scenario registry (definition, mutation list, answer key) loaded from data |
| Add a new control or evidence requirement | **No** | Requires a new method and `DEPENDS` entry | A control registry (inputs, dependency list, severity), still with code for each calculation |

## 3. Configuration structures that would be needed

These are identified, not designed:

1. **Case configuration:** period, time zone, reconciliation days and holidays, reconciliation point, method, basis.
2. **Account configuration:** safeguarding and own-funds accounts, currency, pool, letter slot, top-up pairing.
3. **Fee configuration:** categories, allowed accounts, sign and treatment (deducted from settlement versus charged to the account), own-funds replacement rule, reference pattern.
4. **Matching configuration:** reference fields per link; tolerance per comparison (default zero); timing window for accepting a timing difference.
5. **Control registry:** enabled controls, evidence dependencies, severity.
6. **Scenario registry:** enabled scenarios, mutation definitions, answer keys.

**Important boundary.** Configuration should select and parameterise deterministic calculations. It should not let a user switch off a financial check silently. Every run records the configuration it used, and the pack must cite it.

## 4. Gaps that require code changes

| Gap | Why it requires code |
| --- | --- |
| Loading and validating a configuration source | No configuration loader exists |
| Bank-account fees and fee mapping | No entity or rule for them |
| More than one safeguarding account per currency | Logic keyed by currency |
| Tolerances | All comparisons are exact equality |
| Evidenced timing differences (scenario 2) | R08 acceptance logic not implemented |
| General root-cause grouping (scenarios 3 and 5) | Grouping only recognises the S02 and S05 patterns |
| Scenario and control registries | Scenarios and controls are code |
| Audit pack, AI narrative and approval record | None exist |
