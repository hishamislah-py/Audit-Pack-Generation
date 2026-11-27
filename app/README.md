# UC-042 Standalone Smart Parser (POC)

Deterministic-first parser for UC-042 evidence files (IN-01 … IN-19). It is
independent of the UC-042 application at runtime. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Status

| Phase | State |
|---|---|
| 1 Foundation (structure, interfaces, schema registry, metadata) | done |
| 2 Deterministic CSV engine | done - tested against synthetic schemas |
| Smart Parser Phase 1 (18 Nov 2026): authoritative registry + content classification | done - see [docs/PHASE1_REGISTRY_AND_CLASSIFICATION.md](docs/PHASE1_REGISTRY_AND_CLASSIFICATION.md) |
| Smart Parser Phase 2 (18 Nov 2026): controlled CSV column mapping | done - reorder / policy whitespace+case / BA-approved aliases only (`smartparser/mapping/controlled.py`, `mapping/rules/`); corpus in `corpus/phase2_variations/` |
| 3 PDF engine | classification only (labels, letter slot, policy version, image-only detection); field extraction not started |
| 4 Mixed uploads / ZIP | not started (single-file intake + duplicate/period tracking done; `classify_batch` for a set of files) |
| 5 Test UI | not started |
| 6 AI assistance | not started (interface + no-op only) |

**The 19 canonical schemas are generated from the UC-042 code** (`uc042lib/schema.py` and the modules it relies on)
by a controlled import, with per-item provenance and the SHA-256 of every source module. Do not edit
`smartparser/schemas/definitions/*.json` by hand: re-run the import. Classification is by content only: an exact
canonical CSV header, or a PDF's complete key-detail label set. Near-miss headers (renamed, reordered, re-cased,
extra or missing columns) are diagnosed but **not** accepted in this phase.

## Usage

```bash
pip install -e ".[dev]"          # pydantic, charset-normalizer, pypdf (+ pytest)
python -m pytest                 # run tests (UC-042-tree tests skip when UC042_ROOT is absent)
python -m smartparser schemas    # registry coverage report
python -m smartparser classify a.csv b.pdf ...            # content-only classification of a set of files
python -m smartparser process file.csv --period 2026-10 --summary
python -m smartparser import-registry --uc042-root <UC-042 dir>           # regenerate the 19 definitions
python -m smartparser import-registry --uc042-root <UC-042 dir> --check   # prove the registry is in sync
python tools/baseline_classification.py --uc042-root <UC-042 dir> --out <dir>   # Phase 1 baseline measurement
# the engine with the synthetic test schemas:
python -m smartparser process file.csv --period 2026-10 \
    --schemas tests/fixtures/schemas --test-schemas --summary
```

```python
from smartparser import SmartParser
from smartparser.intake import EvidenceStore
from smartparser.classify.evidence import classify_batch, classify_bytes
from smartparser.schemas import SchemaRegistry

result = SmartParser(store=EvidenceStore("data/store")).process_bytes(data, "file.csv", "2026-10")
result.model_dump_json()
fc = classify_bytes(data, SchemaRegistry.from_directory())      # bytes only, no filename
fc.result.status, fc.result.category, fc.result.reason
```
