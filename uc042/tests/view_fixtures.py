"""Packet fixtures for the phase 4-6 tests: every exception of every scenario pack, of the historical demonstration packs,
and (read-only, only if present) the 20-exception uploaded CASE pack in Clone E's storage. Nothing here writes anywhere."""
import glob
import os
from pathlib import Path

from uc042lib.investigation.packet import build_case, build_packet, build_scope, retrieve
from uc042lib.investigation.retrieval import EvidenceStore, load_pack
from uc042lib.investigation.routing import route_for

ROOT = Path(__file__).resolve().parent.parent
SOURCES = [("scenario", ROOT / "packs", ROOT / "uc042_dataset"),
           ("history", ROOT / "demo_history" / "packs", ROOT / "demo_history" / "datasets")]
CLONE_E_CASE = ("case", Path("C:/Users/artlptp263user/p10/env_e/packs"), Path("C:/Users/artlptp263user/p10/env_e/docstore/cases"),
                "PACK-CASE-PER-2026-09-9c7e777c3353")


def build(pack_id, packs_root, datasets_root, exception_id):
    pack = load_pack(pack_id, packs_root)
    case = build_case(pack, exception_id)
    route = route_for(case["exception"], case["candidates"], case["results"])
    store = EvidenceStore(pack, datasets_root)
    return pack, case, route, store, build_packet(case, build_scope(case), route, retrieve(route, case, store))


def all_packets(include_case=True):
    """Yield (label, pack_id, exception_id, packet, store, case, route)."""
    sources = [(k, p, d, os.path.basename(x)) for k, p, d in SOURCES for x in sorted(glob.glob(str(p / "PACK-*")))]
    if include_case and (CLONE_E_CASE[1] / CLONE_E_CASE[3] / "pack.json").is_file():
        sources.append(CLONE_E_CASE)
    for kind, packs_root, datasets_root, pack_id in sources:
        pack = load_pack(pack_id, packs_root)
        for x in pack["exception_register"]["exceptions"]:
            _, case, route, store, packet = build(pack_id, packs_root, datasets_root, x["exception_id"])
            yield f"{kind}:{pack_id.split('-')[1]}/{x['exception_id']}", pack_id, x["exception_id"], packet, store, case, route


def packet_from_message(content):
    """The evidence packet a mocked model would read from a first user message: the phase 4 model view (reconstructed
    losslessly) or the legacy raw packet JSON. Used by test responders that answer per exception."""
    import json
    from uc042lib.investigation.packet_view import reconstruct_packet
    if "<evidence_view>\n" in content:
        return reconstruct_packet(json.loads(content.split("<evidence_view>\n", 1)[1].rsplit("\n</evidence_view>", 1)[0]))
    return json.loads(content.split("<evidence_packet>\n", 1)[1].rsplit("\n</evidence_packet>", 1)[0])
