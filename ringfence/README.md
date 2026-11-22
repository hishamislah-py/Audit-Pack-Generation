# Ringfence analyst application (React 18 + Vite)

The frontend for the UC-042 Smart Parser case workflow. It talks only to the existing Python backend (`smartparser.webapp.server`, a standard-library HTTP server) through the contract in `Downloads/RINGFENCE_FRONTEND_API_CONTRACT.md`.

The backend owns every business rule:
- case status;
- available actions;
- outstanding tasks;
- steps;
- validation;
- reconciliation.

This app only renders those rules and sends the analyst's actions.

## Layout

| Path | Purpose |
|---|---|
| `src/api/client.js` | Transport: JSON, the `X-Smartparser-Client` header, structured errors (`ApiError`) |
| `src/api/ringfence.js` | One function per contract endpoint; every case mutation sends `expected_revision` |
| `src/components/ui.jsx` | Ringfence design-system components (pill, notice, panel, dialog, drawer, step strip, polling hook) |
| `src/screens/` | Work queue (S02), customers (S03/S04), case workspace (S05–S14), review (S08), reconciliation and exception drawer (S12/S13) |
| `src/styles/` | `tokens.css` (generated from `assets/tokens.json`), `bundle.css` (design system, unchanged), `app.css` |
| `public/fonts/` | Self-hosted IBM Plex (OFL) |
| `legacy_esbuild/` | The previous esbuild prototype; superseded and not built |

## Run locally

All dependencies are already installed in `node_modules`, and were installed offline from the npm cache. For a fresh checkout, run `npm install --offline`.

**1. Backend** (from `p10/smartparser_phase1`):

```
py -3.11 -m smartparser.webapp.server --root C:\u42v\rf_ws ^
   --authority tests\fixtures\review\test_authority_policy.json ^
   --uc042-root C:\u42x\UC042_SMART_PARSER_E2E_TEST_BUNDLE\src\uc042 ^
   --reviewer-id analyst-1 --reviewer-role analyst --reviewer-kind TEST --port 8780
```

**2a. Development** (hot reload; `/api` is proxied to the backend):

```
cd ringfence
npm run dev            # http://127.0.0.1:5173/rf/   (backend URL: set RINGFENCE_BACKEND if not :8780)
```

**2b. Production build** (served same-origin by the backend under its CSP):

```
cd ringfence
npm run build          # writes ../smartparser/webapp/ringfence/
# open http://127.0.0.1:8780/rf/   (restart the backend after a build so it picks up the new asset names)
```

## Tests

`py -3.11 -B tools/ringfence_app_journey.py --bundle <E2E bundle> --out <dir> [--mode dev]` drives this app in headless Edge against a real backend process:
- the full analyst journey, checked through the API and the browser's own network traffic;
- the UC-042 S05 answer key;
- no JavaScript errors and no CSP violations.
