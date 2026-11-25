"""Deterministic packs, read through the existing verified loader (uc042lib.final_pack.sources.load_pack, which wraps
uc042lib.investigation.retrieval.load_pack: identity, content hash and schema). Read-only: nothing here can change an
exception status or any pack content."""
import copy
import threading
from pathlib import Path

from uc042lib.final_pack.sources import FinalPackInputError, load_pack
from uc042lib.investigation.retrieval import RetrievalError

from .. import ids
from ..errors import IntegrityFailure, NotFound

# scenario.json name written by tools/build_demo_history.py for each January-August 2026 historical month
HISTORICAL_SCENARIO_PREFIX = "Historical demonstration month"
EXCEPTION_FIELDS = ("exception_id", "category", "cause_category", "severity", "status", "review_status", "evidence_status",
                    "account_id", "currency", "amount", "first_date", "last_date", "control_codes", "investigation_group_id",
                    "affected_result_ids", "evidence_ids", "root_cause", "flags")


class PackService:
    def __init__(self, layout):
        self.layout = layout  # services.layout.StorageLayout: the primary root set plus any storage profiles
        self.root = layout.primary.packs_root  # where packs produced from uploads are published
        self._cache = {}  # pack_id -> ((path, mtime_ns, size), verified pack); packs are immutable, the stat guards edits
        self._lock = threading.Lock()

    def pack_ids(self):
        return sorted({pack_id for pack_id, _ in self.layout.pack_ids()})

    def root_set(self, pack_id):
        """The storage root set holding the pack (its investigations, datasets and final packs live in the same set)."""
        return self.layout.for_pack(pack_id)

    def load(self, pack_id):
        """The verified pack (a private copy). 404 if absent; 409 PACK_VERIFICATION_FAILED if it does not verify (or exists twice)."""
        return copy.deepcopy(self._verified(pack_id))  # callers may not share (or mutate) the cached copy

    def peek(self, pack_id):
        """The verified pack WITHOUT copying, for read-only aggregation (period lists, pack lists, investigation counts):
        packs are several MB and copying each on every list request dominated page load times. Callers must not mutate it."""
        return self._verified(pack_id)

    def summary_of(self, pack_id):
        return copy.deepcopy(self.summary(self._verified(pack_id)))

    def _verified(self, pack_id):
        root = Path(self.layout.for_pack(pack_id).packs_root)
        st = (root / pack_id / "pack.json").stat()
        sig = (str(root), st.st_mtime_ns, st.st_size)
        with self._lock:
            hit = self._cache.get(pack_id)
        if hit and hit[0] == sig:
            return hit[1]
        try:
            pack = load_pack(pack_id, root)  # full verification (identity, content hash, schema)
        except (RetrievalError, FinalPackInputError, ValueError) as e:
            raise IntegrityFailure(f"the pack does not verify: {e}", code="PACK_VERIFICATION_FAILED") from None
        with self._lock:
            self._cache[pack_id] = (sig, pack)
        return pack

    @staticmethod
    def exception_ids(pack):
        return [x["exception_id"] for x in pack["exception_register"]["exceptions"]]

    def exception(self, pack, exception_id):
        ids.check("exception_id", exception_id)
        x = next((x for x in pack["exception_register"]["exceptions"] if x["exception_id"] == exception_id), None)
        if x is None:
            raise NotFound("exception not found in this pack")
        return x

    @staticmethod
    def affected_results(pack, exception):
        """The engine results behind an exception, copied from the pack's control register (never recalculated)."""
        wanted = set(exception.get("affected_result_ids") or [])
        return [dict(r, check_id=c["check_id"], control_code=c["control_code"], control_name=c["control_name"])
                for c in pack["control_register"] for r in c["results"] if r["result_id"] in wanted]

    @staticmethod
    def reconciliation(pack):
        """The pack's reconciliation tables, copied as reported (the pack computes no totals and nothing is recalculated)."""
        r, m = pack["reconciliation_summary"], pack["metadata"]
        return {"pack_id": m["pack_id"], "accounts": m["accounts"], "currency_scope": m["currency_scope"],
                "reconciliation_days": m["reconciliation_days"], "internal_by_currency_day": r["internal_by_currency_day"],
                "external_by_account_day": r["external_by_account_day"], "opening_positions": r["opening_positions"],
                "client_balances_note": r["client_balances_note"]}

    @staticmethod
    def sources(pack):
        """Source files (evidence register, dataset-relative names and SHA-256) and missing evidence, as recorded."""
        return {"pack_id": pack["metadata"]["pack_id"], "files": pack["evidence_register"]["files"],
                "record_count": len(pack["evidence_register"]["records"]), "missing_evidence": pack["missing_evidence_register"]}

    @staticmethod
    def pack_kind(pack):
        """What kind of deterministic pack this is, from its own recorded source dataset (nothing stored is relabelled):
        HISTORICAL_MONTHLY (the January-August 2026 historical demonstration months), DEMONSTRATION_SCENARIO (a synthetic
        test scenario of a month, e.g. the nine September 2026 scenarios) or UPLOADED_DOCUMENTS (processed from uploads)."""
        ds = pack["metadata"]["source_dataset"]
        if (ds.get("scenario_name") or "").startswith(HISTORICAL_SCENARIO_PREFIX):
            return "HISTORICAL_MONTHLY"
        if ds.get("scenario_id") and ds.get("scenario_id") != "CASE":
            return "DEMONSTRATION_SCENARIO"
        return "UPLOADED_DOCUMENTS"

    @staticmethod
    def summary(pack):
        m, s = pack["metadata"], pack["executive_summary"]
        return {"pack_id": m["pack_id"], "pack_content_sha256": pack["audit_trail"]["pack_content_sha256"],
                "period_id": m["reporting_period"].get("period_id"), "reporting_period": m["reporting_period"],
                "scenario_id": m["source_dataset"].get("scenario_id"), "scenario_name": m["source_dataset"].get("scenario_name") or "",
                "pack_kind": PackService.pack_kind(pack), "engine_case_status": s["engine_case_status"],
                "evidence_completeness": s["evidence_completeness"], "exceptions": s["exceptions"],
                "control_summary": s["control_outcomes"]["summary"], "outcomes": s["control_outcomes"]["by_outcome"],
                "missing_evidence_items": s["missing_evidence_items"], "pack_review_status": s["pack_review_status"]}

    @staticmethod
    def exception_view(x):
        return {k: x.get(k) for k in EXCEPTION_FIELDS}
