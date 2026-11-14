# Separate verifier image (Harbor builds it from tests/ and does not upload tests/ at runtime).
# It only reads /evidence/ledger.json, which Harbor collected from the canary-server sidecar, and checks its
# HMAC-SHA256 signature with /tests/ledger_key (build-time key, written by build.py; never in the agent image).
# /app must exist: Harbor runs verifier commands in [environment].workdir.
FROM python:3.12-slim-bookworm
RUN mkdir -p /app /evidence /logs/verifier /logs/artifacts
WORKDIR /app
COPY . /tests/
RUN chmod 0600 /tests/ledger_key
