"""UC-042 final audit pack (Phase 1 library; spec docs/audit_pack/06). Callable directly from Python; no web framework.

Workflow (each step is a separate call; the assembler never calls a model):

    pack = load_pack(pack_id)
    selections = default_selections(pack)                     # or the analyst's explicit choices
    snapshot = build_review_snapshot(pack_id, selections)     # verified inputs + snapshot SHA-256
    summary = generate_closing_summary(snapshot)              # AI, before the preview (or unavailable_closing_summary);
                                                              # not_required_closing_summary(snapshot) when
                                                              # closing_summary_required(snapshot) is False (no AI request)
    preview = assemble_preview(snapshot, summary)             # what the analyst reads; render_html / render_pdf
    final = assemble_final_pack(snapshot, summary, review, GenerationInfo(version=..., supersedes_final_pack_id=...))
    path = publish_final_pack(final)                          # write-once; verify_final_pack(path)
"""
from .assemble import FinalPackValidationError, assemble_final_pack, assemble_preview, content_sha256
from .model import (ACKNOWLEDGEMENT_TEXT, AnalystReview, ClosingSummary, ClosingSummaryOutput, GenerationInfo, PriorDecision,
                    Reviewer, ReviewRecord, Selection)
from .persistence import (FinalPackExistsError, FinalPackPublicationError, list_final_packs, next_version, publish_final_pack,
                          verify_final_pack)
from .render_html import render_html
from .render_pdf import render_pdf
from .snapshot import ReviewSnapshot, build_review_snapshot
from .sources import FinalPackInputError, default_selections, list_investigations, load_pack
from .outcome import outcome_summary
from .summary import (ClosingSummaryError, closing_summary_input, closing_summary_required, generate_closing_summary,
                      not_required_closing_summary, summary_fingerprint, summary_sha256, unavailable_closing_summary,
                      validate_closing_summary)

__all__ = [n for n in dir() if not n.startswith("_")]
