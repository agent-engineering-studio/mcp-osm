# osm-mcp-agent

Python agent for the OpenStreetMap MCP server, with provider switch (Ollama/Claude/Azure AI Foundry) and dual REST + MCP surface.

See top-level `README.md` for full documentation. See `docs/superpowers/specs/2026-04-27-mcp-osm-parity-design.md` for design.

## Quick start (local dev)

```bash
pip install -e ".[dev]"
python -m osm_agent.main
```

Endpoints (default):
- REST: http://localhost:8002 (`/health`, `/chat`, `/chat/stream`, `/chat/with-geojson`, `/compose-map`)
- MCP: http://localhost:8003/mcp (Streamable HTTP)
