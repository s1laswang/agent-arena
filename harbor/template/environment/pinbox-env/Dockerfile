# The Poisoned Inbox environment server (Harbor sidecar service "pinbox-env").
# It serves one episode's tools over MCP (streamable HTTP, port 8000) and keeps
# the episode state in its own filesystem. The agent's container cannot read or
# write anything here; it can only call the MCP tools.
FROM @@BASE_IMAGE@@

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Pinned MCP SDK and its full dependency set (same versions as our tests).
COPY requirements.txt /opt/pinbox/requirements.txt
RUN pip install --no-cache-dir --root-user-action=ignore -r /opt/pinbox/requirements.txt

# A snapshot of the pinbox package, made by harbor/build_tasks.py.
COPY pinbox.zip /opt/pinbox/pinbox.zip
RUN python -m zipfile -e /opt/pinbox/pinbox.zip /opt/pinbox/src \
    && rm /opt/pinbox/pinbox.zip \
    && python -c "import sys; sys.path.insert(0, '/opt/pinbox/src'); import pinbox.mcp_server, pinbox.grader" \
    && useradd --system --create-home --uid 10001 pinbox \
    && mkdir -p /srv/pinbox \
    && chown pinbox:pinbox /srv/pinbox

COPY start.sh collect.py /opt/pinbox/
RUN chmod 0755 /opt/pinbox/start.sh /opt/pinbox/collect.py

ENV PYTHONPATH=/opt/pinbox/src \
    PINBOX_STATE_DIR=/srv/pinbox/state

USER pinbox
WORKDIR /srv/pinbox
EXPOSE 8000
CMD ["/opt/pinbox/start.sh"]
