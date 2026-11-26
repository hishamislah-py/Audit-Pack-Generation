"""Isolated live E2E backend: the real application (create_app, real routes, services, PostgreSQL test DB, job runner) with
the provider replaced by the test suite's CONTROLLED FIXTURE: the real OpenAIInvestigator whose HTTP layer is mocked, so no
network request to any provider is possible. Investigations are answered from each request's own evidence packet by the
offline stub (deterministic: identical evidence gives identical findings); closing summaries by tests.api_support.MockProvider.
investigator_from_env is patched to fail, exactly as in the tests. Usage: python launch_backend.py <port>"""
import os
import sys
from unittest import mock

import uvicorn

# tests/__init__ clears UC042_DATABASE_URL and redirects UC042_FINAL_PACKS_ROOT (its safety guard for test runs); this isolated
# run sets both explicitly to the disposable test database and the isolated folder, so they are restored after the import.
_KEEP = {k: os.environ[k] for k in ("UC042_DATABASE_URL", "UC042_FINAL_PACKS_ROOT")}
assert _KEEP["UC042_DATABASE_URL"].endswith("/uc042_token_opt_test"), "only the disposable test database may be used"
from tests.api_support import MockProvider, no_live_provider  # noqa: E402
os.environ.update(_KEEP)
from tests.final_pack_support import OFFLINE, raw
from tests.view_fixtures import packet_from_message
from uc042app.api.main import create_app
from uc042lib.investigation.models import LLMInvestigationOutput

CALLS = {"investigation": 0, "summary": 0}
summary = MockProvider()


def respond(kw):
    content = kw["input"][0]["content"]
    if "<audit_pack_input>" in content:
        CALLS["summary"] += 1
        return summary.respond(kw)
    CALLS["investigation"] += 1
    out = OFFLINE.investigate(packet_from_message(content))[0].model_dump()
    return raw(LLMInvestigationOutput.model_validate(out))


provider = MockProvider()
provider.respond = respond
for target in ("uc042lib.investigation.llm.investigator_from_env", "uc042lib.final_pack.summary.investigator_from_env",
               "uc042app.services.investigator_from_env"):
    mock.patch(target, side_effect=no_live_provider).start()
app = create_app(investigator_factory=provider.factory)
uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="info")
