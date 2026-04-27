# mcp-osm — OpenStreetMap MCP server + Python Agent

[![CI](https://github.com/agent-engineering-studio/mcp-osm/actions/workflows/ci.yml/badge.svg)](https://github.com/agent-engineering-studio/mcp-osm/actions)
[![Docker](https://github.com/agent-engineering-studio/mcp-osm/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/agent-engineering-studio/mcp-osm/actions/workflows/docker-publish.yml)

A self-hosted **MCP server for OpenStreetMap** (Python FastMCP) plus a **Python
agent** with switchable LLM provider (Ollama / Claude / Azure AI Foundry) and
**dual REST + MCP surface** so it's directly composable with `mcp-ckan` and
other MCP-aware coordinators.

> **Why this exists:** an OSM-aware assistant you can plug into your own data
> pipelines, that produces standalone HTML maps (Leaflet + tile.openstreetmap.org)
> and doesn't depend on proprietary tile providers.

## TL;DR — Quick start

```bash
cp .env.example .env
make up-cpu                  # boots osm-mcp + agent + Ollama (CPU)
curl http://localhost:8002/health
```

For Claude or Azure Foundry instead of Ollama:

```bash
cp .env.dev-claude.example .env   # then fill ANTHROPIC_API_KEY
make up                            # (no Ollama profile)
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ External clients                                             │
│  • REST: Postman, .http, browser                             │
│  • MCP:  Claude Desktop, VS Code Copilot, other agents       │
└──────────────────┬───────────────────────┬──────────────────┘
                   │                       │
                   ▼ HTTP                  ▼ MCP Streamable HTTP
        ┌──────────────────────────────────────────┐
        │  osm-mcp-agent  (Python, agent_framework)│
        │   FastAPI :8002      MCP surface :8003   │
        │   /chat              agent.as_mcp_       │
        │   /chat/stream         server()          │
        │   /chat/with-geojson                     │
        │   /compose-map  ⭐                       │
        │   ChatAgent → MCPStreamableHTTPTool      │
        └──────────────────┬───────────────────────┘
                           ▼ /sse
            ┌──────────────────────────────────┐
            │  osm-mcp  (FastMCP, Python)      │
            │  13 tools: geocoding, routing,   │
            │  POI, EV, commute, area digest,  │
            │  + render_geojson_map,           │
            │    render_multi_layer_map,       │
            │    compose_map_from_resources    │
            └──────────────────────────────────┘
                           ▼
       Nominatim · Overpass · OSRM · OSM tile (Leaflet)
```

## Provider switching

The agent picks one of three LLM providers at startup based on `LLM_PROVIDER`:

| `LLM_PROVIDER` | Required env | Use when |
|---|---|---|
| `ollama` (default) | `OLLAMA_BASE_URL`, `OLLAMA_LLM_MODEL` | Local dev, offline, no API key |
| `claude` | `ANTHROPIC_API_KEY`, `CLAUDE_MODEL` | Highest reasoning quality |
| `azure_foundry` | `AZURE_AI_PROJECT_ENDPOINT`, `AZURE_AI_MODEL_DEPLOYMENT_NAME` (uses Managed Identity) | Production on Azure |

Three sample envs ship with the repo: `.env.example`, `.env.dev-claude.example`,
`.env.azure.example`. Copy one to `.env`.

## OSM tools (13)

10 geo tools (geocoding, routing, POI, EV charging, commute analysis, area digest, OSM upstream health) plus 3 map renderers:

- **`render_geojson_map(geojson, title?, center?, zoom?)`** — single-layer Leaflet map
- **`render_multi_layer_map(layers, title?, center?, zoom?)`** — multi-layer with legend and toggle
- **`compose_map_from_resources(text, resources, title?, center?, zoom?)`** ⭐ — accepts the `{text, resources[]}` shape emitted by `ckan-mcp-agent` and renders all GeoJSON resources on a single map

All three return MCP **multi-content blocks**: a text summary (LLM-friendly) **and**
an `EmbeddedResource` with `mimeType: text/html` for inline rendering in compatible viewers.

## Composing with mcp-ckan ⭐

The killer use case: a third-party coordinator agent mounts both `ckan-mcp-agent` and
`osm-mcp-agent` as MCP tools and pipes the output of one into the other.

```
Coordinator agent
  ├── tools[0] = MCPStreamableHTTPTool("ckan", url=ckan-mcp-agent /mcp)
  └── tools[1] = MCPStreamableHTTPTool("osm",  url=osm-mcp-agent  /mcp)
```

Two paths to compose:

| Path | What it calls | LLM cost | When |
|---|---|---|---|
| **Deterministic** | `POST /compose-map` (REST) — bypasses LLM, calls `osm-mcp.compose_map_from_resources` directly | $0 | 95% of cases |
| **Intelligent** | MCP `as_mcp_server()` — agent reasons, possibly enriches with OSM POIs | provider-dependent | Want smart layering, custom title, POI enrichment |

End-to-end test: `requests/agent-chat.http` section 7.

## MCP surface — agent-as-tool

The agent itself is exposed as MCP via `agent.as_mcp_server()` on `:8003/mcp`. Wire it
into Claude Desktop:

```jsonc
// claude_desktop_config.json
{
  "mcpServers": {
    "osm-agent": {
      "type": "streamable-http",
      "url": "http://localhost:8003/mcp"
    }
  }
}
```

Claude can now call `OsmAgent` as a single intelligent tool ("show me restaurants
near the Pantheon on a map") and get back the rendered HTML map.

## Testing

```bash
make mcp-test       # pytest on osm-mcp (24 tests)
make agent-test     # pytest on osm-mcp-agent (13 tests)
make smoke          # full stack + newman against the Postman collection
```

Manual: open `requests/agent-chat.http` in VS Code with the **REST Client** extension
and click "Send Request" on any of the 9 sections.

## Docker images on GHCR

Three images are published from `main` and on every `v*` tag:

| Image | Purpose |
|---|---|
| `ghcr.io/agent-engineering-studio/osm-mcp` | FastMCP server (multi-arch) |
| `ghcr.io/agent-engineering-studio/osm-mcp-agent` | Python agent (multi-arch) |
| `ghcr.io/agent-engineering-studio/osm-mcp-ollama` | Ollama with `qwen2.5:16k` baked in |

Pull-only quick start: `make up-ghcr`.

## Deploy on Azure

One-shot deploy to Azure Container Apps via Bicep:

```bash
# 1. (one-time) configure GitHub OIDC federation
make setup-oidc
# → save AZURE_CLIENT_ID / TENANT_ID / SUBSCRIPTION_ID as repo secrets

# 2. deploy
export AZURE_SUBSCRIPTION_ID=...
export ANTHROPIC_API_KEY=...   # if LLM_PROVIDER=claude
make deploy-azure

# 3. destroy when done
make destroy-azure
```

The Bicep template provisions:
- Log Analytics workspace
- User-assigned Managed Identity (for Foundry auth, no client secret)
- Container Apps Environment
- `osm-mcp` (internal-only ingress)
- `osm-mcp-agent` (public ingress on REST :8002 + MCP :8003)

CI deploy: push tag `v*` triggers `.github/workflows/deploy-azure.yml`.

## Roadmap & non-goals

**Out of scope for the current MVP** (see `docs/superpowers/specs/2026-04-27-mcp-osm-parity-design.md`):

- Automatic CRS reprojection (requires `pyproj`)
- PNG/SVG export of maps (requires headless browser)
- MAF orchestration (Magentic / Sequential / Concurrent)
- MapLibre GL with vector tiles
- Persistent session memory (Redis/DB)
- Application-level auth — handled at ingress
- Internal rate limiting — upstream OSM services have their own

## License

See `LICENSE`.
