# Running the UC-042 analyst demo from a clone

Windows, Python 3.11, and optionally Node.js 20.19+ (only to rebuild the UI). Everything runs locally on `127.0.0.1`.
The only external service is OpenAI, and only when AI investigations are switched on.

## 1. Setup (once)

```bat
deploy\setup.cmd
```

This:
- creates `.venv\` at the repository root (Python 3.11);
- installs the engine's pinned dependencies (`uc042/requirements-dev.txt`) and the application (`app/`, with its `api` and `dev` extras);
- falls back to the pure-Python SQLAlchemy wheel if Windows Application Control blocks the compiled one;
- creates the ignored `.runtime\` folder.

Options:
- `-Python <path>` uses a specific Python 3.11.
- `-BuildUi` rebuilds the analyst UI from `app/ringfence-analyst-app` into `app/smartparser/webapp/analyst` with `npm ci` and `npm run build:backend`. A built copy is already committed, so this is only needed after UI changes.

No database is needed. The analyst application keeps its state (cases, uploads, runs, packs, audit log) as files in
its workspace folder, `.runtime\ws` by default. PostgreSQL and its migrations (`uc042\uc042app`, `python -m uc042app.admin
db-upgrade`) belong only to the engine's earlier FastAPI backend, which the analyst demo does not use; see `uc042\README.md`.

## 2. Create a sign-in account

```bat
deploy\create_user.cmd analyst@ringfence.demo
```

The password is prompted for, and stored only as a PBKDF2 hash in `.runtime\auth.json`.

## 3. Optional: switch on AI investigations

Copy `deploy\demo.env.example` to `.runtime\.env` and set `OPENAI_API_KEY`. Without that file the app runs with AI
**off**: Smart Parser, reconciliation, exceptions, analyst decisions and the audit pack all still work.

## 4. Start

```bat
deploy\start_demo.cmd
```

Then open <http://127.0.0.1:8780/analyst/> and sign in.

Options:
- `-Port 8960`
- `-Workspace D:\uc042\ws`
- `-AuthFile …`
- `-EnvFile …`
- `-Theme dark`
- `-AiMaxRequests 5` (hard cap of OpenAI requests per AI operation)
- `-NoRelationshipDiscovery`

What `start_demo` passes to `python -m smartparser.webapp.server`, run from `app\`:

| Setting | Value |
|---|---|
| Workspace (`--root`) | `.runtime\ws`: cases, uploads, runs, packs, audit log |
| Engine (`--uc042-root`) | `uc042\` in this repository |
| Engine interpreter (`--closure-python`) | `.venv\Scripts\python.exe` |
| Authority policy | `app\tests\fixtures\review\test_authority_policy.json`: **TEST_ONLY demo policy**, not for production |
| Demo scenarios | `demo_datasets\ringfence_demo_scenarios` |
| Mapping AI | off |
| `RINGFENCE_ENGINE_RELATIONSHIP_DISCOVERY` | `on` (engine relationship register; `-NoRelationshipDiscovery` turns it off) |

Other process-environment switches. They are not read from `.env`; their defaults match the demo server:

| Variable | Default | Meaning |
|---|---|---|
| `RINGFENCE_AUTO_RECONCILE` | on | Reconcile automatically when Smart Parser accepts the evidence |
| `RINGFENCE_AI_GROUP_INVESTIGATION` | on | One AI investigation and one analyst decision per engine investigation group |
| `RINGFENCE_AI_PARALLEL` | 64 | How many AI operations may run at once |
| `RINGFENCE_AI_CLOSING_SUMMARY` | off | AI closing summary (switched off by owner decision) |
| `SMARTPARSER_DEFAULT_THEME` | light | Default UI theme (`-Theme` overrides it) |

## 5. Demo data

Upload-ready submissions:
- `demo_datasets\september_2026\`: Clean Control, Dunmore TC04 (Smart Parser mapping) and Halden Brook (full journey). Each has a `_STEPS.md` walkthrough.
- `demo_datasets\ringfence_demo_scenarios\`: the five scenarios the server offers as demo cases.

## Tests

```bat
.venv\Scripts\python.exe -m unittest          (run in uc042\)
.venv\Scripts\python.exe -m pytest -q          (run in app\; finds the engine at ..\uc042, override with UC042_ROOT)
```

## Known limitations (proof of concept)

- A single analyst role and a TEST_ONLY authority policy: no maker-checker and no single sign-on.
- Runs on `127.0.0.1` only, with no TLS (pass `--cookie-secure` behind an HTTPS front end).
- Windows-tested; paths in the scripts are Windows-style.
- AI uses OpenAI only. Evidence records for each investigated exception are sent with `store:false`.

## Scripted scenario check

`deploy/validation/uc042_demo_journey.py` runs the September demo scenarios through the same API calls the UI makes. It
covers registration, mapping decisions, late uploads, reconciliation and the one-click audit pack, and checks the
expected results:

| Scenario | Expected result |
|---|---|
| Clean Control | CLEAN |
| Dunmore | 2 exceptions |
| Dunmore corrected | CLEAN |
| Halden Brook | 7 exceptions |

Start the server, then:

```bat
.venv\Scripts\python.exe deploy\validation\uc042_demo_journey.py --base http://127.0.0.1:8780 --password-file <file> --scenario all --out .runtime\validation --decide none
```

The analyst can have only one case in progress at a time, so use a fresh workspace (`-Workspace`) for a full run.
