# Experiment A2: Generating PDF Extraction Validation Rules from UC-042

**Feasibility report, 19 Nov 2026.**

| | |
|---|---|
| **Working copy** | `p10/smartparser_phase1` |
| **Authoritative source** | `p10/uc042_token_optimisation` (read-only) |
| **Status** | Experiment complete; **nothing integrated**; awaiting owner decision |

## 1. Executive summary

**Question.** Can the value rules hand-written in `smartparser/pdf_extraction/rules.py` (Experiment A) be generated from UC-042 instead?

**Answer: partly.**

**Of the 19 hand-maintained rules:**
- **3 are directly derivable** (group A);
- **1 is derivable with a deterministic transformation** (B);
- **4 are partially derivable**, needing explicit configuration (C);
- **3 are not derivable** (D), because UC-042 has no such rule;
- **8 are business-level** (E): they belong to UC-042's downstream controls and should not be extraction rules at all.

In addition, the 6 "UC-042 has no rule for this label" assertions are reproduced exactly by the generator.

**Generation is possible but not complete.** An isolated generator reads UC-042:
- data tables by import;
- consumer code by `ast` parsing, never executing it.

It finds every use of a PDF label: 17 rule-bearing sites, 1 site where the value flows into a variable, 13 read-only sites and **0 unrecognised code shapes**. Each is traced to file, function and line. The generator is byte-reproducible, detects source changes, and fails visibly on a missing source or an unconfigured consumer.

**What it cannot do:**
- **Work out a rule's consequence.** Whether a failure makes the document unusable or is a control result is not in the source as data. It is supplied as explicit configuration (`CONSEQUENCE_BY_FUNCTION`).
- **Follow a value through a variable.** "Document version" is the one such case.
- **Capture what the date and timestamp helpers accept**, short of executing UC-042 code. Their behaviour is restated by hand and pinned to the helper's source hash.

**Behaviour.**
- On the **20 Experiment A cases**, the generated rules give **identical decisions** (20/20).
- On **10 new edge-case PDFs**, they differ in **6**. The hand rules send these to human review; the generated rules do not. **This triggers the brief's stop condition** ("generated behaviour differs materially"), so nothing further was built.
- The differences are explainable and run *in favour of* the generated rules on UC-042 fidelity:
  - on the date and timestamp values, the generated rules match UC-042 exactly (**44/44**), the hand rules only **32/44**;
  - the hand rules contain one rule UC-042 does not have (due-date format);
  - the hand rules contain two inaccurate restatements.

  But fidelity is not the same as safety: the generated rules accept unusual date forms UC-042 tolerates (`20240301`, `2024-W09-5`, `2024-03-01 (original issue)`), which the hand rules send to review.

**Recommendation: partial generation is feasible; a hybrid approach is preferable (§11).** Generate the inventory, the policy data, the regex, the "no rule" set and the drift check. Keep three things explicit and owner-approved:
- the consequence mapping;
- the pinned helper semantics;
- a Smart-Parser-owned "canonical form" strictness policy.

Do not carry business-level (E) rules in extraction validation.

---

## 2. Existing hand-maintained rules inventory

Source: `smartparser/pdf_extraction/rules.py` (Experiment A).

Level codes in the table:
- **P** = PARSE (UC-042 treats the document as unusable);
- **X** = CROSS_DOC (compared with another document);
- **C** = CONTROL (a UC-042 control evaluates it).

| # | Rule ID | Category | Field | Format / condition | Level | Kind | Cited UC-042 source | Duplicated from UC-042? | Explicit or inferred |
|---|---|---|---|---|---|---|---|---|---|
| 1 | LETTER-REF | IN-15/16 | Letter reference | = IN-02 `acknowledgement_letter_ref` of the slot account | X | structural (slot identity) | prepare.py:155-166, validate.py:1179 | Yes | explicit |
| 2 | LETTER-ACCOUNT-NUMBER | IN-15/16 | Account number | = IN-02 `account_number_masked` | X | business (C10) | validate.py:1179 | Yes | explicit |
| 3 | LETTER-CURRENCY | IN-15/16 | Currency | = IN-02 `currency` | X | business (C10) | validate.py:1180 | Yes | explicit |
| 4 | LETTER-ACCOUNT-NAME | IN-15/16 | Account name | = IN-02 `designation_name` | X | business (C10) | validate.py:1180 | Yes | explicit |
| 5 | LETTER-SAFEGUARDING-WORDING | IN-15/16 | Account name | contains "Safeguarding" | C | business (C10) | validate.py:1181 | **Inaccurate**: UC-042 tests IN-02 `designation_name`, not the letter value | explicit (misapplied) |
| 6 | LETTER-DATE | IN-15/16 | Letter date | strict `YYYY-MM-DD`, and ≤ period end | C | syntax + business | validate.py:1183-1185 | **Inaccurate syntax**: UC-042 `_date_or_none` is lenient | syntax inferred; business explicit |
| 7 | POLICY-VERSION | IN-17 | Document version | a registered version | P | structural | policy.py:69-74 (recognise), POLICY_VERSIONS | Yes | explicit (data) |
| 8 | POLICY-APPLIES | IN-17 | Document version | applies to the period | P | structural | policy.py:89-97 (applicability); analysis.py:262 | Yes (algorithm restated) | explicit (code) |
| 9 | POLICY-EFFECTIVE | IN-17 | Effective date | = registered effective date | P | structural | policy.py:76 | Yes | explicit (data) |
| 10 | POLICY-EFFECTIVE-BY-PERIOD-END | IN-17 | Effective date | strict date, ≤ period end | P | syntax + business | validate.py:479-481 | Partly; subsumed by #8 | explicit (code, via a variable) |
| 11 | POLICY-POINT | IN-17 | Reconciliation point | regex `HH:MM Europe/London` | P | syntax | validate.py:472 | Yes | explicit (literal) |
| 12 | POLICY-METHOD | IN-17 | Reconciliation method | = `STANDARD` | C | business (C03) | validate.py:494 | Yes | explicit |
| 13 | POLICY-BASIS | IN-17 | Internal reconciliation basis | = `Per currency` | C | business (C03) | validate.py:494 | Yes | explicit |
| 14 | GOV-PERSON | IN-18 | Accountable person | non-empty | C | business (C16) | validate.py:1197 | Yes | explicit |
| 15 | GOV-ALLOCATED-FROM | IN-18 | Allocated from | strict date, ≤ period end | C | syntax + business | validate.py:1198-1199 | **Inaccurate syntax** (as #6) | syntax inferred; business explicit |
| 16 | RETURN-PERIOD | IN-19 | Period | = previous month | C | business (C16) | validate.py:1215; analysis.py:241 | Yes | explicit |
| 17 | RETURN-SUBMITTED-AT | IN-19 | Submitted at | ISO timestamp with offset | C | syntax | validate.py:1211 (parse_ts) | Yes (same behaviour) | explicit |
| 18 | RETURN-DUE-DATE-FORMAT | IN-19 | Due date | strict `YYYY-MM-DD` | C | syntax | none: UC-042 compares with `due.isoformat()` (validate.py:1217) | **Not in UC-042** | inferred |
| 19 | RETURN-SUBMITTED-BY-STATED-DUE | IN-19 | Submitted at + Due date | submitted ≤ *stated* due date | C | business | none: UC-042 compares with its *computed* due date (validate.py:1207, 1217) | **Not in UC-042** (approximation) | inferred |
| – | NO_RULE_REASON (6 labels) | 15/16/17/18/19 | Institution, Safeguarding method, Frequency, Role, Return, Submission reference | "UC-042 has no rule" | – | absence | whole consumer code | – | inferred by reading |

There are also **identification rules** that live in the classifier, not `rules.py`: label sets, the `Label: value` pattern, letter slots, policy markings. They are **already generated** by the existing registry import (`smartparser/registry_import/uc042.py`), so they were not re-examined.

**Hand-rule defects found during discovery.** These are reported, not fixed, because Experiment A must stay unchanged:
- **#5** checks the wrong operand.
- **#6, #10, #15:** the docstring says the date check matches `_date_or_none`, but it is stricter.
- **#18 and #19** have no UC-042 basis.

---

## 3. Authoritative UC-042 source locations

| What | Where | Form |
|---|---|---|
| PDF labels per category; requirement | `uc042lib/schema.py` `PDF_FILES` (from line 199) | data |
| Letter slots | `uc042lib/schema.py` `LETTER_SLOTS` | data |
| Policy versions, effective dates, markings | `uc042lib/policy.py` `POLICY_VERSIONS` (lines 40, 45) | data |
| Policy recognition; applicability | `policy.recognise` (69-81); `policy.applicability` (89-97) | code |
| Label extraction | `prepare._pdf_details` (48-60); `validate.load_pdf` | code (regex template) |
| Reconciliation point format; effective-date drop | `validate.Validator.setup` (472, 479-481) | code |
| C10 designation | `validate.check_designation` (1179-1185) | code |
| C03 policy | `validate.check_policy_and_points` (494) | code |
| C16 governance and return | `validate.check_checklist` (1197-1217) | code |
| Intake return-period warning | `ingest/analysis.analyse_pdf` (241) | code |
| Date and timestamp parsers | `validate._date_or_none` (86-89); `structure.parse_ts` (35-39) | code |
| Existing generator | `smartparser/registry_import/uc042.py` imports these modules and re-reads inline literals, failing if they disappear | **precedent for this experiment** |

**There is no declarative rule source for PDF values in UC-042.** Apart from three data tables (labels, slots, policy versions), every value rule is imperative code inside the consumers.

---

## 4. Derivability classification

| Group | Meaning | Rules (# from §2) | Count | Share of 19 |
|---|---|---|---|---|
| **A** | directly derivable | 1 (slot identity, from LETTER_SLOTS and the prepare lookup), 7, 9 (POLICY_VERSIONS data) | 3 | 16% |
| **B** | derivable with a deterministic transformation | 11 (regex literal read from the code) | 1 | 5% |
| **C** | partially derivable: the site is generated, the semantics need explicit pinned configuration | 6, 15 (date syntax), 17 (timestamp syntax), 8 (applicability algorithm) | 4 | 21% |
| **D** | not derivable | 10 (the comparison flows through a variable; it is also subsumed by #8), 18, 19 (no UC-042 rule exists) | 3 | 16% |
| **E** | business-level: belongs downstream in UC-042 | 2, 3, 4, 5, 12, 13, 14, 16, and the "≤ period end" halves of 6 and 15 | 8 | 42% |
| (absence) | "no UC-042 rule for this label" | 6 labels | generated exactly, 6/6 | – |

**What these percentages measure.** They count *hand rules by where their authority lies*; they do not measure output quality.
- **Extraction-relevant rules** are groups A+B+C: **8 of 19 (42%)**. All 8 have a generated counterpart.
- Of those 8, **4 need no configuration** (A+B) and **4 need pinned configuration** (C).
- 3 rules (16%) cannot be generated because UC-042 has no such rule.
- 8 rules (42%) should not be generated as extraction rules at all.

---

## 5. Experimental generator architecture

`experiments/pdf_rule_generation/`. It is isolated: nothing in `smartparser/` imports it, and it is not run at start-up or intake.

| File | Role |
|---|---|
| `generate_rules.py` | Reads UC-042: data by import (with `sys.dont_write_bytecode`) and consumer code by `ast.parse`. Every `<x>.get("<PDF label>")` / `<x>["<PDF label>"]` read is classified into a **closed list of patterns** (DATE_PARSE, TIMESTAMP_PARSE, REGEX_MATCH, CONST_EQUALS, CROSS_DOC_EQUALS, NON_EMPTY, COMPUTED_EQUALS, REGISTRY_EQUALS, LOOKUP_KEY, READ_ONLY, ASSIGNED). It steps through value-preserving wrappers (`(x or "")`, `.strip()`). Anything else goes to `unrecognised`. `--check` mode compares bytes with the stored artefact. |
| `generated_pdf_rules.json` | **The generated artefact**, separate from the hand rules (structure below). |
| `generated_rules_adapter.py` | Turns the artefact into executable rules with the hand-rules interface, **for comparison only**. Only syntax and identification sites become rules; E sites become "downstream UC-042 control only: <file:line>". |
| `helper_pins.json` | The SHA-256 of the two helper sources, recorded after reading them in full. A changed helper is refused (`AdapterError`) until it is reviewed and re-pinned. |
| `compare.py` | Value-level and document-level comparison. It swaps the extractor's rule tables in-process and restores them afterwards (verified), so Experiment A's module and evidence are not modified. |
| `test_generation.py` | 10 tests (§8.3) |

**Artefact contents:**
- `source_sha256` of every file read;
- `pdf_categories` (labels, requirement, source line);
- `letter_slots`;
- `policy_versions` (each with its source line);
- `helpers` (source text and hash);
- `sites`: label, categories, file, function, line, exact source line, pattern, parameters, group, `extraction_use`, consequence;
- `unrecognised`;
- `needs_manual_resolution`;
- `labels_without_consumer`;
- the explicit configuration that was applied.

**Explicit configuration (not derivable, kept visible):**
- `CONSEQUENCE_BY_FUNCTION`: what a failure in each consumer function means. Consumers in an unconfigured function make generation **fail**; no default is assumed.
- `GROUP_BY_PATTERN`.
- The pinned helper semantics.

**Artefact location:**
- `p10/smartparser_phase1/experiments/pdf_rule_generation/generated_pdf_rules.json`;
- copy in `generator/` in this folder.

---

## 6. What the generator found

**17 rule-bearing sites, 1 variable-assigned site (D), 13 read-only, 0 unrecognised:**

| Group | Pattern | Label | UC-042 site | Parameters |
|---|---|---|---|---|
| A | LOOKUP_KEY | Letter reference | prepare.py:166 `prepare_case` | `letter_ref_to_slot` |
| A | REGISTRY_EQUALS | Effective date | policy.py:76 `recognise` | `reg.effective.isoformat()` |
| B | REGEX_MATCH | Reconciliation point | validate.py:472 `setup` | `^(\d{2}):(\d{2}) Europe/London$` |
| C | DATE_PARSE | Effective date | validate.py:479 `setup` | `_date_or_none` |
| C | DATE_PARSE | Letter date | validate.py:1183 `check_designation` | `_date_or_none` |
| C | DATE_PARSE | Allocated from | validate.py:1198 `check_checklist` | `_date_or_none` |
| C | TIMESTAMP_PARSE | Submitted at | validate.py:1211 `check_checklist` | `parse_ts` |
| D | ASSIGNED | Document version | policy.py:71 `recognise` | → variable `version` (use not followed) |
| E | CROSS_DOC_EQUALS ×4 | Letter reference, Account number, Currency, Account name | validate.py:1179-1180 | IN-02 columns |
| E | CONST_EQUALS ×2 | Reconciliation method, Internal reconciliation basis | validate.py:494 | `STANDARD`, `Per currency` |
| E | NON_EMPTY | Accountable person | validate.py:1197 | – |
| E | COMPUTED_EQUALS ×3 | Period (×2), Due date | analysis.py:241, validate.py:1215, 1217 | previous month; `due.isoformat()` |

**Labels without any consumer:** Frequency, Institution, Return, Role, Safeguarding method, Submission reference. This is identical to the hand-written `NO_RULE_REASON` set.

**Needs manual resolution:** Document version (policy.py:71). The registered-version check is still derivable, from the `POLICY_VERSIONS` data.

---

## 7. Rule-by-rule comparison

**Column key:** **Equiv.** = equivalent outcome. **Safe** = the generated rule is safe to use as an extraction rule.

| # | Hand rule | Generated counterpart | UC-042 source | Equiv. | Difference | Changes review? | Safe? |
|---|---|---|---|---|---|---|---|
| 1 | LETTER-REF (X) | Slot identity is A, already enforced by the classifier. The C10 equality is E and reported downstream. | prepare.py:166; validate.py:1179 | Yes for slot resolution | The hand rule re-checks equality after the slot is already resolved by that equality: redundant | No | Yes (as identification) |
| 2–4 | ACCOUNT-NUMBER, CURRENCY, ACCOUNT-NAME (X) | none: E, "downstream UC-042 control only" | validate.py:1179-1180 | **No** | The generated set does not check letter values against IN-02 | **Yes**: E10 (`gbp`) review → DETERMINISTIC; V07 loses 1 of 2 review reasons (wrap flag still routes it) | n/a (E) |
| 5 | SAFEGUARDING-WORDING (C) | none (E) | validate.py:1181 (IN-02 value) | n/a | **The hand rule tests the wrong value** | No (CONTROL never routes) | n/a |
| 6 | LETTER-DATE syntax | `GEN:Letter date:DATE_PARSE`, pinned `_date_or_none` | validate.py:1183 | **No** | Hand strict `YYYY-MM-DD`; generated = UC-042 (first 10 characters, ISO basic and week forms) | **Yes**: E01–E03 review → DETERMINISTIC | Faithful to UC-042; whether it is *safe* is the owner's call (§10) |
| 6 | LETTER-DATE ≤ period end | none (E) | validate.py:1185 | n/a | business | No (CONTROL) | n/a |
| 7 | POLICY-VERSION | `GEN:POLICY-VERSION` (data) | policy.py:40-47 | Yes | – | No | Yes |
| 8 | POLICY-APPLIES | `GEN:POLICY-APPLIES` (restated, pinned) | policy.py:89-97 | Yes (v1.1 Sep → review, Jan → deterministic, both) | – | No | Yes, with the pin |
| 9 | POLICY-EFFECTIVE | `GEN:POLICY-EFFECTIVE` (data) | policy.py:76 | Yes | – | No | Yes |
| 10 | EFFECTIVE-BY-PERIOD-END | only the DATE_PARSE site; the comparison is D | validate.py:479-481 | Partly | Subsumed by #8; strict vs lenient syntax as #6 | No (no case reached it: registered dates are exact) | n/a |
| 11 | POLICY-POINT | `GEN:Reconciliation point:REGEX_MATCH` | validate.py:472 | **Yes** (7/7 values) | Hand `fullmatch` vs UC-042 `re.match` with `^…$`: same result | No | Yes |
| 12–14, 16 | METHOD, BASIS, GOV-PERSON, RETURN-PERIOD (C) | none (E) | validate.py:494, 1197, 1215 | n/a | business | No (CONTROL never routes) | n/a |
| 15 | GOV-ALLOCATED-FROM syntax | `GEN:Allocated from:DATE_PARSE` | validate.py:1198 | **No** | As #6 | **Yes**: E09 review → DETERMINISTIC | as #6 |
| 17 | RETURN-SUBMITTED-AT | `GEN:Submitted at:TIMESTAMP_PARSE` | validate.py:1211 | **Yes** (7/7 values, including `Z`, space separator and basic format) | – | No | Yes |
| 18 | DUE-DATE-FORMAT | none: D, no UC-042 rule | validate.py:1217 (string compared with computed) | **No** | Hand invented | **Yes**: E07 (`21/09/2026`) review → DETERMINISTIC (UC-042 C16 still FAILs downstream) | n/a |
| 19 | SUBMITTED-BY-STATED-DUE | none (D) | validate.py:1207, 1217 (computed due) | **No** | Hand approximation | No (CONTROL) | n/a |
| – | NO_RULE_REASON (6) | `labels_without_consumer` (6) | consumer scan | **Yes, 6/6** | – | No | Yes |

**Focus areas the brief asked about:**

| Area | Finding |
|---|---|
| Dates | The only material divergence. The hand rules are *stricter than UC-042* on all three `_date_or_none` labels. |
| Identifiers | No identifier syntax rules exist in UC-042 for PDFs (`Letter reference`, `Submission reference` are free text); the only identifier rule is slot identity (A) |
| Required fields | Label presence is enforced by the registry and classifier (already generated), not by `rules.py` |
| Conflicting and ambiguous values | Handled by the extractor (CONFLICT, NOT_LINE_ANCHORED, AMBIGUOUS slot), **not** by value rules. Identical under both rule sets (§8). |

---

## 8. Behavioural test results

### 8.1 Value level (`comparison/value_level_comparison.json`)

44 syntax values plus 10 due-date values. UC-042 ground truth: its real helpers executed read-only in its own environment (`comparison/uc042_helper_oracle.json`).

| Label | Values | Hand = UC-042 | Generated = UC-042 |
|---|---|---|---|
| Letter date, Allocated from, Effective date (`_date_or_none`) | 10 each | 6/10 each: `20260507`, `2026-05-07T09:00`, `2026-05-07 (board minute 12)` and `2026-W19-4` are rejected by the hand rules but read by UC-042 | **10/10 each** |
| Submitted at (`parse_ts`) | 7 | 7/7 | 7/7 |
| Reconciliation point (regex) | 7 | 7/7 | 7/7 |
| **Total (syntax)** | **44** | **32/44** | **44/44** |
| Due date | 10 | (UC-042 has no syntax rule) the hand rule flags 8 of 10 | no rule, as in UC-042 |

### 8.2 Document level (`comparison/document_level_comparison.json`)

30 documents: the 20 Experiment A cases unchanged, plus 10 A2 edge PDFs built into an isolated folder (`edge_pdfs/`).

| Set | Same decision | Same extracted values and statuses |
|---|---|---|
| Experiment A real PDFs (9 cases) | **9/9** | 9/9 |
| Experiment A constructed variants (11) | **11/11** (missing, conflict, near miss, table, image-only, wrap, unregistered, malformed timestamp, unknown reference, business failure) | 11/11 |
| A2 edge PDFs (10) | **4/10** | 10/10 |

**The six differing edge cases.** In every one, hand = HUMAN_REVIEW and generated = DETERMINISTIC.

| Case | Value | Why it differs | What UC-042 does |
|---|---|---|---|
| E01 | Letter date `20240301` | Hand is stricter than UC-042 | reads 2024-03-01 |
| E02 | `2024-03-01 (original issue)` | same | reads 2024-03-01 |
| E03 | `2024-W09-5` | same | reads 2024-03-01 |
| E09 | Allocated from `2026-05-07 (board minute 12)` | same | reads 2026-05-07 |
| E07 | Due date `21/09/2026` | Hand rule not in UC-042 | C16-RETURN FAIL (downstream) |
| E10 | Currency `gbp` | Generated omits the E cross-document rule | C10 FAIL (downstream) |

**Same under both:** E04 (`01/03/2024`: both review), E05 (`Z` timestamp: both deterministic, UC-042 reads it), E06 (no offset: both review), E08 (`5pm`: both review).

**No uncertain value is silently accepted under either set.** MISSING, CONFLICT, unanchored, wrapped, near-miss, ambiguous and unreadable values route identically. The 6 differences are values that UC-042 can read (E01–E03, E09) or that are business-rule failures UC-042 reports downstream (E07, E10).

**Whether those six should still reach a human early is a policy question (§10), not a defect in either set.**

### 8.3 Generator tests

`experiments/pdf_rule_generation/test_generation.py`: **10/10 pass.**
- deterministic, and equal to the stored artefact;
- every label use classified or reported;
- every site traced to its exact source line;
- a changed regex in a *copy* of the source is detected;
- a missing source fails visibly;
- a consumer in an unconfigured function fails visibly;
- `--check` reports drift;
- a changed helper is refused until re-pinned;
- E sites never become extraction rules;
- generated syntax rules equal UC-042 on every oracle value.

### 8.4 Other checks

| Check | Result |
|---|---|
| Experiment A tests | 35/35 |
| Full Smart Parser suite | **620/620** (unchanged) |
| Reproducibility | The artefact regenerates byte-identically; `--check` reports "in sync" |
| Rule tables after swapping | Restored in all 30 cases |
| Original PDFs | All unchanged |
| UC-042 tree | No file written today (mtime check) |
| Experiment A evidence | Untouched (timestamps predate A2) |

---

## 9. Unsupported or ambiguous rules

| Item | Why not generated | Treatment |
|---|---|---|
| **Consequence of a rule** (PARSE / CONTROL / intake warning) | It is decided by *where* code runs, not stated as data | Explicit `CONSEQUENCE_BY_FUNCTION`; generation fails on an unmapped consumer |
| **Helper semantics** (`_date_or_none`, `parse_ts`) | Code semantics cannot be generated without executing UC-042 code | Restated in the adapter and pinned to the helper source SHA-256 |
| **Applicability algorithm** | Code, not data | Restated and pinned (same mechanism) |
| **Document version usage** | Flows through a variable | `needs_manual_resolution`; the check itself comes from the data |
| **Effective date ≤ period end** (validate.py:480) | The comparison is on a variable | Not generated; subsumed by applicability |
| **Due-date format; submitted ≤ stated due** | No UC-042 rule exists | Not generated (correctly) |
| **"Canonical form" strictness** (should `20240301` be reviewed?) | Not a UC-042 rule; a Smart Parser policy question | Owner decision |

---

## 10. Risks and limitations

1. **Pattern-matching fragility.**
   - **The risk:** the generator recognises a closed set of code shapes. A refactor that keeps behaviour but changes shape (for example `pol["Reconciliation point"]` read into a local variable first) would move a site to `needs_manual_resolution` or `unrecognised`.
   - **The safeguard:** that is **visible**, not silent: the test requires `unrecognised == []`, and `--check` fails on any change.
   - **The cost:** each UC-042 refactor may need a generator update.
2. **Data flow is not followed.** Conditions written on variables, such as `effective > self.period.end`, are not captured. Today this affects 1 label and 2 business conditions.
3. **Helper pins create review work.** Any edit to `_date_or_none` or `parse_ts` blocks the adapter until someone re-reads and re-pins it. This is intended, but it is a manual step.
4. **Fidelity versus caution.** Generated syntax rules reproduce UC-042 exactly, including leniency: ISO basic and week dates, trailing text and `Z`. If Smart Parser should route non-canonical forms to a human anyway, that needs an explicit Smart-Parser-owned policy. It cannot be generated.
5. **Dropping E rules loses early warnings.** Cross-document letter mismatches (E10) and invented checks (E07) would surface only downstream in UC-042 (C10 and C16 FAIL), not at extraction time.
6. **Drift today.** The hand rules already differ from UC-042 in 12 syntax values and contain 2 inaccurate and 2 non-UC-042 rules, written one day ago. That is direct evidence of the drift risk the brief worries about.
7. **Scope.** There are only five PDF categories and 30 test documents, so the code-shape diversity is small. The approach has not been tested on a larger rule surface.

**Maintenance comparison:**

| Approach | Upkeep | Drift detection |
|---|---|---|
| Hand rules | ~200 lines | none (demonstrated) |
| Generated | generator ~250 lines + adapter ~150 lines + 2 pins + configuration of 10 entries | automatic (`--check`, pins) |

---

## 11. Recommendation

**Partial generation is feasible; a hybrid approach is preferable.**

**Evidence:**
- All 8 extraction-relevant hand rules have a traceable generated counterpart.
- The generated syntax rules match UC-042 on 44/44 values (hand: 32/44).
- Decisions are identical on all 20 Experiment A cases.
- The generator is reproducible, traced line by line, and fails visibly.
- But 4 of the 8 still need explicit pinned semantics (C), 3 hand rules are not derivable (D), and consequences need explicit configuration.

**Proposed hybrid** (for decision; **not** implemented):

| Part | Approach |
|---|---|
| Label inventory, policy data, slot identity, regex literals, the "no UC-042 rule" set, source hashes and `--check` drift detection | **Generated** |
| Consequence mapping and helper semantics | **Explicit**, small, pinned, owner-approved |
| Strictness policy (for example "dates must be `YYYY-MM-DD`, otherwise review even if UC-042 can read them") | **Explicit Smart-Parser-owned**, recorded as such, never presented as a UC-042 rule |
| Business-level (E) rules | **Removed from extraction validation**; reported as downstream UC-042 references, or kept only as explicitly labelled early-warning checks if the owner wants them |
| The hand-rule defects (#5, #6/#10/#15 docstring, #18, #19) | **Corrected or removed**, whichever approach is chosen |

**Owner decisions needed before any integration:**
1. Should values UC-042 can read but in a non-canonical form (`20240301`, `2024-W09-5`, trailing text, `Z`) go to human review? (This decides the 4 date differences.)
2. Should business-level cross-document checks (letter vs IN-02) stay as early warnings at extraction, or live only in UC-042? (This decides E10 and part of V07.)
3. Who reviews and re-pins helper semantics when UC-042 changes them?

**This report is evidence for a decision, not approval to integrate.** Nothing in `smartparser/` was changed by A2.

---

## Files in this folder

| Path | Content |
|---|---|
| `PDF_VALIDATION_RULE_GENERATION_FEASIBILITY_REPORT.md` | This report |
| `generator/` | `generate_rules.py`, `generated_pdf_rules.json` (the artefact), `generated_rules_adapter.py`, `helper_pins.json`, `compare.py`, `test_generation.py` |
| `comparison/` | `value_level_comparison.json`, `document_level_comparison.json`, `comparison_summary.json`, `uc042_helper_oracle.json` |
| `edge_pdfs/` | The 10 A2 edge-case PDFs and `edge_manifest.json` |

**Reproduce** (from `p10/smartparser_phase1`):

```
py -3.11 experiments/pdf_rule_generation/generate_rules.py --uc042-root ../uc042_token_optimisation --out experiments/pdf_rule_generation/generated_pdf_rules.json --check
py -3.11 experiments/pdf_rule_generation/compare.py tests/fixtures/uc042_canonical ../pdfx_experiment/constructed ../pdfx_experiment_a2 <out_dir>
py -3.11 -m pytest experiments/pdf_rule_generation/test_generation.py -q
```
