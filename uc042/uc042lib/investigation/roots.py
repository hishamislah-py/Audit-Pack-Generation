"""Approved input roots of the AI investigation layer (packs, datasets) and where its artefacts are written.

The investigation runtime reads only two roots: the packs root (one verified pack.json per pack) and the datasets root
(each pack's source files, listed in the pack's audit trail). Both are chosen explicitly, by profile or by period:

    september        packs/, uc042_dataset/, investigations/                         PER-2026-09 (the POC baseline)
    historical-demo  demo_history/packs/, demo_history/datasets/,                    PER-2026-01 .. PER-2026-08
                     demo_history/investigations/ (created only when an investigation is published)

Each profile also names its final-packs root: september publishes OUTSIDE the repository (UC042_FINAL_PACKS_ROOT, else
the per-user data directory; uc042lib.runtime_paths), historical-demo keeps demo_history/final_packs/. One backend over one database
serves several profiles: profile_for_period / profile_for_pack route a period or pack to its profile (a month outside
every fixed profile only with an explicit default), and storage_profile returns a profile's validated roots.

Boundary (technical, not a prompt instruction):
  * an input root must exist, be a directory, and neither lie inside nor contain a forbidden directory
    (FORBIDDEN_DIRS: verification material, golden snapshots, tests, the supplied historical package with its
    scenario oracles). demo_history/ itself is therefore refused: it contains verification/;
  * every file read is resolved inside its root and refused if a path part is forbidden (retrieval._inside);
  * a pack read under a profile must belong to one of that profile's periods;
  * a configured root that is missing, blank or invalid fails with InvestigationRootsError. There is no fallback to
    September; September is used only when no root, profile or period is given at all (the existing default).
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

from ..runtime_paths import default_final_packs_root
from . import config

PROJECT = config.PROJECT
FORBIDDEN_DIRS = {"verification", "golden", "tests", "UC042_JAN_AUG_HISTORICAL_DEMO"}
ENV_PROFILE = "UC042_INVESTIGATION_PROFILE"
ENV_PERIOD = "UC042_INVESTIGATION_PERIOD"


class InvestigationRootsError(ValueError):
    """The investigation input roots are missing, invalid or outside the approved boundary."""


@dataclass(frozen=True)
class Profile:
    name: str
    packs_root: Path
    datasets_root: Path
    investigations_root: Path
    periods: frozenset
    # Where final audit packs built from this profile's packs are published. Operational (September) packs: outside the
    # source repository (UC042_FINAL_PACKS_ROOT, else the per-user data directory; uc042lib.runtime_paths).
    final_packs_root: Path = field(default_factory=default_final_packs_root)


PROFILES = {
    "september": Profile("september", config.PACKS_ROOT, config.DATASETS_ROOT, config.INVESTIGATIONS_ROOT,
                         frozenset({"PER-2026-09"}), default_final_packs_root()),
    "historical-demo": Profile("historical-demo", PROJECT / "demo_history" / "packs", PROJECT / "demo_history" / "datasets",
                               PROJECT / "demo_history" / "investigations",
                               frozenset(f"PER-2026-{m:02d}" for m in range(1, 9)), PROJECT / "demo_history" / "final_packs"),
}
DEFAULT_PROFILE = "september"
PERIOD_IN_PACK_ID = "-PER-"


@dataclass(frozen=True)
class InvestigationRoots:
    packs_root: Path
    datasets_root: Path
    investigations_root: Path
    profile: str = ""            # "" for explicitly given roots
    periods: frozenset = frozenset()  # empty: not restricted to a profile's periods

    def as_kwargs(self):
        return {"packs_root": self.packs_root, "datasets_root": self.datasets_root,
                "investigations_root": self.investigations_root}

    def check_pack_id(self, pack_id):
        """A pack read under a profile must belong to one of its periods (the period is part of the pack ID)."""
        if not self.periods:
            return
        period = "PER-" + pack_id.split("-PER-", 1)[1][:7] if "-PER-" in (pack_id or "") else ""
        if period not in self.periods:
            raise InvestigationRootsError(f"pack {pack_id} ({period or 'unknown period'}) is not in the {self.profile} "
                                          f"profile ({', '.join(sorted(self.periods))}); select that period's profile")


def _forbidden_parts(path):
    return FORBIDDEN_DIRS & set(Path(path).parts)


def check_input_root(root, label):
    """The validated absolute input root, or InvestigationRootsError."""
    if root is None or not str(root).strip():
        raise InvestigationRootsError(f"the investigation {label} root is not configured")
    path = Path(root).resolve()
    if not path.is_dir():
        raise InvestigationRootsError(f"the investigation {label} root does not exist or is not a directory: {path}")
    bad = _forbidden_parts(path)
    if bad:
        raise InvestigationRootsError(f"the investigation {label} root lies inside a forbidden directory ({', '.join(sorted(bad))}): {path}")
    for dirpath, dirnames, _ in os.walk(path):
        hit = FORBIDDEN_DIRS & set(dirnames)
        if hit:
            raise InvestigationRootsError(f"the investigation {label} root contains a forbidden directory "
                                          f"({Path(dirpath, sorted(hit)[0])}); configure a narrower root")
    return path


def check_output_root(root):
    if root is None or not str(root).strip():
        raise InvestigationRootsError("the investigations (output) root is not configured")
    path = Path(root).resolve()
    if _forbidden_parts(path):
        raise InvestigationRootsError(f"the investigations root lies inside a forbidden directory: {path}")
    if not path.parent.is_dir():
        raise InvestigationRootsError(f"the parent of the investigations root does not exist: {path.parent}")
    return path


def profile_for_period(period_id, default=None):
    """The profile whose periods include period_id. A period no profile covers raises InvestigationRootsError, unless a
    default profile name is given (the caller's explicit choice for months outside every fixed profile, e.g. a newly
    opened operational month). Profiles never overlap, so the answer is unique."""
    hits = [p.name for p in PROFILES.values() if period_id in p.periods]
    if len(hits) > 1:
        raise InvestigationRootsError(f"{period_id} is covered by more than one profile ({', '.join(hits)})")
    if not hits:
        if default is not None:
            if default not in PROFILES:
                raise InvestigationRootsError(f"unknown investigation profile {default!r} (configured: {', '.join(PROFILES)})")
            return default
        raise InvestigationRootsError(f"no investigation profile covers {period_id!r} "
                                      f"(configured: {', '.join(f'{n}: {min(p.periods)}..{max(p.periods)}' for n, p in PROFILES.items())})")
    return hits[0]


def period_of_pack(pack_id):
    """The reporting period recorded in a pack identifier (PACK-<scope>-PER-YYYY-MM-<hash>), or None."""
    if not pack_id or PERIOD_IN_PACK_ID not in pack_id:
        return None
    candidate = "PER-" + pack_id.split(PERIOD_IN_PACK_ID, 1)[1][:7]
    return candidate if len(candidate) == 11 and candidate[4:8].isdigit() and candidate[8] == "-" and candidate[9:].isdigit() else None


def profile_for_pack(pack_id, default=None):
    """The profile of the pack's period (see profile_for_period); InvestigationRootsError for an identifier without a period."""
    period = period_of_pack(pack_id)
    if period is None:
        raise InvestigationRootsError(f"pack {pack_id!r} carries no reporting period in its identifier")
    return profile_for_period(period, default)


def storage_profile(name):
    """A profile's validated roots (packs and datasets must exist inside the approved boundary; the output roots must be
    creatable and outside forbidden directories). Used by a backend that serves several profiles from one database."""
    if name not in PROFILES:
        raise InvestigationRootsError(f"unknown investigation profile {name!r} (configured: {', '.join(PROFILES)})")
    p = PROFILES[name]
    return Profile(p.name, check_input_root(p.packs_root, "packs"), check_input_root(p.datasets_root, "datasets"),
                   check_output_root(p.investigations_root), p.periods, check_output_root(p.final_packs_root))


def resolve(profile=None, period_id=None, packs_root=None, datasets_root=None, investigations_root=None, environ=None):
    """Validated roots. Precedence: explicit roots (all of packs and datasets, or none) > profile > period >
    UC042_INVESTIGATION_PROFILE / UC042_INVESTIGATION_PERIOD > the September default."""
    env = os.environ if environ is None else environ
    explicit = [r is not None for r in (packs_root, datasets_root)]
    if any(explicit):
        if not all(explicit):
            raise InvestigationRootsError("give both the packs root and the datasets root (or neither): a missing one is "
                                          "never filled in from another profile")
        return InvestigationRoots(check_input_root(packs_root, "packs"), check_input_root(datasets_root, "datasets"),
                                  check_output_root(investigations_root if investigations_root is not None else config.INVESTIGATIONS_ROOT))
    if profile is None and period_id is None:
        profile = (env.get(ENV_PROFILE) or "").strip() or None
        period_id = (env.get(ENV_PERIOD) or "").strip() or None
        if ENV_PROFILE in env and profile is None or ENV_PERIOD in env and period_id is None:
            raise InvestigationRootsError(f"{ENV_PROFILE} / {ENV_PERIOD} is set but blank")
    if profile is not None and period_id is not None and period_id not in PROFILES.get(profile, PROFILES[DEFAULT_PROFILE]).periods:
        raise InvestigationRootsError(f"{period_id} is not in the {profile} profile")
    name = profile or (profile_for_period(period_id) if period_id else DEFAULT_PROFILE)
    if name not in PROFILES:
        raise InvestigationRootsError(f"unknown investigation profile {name!r} (configured: {', '.join(PROFILES)})")
    p = PROFILES[name]
    return InvestigationRoots(check_input_root(p.packs_root, "packs"), check_input_root(p.datasets_root, "datasets"),
                              check_output_root(investigations_root if investigations_root is not None else p.investigations_root),
                              p.name, frozenset({period_id}) if period_id else p.periods)
