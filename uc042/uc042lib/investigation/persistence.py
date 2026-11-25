"""Write-once persistence of investigation artefacts, separate from deterministic packs (which are never touched).

Publication is atomic: findings.json, evidence_packet.json and runs/0001.json are staged in a temporary sibling directory
and moved into place with one os.replace. A failure leaves no partial artefact. Later run records are added under the
first free number through an exclusive hard link, so concurrent writers never overwrite each other.
"""
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ..pack.model import canonical
from . import config


class ImmutabilityError(Exception):
    pass


def _safe_dir(root, *parts):
    root = Path(root).resolve()
    p = root.joinpath(*parts).resolve()
    if root not in p.parents and p != root:
        raise ImmutabilityError("artefact path escapes the investigations root")
    return p


def investigation_id(result, packet):
    return investigation_id_from_findings(result.model_dump(), packet["packet_sha256"])


def investigation_id_from_findings(findings, packet_sha256):
    """Identity over the findings exactly as stored, so artefacts written under an earlier findings schema remain
    verifiable after fields are added. Per-call metadata (usage, provider response IDs) is excluded; in tools mode the
    findings include evidence_ledger_sha256, so the accumulated evidence is part of the identity."""
    core = {k: v for k, v in findings.items() if k not in ("investigation_id", "investigated_at", "model_metadata")}
    meta = {k: v for k, v in (findings.get("model_metadata") or {}).items() if k not in ("usage", "provider_response")}
    basis = canonical({"findings": core, "model": meta, "packet": packet_sha256})
    return f"INV-{findings['exception_id']}-{hashlib.sha256(basis.encode()).hexdigest()[:12]}"


def verify_published(path):
    """Read-only integrity check of a published artefact directory. Returns a list of problems (empty means verified):
    packet and ledger self-hashes, the findings' references to them, the investigation ID recomputed from the stored
    findings, the run records' file hashes, and that the findings still load with the current models."""
    from .models import InvestigationResult
    d, problems = Path(path), []
    try:
        findings = json.loads((d / "findings.json").read_text(encoding="utf-8"))
        packet = json.loads((d / "evidence_packet.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [f"unreadable artefact: {e.__class__.__name__}: {e}"]
    if hashlib.sha256(canonical({k: v for k, v in packet.items() if k != "packet_sha256"}).encode()).hexdigest() != packet.get("packet_sha256"):
        problems.append("evidence_packet.json does not match its packet_sha256")
    if findings.get("evidence_packet_sha256") != packet.get("packet_sha256"):
        problems.append("findings.evidence_packet_sha256 does not match the packet")
    if investigation_id_from_findings(findings, packet.get("packet_sha256", "")) != findings.get("investigation_id") or d.name != findings.get("investigation_id"):
        problems.append("investigation_id does not match the stored findings")
    ledger_file = d / "evidence_ledger.json"
    if ledger_file.exists() or findings.get("evidence_ledger_sha256"):
        try:
            ledger = json.loads(ledger_file.read_text(encoding="utf-8"))
            if hashlib.sha256(canonical({k: v for k, v in ledger.items() if k != "ledger_sha256"}).encode()).hexdigest() != ledger.get("ledger_sha256"):
                problems.append("evidence_ledger.json does not match its ledger_sha256")
            if ledger.get("ledger_sha256") != findings.get("evidence_ledger_sha256") or ledger.get("initial_packet_sha256") != packet.get("packet_sha256"):
                problems.append("findings/packet do not reference this ledger")
        except (OSError, ValueError):
            problems.append("evidence_ledger.json missing or unreadable")
    for run in sorted((d / "runs").glob("[0-9][0-9][0-9][0-9].json")):
        for name, digest in (json.loads(run.read_text(encoding="utf-8")).get("artefact_sha256") or {}).items():
            f = d / name
            if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest() != digest:
                problems.append(f"runs/{run.name}: {name} does not match its recorded SHA-256")
    try:
        InvestigationResult.model_validate(findings)
    except ValueError as e:
        problems.append(f"findings no longer load with the current models: {str(e)[:200]}")
    return problems


def _run_text(run_record, now, outcome):
    return json.dumps(dict(run_record, recorded_at=now, outcome=outcome), indent=1) + "\n"


def append_run_record(runs_dir, text):
    """Add text as runs/NNNN.json under the first free number; never overwrites an existing record. Returns the path."""
    runs_dir = Path(runs_dir)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-run-", suffix=".tmp", dir=runs_dir)
    try:
        with os.fdopen(fd, "wb") as f:  # bytes: identical on every platform (no newline translation)
            f.write(text.encode("utf-8"))
        n = len(list(runs_dir.glob("[0-9][0-9][0-9][0-9].json"))) + 1
        for _ in range(10_000):
            target = runs_dir / f"{n:04d}.json"
            try:
                os.link(tmp, target)  # atomic, fails if the name is taken
                return target
            except FileExistsError:
                n += 1
            except OSError:  # file system without hard links: exclusive create instead
                try:
                    with open(target, "xb") as f:
                        f.write(text.encode("utf-8"))
                    return target
                except FileExistsError:
                    n += 1
        raise ImmutabilityError(f"could not allocate a run record number in {runs_dir}")
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def _write_new(path, text):
    """Write a complete new file without ever replacing an existing one: stage it, then hard-link it to the first free
    name (path, path-2, path-3, ...). Returns the path written."""
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(text.encode("utf-8"))
        for n in range(1, 10_000):
            target = path if n == 1 else path.with_name(f"{path.stem}-{n}{path.suffix}")
            try:
                os.link(tmp, target)
                return target
            except FileExistsError:
                continue
            except OSError:  # file system without hard links: exclusive create instead
                try:
                    with open(target, "xb") as f:
                        f.write(text.encode("utf-8"))
                    return target
                except FileExistsError:
                    continue
        raise ImmutabilityError(f"could not allocate a record name for {path}")
    finally:
        Path(tmp).unlink(missing_ok=True)


def _same_findings(target, result):
    existing = json.loads((target / "findings.json").read_text(encoding="utf-8"))
    return {k: v for k, v in existing.items() if k != "investigated_at"} == \
           {k: v for k, v in result.model_dump().items() if k != "investigated_at"}


def _publish(target, files):
    """Stage every file in a temporary sibling directory, then move it into place in one step."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".tmp-", dir=target.parent))
    try:
        for rel, text in files.items():
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp / rel).write_bytes(text.encode("utf-8"))  # bytes, so recorded SHA-256 values match the files exactly
        os.chmod(tmp, 0o755)
        os.replace(tmp, target)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def _json(obj):
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def persist(result, packet, run_record, root=None, extra=None):
    """Publish a VALID result write-once; store REJECTED/FAILED attempts separately. Returns (path, outcome).
    `extra` maps additional artefact names to objects (tools mode: evidence_ledger.json, tool_calls.json); they are staged
    and published in the same atomic step, and their SHA-256 is recorded in the run record.
    Raises OSError on storage failure (nothing partial is left) and ImmutabilityError if a different artefact exists."""
    root = Path(root or config.INVESTIGATIONS_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    extra_text = {name: _json(obj) for name, obj in (extra or {}).items()}
    run_record = dict(run_record, artefact_sha256={name: hashlib.sha256(t.encode("utf-8")).hexdigest() for name, t in extra_text.items()})
    if result.validation_status != "VALID" or result.investigation_status != "COMPLETED":
        d = _safe_dir(root, "_not_published", result.pack_id or "unknown", result.exception_id or "unknown")
        d.mkdir(parents=True, exist_ok=True)
        name = f"{now.replace(':', '')}-{hashlib.sha256(canonical(result.model_dump()).encode()).hexdigest()[:8]}.json"
        record = {"result": result.model_dump(), "run": run_record,
                  "evidence_packet_sha256": packet.get("packet_sha256", "") if packet else ""}
        record.update({n.removesuffix(".json"): obj for n, obj in (extra or {}).items()})  # keep the transcript for diagnosis
        written = _write_new(d / name, json.dumps(record, indent=1, ensure_ascii=False) + "\n")  # never replaces a record
        return str(written), "NOT_PUBLISHED"
    target = _safe_dir(root, result.pack_id, result.exception_id, result.investigation_id)
    if not target.exists():
        try:
            _publish(target, {"findings.json": json.dumps(result.model_dump(), indent=1, sort_keys=True) + "\n",
                              "evidence_packet.json": json.dumps(packet, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
                              **extra_text, "runs/0001.json": _run_text(run_record, now, "PUBLISHED")})
            return str(target), "PUBLISHED"
        except OSError:
            if not (target / "findings.json").is_file():
                raise  # a genuine storage failure; the staged files were removed
            # another writer published the same ID first: fall through to the identical-rerun path
    if not _same_findings(target, result):
        raise ImmutabilityError(f"{target} exists with different findings; artefacts are never overwritten")
    append_run_record(target / "runs", _run_text(run_record, now, "ALREADY_PUBLISHED_IDENTICAL"))
    return str(target), "ALREADY_PUBLISHED_IDENTICAL"
