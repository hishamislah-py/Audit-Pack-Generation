# September 2026 demo datasets

Synthetic, upload-ready evidence packs for the September 2026 reconciliation period.
Upload each ZIP through the analyst app; follow the matching `_STEPS.md` where one exists.

| File | Scenario | Notes |
|------|----------|-------|
| `01_Clean_Control_Ltd_September_2026_CONTROL.zip` | Clean control | Everything reconciles; no exceptions expected. |
| `06_Dunmore_Payments_Ltd_September_2026_TC04_initial_mapping.zip` | TC04 – Smart Parser mapping | First upload stops for a mapping review; the refused file in `06_..._upload_later/` is re-uploaded and mapped. Reconciliation finds the €650 unmatched bank credit (2 exceptions, AI-investigated). See `06_..._TC04_STEPS.md`. |
| `07_Dunmore_Payments_Ltd_September_2026_TC04_corrected.zip` | TC04 – corrected resubmission | Corrected submission for the same customer; comes back CLEAN. |
| `15_Halden_Brook_Payments_Ltd_September_2026.zip` | Full end-to-end demo | One run shows everything: 4-column mapping review, missing settlement lines file (in `15_..._upload_later/`), two reconciliation problems, AI investigation, accept/reject and audit pack PDF. See `15_..._STEPS.md`. |
