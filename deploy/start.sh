#!/bin/sh
# Container entrypoint: prepare the persistent workspace and secrets under $UC042_DATA_DIR (/data, a volume), start
# nginx, then run the analyst application server (Smart Parser + UC-042 engine) on loopback port 8780.
set -e
DATA=${UC042_DATA_DIR:-/data}
WS=$DATA/ws
SECRETS=$DATA/secrets
mkdir -p "$WS" "$SECRETS"
chmod 700 "$SECRETS"
AUTH=$SECRETS/auth.json

# Sign-in account from ANALYST_USERNAME / ANALYST_PASSWORD (deployment secrets). Only a PBKDF2 hash is stored.
if [ -n "${ANALYST_USERNAME:-}" ] && [ -n "${ANALYST_PASSWORD:-}" ]; then
  (cd /app/src/app && python -m smartparser.webapp.auth set-password --file "$AUTH" \
      --username "$ANALYST_USERNAME" --password-env ANALYST_PASSWORD)
fi
unset ANALYST_PASSWORD
[ -f "$AUTH" ] || { echo "No sign-in account: set ANALYST_USERNAME and ANALYST_PASSWORD."; exit 1; }

# AI investigations: the application reads the OpenAI key only from an env file (exact key allowlist), never from its
# own environment. The file is written from the container environment when OPENAI_API_KEY is set. Model, timeout,
# token and reasoning settings are passed only when set; otherwise the application's validated defaults apply.
AIENV=$SECRETS/ai.env
AIARGS=""
if [ -n "${OPENAI_API_KEY:-}" ]; then
  ( umask 077
    echo "OPENAI_API_KEY=$OPENAI_API_KEY"
    for v in UC042_LLM_MODEL UC042_LLM_TIMEOUT_SECONDS UC042_LLM_MAX_TOKENS UC042_OPENAI_REASONING_EFFORT; do
      eval "val=\${$v:-}"
      [ -n "$val" ] && echo "$v=$val"
    done
    true ) > "$AIENV"
  AIARGS="--ai-env-file $AIENV"
  echo "AI investigations: ON"
else
  rm -f "$AIENV"
  echo "AI investigations: OFF (no OPENAI_API_KEY)"
fi
unset OPENAI_API_KEY

# Behind the HTTPS edge the session cookie must be Secure (COOKIE_SECURE=off only for plain-http local tests).
SECURE=""
[ "${COOKIE_SECURE:-on}" = "on" ] && SECURE="--cookie-secure"
export RINGFENCE_ENGINE_RELATIONSHIP_DISCOVERY=${RINGFENCE_ENGINE_RELATIONSHIP_DISCOVERY:-on}

nginx
cd /app/src/app
# Same flags as the validated demo server (deploy/start_demo.ps1). Demo-only TEST authority policy.
exec python -B -m smartparser.webapp.server \
  --root "$WS" \
  --authority tests/fixtures/review/test_authority_policy.json \
  --uc042-root /app/src/uc042 \
  --reviewer-id "${ANALYST_USERNAME:-analyst@ringfence.demo}" --reviewer-role analyst --reviewer-kind TEST \
  --auth-file "$AUTH" \
  --port 8780 \
  --demo-scenarios /app/src/demo_datasets/ringfence_demo_scenarios \
  --closure-python "$(command -v python)" \
  --ai-max-requests-per-operation "${AI_MAX_REQUESTS_PER_OPERATION:-5}" \
  --mapping-ai off \
  --default-theme "${DEFAULT_THEME:-light}" \
  $SECURE $AIARGS
