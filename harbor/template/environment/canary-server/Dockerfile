# Game-server sidecar: the ONLY place the canary package, the Env, the world secret and the ledger token live.
# build.py vendors into this build context:
#   ./canary                         the package source (no data/, no SALT, no worlds)
#   ./data/worlds/judge/SALT         the world secret generated at BUILD time (never committed, never in
#                                    the agent image). canary/world.py reads it as <pkg>/../data/worlds/judge/SALT,
#                                    so the secret is a 0600 file owned by the server uid, not an env var.
FROM python:3.12-slim-bookworm

# Pinned to uv.lock.
RUN pip install --no-cache-dir "numpy==2.4.6" "pydantic==2.14.3" "python-dotenv==1.2.4" "mcp==2.3.0"

RUN useradd --system --uid 10001 --home-dir /opt/canary-server --shell /usr/sbin/nologin canary \
    && mkdir -p /opt/canary-server/data/worlds/judge /run/canary /evidence \
    && chown canary:canary /run/canary /evidence && chmod 0700 /run/canary
WORKDIR /opt/canary-server
COPY canary /opt/canary-server/canary
COPY entrypoint.sh collect.py /opt/canary-server/
# (no COPY --chmod: Harbor may build with the classic builder, which lacks BuildKit features)
COPY --chown=canary:canary data/worlds/judge/SALT /opt/canary-server/data/worlds/judge/SALT
RUN chmod 0600 /opt/canary-server/data/worlds/judge/SALT
ENV PYTHONPATH=/opt/canary-server PYTHONUNBUFFERED=1

USER canary
EXPOSE 8765
ENTRYPOINT ["sh", "/opt/canary-server/entrypoint.sh"]
