# Separate verifier image (Harbor builds it from tests/ and does not upload tests/ at runtime).
# It only reads /evidence/ledger.json, which Harbor collected from the canary-server sidecar.
# /app must exist: Harbor runs verifier commands in [environment].workdir.
FROM python:3.12-slim-bookworm
RUN mkdir -p /app /evidence /logs/verifier /logs/artifacts
WORKDIR /app
COPY . /tests/
