FROM ubuntu:26.04

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON=3.14 \
    UV_PYTHON_INSTALL_DIR=/opt/uv/python \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    LOCAL_SHELL_MCP_WORKSPACE_ROOT=/workspace \
    LOCAL_SHELL_MCP_HOST=0.0.0.0 \
    LOCAL_SHELL_MCP_PORT=8765

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    ca-certificates \
    git \
    openssh-client \
    ripgrep \
    sudo \
    tmux \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE /app/
COPY src /app/src
RUN uv sync --locked --no-dev \
  && /app/.venv/bin/python -m compileall -q /app/src \
  && printf '#!/usr/bin/env bash\nexec /app/.venv/bin/python -m local_shell_mcp.main "$@"\n' > /usr/local/bin/local-shell-mcp \
  && chmod +x /usr/local/bin/local-shell-mcp

COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN mkdir -p /workspace /workspace/.local-shell-mcp /persist/credentials /home/agent \
  && chmod +x /usr/local/bin/docker-entrypoint.sh

WORKDIR /workspace

VOLUME ["/workspace", "/persist/credentials"]

EXPOSE 8765
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["local-shell-mcp", "--mode", "mcp"]
