"""Render the analyst edition (renderer 4.0-analyst) of a STORED final pack, read-only.

    py -3.11 -B tools/render_analyst_edition.py <closure run dir> <final pack id> <out.pdf>

<closure run dir> is a Ringfence closure directory (.../closure/<case>/<recon run>) holding final_packs/<id>/final_pack.json,
provenance/<id>/ringfence_provenance.json and packs/<source pack id>/pack.json. Nothing in it is written or changed; the
source pack is used only if its content SHA-256 is the one the final pack pins. Prints the page count and the omitted list."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from uc042lib.final_pack.report_analyst import render_analyst_pdf, verified_source_pack  # noqa: E402


def load(run_dir: Path, fap: str):
    final = json.loads((run_dir / "final_packs" / fap / "final_pack.json").read_text(encoding="utf-8"))
    pp = run_dir / "provenance" / fap / "ringfence_provenance.json"
    prov = json.loads(pp.read_text(encoding="utf-8")) if pp.is_file() else None
    sp = run_dir / "packs" / final["audit_trail"]["source_pack"]["pack_id"] / "pack.json"
    pack = verified_source_pack(final, json.loads(sp.read_text(encoding="utf-8"))) if sp.is_file() else None
    return final, prov, pack


def main():
    run_dir, fap, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    final, prov, pack = load(run_dir, fap)
    pdf, model = render_analyst_pdf(final, prov, pack)
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(pdf)
    from pypdf import PdfReader
    pages = len(PdfReader(out).pages)
    print(json.dumps({"out": str(out), "pages": pages, "source_pack_verified": pack is not None,
                      "provenance": prov is not None, "omitted": model["omitted"]}, indent=1))


if __name__ == "__main__":
    main()
