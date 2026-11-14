# The agent's container (Harbor service "main").
# It holds NO Poisoned Inbox code and NO episode state. The task lives in the
# "pinbox-env" service and is reachable only over MCP: http://pinbox-env:8000/mcp
FROM @@BASE_IMAGE@@

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
