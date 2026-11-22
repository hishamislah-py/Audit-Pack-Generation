"""Where a period's or pack's files are: one backend over one database, several storage profiles on disk.

The primary root set is the backend's own configuration (UC042_PACKS_ROOT, UC042_DATASETS_ROOT, ...): it holds the
operational months, including every pack produced from uploads, and is never restricted to fixed periods. Further root
sets come from uc042lib.investigation.roots.PROFILES (e.g. historical-demo: demo_history/...): a profile is served when the
database records it on a period (reconciliation_periods.storage_profile, set by the unification migration) or when it is
named in UC042_STORAGE_PROFILES. Files are never moved between root sets.

Resolution is by where the pack is, not by guessing: a pack is found in exactly one root set (two copies is an integrity
failure, never a silent choice), a pack in a profile's packs root must belong to one of that profile's periods, and the
pack's investigations, datasets and final packs are read and written in the same root set."""
from dataclasses import dataclass
from pathlib import Path

from uc042lib.investigation import roots as inv_roots

from .. import ids
from ..config import ConfigurationError
from ..errors import IntegrityFailure, NotFound

PRIMARY = "primary"


@dataclass(frozen=True)
class RootSet:
    name: str
    packs_root: Path
    datasets_root: Path
    investigations_root: Path
    final_packs_root: Path
    periods: frozenset | None = None  # None: not restricted (the primary set)

    def holds_pack(self, pack_id):
        return (Path(self.packs_root) / pack_id / "pack.json").is_file()

    def covers(self, period_id):
        return self.periods is None or period_id in self.periods


class StorageLayout:
    def __init__(self, primary, extras=()):
        self.primary = primary
        sets, seen = [primary], {Path(primary.packs_root).resolve()}
        for s in extras:
            if Path(s.packs_root).resolve() in seen:
                continue  # the primary roots already are this profile's roots (e.g. a backend configured on demo_history)
            seen.add(Path(s.packs_root).resolve())
            sets.append(s)
        self.sets = tuple(sets)

    @classmethod
    def from_settings(cls, settings, profiles=()):
        primary = RootSet(PRIMARY, Path(settings.packs_root), Path(settings.datasets_root), Path(settings.investigations_root),
                          Path(settings.final_packs_root))
        extras = []
        for name in sorted(set(profiles)):
            try:
                p = inv_roots.storage_profile(name)
            except inv_roots.InvestigationRootsError as e:
                raise ConfigurationError(f"storage profile {name!r}: {e}") from None
            extras.append(RootSet(p.name, p.packs_root, p.datasets_root, p.investigations_root, p.final_packs_root, p.periods))
        return cls(primary, extras)

    @property
    def names(self):
        return [s.name for s in self.sets]

    def pack_ids(self):
        """(pack_id, root set) for every pack directory in every root set; a pack ID in two root sets is reported once
        per set (callers treat that as an integrity failure)."""
        out = []
        for s in self.sets:
            root = Path(s.packs_root)
            out += [(p.name, s) for p in sorted(root.glob("PACK-*")) if p.is_dir() and ids.PACK_ID_RE.match(p.name)
                    and (p / "pack.json").is_file()]
        return out

    def for_pack(self, pack_id):
        """The one root set holding the pack (NotFound / IntegrityFailure otherwise)."""
        ids.check("pack_id", pack_id)
        hits = [s for s in self.sets if s.holds_pack(pack_id)]
        if not hits:
            raise NotFound("pack not found")
        if len(hits) > 1:
            raise IntegrityFailure(f"pack {pack_id} exists in more than one storage root ({', '.join(s.name for s in hits)})",
                                   code="DUPLICATE_PACK")
        s = hits[0]
        period = inv_roots.period_of_pack(pack_id)
        if not s.covers(period):
            raise IntegrityFailure(f"pack {pack_id} ({period}) is in the {s.name} storage profile, which holds "
                                   f"{', '.join(sorted(s.periods))} only", code="PACK_OUTSIDE_PROFILE")
        return s

    def for_period(self, period_id):
        """Root sets that may hold packs of the period (the profile covering it, and always the primary set)."""
        return [s for s in self.sets if s.covers(period_id)]

    def investigation_roots(self):
        return [Path(s.investigations_root) for s in self.sets]

    def final_pack_roots(self):
        return [Path(s.final_packs_root) for s in self.sets]

    def describe(self):
        return [{"name": s.name, "packs_root": str(s.packs_root), "periods": sorted(s.periods) if s.periods else None}
                for s in self.sets]
