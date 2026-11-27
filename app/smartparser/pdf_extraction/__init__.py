"""Experiment A: native (no-OCR) PDF field extraction and canonical mapping for the five UC-042 PDF categories.

ISOLATED EXPERIMENT. Not called by the pipeline, packages, handoff, submission or audit-pack code. Produces proposal
records only; never applies, accepts or submits. See docs/PDF_NATIVE_EXTRACTION_FEASIBILITY_REPORT.md.
"""
from .extractor import EXPERIMENT_VERSION, ExtractedField, ExtractionResult, extract_document

__all__ = ["EXPERIMENT_VERSION", "ExtractedField", "ExtractionResult", "extract_document"]
