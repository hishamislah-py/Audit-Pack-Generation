"""UC-042 backend (Phase 2, local POC): a FastAPI application around the existing uc042lib libraries (spec
docs/audit_pack/06 §8, simplified: one analyst, no authentication, bound to 127.0.0.1, one process).

Layers, each importing only the ones below it:

    api/            FastAPI routers, Pydantic request/response schemas, problem-details errors
    services/       application services (packs, investigations, publication registry, reviews, final packs)
    jobs/           background job runner (thread pool, persisted job state, restart recovery)
    repositories/   persistence interfaces (base.py) and their file-backed implementations (files.py)
    storage/        atomic file primitives and the single-process instance lock

The libraries (uc042lib.pack, uc042lib.investigation, uc042lib.final_pack) are called directly and never modified.
"""
