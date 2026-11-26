# Audit Pack Generation (UC-042)

Safeguarding reconciliation and audit pack generation for e-money and payment firms.

The system takes a firm's monthly evidence (bank statements, cashbook, client balances, settlements, reconciliations and
supporting PDFs), and:
- **Smart Parser** identifies and validates every file and asks a person to confirm any column mapping;
- the **UC-042 engine** checks every safeguarding control deterministically and raises one exception per root cause;
- **AI** investigates each exception, or group of related exceptions, with cited evidence;
- an **analyst** accepts or rejects each finding in the web application;
- the system then produces an audit-ready pack (JSON, HTML and PDF).

> All data in this repository is **synthetic**. It describes no real firm, bank, client or account.

> **Branch `internal/uc042-consolidated-poc`** is the integration and testing branch that consolidates the latest engine,
> Smart Parser and analyst application. See [`docs/consolidation/`](docs/consolidation/) for its provenance and validation.

## How it works

1. **Intake (Smart Parser).** Evidence files (a ZIP or single files) are identified by content (exact CSV headers, PDF key details), hashed, and recorded. File names are never trusted. A renamed column is never accepted automatically: the analyst confirms each mapping. Missing files can be uploaded later.
2. **Validation.** Every row is structure-checked before any calculation. Invalid rows are excluded and reported; missing evidence yields `INSUFFICIENT_EVIDENCE`, never zero or PASS.
3. **Reconciliation (engine).** Requirement, resource, ledger and bank balances are recomputed from source data, never taken from the firm's reported figures. Links come from identifiers and references, never from matching amounts. A deterministic reconciliation statement ("Everything checks out" / "Not everything checks out") summarises the result.
4. **Exceptions.** One exception per root cause, each citing the source rows (`file#Lline`) behind it. Effects are grouped with their cause through evidence-backed relationships.
5. **AI investigation.** Each investigation group is investigated by an LLM (OpenAI) with read-only, validated evidence tools. AI never changes an exception's status.
6. **Analyst review.** The analyst accepts or rejects each finding, with an optional note. Rejected AI text is kept out of the pack.
7. **Audit pack.** A write-once pack with control results, exceptions, investigations and analyst decisions, rendered to HTML and PDF, with a hash manifest.

Each case ends in one of three statuses: `CLEAN`, `EXCEPTIONS_OPEN` or `EVIDENCE_INCOMPLETE`.

## Repository layout

| Path | Contents |
| --- | --- |
| [`app/`](app/) | **Application:** Smart Parser (`smartparser/`), the analyst web application (backend `smartparser/webapp/`, built UI `smartparser/webapp/analyst/`, React source `ringfence-analyst-app/`), tests, tools, docs, research corpus |
| [`uc042/`](uc042/) | **Engine:** reconciliation, exceptions, AI investigation, final pack rendering (`uc042lib/`); FastAPI backend (`uc042app/`); tests, test data, verifiers, scenario datasets, Jan–Aug demo history, design docs |
| [`uc042/frontend/`](uc042/frontend/) | **Legacy** React UI for the earlier FastAPI backend. It is not part of the analyst demo; see its README. |
| [`demo_datasets/`](demo_datasets/) | Upload-ready demo submissions (`september_2026/`) and the server's demo scenarios (`ringfence_demo_scenarios/`) |
| [`deploy/`](deploy/) | Setup, account creation and start scripts, plus an AI settings example; see [`deploy/README.md`](deploy/README.md) |
| [`docs/consolidation/`](docs/consolidation/) | How this branch was assembled, what was excluded, and the validation reports |

The application reaches the engine only through its `--uc042-root` folder (default: the sibling `uc042/`), and runs the engine in a separate Python process.

## Quick start (Windows, Python 3.11)

```bat
deploy\setup.cmd
deploy\create_user.cmd analyst@ringfence.demo
deploy\start_demo.cmd
```

Then open <http://127.0.0.1:8780/analyst/>. AI investigations are off until you put an OpenAI key in `.runtime\.env`
(copy `deploy\demo.env.example`). Full details: [`deploy/README.md`](deploy/README.md).

**Engine from the command line:**

```powershell
cd uc042
..\.venv\Scripts\python.exe -m uc042lib.pack.generate uc042_dataset/set_01_clean_baseline
```

Engine configuration, the scenario catalogue and the earlier FastAPI backend are described in [`uc042/README.md`](uc042/README.md).

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
- Smart Parser never accepts a renamed column on its own: a person confirms every mapping.
- AI explains; people decide. AI output never closes an exception.
- Audit packs and investigations are write-once.
