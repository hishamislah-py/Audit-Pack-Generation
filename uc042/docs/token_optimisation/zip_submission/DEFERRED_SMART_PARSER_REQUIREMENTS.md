# UC-042: Deferred ZIP Ingestion Requirements (Smart Parser Phase)

**Status: DEFERRED — NOT RESOLVED.**

These requirements come from `UC042_INDEPENDENT_IMPLEMENTATION_REVIEW.md` (17 Nov 2026). By owner decision (consolidated remediation brief §5) they are deferred to the future Smart Parser ingestion and validation layer.

**They must all be met before any Smart Parser, or the ZIP upload itself, is exposed to untrusted uploads.** Deferring them does not mean they are resolved.

Current ZIP reader: `uc042app/ingest/zip_package.py`. Package service: `uc042app/services/monthly.py` (`upload_package`, `_package_gate`).

Each item below has its location, the reproduction from the independent review, and the acceptance criteria. Reviewer probes are in the session scratchpad (`review_zip/p1.py`, `review_zip/probe_svc.py`).

---

## M5: Multiple IN-17 policy versions in one package

- **Location:** `zip_package.read_package` (duplicate-type rule: every IN-17 version counts as the same type); `monthly._set_of` → `uc042lib.policy.select`.
- **Problem:**
  - `policy.APPROVED_SELECTIONS["PER-2026-05"]` (owner decision HD-2) supplies both `safeguarding_reconciliation_policy_v1.1.pdf` and `…_v1.2.pdf`.
  - A package containing both is rejected with `duplicate_types {'IN-17': [...]}`.
  - A package with only v1.1 is `PACKAGE_INCOMPLETE` with `missing ['IN-17']`, and the gate gives no reason.
  - The code comment saying "the engine refuses more than one policy version" is wrong for approved selections.
- **Reproduction (`probe_svc.test_D`):** upload the May 2026 dataset as a ZIP for PER-2026-05, once with both policies and once with v1.1 only.
- **Acceptance:**
  - Several IN-17 versions are accepted when `policy.select` resolves them through an approved selection; otherwise the package is refused with that reason.
  - The gate reports the selection status of each version (SELECTED / SUPPLIED_NOT_SELECTED / not applicable). A supplied but unselected policy is never reported as "missing".
  - There is a test for PER-2026-05 with both versions, with v1.1 only, and with v1.2 only.

## M6: Entry-count limit and bounded ingestion reports

- **Location:** `zip_package.read_package`. Going over `max_entries` is recorded in `unsafe`, but every entry is still read, hashed and listed. `monthly.upload_package` stores `inventory` and `gate.unexpected` in the batch summary JSON, with no cap.
- **Reproduction:**
  - 20,000 empty entries (a 1.9 MB ZIP) give 20,000 `entries` and 20,000 `unexpected` in 1.22 s.
  - 5,000 junk entries give a batch summary of 2,066,723 characters.
  - The 100 MB archive cap allows about one million entries per request.
- **Acceptance:**
  - The package is rejected **before** reading any entry when the number of file entries exceeds the limit.
  - Every list in the report is capped (for example the first 100 entries plus a count).
  - The stored summary has a fixed maximum size.
  - There are tests for over-limit counts and for report size.

## M7: Storage ordering, HTTP upload size and storage-reference exposure

- **Location:**
  - `monthly.upload_package`: `self.store.put(data)` runs **before** `read_package`, including for NOT_A_ZIP and unsafe archives.
  - `api/routers/monthly.py` `upload_package`: `await file.read(max+1)` runs after the multipart body has been spooled in full.
  - `BatchDetail.summary.package.zip_storage_ref` is returned to clients.
  - `ZipLimits.from_env()` errors surface as a 500 at request time.
- **Reproduction (`probe_svc.test_F`):** a "not a zip" upload took the object store from 0 to 1 objects, referenced from a `PACKAGE_REJECTED` batch.
- **Acceptance:**
  - The package is validated first. The ZIP is stored only for packages that reach analysis; a rejected package keeps only its hash.
  - A request-body limit is enforced at the server or proxy before the body is spooled.
  - No storage reference appears in any response.
  - The limits are validated at start-up.
  - There are tests for each point.

## M8: Document-level decisions after ZIP validation and gate recomputation

- **Location:** `monthly.review_document` and `_summarise`; the stored `package.gate`.
- **Current state after the consolidated remediation:**
  - `review_document` now refuses every ZIP batch (409 `ZIP_PACKAGE_USE_SUBMIT`), so the stale-gate scenario can no longer be reached.
  - There is still no **supported** way to resolve a document that needs a decision inside a package: the package must be corrected and uploaded again.
- **Acceptance (Smart Parser phase):**
  - Define whether decisions inside a package are allowed at all.
  - If they are, the gate is recomputed after every decision, and Submit for Audit uses only the recomputed gate.
  - Tests cover excluding a required document and excluding an optional document.

## L1: Directory-entry path checks

- **Location:** `read_package`, `file_infos = [i for i in infos if not i.is_dir()]`.
- **Reproduction (`p1.py` #5, #6):**
  - Directory entries `../evil/` and `/abs/` are not reported.
  - A directory entry `hidden/` carrying 1,000 bytes of data is neither reported nor listed.
- **Acceptance:**
  - `_unsafe_path` is applied to directory names too.
  - A directory entry with a non-zero size is unsafe.
  - Tests cover both.

## L2: NUL-character path checks

- **Location:** `_unsafe_path`. Python's `zipfile` truncates the name at the first NUL, so the check never runs.
- **Reproduction (`p1.py` #4):** `recon_calendar_2026-09.csv\x00../../evil` is accepted as IN-01.
- **Acceptance:**
  - `info.orig_filename` (or the raw central-directory name) is checked for `\x00`.
  - Such an entry is unsafe.
  - There is a test for it.

## L3: Metadata path handling

- **Location:** `_is_metadata` and the `max_entries` count.
- **Reproduction (`p1.py` #8, #15):**
  - `sub/__MACOSX/x.csv` and backslash forms are not recognised as metadata.
  - 45 `__MACOSX` entries make the whole archive unsafe.
  - A Finder ZIP with extended attributes (about 41 entries) would probably be rejected. This was not reproduced with Finder itself.
- **Acceptance:**
  - Any `__MACOSX` path component is recognised, with separators normalised.
  - Metadata is excluded from the file-entry count, or has its own cap.
  - There is a test with a Finder-style archive.

## L4: Report categorisation, cascading errors, zero-byte files, IN-19 month

- **Location:** `monthly._package_gate`; `analysis.analyse_pdf` (IN-19 `WRONG_PERIOD` is only a WARNING).
- **Problems found:**
  - Unreadable files appear under both `mismatches` and `unusable`, and there is no "unreadable" category.
  - An IN-02 failure cascades into IN-15 and IN-16 mismatches.
  - A 0-byte IN-04 or IN-14 fails, because `EMPTY_FILE` is an ERROR; only header-only files pass.
  - An IN-19 whose content is for the wrong month only produces a warning.
  - One branch of `map_filename` is dead code.
- **Acceptance:**
  - A separate "unreadable" category.
  - Root-cause reporting for cascades.
  - Owner decisions on 0-byte IN-04 and IN-14 and on IN-19 month content.
  - The dead branch is removed.
  - Tests for each.

---

**Not deferred (resolved in the consolidated remediation):**
- H1/A2: the legacy endpoints on ZIP batches;
- H2/A4: legacy influence;
- M1: decision and review isolation;
- M2: final-pack chaining and cross-references;
- M3: submission retry and recovery;
- M4: per-submission reviews;
- M9: C09 hidden duplicates;
- M10: history scoping;
- L5–L12.

L13, the C09 `executed_ts` vs `allocated_ts` check, is an **accepted design risk**. It is recorded in `docs/audit_pack/20B_RECONCILIATION_CALCULATIONS.md` (C09, item 16) and was not changed.
