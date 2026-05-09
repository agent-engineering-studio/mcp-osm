# osm-mcp-agent/Dockerfile
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

# Install with claude extra so both providers are available at
# runtime (chosen via LLM_PROVIDER env var). --pre is required because the
# agent-framework packages are still published as 1.0.0b* pre-releases.
# Extended timeout + retries for large wheels (anthropic SDK ~74MB).
RUN pip install --no-cache-dir --pre --timeout 120 --retries 3 -e ".[claude]"

EXPOSE 8002 8003

HEALTHCHECK --interval=30s --timeout=5s --retries=5 --start-period=20s \
  CMD curl -fsS http://localhost:8002/health || exit 1

CMD ["python", "-m", "osm_agent.main"]
