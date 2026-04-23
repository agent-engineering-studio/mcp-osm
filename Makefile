.PHONY: \
  help \
  mcp-install mcp-test mcp-run mcp-inspector \
  agent-build agent-run \
  build up up-cpu up-gpu up-dev-cpu up-dev-gpu down logs \
  pull-models \
  deploy-azure deploy-azure-ps

DC = docker compose

help:  ## Show this help
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ── Python MCP ────────────────────────────────────────────────────────────────
mcp-install:  ## Install osm-mcp with dev extras
	cd osm-mcp && pip install -e ".[dev]"

mcp-test:  ## Run pytest on osm-mcp
	cd osm-mcp && pytest -v

mcp-run:  ## Run osm-mcp locally in stdio mode (for Claude Desktop/Code)
	cd osm-mcp && MCP_TRANSPORT=stdio python -m osm_mcp.server

mcp-run-sse:  ## Run osm-mcp locally in SSE mode on :8080
	cd osm-mcp && MCP_TRANSPORT=sse MCP_HOST=0.0.0.0 MCP_PORT=8080 python -m osm_mcp.server

mcp-inspector:  ## Open the MCP Inspector against the stdio server
	cd osm-mcp && npx @modelcontextprotocol/inspector python -m osm_mcp.server

# ── .NET Agent ────────────────────────────────────────────────────────────────
agent-build:  ## dotnet restore + build
	cd osm-agent && dotnet build -c Release

agent-run:  ## Run the agent locally (needs MCP on :8080 and Ollama on :11434)
	cd osm-agent && dotnet run

# ── Docker ────────────────────────────────────────────────────────────────────
build:  ## Build all docker images (all profiles)
	$(DC) --profile prod --profile gpu --profile cpu build

up:  ## Full stack, Ollama on host (via host.docker.internal)
	$(DC) --profile prod up --build -d

up-cpu:  ## Full stack + Ollama CPU-only in container
	$(DC) --profile prod --profile cpu up --build -d

up-gpu:  ## Full stack + Ollama with NVIDIA GPU in container
	$(DC) --profile prod --profile gpu up --build -d

up-dev-cpu:  ## Only Ollama CPU container (for local dev of the agent)
	$(DC) --profile cpu up -d

up-dev-gpu:  ## Only Ollama GPU container (for local dev of the agent)
	$(DC) --profile gpu up -d

down:  ## Stop & remove everything across profiles
	$(DC) --profile prod --profile gpu --profile cpu down

logs:  ## Tail logs for both app services
	$(DC) logs -f osm-mcp osm-agent

pull-models:  ## Force re-pull of Ollama models on the host
	ollama pull qwen2.5:7b

# ── Azure deploy ──────────────────────────────────────────────────────────────
deploy-azure:  ## Deploy to Azure Container Apps (bash)
	bash scripts/deploy-azure.sh

deploy-azure-ps:  ## Deploy to Azure Container Apps (PowerShell)
	pwsh scripts/deploy-azure.ps1
