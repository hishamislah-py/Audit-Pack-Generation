"""Default locations of runtime OUTPUT, outside the source repository. No user name or machine-specific path is written
here: the default is derived from the operating system's per-user data directory, and every deployment may (and should)
set the location explicitly.

    UC042_FINAL_PACKS_ROOT   where primary (operational) final audit packs are published. Default:
                             %LOCALAPPDATA%/UC042/final_packs on Windows, $XDG_DATA_HOME/uc042/final_packs (or
                             ~/.local/share/uc042/final_packs) elsewhere.

The value is read when it is needed (not at import), so a local .env loaded by the investigation layer applies. The
historical-demonstration profile keeps its own, fixed location (demo_history/final_packs); see
uc042lib.investigation.roots."""
import os
from pathlib import Path

ENV_FINAL_PACKS_ROOT = "UC042_FINAL_PACKS_ROOT"
PROJECT = Path(__file__).resolve().parents[1]


def user_data_dir():
    """The per-user application data directory (outside any source checkout)."""
    if os.environ.get("LOCALAPPDATA", "").strip():
        return Path(os.environ["LOCALAPPDATA"].strip()) / "UC042"
    base = os.environ.get("XDG_DATA_HOME", "").strip()
    return (Path(base) if base else Path.home() / ".local" / "share") / "uc042"


def default_final_packs_root():
    """UC042_FINAL_PACKS_ROOT when set (a blank value counts as unset), else the per-user data directory."""
    configured = os.environ.get(ENV_FINAL_PACKS_ROOT, "").strip()
    return Path(configured).resolve() if configured else (user_data_dir() / "final_packs").resolve()


def inside_project(path):
    """True when path is the source repository or lies inside it."""
    path, project = Path(path).resolve(), PROJECT.resolve()
    return path == project or project in path.parents
