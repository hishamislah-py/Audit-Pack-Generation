"""Shared helpers for the Phase 1 UC-042 tests (not a test module)."""
from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest

from smartparser.schemas import SchemaRegistry

FIXTURES = Path(__file__).parent / "fixtures" / "uc042_canonical"
SEP = FIXTURES / "PER-2026-09_set_01_clean_baseline"
MAY = FIXTURES / "PER-2026-05_demo_history"
# The isolated UC-042 working copy the registry was generated from. Tests that need it are skipped when it is absent.
UC042_ROOT = Path(os.environ.get("UC042_ROOT", r"C:\Users\artlptp263user\p10\uc042_token_optimisation"))
needs_uc042 = pytest.mark.skipif(not (UC042_ROOT / "uc042lib" / "schema.py").is_file(),
                                 reason=f"UC-042 tree not available at {UC042_ROOT} (set UC042_ROOT)")


def registry() -> SchemaRegistry:
    return SchemaRegistry.from_directory()


def manifest(dataset: Path) -> dict[str, dict]:
    """{relative_path: manifest row} - the dataset's own declaration (ground truth)."""
    with open(dataset / "manifest.csv", encoding="utf-8", newline="") as f:
        return {r["relative_path"]: r for r in csv.DictReader(f)}


def files_with_truth(dataset: Path) -> list[tuple[Path, str, dict]]:
    return [(dataset / rel, row["file_id"], row) for rel, row in sorted(manifest(dataset).items())]


def read(dataset: Path, file_id: str, nth: int = 0) -> bytes:
    """Bytes of the nth file the manifest declares as `file_id` (found via the manifest, not by name guessing)."""
    paths = [p for p, fid, _ in files_with_truth(dataset) if fid == file_id]
    return paths[nth].read_bytes()


def canonical_header(file_id: str) -> list[str]:
    return registry().get(file_id).csv.header
