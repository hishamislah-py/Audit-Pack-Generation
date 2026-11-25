# Audit Pack Generation (UC-042)

Safeguarding reconciliation and audit pack generation for e-money and payment firms.

The system takes a firm's monthly evidence (bank statements, cashbook, client balances, settlements, reconciliations and supporting PDFs), checks every safeguarding control deterministically, raises one exception per root cause, lets AI investigate each exception with cited evidence, and produces an audit-ready pack (JSON, HTML and PDF) that an analyst reviews and signs off.

> All data in this repository is **synthetic**. It describes no real firm, bank, client or account.

## How it works

1. **Intake.** Evidence files are identified by content (exact CSV headers, PDF key details), hashed, and recorded in a manifest. File names are never trusted.
2. **Validation.** Every row is structure-checked before any calculation. Invalid rows are excluded and reported; missing evidence yields `INSUFFICIENT_EVIDENCE`, never zero or PASS.
3. **Reconciliation.** Requirement, resource, ledger and bank balances are recomputed from source data, never taken from the firm's reported figures. Links come from identifiers and references, never from matching amounts.
4. **Exceptions.** One exception per root cause, each citing the source rows (`file#Lline`) behind it.
5. **AI investigation.** Each exception is investigated by an LLM (OpenAI by default) with read-only, validated evidence tools. AI never changes an exception's status; an analyst accepts or rejects every finding.
6. **Audit pack.** A write-once pack with control results, exceptions, investigations and analyst decisions, rendered to HTML and PDF.

Each case ends in one of three statuses: `CLEAN`, `EXCEPTIONS_OPEN` or `EVIDENCE_INCOMPLETE`.

## Repository layout

| Path | Contents |
| --- | --- |
| [`uc042/uc042lib/`](uc042/uc042lib/) | Core engine: schema and file contract, row validation, period rules, reconciliation checks, pack generation, AI investigation, final pack rendering |
| [`uc042/uc042app/`](uc042/uc042app/) | FastAPI backend: ingestion, background jobs, PostgreSQL persistence and migrations, monthly document archive |
| [`uc042/frontend/`](uc042/frontend/) | React + TypeScript + Vite analyst UI |
| [`uc042/tests/`](uc042/tests/) | Unit, regression and golden tests (offline; no API key needed) |
| [`uc042/tools/`](uc042/tools/) | Independent dataset and output verifiers |
| [`uc042/uc042_dataset/`](uc042/uc042_dataset/) | Clean baseline plus scenario datasets, each with an answer key |
| [`uc042/packs/`](uc042/packs/), [`uc042/investigations/`](uc042/investigations/), [`uc042/demo_history/`](uc042/demo_history/) | Reference audit packs, AI investigations and Jan–Aug historical demo data |
| [`uc042/docs/`](uc042/docs/) | Input evidence spec, upload contract, period and header rules, source-to-control matrix, phase reports |
| [`demo_datasets/september_2026/`](demo_datasets/september_2026/) | Upload-ready demo ZIPs: Clean Control, Dunmore Payments (Smart Parser mapping) and Halden Brook (full end-to-end demo) |

## Quick start

Requirements: Python 3.11, Node.js 20.19+, and PostgreSQL (optional; needed only for the monthly archive features).

```powershell
cd uc042
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m unittest                      # offline test suite
```

Copy `uc042/.env.example` to `uc042/.env` and set `OPENAI_API_KEY` for live AI investigations. `.env` is git-ignored; never commit it.

**Backend API**

```powershell
python -m uc042app.admin db-upgrade     # create / migrate the PostgreSQL schema (if UC042_DATABASE_URL is set)
python -m uc042app                      # http://127.0.0.1:8000/docs
```

**Frontend**

```powershell
cd uc042/frontend
npm install
npm run dev                             # http://127.0.0.1:5173
```

**Generate an audit pack from the command line**

```powershell
python -m uc042lib.validate uc042_dataset/set_01_clean_baseline
python -m uc042lib.pack.generate uc042_dataset/set_01_clean_baseline
```

Full instructions, configuration variables and the scenario catalogue are in [`uc042/README.md`](uc042/README.md).

## Demo datasets

[`demo_datasets/september_2026/`](demo_datasets/september_2026/) holds ready-to-upload evidence packs for September 2026:

| Dataset | Shows |
| --- | --- |
| Clean Control Ltd | A clean month: everything reconciles |
| Dunmore Payments Ltd (TC04) | Smart Parser column mapping, re-upload of a refused file, a €650 unmatched bank credit, then a corrected CLEAN submission |
| Halden Brook Payments Ltd | The full demo in one run: column mapping, a missing file uploaded later, two reconciliation problems, AI investigation, accept/reject and the audit pack PDF |

Each has a `_STEPS.md` walkthrough.

## Design principles

- Reported values are never trusted; every balance is recomputed from source files.
- Missing evidence is `INSUFFICIENT_EVIDENCE`, never zero and never PASS.
- Every comparison stays in one currency; there is no FX conversion.
- One exception per root cause, with line-level citations to the source rows.
- AI explains; people decide. AI output never closes an exception.
- Audit packs and investigations are write-once.
