"""Approved evidence-retrieval functions. The investigation layer reads data only through this module.

- Packs are loaded by validated pack ID from the packs root; identity and content hash are verified.
- Source rows are read from the pack's dataset folder via the existing loader (uc042lib.pack.assemble.load_sources),
  after verifying each source file's SHA-256 against the pack's audit trail.
- Planted-answer files (answer keys, mutations, scenario notes, golden snapshots) are never opened.
"""
import hashlib
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from .. import schema
from ..pack import model as pack_model
from ..pack.assemble import load_sources
from ..period import PeriodConfig, PeriodError, policy_version_of
from . import config, roots


class RetrievalError(Exception):
    """Evidence could not be retrieved safely or its integrity could not be verified."""


def _inside(path, root):
    path, root = Path(path).resolve(), Path(root).resolve()
    if path != root and root not in path.parents:
        raise RetrievalError(f"path outside approved root: {path}")
    if path.name in config.FORBIDDEN_NAMES or config.FORBIDDEN_DIR_PARTS & set(path.relative_to(root).parts) \
            or roots.FORBIDDEN_DIRS & set(root.parts):
        raise RetrievalError(f"access to {path.name} is not permitted for investigation")
    return path


def _root(root, default, label):
    """The configured input root. None: the September default; a blank, missing or forbidden root is an error, never
    replaced by the default (uc042lib.investigation.roots)."""
    if root is None:
        return Path(default)
    path = Path(root).resolve() if str(root).strip() else None
    if path is None or not path.is_dir():
        raise RetrievalError(f"the investigation {label} root is not configured or does not exist: {root!r}")
    if roots.FORBIDDEN_DIRS & set(path.parts):
        raise RetrievalError(f"the investigation {label} root lies inside a forbidden directory: {path}")
    return path


def load_pack(pack_id, packs_root=None):
    """Load and verify a published deterministic pack (read-only)."""
    if not config.PACK_ID_RE.match(pack_id or ""):
        raise RetrievalError(f"invalid pack_id format: {pack_id!r}")
    root = _root(packs_root, config.PACKS_ROOT, "packs")
    path = _inside(root / pack_id / "pack.json", root)
    if not path.is_file():
        raise RetrievalError(f"pack not found: {pack_id}")
    pack = json.loads(path.read_text(encoding="utf-8"))
    if pack.get("metadata", {}).get("pack_id") != pack_id:
        raise RetrievalError("pack identity mismatch")
    recorded = pack.get("audit_trail", {}).get("pack_content_sha256", "")
    if pack_model.content_hash(pack) != recorded or not pack_id.endswith(recorded[:12]):
        raise RetrievalError("pack content hash does not verify; refusing to investigate a modified pack")
    return pack


def pack_policy_version(pack):
    """The policy (IN-17) version the pack's engine run read, so the same documents are read again. A case may supply
    more than one version (all are listed in the audit trail): the run's version is the one its results cite."""
    names = {i["relative_path"] for i in pack["audit_trail"]["inputs"] if i["file_id"] == "IN-17"}
    if len(names) > 1:
        names = {m.group(1) for c in pack["control_register"] for r in c["results"]
                 for m in re.finditer(r"IN-17:([^#;\]\s,]+)", r.get("evidence_refs", ""))}
    versions = {policy_version_of(n) for n in names} - {None}
    return next(iter(versions)) if len(versions) == 1 else None


class EvidenceStore:
    """Scoped, read-only access to one dataset's source records, with provenance on every record."""

    def __init__(self, pack, datasets_root=None):
        root = _root(datasets_root, config.DATASETS_ROOT, "datasets")
        name = pack["metadata"]["source_dataset"]["dataset"]
        if not name or "/" in name or "\\" in name or name.startswith("."):
            raise RetrievalError("invalid dataset name in pack")
        self.dir = _inside(root / name, root)
        # Source files must be byte-identical to what the pack was generated from.
        self.file_sha = {}
        for i in pack["audit_trail"]["inputs"]:
            p = _inside(self.dir / i["relative_path"], root)
            if not p.is_file():
                raise RetrievalError(f"source file missing: {i['relative_path']}")
            actual = hashlib.sha256(p.read_bytes()).hexdigest()
            if actual != i["sha256_actual"]:
                raise RetrievalError(f"source file changed since pack generation: {i['relative_path']}")
            self.file_sha[i["file_id"]] = actual
        try:
            period = PeriodConfig.from_id(pack["metadata"]["reporting_period"]["period_id"], pack_policy_version(pack))
            rows, self.fid_of, self.pk_of = load_sources(self.dir, period)
        except PeriodError as e:
            raise RetrievalError(f"reporting period of the pack's case: {e}") from e
        self.by_fid = defaultdict(list)
        self.by_pk = defaultdict(dict)
        for (fname, line), r in sorted(rows.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            fid = self.fid_of[fname]
            self.by_fid[fid].append((fname, line, r))
            self.by_pk[fid][r[self.pk_of[fid]]] = (fname, line, r)

    # -- record construction ----------------------------------------------------------------------------------
    def _item(self, fid, fname, line, row, via, join_key):
        pk = row[self.pk_of[fid]]
        return {"evidence_id": f"{fid}:{pk}", "file_id": fid, "record_type": schema.CSV_FILES[fid][1],
                "source_file": f"source_data/{fname}", "source_line": line, "file_sha256": self.file_sha.get(fid, ""),
                "retrieved_via": via, "join_key": join_key,
                "fields": {k: v for k, v in row.items() if not k.startswith("_")}}

    def get(self, evidence_id, via, join_key=""):
        """Record for an evidence ID 'IN-xx:<primary key>' or None."""
        fid, _, pk = (evidence_id or "").partition(":")
        hit = self.by_pk.get(fid, {}).get(pk)
        return self._item(fid, *hit, via, join_key or f"{self.pk_of.get(fid, 'pk')}={pk}") if hit else None

    def find(self, fid, via, **equals):
        """Records of one file whose fields equal all given values."""
        out = []
        for fname, line, r in self.by_fid.get(fid, []):
            if all(r.get(k) == v for k, v in equals.items()):
                out.append(self._item(fid, fname, line, r, via, ", ".join(f"{k}={v}" for k, v in equals.items())))
        return out

    def find_where(self, fid, via, join_key, predicate):
        return [self._item(fid, fname, line, r, via, join_key) for fname, line, r in self.by_fid.get(fid, []) if predicate(r)]

    # -- typed retrieval helpers ------------------------------------------------------------------------------
    def bank_entries_by_reference(self, account, ref, via):
        return self.find_where("IN-09", via, f"account_id={account}, bank_reference|end_to_end_ref={ref}",
                               lambda r: r["account_id"] == account and ref in (r["bank_reference"], r["end_to_end_ref"]))

    def cashbook_by_reference(self, account, ref, via):
        return self.find("IN-10", via, account_id=account, payment_reference=ref)

    def cashbook_on_date(self, account, d, via):
        return self.find_where("IN-10", via, f"account_id={account}, posted_ts date={d}",
                               lambda r: r["account_id"] == account and r["posted_ts"][:10] == d)

    def statement(self, account, d, via):
        return self.find("IN-08", via, account_id=account, statement_date=d)

    def confirmation(self, account, d, via):
        return self.find_where("IN-07", via, f"account_id={account}, as_at_ts date={d}",
                               lambda r: r["account_id"] == account and r["as_at_ts"][:10] == d)

    def entries_on_statement(self, statement_id, via):
        return self.find("IN-09", via, statement_id=statement_id)

    def external_record(self, account, d, via):
        return self.find("IN-06", via, account_id=account, recon_date=d)

    def internal_record(self, ccy, d, via):
        return self.find("IN-05", via, currency=ccy, recon_date=d)

    def batches_on_date(self, account, d, via):
        return self.find("IN-12", via, account_id=account, settlement_date=d)

    def lines_of_batch(self, batch_id, via):
        return self.find("IN-13", via, batch_id=batch_id)

    def snapshots(self, client, ccy, dates, via):
        return self.find_where("IN-03", via, f"client_id={client}, currency={ccy}, recon_date in {sorted(dates)}",
                               lambda r: r["client_id"] == client and r["currency"] == ccy and r["recon_date"] in dates)

    def client_transactions(self, client, ccy, after_ts, upto_ts, via):
        from datetime import datetime
        a, b = datetime.fromisoformat(after_ts), datetime.fromisoformat(upto_ts)
        return self.find_where("IN-11", via, f"client_id={client}, currency={ccy}, executed_ts in ({after_ts}, {upto_ts}]",
                               lambda r: r["client_id"] == client and r["currency"] == ccy and a < datetime.fromisoformat(r["executed_ts"]) <= b)

    def discrepancy_log_for(self, recon_refs, via):
        return self.find_where("IN-14", via, f"recon_ref in {sorted(recon_refs)}", lambda r: r["recon_ref"] in recon_refs)

    def search_reference(self, account, ref):
        """Where a reference string appears across all reference-bearing fields (records found, possibly none)."""
        fields = {"IN-09": ("bank_reference", "end_to_end_ref", "narrative_text"), "IN-10": ("payment_reference",),
                  "IN-12": ("expected_bank_reference",), "IN-11": ("payment_reference",), "IN-04": ("bank_reference",),
                  "IN-14": ("cause_evidence_ref", "description")}
        hits = []
        for fid, cols in fields.items():
            for fname, line, r in self.by_fid.get(fid, []):
                if any(ref and ref in (r.get(c) or "") for c in cols):
                    hits.append(f"{fid}:{r[self.pk_of[fid]]}")
        return {"reference": ref, "account": account, "searched": {k: list(v) for k, v in fields.items()}, "found": hits}

    def recon_days(self):
        return [r["calendar_date"] for _, _, r in self.by_fid.get("IN-01", []) if r["is_recon_day"] == "true"]

    def previous_snapshot_date(self, client, ccy, d):
        ds = sorted({r["recon_date"] for _, _, r in self.by_fid.get("IN-03", [])
                     if r["client_id"] == client and r["currency"] == ccy and r["recon_date"] < d})
        return ds[-1] if ds else None

    def next_recon_day(self, d):
        later = [x for x in self.recon_days() if x > d]
        return later[0] if later else None

    @staticmethod
    def point(d):
        """The 17:00 Europe/London reconciliation point for a date, as an ISO timestamp (offset from the timezone)."""
        from datetime import datetime, time
        from zoneinfo import ZoneInfo
        return datetime.combine(date.fromisoformat(d), time(17, 0), tzinfo=ZoneInfo("Europe/London")).isoformat()
