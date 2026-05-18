# presto-mcp server image
# Runs the MCP STDIO server. Mounts data/ and runs/ from the host.
#
# Build:
#   docker build -t presto-mcp:latest .
#
# Run (Claude Desktop / any MCP client):
#   docker run --rm -i \
#     -v /abs/path/to/data:/workspace/data:ro \
#     -v /abs/path/to/runs:/workspace/runs \
#     presto-mcp:latest
#
# NOTE: MVP production usage is host stdio (`uv run python -m presto_mcp.server`).
# Do not mount docker.sock for this server; host Docker is invoked directly by
# the stdio process.

FROM python:3.11-slim

# Install docker CLI (needed to spawn PRESTO sub-containers)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
 && curl -fsSL https://download.docker.com/linux/debian/gpg \
    | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] \
    https://download.docker.com/linux/debian $(lsb_release -cs) stable" \
    > /etc/apt/sources.list.d/docker.list \
 && apt-get update && apt-get install -y --no-install-recommends docker-ce-cli \
 && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install --no-cache-dir uv

WORKDIR /workspace

# Copy project metadata first (layer-cache friendly)
COPY pyproject.toml uv.lock* ./

# Install runtime deps only (no dev)
RUN uv sync --no-dev

# Copy source
COPY src/ src/

ENV PRESTO_DATA_DIR=/workspace/data \
    PRESTO_RUNS_DIR=/workspace/runs \
    PRESTO_OUTPUTS_DIR=/workspace/outputs \
    PRESTO_IMAGE=alex88ridolfi/presto5:png

# stdio — no EXPOSE needed
CMD ["uv", "run", "python", "-m", "presto_mcp.server"]
