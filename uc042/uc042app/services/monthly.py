"""Monthly document management: reconciliation periods, upload batches, source documents and processing runs.

Pipeline: upload -> validation (content identification, dates, duplicates, completeness) -> analyst decisions on flagged
documents -> confirm -> processing job (prepare the case with uc042lib.prepare, build the pack with
uc042lib.pack.generate.build, publish it write-once) -> the existing exception / investigation / review workflow.

Rules kept here:
  * Nothing is deleted or overwritten. Originals are content-addressed; a later batch SUPERSEDES an earlier document of the
    same evidence type for future processing runs, and the earlier document stays in the archive.
  * Records are never moved between months. Dates outside the selected month are reported, not corrected.
  * Duplicates are flagged and need an explicit analyst decision (INCLUDE / EXCLUDE, with a comment) before confirmation.
  * A run that cannot produce a verified pack is FAILED, never reported as a success.
  * The engine is period-configurable (uc042lib.period.PeriodConfig): every run passes the period's own configuration to
    case preparation and pack generation; no business logic is duplicated here. A month is processed when its mandatory
    inputs are present and valid for that month.
"""
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import threading
from datetime import date, datetime
from pathlib import Path

from uc042lib import policy, schema
from uc042lib.pack import model as pack_model
from uc042lib.pack.generate import build
from uc042lib.period import PeriodConfig, PeriodError
from uc042lib.prepare import prepare_case, selected_policy

from .. import ids
from ..clock import now_iso
from ..errors import Conflict, InvalidInput, NotFound, ServiceUnavailable
from ..repositories.base import DuplicateRecord
from ..ingest import analysis as A
from ..ingest.store import DocumentStore, StoreError

log = logging.getLogger("uc042app")

SUBMISSION_KINDS = ("INITIAL", "ADDITIONAL_EVIDENCE", "CORRECTION")
SUPPORTING_CATEGORY = "Supporting evidence (not a reconciliation input)"
MAX_FILES = 60
MAX_FILE_BYTES = 50 * 1024 * 1024
BATCH_ID_RE = re.compile(r"^UPL-[0-9a-f]{24}$")
BASELINE_FILE_RE = re.compile(r"^(source_data/[A-Za-z0-9_.-]+\.csv|supporting_documents/[A-Za-z0-9_.-]+\.pdf)$")
BASELINE_REF = "BASELINE"  # a document-set entry taken from the verified source inventory of a registered pack
DOCUMENT_ID_RE = re.compile(r"^DOC-[0-9a-f]{24}$")
RUN_ID_RE = re.compile(r"^RUN-[0-9a-f]{24}$")
RUN_PURPOSES = ("INITIAL", "REASSESSMENT")


def processing_supported(period_id):
    """Whether the engine can process the month: a valid reporting period for which at least one registered safeguarding
    policy version (IN-17, a required input) applies. Without an applicable policy no document set can be complete."""
    return processing_limitation(period_id) is None


def processing_limitation(period_id):
    """Why the month cannot be processed, or None."""
    try:
        period = PeriodConfig.from_id(period_id)
    except PeriodError as e:
        return f"not a processable reporting period: {e}"
    if not policy.applicable_versions(period):
        first = min(v.effective for v in policy.POLICY_VERSIONS.values())
        return (f"no registered safeguarding policy version applies to {period.label} (the earliest takes effect on {first}); "
                "the policy (IN-17) is a required input, so the month cannot be processed")
    return None


def _check(regex, value, what):
    if not isinstance(value, str) or not regex.match(value):
        raise InvalidInput(f"invalid {what}", code="INVALID_ID")
    return value


def _safe_name(name):
    name = Path(str(name or "")).name.strip()  # metadata only; the stored object is named by its hash
    name = re.sub(r"[\x00-\x1f]", "", name)[:255]
    return name or "unnamed"


class MonthlyService:
    def __init__(self, settings, repos, packs, runner, final_packs=None):
        self.settings, self.repos, self.packs, self.runner = settings, repos, packs, runner
        self.final_packs = final_packs  # published final packs and their reassessment lineage (FinalPackService)
        self.store = DocumentStore(settings.document_store, settings.datasets_root) if settings.document_store else None
        self._lock = threading.RLock()  # serialises batch state changes (single backend process)

    # ------------------------------------------------------------------ guards
    def _require(self):
        if self.repos.periods is None or self.store is None:
            raise ServiceUnavailable("monthly document management needs the PostgreSQL database (UC042_DATABASE_URL) and a "
                                     "document store", code="DATABASE_REQUIRED")

    def _period(self, period_id):
        try:
            A.parse_period(period_id)
        except ValueError:
            raise InvalidInput("invalid period id (expected PER-YYYY-MM)", code="INVALID_ID") from None
        p = self.repos.periods.get(period_id)
        if p is None:
            raise NotFound("reconciliation period not found")
        return p

    def _activity(self, action, entity_type, entity_id, **details):
        self.repos.activity.append({"at": now_iso(), "actor": self.settings.analyst_id, "action": action,
                                    "entity_type": entity_type, "entity_id": entity_id, "details": details})

    # ------------------------------------------------------------------ periods
    @staticmethod
    def _title(title):
        title = re.sub(r"\s+", " ", str(title or "")).strip()
        if title and not 3 <= len(title) <= 120:
            raise InvalidInput("the report title must be 3 to 120 characters", code="INVALID_TITLE")
        return title

    def create_period(self, year, month, title=None):
        """Open a month for upload. Only the current or a past month; nothing is created inside the period. The period ID
        (PER-YYYY-MM) is derived from the month and is the immutable key. If the month already exists it is returned
        unchanged (created False): a second period for the same month is never created, and its title is not altered
        (renaming is the explicit rename_period action)."""
        self._require()
        if not (2000 <= year <= 2100 and 1 <= month <= 12):
            raise InvalidInput("invalid year or month")
        today = date.today()
        if (year, month) > (today.year, today.month):
            raise InvalidInput("a reconciliation period cannot be opened for a future month", code="FUTURE_PERIOD")
        title = self._title(title)
        pid = A.period_id(year, month)
        existed = self.repos.periods.get(pid) is not None
        p = self.repos.periods.ensure(pid, year, month, title=title)
        if not existed:
            self._activity("PERIOD_OPENED", "period", pid, title=title)
        return p, not existed

    def rename_period(self, period_id, title):
        """Change a period's report title (explicit action, recorded). The period ID and every pack reference stay as they are."""
        self._require()
        p = self._period(period_id)
        title = self._title(title)
        if not title:
            raise InvalidInput("the report title must not be empty", code="INVALID_TITLE")
        previous = p.get("title") or ""
        if title == previous:
            return p
        with self._lock:
            p = self.repos.periods.update(period_id, {"title": title})
        self._activity("PERIOD_RETITLED", "period", period_id, previous_title=previous, title=title)
        return p

    def periods(self):
        self._require()
        return self.repos.periods.list()

    def period_detail(self, period_id):
        self._require()
        p = self._period(period_id)
        batches = self.repos.uploads.batches(period_id)
        docs = self.repos.uploads.documents(period_id=period_id)
        current = self.current_set(period_id)
        return {"period": p, "batches": batches, "documents": docs, "runs": self.repos.runs.list(period_id=period_id),
                "packs": self.repos.periods.packs(period_id), "current_set": current,
                "missing_required": [f for f in A.REQUIRED_IDS if f not in current],
                "processing_supported": processing_supported(period_id), "processing_limitation": processing_limitation(period_id)}

    # ------------------------------------------------------------------ document sets
    @staticmethod
    def _usable(doc):
        return (doc["validation_status"] != "ERROR" and doc["review_decision"] != "EXCLUDE" and doc["evidence_id"]
                and not (doc["checks"].get("decision_required") and doc["review_decision"] != "INCLUDE"))

    def current_set(self, period_id, through_batch=None):
        """{evidence_id: document_id}: the latest usable document of each type over CONFIRMED batches (in confirmation
        order), plus `through_batch` (being validated) last. Earlier versions stay archived; they are superseded only.

        Policies (IN-17) are kept per version: "IN-17" is the version that governs the month (uc042lib.policy.select:
        the single applicable version or the month's approved selection) and "IN-17@vN.N" another applicable version
        that stays in the source inventory without governing reconciliation. No governing version: no "IN-17" entry."""
        out = {}
        batches = [b for b in self.repos.uploads.batches(period_id) if b["confirmed_at"]]
        batches.sort(key=lambda b: b["confirmed_at"])
        if through_batch is not None:
            batches = [b for b in batches if b["batch_id"] != through_batch] + [{"batch_id": through_batch}]
        for b in batches:
            for d in self.repos.uploads.documents(batch_id=b["batch_id"]):
                if self._usable(d):
                    out[A.slot(d)] = d["document_id"]
        versions = {k.split("@v", 1)[1]: out.pop(k) for k in [k for k in out if k.startswith("IN-17@v")]}
        if versions:
            chosen, _, status = policy.select(period_id, {v: 1 for v in versions})
            for v, doc_id in versions.items():
                if v == chosen:
                    out["IN-17"] = doc_id
                elif status[v][0] == policy.SUPPLIED_NOT_SELECTED:
                    out[f"IN-17@v{v}"] = doc_id
        return out

    def policy_selection(self, period_id, current):
        """The month's policy selection (recorded in the batch summary and the processing run)."""
        selected = current.get("IN-17")
        approved = policy.APPROVED_SELECTIONS.get(period_id)
        return {"selected_version": A.policy_version(self.repos.uploads.document(selected)) if selected else None,
                "selected_document": selected, "approved_selection": approved.decision if approved else None,
                "supplied_not_selected": sorted(k.split("@v", 1)[1] for k in current if k.startswith("IN-17@v"))}

    # ------------------------------------------------------------------ published packs, reassessment and verified baselines
    def published_final_packs(self, period_id):
        """Final audit packs published from the period's deterministic packs, oldest first (by generation time)."""
        if self.final_packs is None:
            return []
        packs = {r["pack_id"] for r in self.repos.periods.packs(period_id)}
        return sorted((f for f in self.final_packs.list() if f["pack_id"] in packs), key=lambda f: f["generated_at"])

    def reassessment_target(self, period_id):
        """(latest final pack, its source pack ID): what a reassessment of the period reassesses, or (None, None)."""
        finals = self.published_final_packs(period_id)
        return (finals[-1], finals[-1]["pack_id"]) if finals else (None, None)

    def baseline(self, pack_id, period_id):
        """The verified source inventory a reassessment starts from: the source files of the lineage's FIRST pack, read in
        place from that pack's own dataset folder in its own storage root set. Only files the pack's evidence register lists
        as PRESENT with a SHA-256, only under source_data/*.csv and supporting_documents/*.pdf (never answer keys, scenario
        definitions or verification material), only for the same month. Returns None when the lineage starts from uploaded
        documents (their latest confirmed versions are already the period's document set). Raises Conflict
        BASELINE_UNVERIFIABLE when a listed file is missing or its content differs from the recorded hash."""
        root_id = self.final_packs.lineage_root(pack_id) if self.final_packs is not None else pack_id
        pack = self.packs.load(root_id)
        if pack["metadata"]["reporting_period"]["period_id"] != period_id:
            raise Conflict(f"the lineage of {pack_id} starts from a pack of another month", code="BASELINE_UNVERIFIABLE")
        dataset = pack["metadata"]["source_dataset"].get("dataset", "")
        roots = self.packs.root_set(root_id)
        datasets_root = Path(roots.datasets_root).resolve()
        folder = (datasets_root / dataset).resolve() if dataset else None
        if folder is None or datasets_root not in folder.parents or not folder.is_dir():
            return None
        files, problems = {}, []
        for f in pack["evidence_register"]["files"]:
            if f.get("availability") != "PRESENT" or not f.get("sha256") or not f.get("evidence_id"):
                continue  # missing evidence stays missing; nothing is substituted
            rel = str(f.get("source_file") or "")
            if not BASELINE_FILE_RE.match(rel):
                problems.append(f"{f['evidence_id']}: {rel or '(no path)'} is not a source document location")
                continue
            path = (folder / rel).resolve()
            if folder not in path.parents:
                problems.append(f"{f['evidence_id']}: outside the dataset folder")
                continue
            try:
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                problems.append(f"{f['evidence_id']}: {rel} cannot be read")
                continue
            if actual != f["sha256"]:
                problems.append(f"{f['evidence_id']}: {rel} does not match its recorded SHA-256")
                continue
            files[f["evidence_id"]] = {"source_file": rel, "sha256": f["sha256"], "file_format": "PDF" if rel.endswith(".pdf") else "CSV"}
        if problems:
            raise Conflict("the original source documents of " + root_id + " cannot be verified: " + "; ".join(problems[:5]),
                           code="BASELINE_UNVERIFIABLE", extra={"problems": problems})
        return {"pack_id": root_id, "dataset": dataset, "storage_profile": roots.name, "files": files}

    def _baseline_bytes(self, baseline, fid):
        """Read one baseline file again and verify it (at use time, not only when the plan was made)."""
        f = baseline["files"][fid]
        roots = self.packs.root_set(baseline["pack_id"])
        folder = (Path(roots.datasets_root) / baseline["dataset"]).resolve()
        path = (folder / f["source_file"]).resolve()
        if folder not in path.parents:
            raise RuntimeError(f"{fid}: outside the dataset folder")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != f["sha256"]:
            raise RuntimeError(f"{fid}: {f['source_file']} changed since it was verified")
        return data

    def reassessment_plan(self, period_id, pending_reassessment=None):
        """What a reassessment of the period would use (read-only): the pack being reassessed, the documents received after
        publication, the verified baseline and the uploaded documents that supersede it, and what is still missing."""
        self._require()
        self._period(period_id)
        final, target = self.reassessment_target(period_id)
        uploaded = self.current_set(period_id)
        plan = {"period_id": period_id, "latest_final_pack_id": final["final_pack_id"] if final else None,
                "latest_final_pack_at": final["generated_at"] if final else None, "target_pack_id": target,
                "pending_reassessment": bool(pending_reassessment), "uploaded_set": uploaded, "baseline": None,
                "baseline_problems": [], "effective_set": {}, "missing_required": [], "new_documents": [], "can_reassess": False,
                "blockers": []}
        if final is not None:
            plan["new_documents"] = [{k: d[k] for k in ("document_id", "original_filename", "evidence_id", "category",
                                                        "submission_kind", "submission_reason", "created_at", "validation_status",
                                                        "batch_id")}
                                     for d in self.repos.uploads.documents(period_id=period_id)
                                     if datetime.fromisoformat(d["created_at"]) > datetime.fromisoformat(final["generated_at"])]
            try:
                plan["baseline"] = self.baseline(target, period_id)
            except Conflict as e:
                plan["baseline_problems"] = e.extra.get("problems") or [e.detail]
        base = (plan["baseline"] or {}).get("files", {})
        plan["effective_set"] = {fid: {"source": "UPLOADED", "document_id": doc} for fid, doc in uploaded.items()}
        for fid, f in base.items():
            plan["effective_set"].setdefault(fid, {"source": BASELINE_REF, "pack_id": plan["baseline"]["pack_id"], **f})
        plan["missing_required"] = [f for f in A.REQUIRED_IDS if f not in plan["effective_set"]]
        confirmed = [b for b in self.repos.uploads.batches(period_id) if b["origin"] == "UPLOAD"
                     and b["status"] not in ("VALIDATED", "ARCHIVED_SCENARIO")]
        if final is None:
            plan["blockers"].append("no final audit pack has been published for this period (use the initial processing instead)")
        if not pending_reassessment:
            plan["blockers"].append("no evidence was received after the latest final audit pack")
        if not confirmed:
            plan["blockers"].append("confirm the batch holding the new evidence first")
        if plan["baseline_problems"]:
            plan["blockers"].append("the original source documents cannot be verified")
        if plan["missing_required"]:
            plan["blockers"].append("required evidence is missing: " + ", ".join(plan["missing_required"]))
        plan["can_reassess"] = not plan["blockers"]
        return plan

    # ------------------------------------------------------------------ upload and validation
    def _submission(self, period_id, files, kind, reason, replaces):
        """Validate how documents are being added: INITIAL source documents, ADDITIONAL_EVIDENCE for the period, or a
        CORRECTION of one earlier document of the same period (that document is never changed)."""
        if kind not in SUBMISSION_KINDS:
            raise InvalidInput(f"submission kind must be one of {', '.join(SUBMISSION_KINDS)}", code="INVALID_SUBMISSION")
        reason = re.sub(r"\s+", " ", str(reason or "")).strip()[:2000]
        if kind != "INITIAL" and len(reason) < 3:
            raise InvalidInput("a reason is required when adding evidence or a correction", code="REASON_REQUIRED")
        if kind != "CORRECTION":
            if replaces:
                raise InvalidInput("only a correction replaces an earlier document", code="INVALID_SUBMISSION")
            return reason, None
        if len(files) != 1:
            raise InvalidInput("a correction replaces exactly one earlier document: upload one file", code="INVALID_SUBMISSION")
        earlier = self.repos.uploads.document(_check(DOCUMENT_ID_RE, replaces or "", "replaced document id"))
        if earlier is None or earlier["reporting_period"] != period_id:
            raise InvalidInput("the replaced document must be an earlier document of this period", code="INVALID_SUBMISSION")
        return reason, earlier

    def upload(self, period_id, files, submission_kind="INITIAL", reason="", replaces_document_id=None, published_final_packs=()):
        """files: [(original_filename, bytes)]. Stores every original, analyses it and records a batch. Nothing is
        processed here. submission_kind / reason / replaces_document_id record how the documents were added (_submission).
        published_final_packs: final audit packs already published for the period; documents received afterwards are
        marked as not yet incorporated in them (pending reassessment). Nothing published is changed."""
        self._require()
        period = self._period(period_id)
        if not files:
            raise InvalidInput("no files were uploaded", code="NO_FILES")
        reason, earlier = self._submission(period_id, files, submission_kind, reason, replaces_document_id)
        if len(files) > MAX_FILES:
            raise InvalidInput(f"at most {MAX_FILES} files per batch", code="TOO_MANY_FILES")
        for name, data in files:
            if len(data) > MAX_FILE_BYTES:
                raise InvalidInput(f"{_safe_name(name)} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB", code="FILE_TOO_LARGE")
        year, month = period["year"], period["month"]
        batch_id, created = ids.new_id("UPL"), now_iso()
        docs = []
        for name, data in files:
            name = _safe_name(name)
            ref, sha = self.store.put(data)  # stored first: an upload is never lost, even if analysis rejects it
            try:
                a = A.analyse_file(self.store.path(ref), name, year, month)
            except Exception as e:  # an unreadable file is recorded as an ERROR document, never dropped
                log.warning("analysis failed for an uploaded file: %s", type(e).__name__)
                a = {"original_filename": name, "size_bytes": len(data), "evidence_id": None, "category": None, "file_format": "OTHER",
                     "record_count": None, "date_from": None, "date_to": None, "slot_candidates": [],
                     "checks": {"messages": [A._msg("UNREADABLE", "ERROR", f"the file could not be analysed ({type(e).__name__})")]}}
            docs.append(dict(a, document_id=ids.new_id("DOC"), batch_id=batch_id, sha256=sha, storage_ref=ref,
                             reporting_period=period_id, created_at=created, submission_kind=submission_kind,
                             submission_reason=reason, replaces_document_id=earlier["document_id"] if earlier else None))
        for d in docs:
            self._submission_checks(d, submission_kind, earlier, published_final_packs)
        self._resolve_letters(period_id, docs)
        self._duplicates(period_id, docs)
        for d in docs:
            d["validation_status"] = A.status_of(d["checks"]["messages"])
            d.pop("slot_candidates", None)
            d.update(review_decision=None, review_comment="", reviewed_at=None, reviewed_by=None)
        batch = {"batch_id": batch_id, "period_id": period_id, "origin": "UPLOAD", "created_at": created,
                 "created_by": self.settings.analyst_id, "file_count": len(docs), "validation_status": "VALID",
                 "status": "VALIDATED", "summary": {}, "error": "", "confirmed_at": None, "confirmed_by": None}
        with self._lock:
            self.repos.uploads.create_batch(batch, docs)
            batch = self._summarise(batch_id)
            if period["status"] == "EMPTY":
                self.repos.periods.update(period_id, {"status": "DOCUMENTS_UPLOADED"})
        self._activity("DOCUMENTS_UPLOADED", "batch", batch_id, period_id=period_id, files=len(docs),
                       validation_status=batch["validation_status"])
        return self.batch_detail(batch_id)

    @staticmethod
    def _submission_checks(d, kind, earlier, published_final_packs):
        """Messages that record how a document was added. Content identification and validation are unchanged."""
        msgs = d["checks"]["messages"]
        # a correction of a supporting document is itself supporting evidence (it cannot become a reconciliation input)
        supporting = kind == "ADDITIONAL_EVIDENCE" or (kind == "CORRECTION" and earlier is not None
                                                       and earlier.get("category") == SUPPORTING_CATEGORY)
        if supporting and d["evidence_id"] is None and d["size_bytes"] > 0:
            unrecognised = [m for m in msgs if m["code"] == "UNRECOGNISED"]
            if unrecognised:  # readable but not one of IN-01..IN-19: kept as supporting evidence, never a reconciliation input
                msgs.remove(unrecognised[0])
                d["category"] = SUPPORTING_CATEGORY
                msgs.append(A._msg("SUPPORTING_EVIDENCE", "WARNING", "not one of the reconciliation evidence types (IN-01 to IN-19): "
                                   "stored as supporting evidence for the period; it is not used by deterministic processing "
                                   f"({unrecognised[0]['message'].removeprefix('not a supported evidence file: ')})"))
        if earlier is not None:
            msgs.append(A._msg("REPLACES_DOCUMENT", "INFO", f"correction of {earlier['original_filename']} ({earlier['document_id']}); "
                               "the earlier document is kept unchanged", replaces=earlier["document_id"]))
            if d["evidence_id"] and earlier["evidence_id"] and d["evidence_id"] != earlier["evidence_id"]:
                msgs.append(A._msg("REPLACEMENT_TYPE_DIFFERS", "WARNING", f"this file identifies as {d['evidence_id']}; the document it "
                                   f"replaces is {earlier['evidence_id']}"))
        if published_final_packs:
            msgs.append(A._msg("RECEIVED_AFTER_PUBLICATION", "INFO", "received after publication of final audit pack(s) "
                               f"{', '.join(published_final_packs)}; the published pack(s) do not incorporate this document and are "
                               "not changed (pending reassessment)", final_packs=list(published_final_packs)))

    def reference_baseline(self, period_id):
        """The verified source inventory a document of the period can be checked against when the period's own uploads do
        not hold it: the lineage being reassessed (the latest final pack's), else the period's single registered pack.
        None when there is none or it is ambiguous (several independent scenario packs) or it cannot be verified."""
        _, target = self.reassessment_target(period_id)
        if target is None:
            packs = [r["pack_id"] for r in self.repos.periods.packs(period_id)]
            target = packs[0] if len(packs) == 1 else None
        if target is None:
            return None
        try:
            return self.baseline(target, period_id)
        except Conflict:
            return None

    def _baseline_rows(self, baseline, fid):
        from uc042lib.structure import read_csv
        with tempfile.TemporaryDirectory(prefix="u42ref-") as tmp:
            path = Path(tmp) / f"{fid}.csv"
            path.write_bytes(self._baseline_bytes(baseline, fid))  # re-verified against the recorded SHA-256
            return read_csv(path)[1]

    def _resolve_letters(self, period_id, docs):
        """Acknowledgement letters share key details; the slot is chosen by the letter reference in the account
        inventory (IN-02) of this batch, failing that of the period's current set (the engine's own rule), and failing
        that of the period's verified pack source inventory (a month registered from its dataset has no uploaded IN-02).
        A reference that matches none of them is an error: the letter is never assigned to a slot by guesswork."""
        inventory = next((d for d in docs if d["evidence_id"] == "IN-02"
                          and not any(m["level"] == "ERROR" for m in d["checks"]["messages"])), None)
        rows, source = None, "the account inventory (IN-02)"
        try:
            if inventory is not None:
                rows = self._rows(inventory["storage_ref"], inventory["sha256"])
            else:
                cur = self.current_set(period_id).get("IN-02")
                if cur:
                    d = self.repos.uploads.document(cur)
                    rows = self._rows(d["storage_ref"], d["sha256"])
        except (StoreError, OSError):
            rows = None
        if rows is None and any(d["file_format"] == "PDF" and len(d.get("slot_candidates") or []) > 1 for d in docs):
            ref = self.reference_baseline(period_id)
            if ref is not None and "IN-02" in ref["files"]:
                try:
                    rows = self._baseline_rows(ref, "IN-02")
                    source = f"the verified account inventory (IN-02) of {ref['pack_id']}"
                except (OSError, RuntimeError, ValueError):
                    rows = None
        ref_to_slot = {r.get("acknowledgement_letter_ref"): schema.LETTER_SLOTS[r["account_id"]] for r in rows or []
                       if r.get("account_id") in schema.LETTER_SLOTS and r.get("acknowledgement_letter_ref")}
        for d in docs:
            cands = d.get("slot_candidates") or []
            if d["file_format"] != "PDF" or len(cands) < 2:
                continue
            slot = ref_to_slot.get(d["checks"].get("key_details", {}).get("Letter reference", ""))
            if slot in cands:
                d.update(evidence_id=slot, category=A.evidence_label(slot, period_id))
                d["checks"]["slot_resolved_by"] = f"letter reference matched in {source}"
            else:
                d["checks"]["messages"].append(A._msg("LETTER_NOT_MATCHED", "ERROR", "the acknowledgement letter reference does not "
                                                      "match an account in the account inventory (IN-02); upload IN-02 with it"))

    def _rows(self, ref, sha):
        from uc042lib.structure import read_csv
        self.store.read(ref, sha)  # verifies the recorded SHA-256 first
        return read_csv(self.store.path(ref))[1]

    def _key_set(self, doc):
        key = doc["checks"].get("key_column")
        if not key:
            return set()
        try:
            return {r.get(key) for r in self._rows(doc["storage_ref"], doc["sha256"])}
        except (StoreError, OSError, ValueError):
            return set()

    def _duplicates(self, period_id, docs):
        """Flag (never remove) duplicates. Each flag that needs an analyst decision sets checks.decision_required."""
        def flag(d, code, level, text, decide=True, **extra):
            d["checks"]["messages"].append(A._msg(code, level, text, **extra))
            if decide:
                d["checks"]["decision_required"] = True
        earlier = self.repos.uploads.documents(period_id=period_id)
        first_by_sha = {}
        for d in docs:
            if d["sha256"] in first_by_sha:
                flag(d, "DUPLICATE_IN_BATCH", "WARNING", f"identical content to {first_by_sha[d['sha256']]['original_filename']} in this "
                     "batch", duplicate_of=first_by_sha[d["sha256"]]["document_id"])
            else:
                first_by_sha[d["sha256"]] = d
            same = [e for e in earlier if e["sha256"] == d["sha256"]]
            if same:
                flag(d, "DUPLICATE_OF_EARLIER_UPLOAD", "WARNING", f"identical content was already uploaded for this period "
                     f"({same[0]['original_filename']}, batch {same[0]['batch_id']})", duplicate_of=same[0]["document_id"])
            renamed = [e for e in earlier if e["original_filename"] == d["original_filename"] and e["sha256"] != d["sha256"]]
            if renamed:
                flag(d, "SAME_NAME_DIFFERENT_CONTENT", "WARNING", f"a different file with the same name was uploaded earlier "
                     f"(batch {renamed[0]['batch_id']}); both are kept, nothing is overwritten", other=renamed[0]["document_id"])
            elsewhere = [e for e in self.repos.uploads.find_documents(sha256=d["sha256"]) if e["reporting_period"] != period_id]
            if elsewhere:
                if d["file_format"] == "CSV" and d["evidence_id"] and d.get("record_count") == 0:
                    # A header-only file is identical in every month that has no records of its type: equal hashes say
                    # nothing about which month it belongs to. Reported, no decision needed (files with records still need one).
                    flag(d, "HEADER_ONLY_SAME_AS_OTHER_PERIOD", "INFO", f"header-only file (no records) identical to the "
                         f"{d['evidence_id']} supplied for {elsewhere[0]['reporting_period']}; empty files of one type are identical "
                         "in every month", decide=False)
                elif d["evidence_id"] in A.RECURRING_IDS:
                    flag(d, "RECURRING_DOCUMENT", "INFO", f"identical to the document supplied for {elsewhere[0]['reporting_period']} "
                         "(standing data or a standing document that legitimately recurs)", decide=False)
                else:
                    flag(d, "SAME_CONTENT_AS_OTHER_PERIOD", "WARNING", f"identical content was uploaded for "
                         f"{elsewhere[0]['reporting_period']}; check that this is the right month's file",
                         other=elsewhere[0]["document_id"])
            if d["evidence_id"] and d["file_format"] == "CSV":
                prior = [e for e in earlier if e["evidence_id"] == d["evidence_id"] and e["sha256"] != d["sha256"]]
                if prior:
                    mine, theirs = self._key_set(d), self._key_set(prior[-1])
                    overlap = len(mine & theirs) if mine and theirs else 0
                    flag(d, "NEW_VERSION", "INFO", f"a version of {d['evidence_id']} was uploaded earlier for this period "
                         f"({prior[-1]['original_filename']}); if included and confirmed, this one supersedes it for future "
                         f"processing runs. {overlap} of {len(mine)} record IDs also appear in the earlier version.",
                         decide=False, earlier=prior[-1]["document_id"], overlapping_ids=overlap)
        by_slot = {}
        for d in docs:
            if d["evidence_id"] and not any(m["level"] == "ERROR" for m in d["checks"]["messages"]):
                by_slot.setdefault(A.slot(d), []).append(d)  # policies: one slot per version
        for fid, group in by_slot.items():
            distinct = {d["sha256"] for d in group}
            if len(distinct) > 1:
                for d in group:
                    flag(d, "AMBIGUOUS_EVIDENCE_TYPE", "WARNING", f"{len(group)} different files in this batch identify as {fid} "
                         f"({A.evidence_label(fid, period_id)}); include exactly one")

    def _summarise(self, batch_id):
        """Recompute and store the batch summary and validation status from its documents."""
        batch = self.repos.uploads.batch(batch_id)
        docs = self.repos.uploads.documents(batch_id=batch_id)
        in_batch = {d["evidence_id"] for d in docs
                    if d["evidence_id"] and d["validation_status"] != "ERROR" and d["review_decision"] != "EXCLUDE"}
        combined = self.current_set(batch["period_id"], through_batch=batch_id)
        # A document with errors is never processed, so it needs no decision (it cannot be included).
        pending = [d["document_id"] for d in docs if d["checks"].get("decision_required") and not d["review_decision"]
                   and d["validation_status"] != "ERROR"]
        counts = {s: sum(1 for d in docs if d["validation_status"] == s) for s in ("VALID", "WARNING", "ERROR")}
        summary = {"documents": counts, "identified": sorted(in_batch),
                   "missing_in_batch": [f for f in A.REQUIRED_IDS if f not in in_batch],
                   "missing_required": [f for f in A.REQUIRED_IDS if f not in combined],
                   "missing_optional": [f for f in A.OPTIONAL_IDS if f not in combined],
                   "decisions_pending": pending, "processing_set": combined,
                   "policy_selection": self.policy_selection(batch["period_id"], combined)}
        if counts["ERROR"] == len(docs):
            status = "INVALID"
        elif summary["missing_required"]:
            status = "INCOMPLETE"
        elif counts["WARNING"] or counts["ERROR"] or pending:
            status = "WARNINGS"
        else:
            status = "VALID"
        return self.repos.uploads.update_batch(batch_id, {"summary": summary, "validation_status": status})

    def batch_detail(self, batch_id):
        self._require()
        _check(BATCH_ID_RE, batch_id, "batch id")
        batch = self.repos.uploads.batch(batch_id)
        if batch is None:
            raise NotFound("upload batch not found")
        return {"batch": batch, "documents": self.repos.uploads.documents(batch_id=batch_id),
                "runs": self.repos.runs.list(batch_id=batch_id)}

    def document(self, document_id):
        self._require()
        _check(DOCUMENT_ID_RE, document_id, "document id")
        d = self.repos.uploads.document(document_id)
        if d is None:
            raise NotFound("document not found")
        return d

    def document_content(self, document_id):
        d = self.document(document_id)
        try:
            return d, self.store.read(d["storage_ref"], d["sha256"])
        except StoreError as e:
            raise Conflict(str(e), code="DOCUMENT_INTEGRITY") from None

    def review_document(self, document_id, decision, comment):
        """INCLUDE or EXCLUDE one document of an unconfirmed batch (recorded with reviewer and time; never deletes)."""
        if decision not in ("INCLUDE", "EXCLUDE"):
            raise InvalidInput("decision must be INCLUDE or EXCLUDE")
        comment = (comment or "").strip()
        if len(comment) < 3:
            raise InvalidInput("a comment explaining the decision is required", code="COMMENT_REQUIRED")
        with self._lock:
            d = self.document(document_id)
            batch = self.repos.uploads.batch(d["batch_id"])
            if batch["status"] != "VALIDATED":
                raise Conflict("the batch is confirmed; decisions on its documents are final (upload a new batch to correct)",
                               code="BATCH_CONFIRMED")
            if decision == "INCLUDE" and d["validation_status"] == "ERROR":
                raise Conflict("a document with validation errors cannot be included", code="DOCUMENT_HAS_ERRORS")
            d = self.repos.uploads.update_document(document_id, {"review_decision": decision, "review_comment": comment[:2000],
                                                                 "reviewed_at": now_iso(), "reviewed_by": self.settings.analyst_id})
            self._summarise(d["batch_id"])
        self._activity(f"DOCUMENT_{decision}D", "document", document_id, batch_id=d["batch_id"], comment=comment[:200])
        return d

    def confirm(self, batch_id):
        with self._lock:
            detail = self.batch_detail(batch_id)
            batch, docs = detail["batch"], detail["documents"]
            if batch["status"] != "VALIDATED":
                raise Conflict("the batch is already confirmed", code="BATCH_CONFIRMED")
            if batch["validation_status"] == "INVALID":
                raise Conflict("the batch has no usable document", code="BATCH_INVALID")
            if batch["summary"].get("decisions_pending"):
                raise Conflict("flagged documents need an INCLUDE or EXCLUDE decision first", code="DECISIONS_PENDING",
                               extra={"documents": batch["summary"]["decisions_pending"]})
            slots = {}
            for d in docs:
                if self._usable(d):
                    slots.setdefault(A.slot(d), []).append(d["document_id"])
            clash = {k: v for k, v in slots.items() if len(v) > 1}
            if clash:
                raise Conflict("more than one included document per evidence type: " + ", ".join(sorted(clash)),
                               code="AMBIGUOUS_EVIDENCE_TYPE", extra={"evidence_types": clash})
            self.repos.uploads.update_batch(batch_id, {"status": "CONFIRMED", "confirmed_at": now_iso(),
                                                       "confirmed_by": self.settings.analyst_id})
            batch = self._summarise(batch_id)
        self._activity("BATCH_CONFIRMED", "batch", batch_id, period_id=batch["period_id"])
        return self.batch_detail(batch_id)

    # ------------------------------------------------------------------ processing
    def period(self, period_id):
        self._require()
        return self._period(period_id)

    def reconcile(self, period_id, purpose="INITIAL", reason="", pending_reassessment=False):
        """Analyst-initiated reconciliation of one period (never automatic: not at start-up, on upload, on opening a report
        or on any other change). INITIAL runs the existing deterministic engine over the period's current confirmed
        document set. REASSESSMENT is for evidence received after a final audit pack was published: it needs that evidence
        (pending_reassessment), a reason and a confirmed batch, and it runs over the reassessment plan's document set (the
        uploaded documents, superseding the verified original source documents of the pack being reassessed). The
        published packs are never changed; the new pack is linked to the pack it reassesses (pack lineage)."""
        self._require()
        self._period(period_id)
        if purpose not in RUN_PURPOSES:
            raise InvalidInput(f"purpose must be one of {', '.join(RUN_PURPOSES)}", code="INVALID_PURPOSE")
        reason = re.sub(r"\s+", " ", str(reason or "")).strip()
        if purpose == "REASSESSMENT":
            if not pending_reassessment:
                raise Conflict("nothing to reassess: no evidence was received after the period's latest final audit pack",
                               code="NOTHING_TO_REASSESS")
            if len(reason) < 3:
                raise InvalidInput("a reason is required for a reassessment", code="REASON_REQUIRED")
        confirmed = [b for b in self.repos.uploads.batches(period_id)
                     if b["origin"] == "UPLOAD" and b["status"] not in ("VALIDATED", "ARCHIVED_SCENARIO")]
        if not confirmed:
            raise Conflict("the period has no confirmed upload batch to reconcile; upload, validate and confirm documents first",
                           code="NO_CONFIRMED_DOCUMENTS")
        return self.process(confirmed[-1]["batch_id"], purpose=purpose, reason=reason[:500])

    def process(self, batch_id, purpose="INITIAL", reason=""):
        """Start a processing run for the period's document set (after this confirmed batch). A retry is a new run.
        INITIAL processing is refused once the period has a published final audit pack: new evidence for a published
        period is assessed only through an explicit REASSESSMENT (never silently through the normal processing action)."""
        with self._lock:
            batch = self.batch_detail(batch_id)["batch"]
            if batch["status"] == "VALIDATED":
                raise Conflict("confirm the batch before processing", code="BATCH_NOT_CONFIRMED")
            if any(r["status"] in ("QUEUED", "RUNNING") for r in self.repos.runs.list(period_id=batch["period_id"])):
                raise Conflict("a processing run for this period is already in progress", code="RUN_IN_PROGRESS")
            period_id = batch["period_id"]
            final, target = self.reassessment_target(period_id)
            baseline = None
            if purpose == "INITIAL" and final is not None:
                raise Conflict(f"{period_id} has a published final audit pack ({final['final_pack_id']}); new evidence is assessed "
                               "with an explicit reassessment, which keeps the published pack and links the new result to it",
                               code="REASSESSMENT_REQUIRED", extra={"final_pack_id": final["final_pack_id"]})
            current = self.current_set(period_id)
            effective = dict(current)
            if purpose == "REASSESSMENT":
                if final is None:
                    raise Conflict("nothing to reassess: the period has no published final audit pack", code="NOTHING_TO_REASSESS")
                baseline = self.baseline(target, period_id)
                for fid in (baseline or {}).get("files", {}):
                    effective.setdefault(fid, BASELINE_REF)
            missing = [f for f in A.REQUIRED_IDS if f not in effective]
            if missing:
                raise Conflict("required evidence is missing for this period: " + ", ".join(missing), code="INCOMPLETE",
                               extra={"missing": missing})
            run = {"run_id": ids.new_id("RUN"), "period_id": period_id, "batch_id": batch_id, "job_id": None, "status": "QUEUED",
                   "started_at": None, "completed_at": None, "error": "", "created_at": now_iso(), "created_by": self.settings.analyst_id,
                   "result": {"document_set": current, "purpose": purpose, "reason": reason,
                              "predecessor_pack_id": target if purpose == "REASSESSMENT" else None,
                              "reassessed_final_pack_id": final["final_pack_id"] if purpose == "REASSESSMENT" else None,
                              "baseline": ({k: baseline[k] for k in ("pack_id", "dataset", "storage_profile")}
                                           | {"files": {fid: baseline["files"][fid] for fid, src in effective.items() if src == BASELINE_REF}})
                              if baseline else None}}
            job = self.runner.create("PROCESSING", period_id, self.settings.analyst_id, inputs={"run_id": run["run_id"],
                                                                                                "batch_id": batch_id})
            run["job_id"] = job["job_id"]
            self.repos.runs.create(run)
            self.repos.uploads.update_batch(batch_id, {"status": "PROCESSING"})
            self.repos.periods.update(period_id, {"status": "PROCESSING"})
            self.runner.submit(job, self._execute)
        self._activity("PROCESSING_STARTED", "run", run["run_id"], period_id=period_id, job_id=job["job_id"], purpose=purpose)
        if purpose == "REASSESSMENT":
            self._activity("REASSESSMENT_STARTED", "period", period_id, run_id=run["run_id"], reason=reason, pack_id=target,
                           final_pack_id=final["final_pack_id"])
        return self.repos.runs.get(run["run_id"])

    def run(self, run_id):
        self._require()
        _check(RUN_ID_RE, run_id, "processing run id")
        r = self.repos.runs.get(run_id)
        if r is None:
            raise NotFound("processing run not found")
        return r

    def _execute(self, job):
        run_id = job["inputs"]["run_id"]
        run = self.repos.runs.update(run_id, {"status": "RUNNING", "started_at": now_iso()})
        try:
            status, result, error = self._process(run)
        except Exception as e:
            log.exception("processing run %s failed", run_id)
            from ..jobs import safe_error
            status, result, error = "FAILED", {}, safe_error(e)
        result = dict(run["result"], **(result or {}))
        self.repos.runs.update(run_id, {"status": status, "completed_at": now_iso(), "error": error, "result": result})
        ok = status == "SUCCEEDED"
        self.repos.uploads.update_batch(run["batch_id"], {"status": "PROCESSED" if ok else "PROCESSING_FAILED"})
        self.repos.periods.update(run["period_id"], {"status": "PROCESSED" if ok or self.repos.periods.packs(run["period_id"])
                                                     else "PROCESSING_FAILED", "last_processed_at": now_iso()})
        self._activity("PROCESSING_SUCCEEDED" if ok else "PROCESSING_FAILED", "run", run_id, pack_id=result.get("pack_id"),
                       outcome=result.get("outcome"))
        job_result = {"run_id": run_id, "status": status, "pack_id": result.get("pack_id"), "outcome": result.get("outcome")}
        return ("COMPLETED" if ok else "FAILED"), job_result, error

    def _process(self, run):
        """Materialise the document set, prepare the case, build the pack, publish write-once. Returns (status, result, error).

        The case folder is named by the period and the content of the document set (SET-<hash>): identical documents for
        the same period give the same case and therefore the same pack, so a retry never produces a second copy, and a
        prepared case is never rewritten. The period's configuration is passed explicitly to preparation and generation."""
        period = PeriodConfig.from_id(run["period_id"])
        docs = {fid: self.repos.uploads.document(doc_id) for fid, doc_id in sorted(run["result"]["document_set"].items())}
        baseline = run["result"].get("baseline")
        base = {fid: f for fid, f in sorted(((baseline or {}).get("files") or {}).items()) if fid not in docs}
        shas = dict(sorted({**{fid: d["sha256"] for fid, d in docs.items()}, **{fid: f["sha256"] for fid, f in base.items()}}.items()))
        key = hashlib.sha256("\n".join([period.period_id] + [f"{fid}:{sha}" for fid, sha in shas.items()]).encode()).hexdigest()[:16]
        case_dir = self.store.cases_root / f"SET-{key}"
        if case_dir.exists():
            intake = self._read_intake(case_dir)
            accepted = sorted((r["file_id"], r["sha256"]) for r in intake if r["decision"] == "ACCEPTED")
            if accepted != sorted((fid.split("@", 1)[0], sha) for fid, sha in shas.items()):
                return "FAILED", {"case": case_dir.name}, "the prepared case folder does not match this document set"
        else:
            work = Path(tempfile.mkdtemp(prefix="u42in-"))
            self.store.cases_root.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=".tmp-", dir=self.store.cases_root))
            try:
                for fid, d in docs.items():
                    data = self.store.read(d["storage_ref"], d["sha256"])  # verifies the SHA-256 recorded at upload
                    (work / f"{fid}_{d['document_id']}.{'pdf' if d['file_format'] == 'PDF' else 'csv'}").write_bytes(data)
                for fid, f in base.items():  # verified original source documents of the reassessed lineage, re-verified now
                    data = self._baseline_bytes(baseline, fid)
                    (work / f"{fid}_{BASELINE_REF}.{'pdf' if f['file_format'] == 'PDF' else 'csv'}").write_bytes(data)
                intake = prepare_case(work, staging / "case", period)
                os.replace(staging / "case", case_dir)
            finally:
                shutil.rmtree(work, ignore_errors=True)
                shutil.rmtree(staging, ignore_errors=True)
        intake_summary = [{k: r[k] for k in ("decision", "file_id", "reason")} for r in intake if r["decision"] != "ACCEPTED"]
        blocking = [r for r in intake if r["decision"] in ("MISSING", "AMBIGUOUS", "REJECTED")
                    and (r["file_id"] in A.REQUIRED_IDS or r["decision"] != "MISSING")]
        if blocking:
            return "FAILED", {"intake": intake_summary, "case": case_dir.name}, ("the prepared case is incomplete: " + "; ".join(
                f"{r['decision']} {r['file_id'] or ''} {r['reason']}".strip() for r in blocking[:5]))
        # The governing policy chosen at intake is passed explicitly: a case holding more than one policy version is never
        # resolved implicitly by the engine.
        version = selected_policy(case_dir)
        period = PeriodConfig(period.year, period.month, version) if version else period
        status, pack, html, outputs, findings = build(case_dir, period)
        if status != "GENERATED":
            return "FAILED", {"intake": intake_summary, "case": case_dir.name, "findings": findings[:20]}, (
                "the pack could not be generated: " + "; ".join(str(f) for f in findings[:3]))
        pack_id, outcome = self._publish(pack, html, outputs, run)
        verified = self.packs.load(pack_id)  # the published pack must verify like every other pack
        self.repos.periods.add_pack({"period_id": run["period_id"], "pack_id": pack_id, "origin": "UPLOAD_PROCESSING",
                                     "scenario_id": "", "dataset": case_dir.name, "processing_run_id": run["run_id"],
                                     "pack_content_sha256": verified["audit_trail"]["pack_content_sha256"], "registered_at": now_iso()})
        exc = verified["exception_register"]["exceptions"]
        lineage = self._record_lineage(run, verified)
        return "SUCCEEDED", {"pack_id": pack_id, "outcome": outcome, "case": case_dir.name, "intake": intake_summary,
                             "policy_version": version, "baseline_files": sorted(base),
                             "exceptions": len(exc), "engine_case_status": self.packs.summary(verified)["engine_case_status"],
                             "continuity": self._continuity(period, case_dir), "lineage": lineage}, ""

    def _record_lineage(self, run, pack):
        """A REASSESSMENT pack is linked to the pack it reassesses (and to its lineage's first pack), with what changed.
        Written once; the same pack produced again by a later run keeps its first record. Returns the lineage view or None."""
        predecessor = run["result"].get("predecessor_pack_id")
        pack_id = pack["metadata"]["pack_id"]
        if run["result"].get("purpose") != "REASSESSMENT" or not predecessor or self.repos.lineage is None:
            return None
        if pack_id == predecessor:  # identical inputs and identity: the reassessment reproduced the same pack
            return {"predecessor_pack_id": predecessor, "same_pack": True}
        existing = self.repos.lineage.get(pack_id)
        if existing is not None:
            return {k: existing[k] for k in ("predecessor_pack_id", "lineage_root_pack_id")} | {"recorded_earlier": True}
        root = self.final_packs.lineage_root(predecessor) if self.final_packs is not None else predecessor
        row = {"pack_id": pack_id, "period_id": run["period_id"], "predecessor_pack_id": predecessor, "lineage_root_pack_id": root,
               "purpose": "REASSESSMENT", "processing_run_id": run["run_id"], "reason": run["result"].get("reason") or "",
               "change_summary": self.change_summary(self.packs.load(predecessor), pack, run),
               "recorded_at": now_iso(), "recorded_by": self.settings.analyst_id}
        try:
            self.repos.lineage.add(row)
        except DuplicateRecord:
            pass
        self._activity("PACK_LINEAGE_RECORDED", "pack", pack_id, period_id=run["period_id"], predecessor_pack_id=predecessor,
                       run_id=run["run_id"])
        return {"predecessor_pack_id": predecessor, "lineage_root_pack_id": root}

    @staticmethod
    def change_summary(before, after, run=None):
        """What differs between two deterministic packs of the same month (read from the packs; nothing is recomputed):
        source inputs by evidence type and hash, engine status, evidence completeness, control outcomes and exceptions
        (matched by category, account, currency, dates and amount, since exception IDs carry the pack's scenario prefix)."""
        def inputs(p):
            return {f["evidence_id"]: f.get("sha256") for f in p["evidence_register"]["files"]
                    if f.get("availability") == "PRESENT" and f.get("evidence_id")}

        def exc_key(x):
            return "|".join(str(x.get(k) or "") for k in ("category", "account_id", "currency", "first_date", "last_date", "amount"))

        def outcomes(p):
            out = {}
            for c in p["control_register"]:  # one entry per engine check
                out[c.get("check_outcome")] = out.get(c.get("check_outcome"), 0) + 1
            return dict(sorted(out.items(), key=lambda kv: str(kv[0])))
        bi, ai = inputs(before), inputs(after)
        be = {exc_key(x): x["exception_id"] for x in before["exception_register"]["exceptions"]}
        ae = {exc_key(x): x["exception_id"] for x in after["exception_register"]["exceptions"]}
        es_b, es_a = before["executive_summary"], after["executive_summary"]
        return {"predecessor_pack_id": before["metadata"]["pack_id"], "pack_id": after["metadata"]["pack_id"],
                "reason": (run or {}).get("result", {}).get("reason", ""),
                "inputs_changed": sorted(f for f in set(bi) | set(ai) if bi.get(f) != ai.get(f)),
                "inputs_added": sorted(set(ai) - set(bi)), "inputs_removed": sorted(set(bi) - set(ai)),
                "engine_case_status": [es_b.get("engine_case_status"), es_a.get("engine_case_status")],
                "evidence_completeness": [es_b.get("evidence_completeness"), es_a.get("evidence_completeness")],
                "control_outcomes": [outcomes(before), outcomes(after)],
                "exceptions": {"before": len(be), "after": len(ae),
                               "added": sorted(ae[k] for k in set(ae) - set(be)), "removed": sorted(be[k] for k in set(be) - set(ae)),
                               "unchanged": sorted(f"{be[k]} = {ae[k]}" for k in set(ae) & set(be))},
                "baseline_files": sorted(((run or {}).get("result", {}).get("baseline") or {}).get("files", {}))}

    def _continuity(self, period, case_dir):
        """Opening positions against the previous period's closing positions (uc042lib.continuity), using the previous
        period's latest successful run's case. Without one: NOT_VERIFIABLE; nothing is assumed."""
        from uc042lib.continuity import compare
        prev_runs = [r for r in self.repos.runs.list(period_id=period.previous.period_id) if r["status"] == "SUCCEEDED"
                     and r["result"].get("case")]
        prev_case = self.store.cases_root / prev_runs[-1]["result"]["case"] if prev_runs else None
        try:
            report = compare(prev_case if prev_case and prev_case.is_dir() else None, case_dir, period, period.previous)
        except Exception as e:  # continuity is reported, never allowed to change or fail the run's engine result
            return {"status": "NOT_VERIFIABLE", "previous_period": period.previous.period_id,
                    "items": [], "error": f"{type(e).__name__}: continuity could not be assessed"}
        counts = {}
        for i in report["items"]:
            counts[i["status"]] = counts.get(i["status"], 0) + 1
        return dict(report, counts=counts)

    @staticmethod
    def _read_intake(case_dir):
        import csv
        with open(case_dir / "intake.csv", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    def _publish(self, pack, html, outputs, run):
        """Write-once into packs_root (the engine's layout). An identical existing pack is left untouched."""
        root = Path(self.settings.packs_root)
        text = pack_model.canonical(pack)
        pack_id = pack["metadata"]["pack_id"]
        target = root / pack_id
        if target.exists():
            if (target / "pack.json").read_text(encoding="utf-8") != text:
                raise RuntimeError("a different pack with this identifier exists; packs are never overwritten")
            return pack_id, "ALREADY_EXISTS"
        tmp = Path(tempfile.mkdtemp(prefix=".tmp-", dir=root))
        try:
            (tmp / "pack.json").write_text(text, encoding="utf-8")
            (tmp / "pack.html").write_text(html, encoding="utf-8")
            (tmp / "processing").mkdir()
            for name, content in outputs.items():
                (tmp / "processing" / name).write_text(content, encoding="utf-8")
            (tmp / "generations").mkdir()
            rec = {"generated_at": now_iso(), "status": "GENERATED", "outcome": "PUBLISHED",
                   "case_dir": "cases/" + pack["metadata"]["source_dataset"].get("dataset", ""),
                   "pack_id": pack_id, "processing_run_id": pack["metadata"]["processing_run_id"],
                   "pack_content_sha256": pack["audit_trail"]["pack_content_sha256"], "validation_findings": [],
                   "uc042app_processing_run": run["run_id"]}
            (tmp / "generations" / "0001.json").write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8")
            os.replace(tmp, target)
        finally:
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
        return pack_id, "PUBLISHED"

    # ------------------------------------------------------------------ reference integrity (read-only)
    def pack_references(self):
        """Every pack reference held in application state, checked against the verified pack in packs_root: pack
        identity and content hash, the registered period and content hash, and the pack each run, job, review,
        final-pack record and registry entry names. Read-only. Returns {"references": n, "problems": [...],
        "unregistered_packs": [...], "periods": {period_id: [pack_id, ...]}}."""
        problems, checked, cache = [], 0, {}

        def pack(pid):
            if pid not in cache:
                try:
                    cache[pid] = self.packs.load(pid)
                except Exception as e:  # missing, unverifiable or modified: reported, never repaired
                    cache[pid] = f"{type(e).__name__}: {getattr(e, 'detail', e)}"
            return cache[pid]

        def check(source, key, pid, period=None, sha=None):
            nonlocal checked
            checked += 1
            p = pack(pid)
            if isinstance(p, str):
                problems.append({"source": source, "key": key, "pack_id": pid, "problem": f"pack does not load: {p}"})
                return
            actual = p["metadata"]["reporting_period"]["period_id"]
            if period and period != actual:
                problems.append({"source": source, "key": key, "pack_id": pid, "problem": f"registered under {period}, pack is {actual}"})
            if sha and sha != p["audit_trail"]["pack_content_sha256"]:
                problems.append({"source": source, "key": key, "pack_id": pid, "problem": "registered content hash differs from the pack"})

        periods = {}
        for r in self.repos.periods.packs():
            periods.setdefault(r["period_id"], []).append(r["pack_id"])
            check("period_packs", f"{r['period_id']}/{r['pack_id']}", r["pack_id"], r["period_id"], r.get("pack_content_sha256"))
        for p in self.repos.periods.list():
            for run in self.repos.runs.list(period_id=p["period_id"]):
                if (run.get("result") or {}).get("pack_id"):
                    check("processing_runs", run["run_id"], run["result"]["pack_id"], run["period_id"])
        for j in self.repos.jobs.list():
            if str(j.get("pack_id", "")).startswith("PACK-"):
                check("jobs", j["job_id"], j["pack_id"])
        for s in self.repos.reviews.list():
            check("review_sessions", s["review_id"], s["pack_id"])
        for f in self.repos.final_packs.list():
            check("final_pack_records", f.get("decision_id", ""), f["pack_id"])
        for e in self.repos.registry.entries():
            check("investigation_registry", f"seq {e.get('seq')}", e["pack_id"])
        known = {r["pack_id"] for r in self.repos.periods.packs()}
        return {"references": checked, "problems": problems, "periods": periods,
                "unregistered_packs": [p for p in self.packs.pack_ids() if p not in known]}

    # ------------------------------------------------------------------ POC scenario packs (September 2026)
    def unregistered_packs(self):
        """Verified packs in packs_root that are not yet registered under their period (read-only)."""
        known = {r["pack_id"] for r in self.repos.periods.packs()}
        return [p for p in self.packs.pack_ids() if p not in known]

    def sync_packs(self):
        """Register every verified pack in packs_root under its period (reference only). Scenario packs of the synthetic
        POC are labelled POC_SCENARIO: they are separate TEST SCENARIOS of one month, never separate months. Creates a
        period record only for a period that has a pack (no month is invented)."""
        if self.repos.periods is None:
            return []
        known = {(r["period_id"], r["pack_id"]) for r in self.repos.periods.packs()}
        added = []
        for pack_id in self.packs.pack_ids():
            try:
                summary = self.packs.summary(self.packs.load(pack_id))
            except Exception:  # a pack that does not verify is listed by /packs with its problem; never registered
                continue
            pid = summary["period_id"]
            if (pid, pack_id) in known:
                continue
            try:
                year, month = A.parse_period(pid)
            except ValueError:
                continue
            existed = self.repos.periods.get(pid) is not None
            self.repos.periods.ensure(pid, year, month, status="PROCESSED")
            if not existed:
                self._activity("PERIOD_REGISTERED_FROM_PACKS", "period", pid)
            dataset = self.packs.load(pack_id)["metadata"]["source_dataset"].get("dataset", "")
            scenario = summary.get("scenario_id") or ""
            origin = "POC_SCENARIO" if scenario and scenario != "CASE" else "UPLOAD_PROCESSING"
            self.repos.periods.add_pack({"period_id": pid, "pack_id": pack_id, "origin": origin, "scenario_id": scenario,
                                         "dataset": dataset, "processing_run_id": None,
                                         "pack_content_sha256": summary["pack_content_sha256"], "registered_at": now_iso()})
            added.append(pack_id)
        return added

    def import_poc_documents(self, dry_run=False):
        """Register the source documents of each POC scenario pack (uc042_dataset/<dataset>/source_data/*.csv and
        supporting_documents/*.pdf only) as a read-only POC_DATASET_IMPORT batch referencing the files in place, after
        checking each SHA-256 against the pack's evidence register. Never copies, moves or changes the dataset; never
        touches answer keys, mutation lists or scenario notes. Idempotent. These batches are archive records of the test
        scenarios: they are never part of a processing document set."""
        self._require()
        if not dry_run:
            self.sync_packs()
        out = []
        existing = {(b["summary"] or {}).get("pack_id") for p in self.repos.periods.list() for b in self.repos.uploads.batches(p["period_id"])
                    if b["origin"] == "POC_DATASET_IMPORT"}
        for rec in self.repos.periods.packs():
            if rec["origin"] != "POC_SCENARIO" or rec["pack_id"] in existing:
                continue
            pack = self.packs.load(rec["pack_id"])
            files = pack["evidence_register"]["files"]
            year, month = A.parse_period(rec["period_id"])
            batch_id, created = ids.new_id("UPL"), now_iso()
            docs, problems = [], []
            for f in files:
                if f.get("availability") != "PRESENT" or not f.get("sha256"):
                    continue  # missing evidence stays missing; nothing is substituted
                rel = f["source_file"]
                ref = f"dataset:{rec['dataset']}/{rel}"
                try:
                    path = self.store.path(ref)
                    data = self.store.read(ref, f["sha256"])
                except (StoreError, KeyError) as e:
                    problems.append(f"{rel}: {e}")
                    continue
                a = A.analyse_file(path, Path(rel).name, year, month)
                if a["evidence_id"] is None and len(a.get("slot_candidates") or []) > 1:
                    a.update(evidence_id=f["evidence_id"], category=A.evidence_label(f["evidence_id"], rec["period_id"]))
                a.pop("slot_candidates", None)
                docs.append(dict(a, document_id=ids.new_id("DOC"), batch_id=batch_id, sha256=f["sha256"], storage_ref=ref,
                                 reporting_period=rec["period_id"], created_at=created, size_bytes=len(data),
                                 validation_status=A.status_of(a["checks"]["messages"]), review_decision=None, review_comment="",
                                 reviewed_at=None, reviewed_by=None))
            out.append({"pack_id": rec["pack_id"], "scenario_id": rec["scenario_id"], "documents": len(docs), "problems": problems})
            if dry_run or problems:
                continue
            self.repos.uploads.create_batch({"batch_id": batch_id, "period_id": rec["period_id"], "origin": "POC_DATASET_IMPORT",
                                             "created_at": created, "created_by": self.settings.analyst_id, "file_count": len(docs),
                                             "validation_status": "VALID", "status": "ARCHIVED_SCENARIO",
                                             "summary": {"pack_id": rec["pack_id"], "scenario_id": rec["scenario_id"],
                                                         "dataset": rec["dataset"],
                                                         "note": "POC test scenario documents registered in place (read-only)"},
                                             "error": "", "confirmed_at": None, "confirmed_by": None}, docs)
            self._activity("POC_SCENARIO_DOCUMENTS_REGISTERED", "batch", batch_id, pack_id=rec["pack_id"], documents=len(docs))
        return out

    def recover(self):
        """Runs left QUEUED/RUNNING by a previous process are marked INTERRUPTED (never re-run automatically)."""
        if self.repos.runs is None:
            return []
        out = []
        for r in self.repos.runs.list():
            if r["status"] in ("QUEUED", "RUNNING"):
                self.repos.runs.update(r["run_id"], {"status": "INTERRUPTED", "completed_at": now_iso(),
                                                     "error": "the backend restarted during processing; start a new run"})
                self.repos.uploads.update_batch(r["batch_id"], {"status": "PROCESSING_FAILED"})
                period = self.repos.periods.get(r["period_id"])
                if period and period["status"] == "PROCESSING":
                    self.repos.periods.update(r["period_id"], {"status": "PROCESSED" if self.repos.periods.packs(r["period_id"])
                                                               else "PROCESSING_FAILED"})
                out.append(r["run_id"])
        return out
