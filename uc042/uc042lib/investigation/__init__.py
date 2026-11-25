"""UC-042 AI investigation layer (V1): a fixed LangGraph workflow that investigates exceptions already identified by the
deterministic engine. It never re-reconciles, never resolves exceptions and never edits deterministic packs."""
import logging

# Library convention: silent unless the application (for example the CLI in run.py) configures logging.
logging.getLogger("uc042.investigation").addHandler(logging.NullHandler())
