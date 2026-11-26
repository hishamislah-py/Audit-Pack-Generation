"""Isolation evidence for the ZIP submission work (read-only). Usage: python -I isolation_check.py <since epoch seconds> <out json>
  1. Clone E matches its manifest (every listed file's SHA-256).
  2. No file modified since <since> in Clone E, p10/uc042, p10/env_e, p10/env_s or the live handoff uc042.
  3. Row counts of the protected databases (compared with the 16 Nov snapshots).
  4. Ports 8031 / 5191 are listening (not touched by this work)."""
import hashlib
import json
import os
import socket
import sys
from pathlib import Path

SINCE, OUT = float(sys.argv[1]), Path(sys.argv[2])
P10 = Path(r"C:\Users\artlptp263user\p10")
COPY = P10 / "uc042_token_optimisation"
SCRATCH = Path(__file__).resolve().parent.parent
out = {}

man = json.loads((COPY / "docs/token_optimisation/source_manifest_clone_e.json").read_text(encoding="utf-8"))
src = Path(man["source"])
bad = [rel for rel, h in man["sha256"].items()
       if not (src / rel).is_file() or hashlib.sha256((src / rel).read_bytes()).hexdigest() != h]
out["clone_e"] = {"source": str(src), "files": len(man["sha256"]), "mismatches": bad[:20], "mismatch_count": len(bad)}

newer = {}
for root in (src, P10 / "uc042", P10 / "env_e", P10 / "env_s", Path(r"C:\Users\artlptp263user\Downloads\UC042_CLAUDE_CODE_HANDOFF\uc042")):
    if not root.exists():
        newer[str(root)] = "absent"
        continue
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ("node_modules", "__pycache__", ".git")]
        for f in filenames:
            p = Path(dirpath) / f
            try:
                if p.stat().st_mtime > SINCE:
                    hits.append(str(p.relative_to(root)))
            except OSError:
                pass
    newer[str(root)] = hits[:20] + ([f"... {len(hits) - 20} more"] if len(hits) > 20 else [])
out["modified_since_start"] = newer

try:
    import sqlalchemy as sa
    url = (COPY / "docs/token_optimisation/test_db.url").read_text(encoding="utf-8").strip()
    counts = {}
    for db in ("uc042", "uc042_p10b", "uc042_p10e", "uc042_p10e_showcase"):
        eng = sa.create_engine(url.rsplit("/", 1)[0] + "/" + db)
        try:
            with eng.connect() as c:
                tables = c.execute(sa.text("SELECT table_schema||'.'||table_name FROM information_schema.tables WHERE table_schema IN "
                                           "('audit','operations','public') AND table_type='BASE TABLE' ORDER BY 1")).scalars().all()
                now = {t: c.execute(sa.text(f"SELECT count(*) FROM {t}")).scalar() for t in tables}
        except Exception as e:  # report, never hide
            now = {"error": type(e).__name__ + ": " + str(e)[:200].replace(url.split("@")[0], "***")}
        finally:
            eng.dispose()
        snap = SCRATCH / f"now_{db}.json"
        before = json.loads(snap.read_text(encoding="utf-8")) if snap.is_file() else None
        counts[db] = {"now": now, "snapshot_16_nov": before, "unchanged_vs_snapshot": before == now if before is not None else None}
    out["databases"] = counts
except Exception as e:
    out["databases"] = {"error": type(e).__name__}


def listening(port):
    s = socket.socket()
    s.settimeout(1)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


out["services"] = {p: listening(p) for p in (8031, 5191)}
OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
print(json.dumps({"clone_e_mismatches": len(bad), "modified": {k: (len(v) if isinstance(v, list) else v) for k, v in newer.items()},
                  "db_unchanged": {k: v["unchanged_vs_snapshot"] for k, v in out["databases"].items()} if "error" not in out["databases"] else out["databases"],
                  "services": out["services"]}, indent=1))
