"""Contract check: every TypeScript interface in src/api/types.ts whose name matches a Pydantic response/request model in
uc042app/api/schemas.py must not declare fields the backend does not have (no invented fields). Run from uc042/:

    .venv/Scripts/python.exe -B frontend/scripts/check_contract.py

Exit code 1 lists mismatches. Interfaces for stored documents (findings, evidence, final-pack JSON) have no Pydantic
model in the API layer and are checked by the live integration test instead.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from pydantic import BaseModel  # noqa: E402

from uc042app.api import schemas  # noqa: E402

TS = (ROOT / "frontend" / "src" / "api" / "types.ts").read_text(encoding="utf-8")
ALIASES = {"Selection": "SelectionIn", "PublishedInvestigation": "PublishedInvestigation"}


def ts_interfaces(text):
    out = {}
    for m in re.finditer(r"export interface (\w+) \{(.*?)\n\}", text, re.S):
        fields = {}
        depth = 0
        for line in m.group(2).splitlines():
            if depth == 0:
                f = re.match(r"\s{2}(\w+)(\?)?:", line)
                if f:
                    fields[f.group(1)] = bool(f.group(2))
            depth += line.count("{") - line.count("}")
        out[m.group(1)] = fields
    return out


def main():
    models = {n: m for n, m in vars(schemas).items() if isinstance(m, type) and issubclass(m, BaseModel) and m.__module__ == schemas.__name__}
    problems, checked = [], []
    for name, fields in ts_interfaces(TS).items():
        model = models.get(ALIASES.get(name, name))
        if model is None:
            continue
        checked.append(name)
        backend = set(model.model_fields)
        for f in fields:
            if f not in backend:
                problems.append(f"{name}.{f}: not a field of {model.__name__}")
        for f, info in model.model_fields.items():
            if info.is_required() and f not in fields:
                problems.append(f"{name}: required backend field {f!r} is not typed (only a warning if the UI never reads it)")
    print(f"checked {len(checked)} interfaces against Pydantic models: {', '.join(sorted(checked))}")
    for p in problems:
        print("  " + p)
    hard = [p for p in problems if "not a field of" in p]
    print("OK" if not hard else f"{len(hard)} invented field(s)")
    sys.exit(1 if hard else 0)


if __name__ == "__main__":
    main()
