"""ZIP submission package: safe reading, inventory and deterministic filename mapping (approved 17 Nov 2026).

One ZIP is one complete, independent document set for one reporting period. This module only reads the archive and maps
file names; it never writes to disk, never identifies content and never decides completeness on its own:

  * safety: every entry is checked BEFORE its bytes are used (absolute paths, '..', drive letters, symbolic links,
    encryption, nested archives, entry count, per-file and total uncompressed size, compression ratio), and the bytes
    read are capped, so a lying header cannot exceed the limits. Nothing is extracted to the file system;
  * filename mapping: the ONLY source of truth is the central schema: uc042lib.period.FILE_PATTERNS through
    PeriodConfig.file_id_of() (and period.POLICY_FILE_RE for the versioned policy IN-17). No second schema exists here;
  * strict membership: a file that does not map to IN-01..IN-19 for the selected period is UNEXPECTED and rejects the
    package (no fallback inference, no AI). Operating-system metadata (macOS resource forks, Finder / Explorer files) is
    listed explicitly as ignored, never processed.

Content identification and validation stay where they are (uc042app.ingest.analysis / uc042lib.prepare); the caller
cross-checks the filename-derived evidence ID against the content-derived one. A future Smart Parser would plug in at
`resolve_unexpected` (not implemented: it returns nothing, so the deterministic path is complete without it)."""
import hashlib
import io
import os
import re
import stat
import zipfile
from dataclasses import asdict, dataclass

from uc042lib.period import MONTH_TOKEN, POLICY_FILE_RE, PeriodConfig, PeriodError


@dataclass(frozen=True)
class ZipLimits:
    max_entries: int = 40  # file entries (19 document types plus room for ignored metadata)
    max_file_bytes: int = 50 * 1024 * 1024  # per file, uncompressed (the same per-file limit as single-document upload)
    max_total_bytes: int = 200 * 1024 * 1024  # all files, uncompressed
    max_ratio: int = 200  # uncompressed / compressed, per entry (zip-bomb guard)
    max_archive_bytes: int = 100 * 1024 * 1024  # the ZIP itself

    @classmethod
    def from_env(cls, env=None):
        """Defaults, overridable by UC042_ZIP_MAX_ENTRIES / _MAX_FILE_BYTES / _MAX_TOTAL_BYTES / _MAX_RATIO / _MAX_ARCHIVE_BYTES."""
        env = os.environ if env is None else env
        out = {}
        for field in cls.__dataclass_fields__:
            raw = env.get(f"UC042_ZIP_{field.upper()}")
            if raw:
                try:
                    value = int(raw)
                except ValueError:
                    raise ValueError(f"UC042_ZIP_{field.upper()} must be a positive integer") from None
                if value <= 0:
                    raise ValueError(f"UC042_ZIP_{field.upper()} must be a positive integer")
                out[field] = value
        return cls(**out)


# Operating-system metadata: never documents, never processed, always listed (explicit, not silent).
_METADATA_DIRS = ("__MACOSX/",)
_METADATA_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini", "ehthumbs.db"}
_DRIVE = re.compile(r"^[A-Za-z]:")
_ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


class PackageRejected(Exception):
    """The archive itself cannot be read safely (not a ZIP, too large, unreadable). Per-entry problems are reported in the
    inventory instead, so the user sees every issue at once."""

    def __init__(self, message, code="PACKAGE_UNREADABLE"):
        super().__init__(message)
        self.code = code


def _is_metadata(name):
    base = name.rsplit("/", 1)[-1]
    return name.startswith(_METADATA_DIRS) or base in _METADATA_NAMES or base.startswith("._")


def _unsafe_path(name):
    """Why an entry name is unsafe, or None. Checked on the raw name (both separators) before anything else."""
    raw = name.replace("\\", "/")
    if raw.startswith("/") or name.startswith("\\"):
        return "absolute path"
    if _DRIVE.match(raw):
        return "Windows drive path"
    if any(part == ".." for part in raw.split("/")):
        return "path traversal ('..')"
    if "\x00" in name:
        return "NUL character in the name"
    return None


def resolve_unexpected(name, data):
    """Future Smart Parser integration point: map a file whose name is outside the convention to an evidence ID.
    Not implemented in this phase: the deterministic filename convention is the only mapping, so this returns None."""
    return None


def map_filename(name, period):
    """(evidence_id, policy_version, problem) for a flattened base name under the selected period's conventions.
    evidence_id None means the name is outside the approved schema; `problem` then says why (another period, unknown)."""
    m = POLICY_FILE_RE.match(name)
    if m:  # IN-17 is a versioned standing document; the version is part of its name (period.FILE_PATTERNS["IN-17"])
        return "IN-17", m.group(1), None
    fid = period.file_id_of(name)
    if fid and fid != "IN-17":
        return fid, None, None
    tok = MONTH_TOKEN.search(name)
    if tok:  # a schema file name, but for another month: the wrong reporting period (never re-mapped)
        try:
            other = PeriodConfig.from_id(f"PER-{tok.group(1)}")
        except PeriodError:
            other = None
        if other is not None and other.file_id_of(name):
            if name.startswith("rep027_submission_receipt_"):
                return None, None, (f"the return receipt is named for {tok.group(1)}; a {period.token} package carries the "
                                    f"receipt for the previous month ({period.previous.token})")
            return None, None, f"named for another reporting period ({tok.group(1)}); this package is for {period.token}"
        if name.startswith("rep027_submission_receipt_") and tok.group(1) != period.previous.token:
            return None, None, (f"the return receipt is named for {tok.group(1)}; a {period.token} package carries the receipt "
                                f"for the previous month ({period.previous.token})")
    return None, None, "not a file of the approved UC-042 schema (IN-01 to IN-19) for this period"


def read_package(data, period, limits=None):
    """Read a ZIP submission safely. Returns (inventory, files):
       inventory: {zip_sha256, zip_bytes, entries: [...], ignored_metadata: [...], unsafe: [...], unexpected: [...],
                   duplicate_names: [...], duplicate_types: {...}, limits}
       files: [(base_name, bytes, evidence_id, policy_version)] for the entries mapped to IN-01..IN-19 (only when the
              archive and every entry are safe; otherwise empty, so nothing unsafe reaches document processing).
    Raises PackageRejected when the archive itself cannot be read."""
    limits = limits or ZipLimits()
    if not isinstance(period, PeriodConfig):
        period = PeriodConfig.from_id(period)
    if len(data) > limits.max_archive_bytes:
        raise PackageRejected(f"the ZIP is larger than {limits.max_archive_bytes // (1024 * 1024)} MB", code="PACKAGE_TOO_LARGE")
    if not data[:4] in _ZIP_MAGIC:
        raise PackageRejected("the upload is not a ZIP archive", code="NOT_A_ZIP")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
    except (zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, ValueError) as e:
        raise PackageRejected(f"the ZIP cannot be read ({type(e).__name__})") from None
    inv = {"zip_sha256": hashlib.sha256(data).hexdigest(), "zip_bytes": len(data), "period_id": period.period_id,
           "entries": [], "ignored_metadata": [], "unsafe": [], "unexpected": [], "duplicate_names": [],
           "duplicate_types": {}, "limits": asdict(limits)}
    files, total, seen_names = [], 0, {}
    file_infos = [i for i in infos if not i.is_dir()]
    if len(file_infos) > limits.max_entries:
        inv["unsafe"].append({"name": "(archive)", "reason": f"{len(file_infos)} files; at most {limits.max_entries} are allowed"})
    for info in file_infos:
        name = info.filename
        why = _unsafe_path(name)
        mode = (info.external_attr >> 16) & 0xFFFF
        if why is None and stat.S_ISLNK(mode):
            why = "symbolic link"
        if why is None and info.flag_bits & 0x1:
            why = "encrypted entry"
        if why is None and info.file_size > limits.max_file_bytes:
            why = f"larger than {limits.max_file_bytes} bytes uncompressed"
        if why is None and info.compress_size and info.file_size / info.compress_size > limits.max_ratio:
            why = f"compression ratio above {limits.max_ratio}:1"
        if why:
            inv["unsafe"].append({"name": name, "reason": why})
            continue
        if _is_metadata(name):
            inv["ignored_metadata"].append(name)
            continue
        base = name.replace("\\", "/").rsplit("/", 1)[-1]
        key = base.casefold()  # duplicates that become identical after flattening folders (case-insensitive file systems)
        if key in seen_names:
            inv["duplicate_names"].append({"name": base, "paths": [seen_names[key], name]})
            continue
        seen_names[key] = name
        total += info.file_size
        if total > limits.max_total_bytes:
            inv["unsafe"].append({"name": "(archive)", "reason": f"more than {limits.max_total_bytes} bytes uncompressed in total"})
            break
        try:
            with zf.open(info) as fh:
                content = fh.read(limits.max_file_bytes + 1)  # capped: a lying header cannot exceed the limit
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError) as e:
            inv["unsafe"].append({"name": name, "reason": f"unreadable entry ({type(e).__name__})"})
            continue
        if len(content) > limits.max_file_bytes:
            inv["unsafe"].append({"name": name, "reason": f"larger than {limits.max_file_bytes} bytes uncompressed"})
            continue
        if base.lower().endswith(".zip") or content[:4] in _ZIP_MAGIC:
            inv["unexpected"].append({"name": base, "reason": "nested ZIP archives are not accepted"})
            continue
        fid, version, problem = map_filename(base, period)
        if fid is None and resolve_unexpected(base, content) is not None:  # pragma: no cover - future Smart Parser hook
            pass
        entry = {"path": name, "name": base, "size": len(content), "sha256": hashlib.sha256(content).hexdigest(),
                 "evidence_id_by_name": fid, "policy_version_by_name": version}
        inv["entries"].append(entry)
        if fid is None:
            inv["unexpected"].append({"name": base, "reason": problem})
            continue
        files.append((base, content, fid, version))
    by_type = {}
    for base, _, fid, version in files:  # every type exactly once (two IN-17 policy versions are two policies: refused,
        by_type.setdefault(fid, []).append(base)  # as the engine itself refuses more than one policy version per case)
    inv["duplicate_types"] = {k: v for k, v in by_type.items() if len(v) > 1}
    inv["archive_safe"] = not inv["unsafe"]
    return inv, (files if inv["archive_safe"] else [])
