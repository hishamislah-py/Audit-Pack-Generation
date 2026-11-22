# Smart Parser - architecture and module boundaries

Standalone POC. It does not import from or modify the UC-042 application, and
it performs no reconciliation or audit-pack generation.

## Processing flow (one file)

```
bytes ─► A intake ─► B identify ─► D read CSV ─► C classify ─► F map ─► H normalise ─► I validate ─► result
          hash/store   format/enc/    structural    category     columns→   Decimal/date/   issues
          duplicates   delimiter      only          only         fields     currency        + statuses
```

`pipeline.py` is the only module that knows about all the others. Each module
can be used and tested on its own.

| Module | Package | Input → Output | Never does |
|---|---|---|---|
| A Upload/intake | `intake/` | bytes + filename + period → `IntakeRecord` (sha256, stored path, evidence id), duplicate check | use the filename as a path or a category signal |
| B Identification | `identify/` | bytes → `FileIdentification` (format by magic bytes, encoding, delimiter) | AI; trust the extension |
| C Classification | `classify/` | CSV: header + rows + registry → `ClassificationResult` (exact canonical header for UC-042 schemas; scored tiers for synthetic ones). PDF: extracted text + registry (+ IN-02 letter references) → result. `evidence.py`: bytes-only entry point and `classify_batch` | extract or validate; use filename; accept a near-miss header |
| D CSV engine | `csv_engine/` | bytes + encoding + delimiter → `CsvTable` (original strings, row + physical line numbers, preamble, empty/ragged rows) | interpret values |
| E Schema registry | `schemas/` | JSON definitions → `SchemaDefinition` per category | invent fields |
| F Mapping | `mapping/` | headers + schema (+ templates, manual overrides) → `MappingResult` | choose arbitrarily between conflicting candidates |
| G PDF engine | `pdf_engine/` | bytes → `PdfExtraction` (per-page selectable text, image count, image-only flag). Field extraction with page references is Phase 3 | OCR; guess text from images |
| E' Registry import | `registry_import/` | UC-042 tree (read-only) → the 19 `IN-xx.json` definitions with provenance + source hashes; `--check` proves sync | define or edit a rule itself; write to the UC-042 tree |
| H Normalisation | `normalise/` | table + mapping → normalised values alongside originals | round amounts, use float, guess silently |
| I Validation | `validation/` | everything above → `ValidationResult` (issues with row/line/column/field/value) | fill or correct values |
| J AI assistance | `ai/` | *Phase 6 - Protocol + `NullAssistant` only* | anything deterministic; override validation |

## Mapping tiers (Module F)

1. exact canonical name → 2. known alias (case-insensitive) → 3. normalised name
(`Client ID` = `client-id` = `ClientId`) → 4. **validated** mapping template →
5. AI suggestion (Phase 6, advisory, never auto-applied).

Conflicts are never resolved by the engine: two source columns claiming one
field, or one column fitting two fields, are recorded in `mapping.ambiguities`,
left unmapped, and the file is marked `needs_resolution`. Extra columns are kept
in each record's `unmapped` dict and reported as INFO.

Templates (`mapping/templates.py`) store category, schema version, source columns,
order-independent layout fingerprint, mapping, version, created date, validation
outcome and status (`proposed` / `validated` / `rejected` / `superseded`). Only
`validated` templates for the same schema version are reused, and only when the
fingerprint matches or all of the template's mapped columns are present.

## Separate status dimensions

`metadata` carries independent statuses: `classification_status`,
`extraction_status`, `mapping_status`, `validation_status`, plus a roll-up
`processing_status`. `flags` exposes the spec's states as separate booleans:
`parsed_successfully`, `partially_parsed`, `missing_required_fields`,
`invalid_values`, `unmapped_columns`, `unknown_category`, `needs_resolution`.

So "recognised but not extracted" is e.g. `classification_status=identified`
with `extraction_status=failed`, or `mapping_status=schema_unavailable`.

| processing_status | meaning |
|---|---|
| completed | valid, no warnings |
| completed_with_warnings | valid; warnings (e.g. provisional schema, assumed date order) |
| completed_with_errors | processed; validation errors or partial extraction |
| needs_resolution | unknown/ambiguous category, ambiguous mapping, schema unavailable, inconsistent date/decimal convention |
| failed | file identified but could not be read |
| rejected | empty / unsupported / corrupted / too large |
| not_implemented | PDF field extraction/validation (Phase 3; PDFs are classified, see `classification_status`) and ZIP (Phase 4) |

## Normalisation rules (Module H)

* Amounts → `Decimal`, serialised as strings. No rounding, no float, scientific notation rejected.
  Handles `1,234.56`, `(50.00)`, `100-`, `£12`, `GBP 7.25`, `1 234.56`, and decimal-comma files.
* Decimal convention and day/month order are decided **per column** from unambiguous values.
  With no evidence the default (`.` / DMY) is applied **and a warning is raised**. Mixed
  conventions in one column are errors and mark the file `needs_resolution`.
* Two-digit years → 20xx with a warning. Currency codes upper-cased; unknown ISO 4217 → warning.
* Null tokens per schema (default `""`, `NULL`, `null`, `N/A`, `n/a`, `#N/A`).
* Original cell values are always kept in `record.original`.

## Schema definitions (Module E)

One JSON file per category in `smartparser/schemas/definitions/`. **Since Smart Parser Phase 1 (18 Nov 2026) all 19
are `verified` and generated** from the UC-042 code by `python -m smartparser import-registry` (module
`registry_import/uc042.py`): CSV headers, types, requiredness, enumerations, conditional rules, primary keys, period
rules and relationships for IN-01..IN-14; label sets, letter-slot resolution and recognised policy versions for
IN-15..IN-19. Each definition records the UC-042 symbol it came from and the SHA-256 of every UC-042 module read.
Generated definitions add `official_name`, `requirement`, `csv` / `pdf` contracts, `period_rule`, `relationships`,
`consumed_by_checks`, `unresolved` and `provenance` to the format below, and use `classification.match_policy:
"exact_header"`. Synthetic test schemas keep the original format. See
[PHASE1_REGISTRY_AND_CLASSIFICATION.md](PHASE1_REGISTRY_AND_CLASSIFICATION.md). Original format:

```json
{
  "category": "IN-03", "title": "...", "evidence_format": "csv",
  "optional_evidence": false, "schema_version": "1.0.0",
  "verification_status": "verified | provisional | missing",
  "definition_source": "required when verified, e.g. 'UC-042 manifest v1'",
  "fields": [
    {"name": "currency", "type": "currency_code", "required": true, "nullable": false,
     "aliases": ["CCY"], "constraints": {"allowed_values": null, "pattern": null,
     "min_value": null, "max_value": null, "min_length": null, "max_length": null,
     "max_decimal_places": null}}
  ],
  "unique_key": ["..."],
  "null_tokens": ["", "NULL", "N/A"],
  "classification": {"signature_fields": ["..."]}
}
```

Types: `string, integer, decimal, date, datetime, boolean, currency_code`.
Load-time checks reject: verified schemas without a source, duplicate fields,
aliases that collide across fields, unknown category ids, format contradicting the brief.
`provisional` schemas work but every result carries a `schema_unverified` warning.

Test-only synthetic schemas (`TST-*`) live in `tests/fixtures/schemas/`.
