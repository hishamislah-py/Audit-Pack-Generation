# Phase 7: Controlled A/B Test Plan (prepared; NOT executed)

**No live call has been made. Running this plan needs explicit owner approval of the budget below.**

## Arms

| Arm | What runs | Code |
|---|---|---|
| **A** | current behaviour: tools mode (model-directed tool loop), raw packet JSON | Clone E behaviour. In this copy, equivalent to `mode="tools"` with the phase 1–5 changes switched off. Clone E itself can serve as arm A unchanged. |
| **B** | deterministic retrieval + one fixed-mode structured request on the lossless model view | this copy, `run_investigation(..., mode="deterministic")` |

**Held equal in both arms:**
- the same deterministic pack and exception;
- model `gpt-6-luna` and reasoning effort `medium`;
- tool limits 8 / 4 / 25 / 160 / 150k (arm A);
- temporary investigations root, so nothing is published or registered;
- per-request telemetry (phase 3, in this copy; arm A on Clone E needs the 15 Nov wrapper script);
- runs alternated A, B, A, B … within one session window.

**Output budget.** Arm B uses `UC042_INVESTIGATION_MAX_OUTPUT_TOKENS` = 12,000. For a clean comparison, run arm A on this copy with the same budget. To measure the effect of the budget itself, add arm A' with 8,000.

## Subjects (≥ 3 runs per arm per exception)

| Exception | Why | Arm A measured total tokens per investigation (persisted) | Arm B ESTIMATE (input + output) |
|---|---|---|---|
| S02 EXC-01 | missing EUR bank evidence | 35,629 – 58,183 | ≈ 12k + ≈ 8k |
| SC3C EXC-01 | GBP shortfall; truncation-prone | 128,120 – 130,596 | ≈ 22–23k + ≤ 12k |
| SC3C EXC-02 | settlement shortfall | 128,655 – 130,206 | ≈ 22–23k + ≤ 12k |
| SC3C EXC-03 | cash-book link | 88,577 (truncated) | ≈ 22–23k + ≤ 12k |
| SC5A EXC-01 | candidate relationship (refused ×3) | 34,278 – 56,412 | ≈ 11.5k + ≈ 8k |
| SC5A EXC-02 | roll-forward | 36,681 – 37,409 | ≈ 11.5k + ≈ 8k |
| S05 EXC-01 | unexplained GBP difference | 58,787 – 61,969 | ≈ 21k + ≈ 8k |
| SC2 EXC-01 | settlement timing | 83,434 | ≈ 15k + ≈ 8k |
| SC5C EXC-17 | large group (bounded by rule 1.2) | not measured (≈ 40k ESTIMATE) | ≈ 13.5k + ≈ 8k |
| one uncovered route (CASE C07 / BC-VS-EOD) | B falls back to tools | same as A | same as A (verifies the fallback only) |

**How arm B is estimated.**
- The input estimate is the measured deterministic view characters (`packet_sizes.json`, rule 1.2) plus about 7.2k characters of instructions and task text, times 0.35–0.37 tokens per character (the calibration from the 15 Nov provider measurement).
- The output is assumed at the observed final-turn size of 6–9k.
- **These are estimates, not measurements.** Only provider telemetry from the runs can confirm them.

## Budget (needs owner approval)

| Option | Runs | Arm A tokens | Arm B tokens (ESTIMATE) | Total ESTIMATE |
|---|---|---|---|---|
| **Full** (9 exceptions × 3 runs × 2 arms) | 54 | ≈ 3 × 680k = **2.04M** (about 60–66% of input cached) | ≈ 3 × 227k = **0.68M** | **≈ 2.7M tokens** |
| **Minimum** (S02, SC3C-01, SC5A-01, SC2 × 3 × 2) | 24 | ≈ 0.97M | ≈ 0.28M | **≈ 1.25M tokens** |

- No currency figure is given, because no verified `gpt-6-luna` price table is available.
- Cached input is input. It is billed at a discounted rate, **not** at zero, and is reported separately.

## Measures (per run, from provider telemetry)

- requests per investigation;
- input, cached and uncached input, output and reasoning tokens per request and in total;
- latency;
- `validation_status` and refusal type;
- truncation (incomplete reason);
- citation coverage (every cited `IN-xx` checked against its source CSV with the independent method);
- findings quality (reviewer rubric: facts against interpretation, `does_not_establish` present, no causes);
- missing-evidence handling (every MISS-/NOT_FOUND kept; S02's 15 Sep balance "not available");
- candidate handling (`CAND-*` never in a confirmed finding);
- final exception status (UNRESOLVED).

## Quality gates (every B run must pass)

- VALID, with no new refusal type;
- no citation outside the ledger or packet;
- every cited value equal to its source CSV row;
- no `CAND-*` in a confirmed finding;
- every MISS item preserved;
- no causal or resolution phrase;
- the key facts present (SC3C: −4.50 on 17 days; AQ 9,954.50 against bank 9,950.00; LE-0003 9,954.50);
- all exceptions UNRESOLVED.

## Decision rule (proposal)

Adopt B for a route only if **every** B run passes every gate **and** the median total input tokens are lower than A's. Fewer requests alone is not sufficient, and cached tokens are never counted as free.
