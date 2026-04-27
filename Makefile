.PHONY: help \
  mcp-install mcp-test mcp-run mcp-inspector \
  agent-install agent-test agent-run \
  build up up-cpu up-gpu up-ghcr down logs \
  build-ollama refresh-ollama pull-models \
  smoke \
  deploy-azure destroy-azure setup-oidc

DC = docker compose

help:  ## Show this help
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ── MCP server (Python) ─────────────────────────────────────────────────
mcp-install:    ## Install osm-mcp with dev extras
	cd osm-mcp && pip install -e ".[dev]"

mcp-test:       ## Run pytest on osm-mcp
	cd osm-mcp && pytest -v

mcp-run:        ## Run osm-mcp locally (SSE on :8080)
	cd osm-mcp && MCP_TRANSPORT=sse MCP_HOST=0.0.0.0 MCP_PORT=8080 python -m osm_mcp.server

mcp-inspector:  ## Open the MCP Inspector against osm-mcp (stdio)
	cd osm-mcp && npx @modelcontextprotocol/inspector python -m osm_mcp.server

# ── Agent (Python) ──────────────────────────────────────────────────────
agent-install:  ## Install osm-mcp-agent with dev + claude + azure extras
	cd osm-mcp-agent && pip install --pre -e ".[dev,claude,azure]"

agent-test:     ## Run pytest on osm-mcp-agent
	cd osm-mcp-agent && pytest -v

agent-run:      ## Run the agent locally (REST :8002 + MCP :8003)
	cd osm-mcp-agent && python -m osm_agent.main

# ── Docker ──────────────────────────────────────────────────────────────
build:          ## Build all docker images
	$(DC) build

up:             ## Up the stack (no Ollama profile — assumes Ollama on host or claude/foundry)
	$(DC) up --build -d

up-cpu:         ## Up the stack with Ollama CPU container
	$(DC) --profile cpu up --build -d

up-gpu:         ## Up the stack with Ollama GPU container
	$(DC) --profile gpu up --build -d

up-ghcr:        ## Up using pre-built GHCR images (no local build)
	$(DC) -f docker-compose.ghcr.yml up -d

down:           ## Stop & remove everything
	$(DC) --profile gpu --profile cpu down

logs:           ## Tail logs of osm-mcp + agent
	$(DC) logs -f osm-mcp osm-mcp-agent

# ── Ollama image ────────────────────────────────────────────────────────
build-ollama:   ## Build the Ollama image with model baked
	docker build -t ghcr.io/agent-engineering-studio/osm-mcp-ollama:latest infra/ollama

refresh-ollama: build-ollama  ## Rebuild + recreate the Ollama container
	$(DC) --profile cpu up -d --force-recreate ollama-cpu

pull-models:    ## Pull base Ollama model on the host
	ollama pull qwen2.5:7b-instruct

# ── Smoke / integration ─────────────────────────────────────────────────
smoke:          ## Up stack + run newman against /compose-map and friends
	$(DC) up -d
	@bash requests/postman/test-agent-chat.sh

# ── Azure ───────────────────────────────────────────────────────────────
deploy-azure:   ## Deploy to Azure Container Apps via Bicep (bash)
	bash infra/scripts/deploy.sh

destroy-azure:  ## Destroy the resource group (irreversible)
	bash infra/scripts/destroy.sh

setup-oidc:     ## Configure GitHub OIDC federation for deploy-azure.yml
	bash infra/scripts/setup-github-oidc.sh
