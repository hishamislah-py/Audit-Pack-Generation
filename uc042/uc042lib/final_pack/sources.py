"""Source loading and verification for the final pack: the deterministic pack (via the existing load_pack) and the
published investigation artefacts (via the existing verify_published), with eligibility re-checked under the CURRENT
investigation validation rules. Read-only: nothing here writes, and no AI is called."""
import hashlib
import json
import re
from pathlib import Path

from ..investigation import config as inv_config
from ..investigation.models import LLMInvestigationOutput
from ..investigation.packet import build_case
from ..investigation.persistence import verify_published
from ..investigation.retrieval import load_pack as _load_pack
from ..investigation.validation import validate_output
from .model import SUPPORTED_PACK_SCHEMAS

INVESTIGATION_ID_RE = re.compile(r"^INV-EXC-[A-Z0-9]{1,12}-\d{2,3}-[0-9a-f]{12}$")


class FinalPackInputError(ValueError):
    """A source cannot be used for a final pack (unverifiable pack, ineligible investigation, bad selection, ...)."""


def load_pack(pack_id, packs_root=None):
    """Load and verify the deterministic pack (identity + content hash) and check that its schema is supported."""
    pack = _load_pack(pack_id, packs_root)
    if pack["metadata"].get("pack_schema_version") not in SUPPORTED_PACK_SCHEMAS:
        raise FinalPackInputError(f"unsupported pack schema {pack['metadata'].get('pack_schema_version')!r}")
    return pack


def _root(investigations_root):
    return Path(investigations_root or inv_config.INVESTIGATIONS_ROOT)


def load_bundle(path):
    """The artefacts of one published investigation, parsed. findings_sha256 is the hash of the stored findings bytes."""
    path = Path(path)
    raw = (path / "findings.json").read_bytes()
    bundle = {"path": path, "findings": json.loads(raw), "findings_sha256": hashlib.sha256(raw).hexdigest(),
              "packet": json.loads((path / "evidence_packet.json").read_text(encoding="utf-8")), "ledger": None, "tool_calls": None}
    for name, key in (("evidence_ledger.json", "ledger"), ("tool_calls.json", "tool_calls")):
        if (path / name).is_file():
            bundle[key] = json.loads((path / name).read_text(encoding="utf-8"))
    return bundle


def evidence_of(bundle):
    """The evidence the findings were validated against: the accumulated ledger (tools mode) or the packet (fixed)."""
    return bundle["ledger"] or bundle["packet"]


def output_of(bundle):
    """The model-output part of the stored findings as LLMInvestigationOutput (schema 1.4 fields None if not supplied)."""
    f = bundle["findings"]
    return LLMInvestigationOutput.model_validate({k: f[k] for k in LLMInvestigationOutput.model_fields if k in f})


def check_eligibility(bundle, pack):
    """Reasons why a published investigation may not be included (empty list = eligible)."""
    f, reasons = bundle["findings"], []
    problems = verify_published(bundle["path"])
    if problems:
        return [f"artefact verification failed: {p}" for p in problems]
    if f.get("pack_id") != pack["metadata"]["pack_id"] or f.get("pack_content_sha256") != pack["audit_trail"]["pack_content_sha256"]:
        reasons.append("belongs to a different pack or pack content hash")
    if f.get("investigation_status") != "COMPLETED" or f.get("validation_status") != "VALID":
        reasons.append(f"investigation_status {f.get('investigation_status')}, validation_status {f.get('validation_status')}")
    if (f.get("model_metadata") or {}).get("simulated", True):
        reasons.append("simulated (offline) output is not AI analysis")
    if reasons:
        return reasons
    try:
        case = build_case(pack, f["exception_id"])
        errors = validate_output(output_of(bundle), evidence_of(bundle), case)[0]
    except (KeyError, ValueError) as e:
        return [f"re-validation could not run: {e.__class__.__name__}: {e}"]
    return [f"fails current validation rules ({inv_config.FINDINGS_SCHEMA_VERSION}): {e}" for e in errors]


def list_investigations(pack, exception_id, investigations_root=None):
    """Every investigation attempt for an exception: published artefacts with eligibility, and unpublished attempts
    (FAILED / REJECTED) from _not_published/. Newest first."""
    root, pack_id = _root(investigations_root), pack["metadata"]["pack_id"]
    published = []
    for d in sorted((root / pack_id / exception_id).glob("INV-*")):
        if not (d.is_dir() and INVESTIGATION_ID_RE.match(d.name)):
            continue
        try:
            bundle = load_bundle(d)
        except (OSError, ValueError) as e:
            published.append({"investigation_id": d.name, "eligible": False, "reasons": [f"unreadable: {e}"], "path": str(d)})
            continue
        f, m = bundle["findings"], bundle["findings"].get("model_metadata") or {}
        reasons = check_eligibility(bundle, pack)
        published.append({"investigation_id": d.name, "path": str(d), "eligible": not reasons, "reasons": reasons,
                          "investigation_mode": f.get("investigation_mode", "fixed"), "investigated_at": f.get("investigated_at", ""),
                          "validation_status": f.get("validation_status"), "simulated": m.get("simulated"),
                          "provider": m.get("provider"), "model": m.get("model"),
                          "findings_schema_version": m.get("findings_schema_version"),
                          "overall_evidence_assessment": f.get("overall_evidence_assessment")})
    unpublished = []
    for p in sorted((root / "_not_published" / pack_id / exception_id).glob("*.json")):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))["result"]
        except (OSError, ValueError, KeyError):
            continue
        unpublished.append({"record": p.name, "investigation_status": r.get("investigation_status"),
                            "validation_status": r.get("validation_status"), "failure_reason": r.get("failure_reason", "")[:300]})
    published.sort(key=lambda x: x.get("investigated_at") or "", reverse=True)
    return {"published": published, "not_published": unpublished}


def default_selections(pack, investigations_root=None):
    """Explicit helper (spec 06 Q2): per exception, the newest eligible tools-mode investigation, otherwise the newest
    eligible fixed-mode one, otherwise NOT_INVESTIGATED. Callers may override any entry."""
    from .model import Selection
    out = []
    for x in pack["exception_register"]["exceptions"]:
        eligible = [i for i in list_investigations(pack, x["exception_id"], investigations_root)["published"] if i["eligible"]]
        pick = next((i for i in eligible if i["investigation_mode"] == "tools"), None) or (eligible[0] if eligible else None)
        out.append(Selection(exception_id=x["exception_id"], inclusion="INCLUDED", investigation_id=pick["investigation_id"])
                   if pick else Selection(exception_id=x["exception_id"], inclusion="NOT_INVESTIGATED"))
    return out
