# mcp-osm parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `mcp-osm` to infrastructure parity with `mcp-ckan` (Python agent with provider switch ollama/claude/azure_foundry, dual REST+MCP surface, Bicep IaC, full CI/CD, .http+Postman tests) and add GeoJSON→HTML map rendering composable with `ckan-mcp-agent`.

**Architecture:** 3-tier — (L1) external clients · (L2) `osm-mcp` FastMCP server (8 existing + 3 new tools) · (L3) `osm-mcp-agent` Python agent exposed as both REST :8002 and MCP :8003 via `agent.as_mcp_server()`. The new tool `compose_map_from_resources` accepts the stable `{text, resources[]}` contract emitted by `ckan-mcp-agent` so a third-party coordinator can chain `ckan→osm` with zero adapter code.

**Tech Stack:** Python 3.12, FastAPI, agent_framework + agent-framework-{ollama,anthropic,foundry}, FastMCP, Leaflet 1.9.4 (CDN), OSM raster tiles, Jinja2, pydantic-settings, httpx, Docker Compose, GitHub Actions, Bicep, Azure Container Apps. Spec reference: `docs/superpowers/specs/2026-04-27-mcp-osm-parity-design.md`.

**Out of scope (per spec §12):** CRS reprojection, PNG/SVG export, MAF orchestration, MapLibre vector tiles, persistent session memory, app-level auth, internal rate limiting.

---

## File Structure (decomposition lock-in)

### `osm-mcp/` (existing — extend)

| File | Action | Responsibility |
|---|---|---|
| `pyproject.toml` | modify | add deps: `jinja2`, `geojson` |
| `src/osm_mcp/config.py` | modify | add `MAP_TILE_URL`, `MAP_ATTRIBUTION`, `MAP_DEFAULT_ZOOM`, `MAP_MAX_FEATURES_PER_LAYER` |
| `src/osm_mcp/geojson_builder.py` | create | parse/validate GeoJSON, normalize to FeatureCollection, compute bounds, palette |
| `src/osm_mcp/html_renderer.py` | create | Jinja2 → HTML self-contained Leaflet map |
| `src/osm_mcp/tools.py` | modify | register 3 new tools (`render_geojson_map`, `render_multi_layer_map`, `compose_map_from_resources`) |
| `templates/map.html.j2` | create | Leaflet template with OSM raster tiles |
| `tests/test_geojson_builder.py` | create | unit tests for parser/bounds/palette |
| `tests/test_html_renderer.py` | create | template rendering smoke tests |
| `tests/test_compose_resources.py` | create | end-to-end test using ckan fixture |
| `tests/fixtures/ckan_response.json` | create | realistic ckan-mcp-agent response with 2 GeoJSON resources + 1 PDF skipped |

### `osm-mcp-agent/` (new — replaces `osm-agent/` .NET)

| File | Action | Responsibility |
|---|---|---|
| `pyproject.toml` | create | deps + entrypoint `osm-agent` |
| `Dockerfile` | create | python:3.12-slim, expose 8002+8003 |
| `README.md` | create | quick reference for the agent module |
| `src/osm_agent/__init__.py` | create | empty package marker |
| `src/osm_agent/config.py` | create | pydantic Settings (provider switch + ports) |
| `src/osm_agent/contracts.py` | create | `Resource`, `ChatResponse`, `ComposeMapRequest`, `ChatRequest` pydantic mirrors |
| `src/osm_agent/factory.py` | create | `build_chat_client` + `AgentSession` (mirror of ckan factory, no regional router) |
| `src/osm_agent/api.py` | create | FastAPI app: `/chat`, `/chat/stream`, `/chat/with-geojson`, `/compose-map`, `/health` |
| `src/osm_agent/mcp_surface.py` | create | wires `agent.as_mcp_server()` on Streamable HTTP :8003 |
| `src/osm_agent/main.py` | create | entrypoint: runs FastAPI + MCP surface in parallel |
| `tests/test_factory.py` | create | provider switch with mocked clients |
| `tests/test_contracts.py` | create | pydantic Resource/ChatResponse roundtrip with ckan fixture |
| `tests/test_compose_endpoint.py` | create | POST /compose-map → MCP raw call → ChatResponse |
| `tests/test_chat_with_geojson.py` | create | multipart upload triggers prompt enrichment |

### `infra/`

| File | Action | Responsibility |
|---|---|---|
| `infra/ollama/Dockerfile` | modify | base ollama/ollama + COPY Modelfile + entrypoint |
| `infra/ollama/Modelfile` | create | `qwen2.5:7b-instruct` + `num_ctx 16384` + system prompt |
| `infra/ollama/entrypoint.sh` | create | `ollama serve & ollama create qwen2.5:16k -f /Modelfile` |
| `infra/bicep/main.bicep` | create | orchestrator (CAE + ACR-less GHCR + Log Analytics + 2 Container Apps + identity) |
| `infra/bicep/main.parameters.json` | create | default parameters |
| `infra/bicep/modules/log-analytics.bicep` | create | workspace |
| `infra/bicep/modules/container-app-env.bicep` | create | CAE wired to Log Analytics |
| `infra/bicep/modules/container-app-mcp.bicep` | create | osm-mcp Container App, internal ingress only |
| `infra/bicep/modules/container-app-agent.bicep` | create | osm-mcp-agent Container App, public ingress + additional port for MCP :8003 |
| `infra/bicep/modules/identity.bicep` | create | user-assigned managed identity for Foundry auth |
| `infra/scripts/deploy.sh` | create | `az deployment group create` wrapper |
| `infra/scripts/deploy.ps1` | create | PowerShell mirror |
| `infra/scripts/destroy.sh` | create | `az group delete --no-wait` with confirm |
| `infra/scripts/destroy.ps1` | create | PowerShell mirror |
| `infra/scripts/setup-github-oidc.sh` | create | AAD app + federated credentials + role assignment |

### `requests/` (new)

| File | Action | Responsibility |
|---|---|---|
| `requests/agent-chat.http` | create | 9 sections: health, geocode, POI, route, stream, geojson upload, compose ckan→osm, MCP surface, MCP raw |
| `requests/postman/osm-mcp-agent.postman_collection.json` | create | 8 folders, env vars, basic test scripts |
| `requests/postman/test-agent-chat.sh` | create | newman runner |
| `requests/postman/test-agent-chat.ps1` | create | PowerShell mirror |

### `.github/workflows/` (rewrite + add)

| File | Action | Responsibility |
|---|---|---|
| `.github/workflows/ci.yml` | rewrite | 3 jobs: python-mcp-server, python-agent, smoke-integration |
| `.github/workflows/docker-publish.yml` | create (replaces release-docker.yml) | multi-arch GHCR push for both services |
| `.github/workflows/publish-ollama.yml` | create | bake Ollama image with model |
| `.github/workflows/deploy-azure.yml` | rewrite | OIDC + Bicep deploy |
| `.github/workflows/release-docker.yml` | delete | superseded by docker-publish.yml |

### Root

| File | Action | Responsibility |
|---|---|---|
| `docker-compose.yml` | rewrite | osm-mcp + osm-mcp-agent + ollama profiles |
| `docker-compose.ghcr.yml` | rewrite | pull-only variant pointing at GHCR images |
| `.env.example` | rewrite | local dev defaults (Ollama) |
| `.env.azure.example` | create | provider=azure_foundry profile |
| `.env.dev-claude.example` | create | provider=claude profile |
| `Makefile` | rewrite | targets for mcp/agent/docker/ollama/azure/smoke |
| `README.md` | rewrite | quick-start, architecture, composition, MCP surface, deploy |
| `osm-agent/` | DELETE | .NET agent removed in same PR |
| `scripts/deploy-azure.sh` | DELETE | superseded by `infra/scripts/deploy.sh` |
| `scripts/deploy-azure.ps1` | DELETE | superseded by `infra/scripts/deploy.ps1` |

---

## Task Order Rationale

Tasks 1–2 set up the foundation files. Tasks 3–6 build `osm-mcp` GeoJSON/HTML capabilities (TDD). Tasks 7–11 build the new Python agent (TDD where applicable). Tasks 12–14 wire infrastructure (Docker + Ollama image). Tasks 15–17 add tests/CI/Bicep. Task 18 writes README and Makefile. Task 19 is the cleanup commit (delete .NET).

Each task commits independently. Following commits unblock CI on the next task. If a task fails verification, fix before moving on.

---

## Task 1: Bootstrap `osm-mcp-agent/` package skeleton

**Files:**
- Create: `osm-mcp-agent/pyproject.toml`
- Create: `osm-mcp-agent/src/osm_agent/__init__.py`
- Create: `osm-mcp-agent/README.md`
- Create: `osm-mcp-agent/.dockerignore`

- [ ] **Step 1: Create `osm-mcp-agent/pyproject.toml`**

> **Note:** Mirror of `mcp-ckan/ckan-mcp-agent/pyproject.toml` — same build backend (hatchling), same beta-pinned versions (`>=1.0.0b1`), same `[claude]` / `[azure]` extras pattern. The Microsoft Agent Framework is currently published only as pre-release (`1.0.0b*`), so the `>=1.0.0b1` pin is required for pip to resolve.

```toml
[project]
name = "osm-mcp-agent"
version = "0.1.0"
description = "Microsoft Agent Framework agent that consumes the OSM MCP server and renders Leaflet maps. Provider switch ollama/claude/azure_foundry, dual REST + MCP surface."
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
authors = [{ name = "Agent Engineering Studio" }]
dependencies = [
    "agent-framework>=1.0.0b1",
    "agent-framework-ollama>=1.0.0b1",
    "mcp>=1.2.0",
    "openai>=1.50.0",
    "httpx>=0.27.0",
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "pydantic>=2.7.0",
    "pydantic-settings>=2.3.0",
    "python-dotenv>=1.0.0",
    "python-multipart>=0.0.9",
    "geojson>=3.0.0",
    "rich>=13.7.0",
]

[project.optional-dependencies]
azure = [
    "azure-identity>=1.17.0",
    "agent-framework-foundry>=1.0.0b1",
]
claude = [
    "agent-framework-anthropic>=1.0.0b1",
]
dev = [
    "pytest>=8.2.0",
    "pytest-asyncio>=0.23.0",
    "respx>=0.21.0",
    "ruff>=0.6.0",
]

[project.scripts]
osm-agent = "osm_agent.main:run"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/osm_agent"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Create empty package marker**

```python
# osm-mcp-agent/src/osm_agent/__init__.py
"""OpenStreetMap MCP agent."""
__version__ = "0.1.0"
```

- [ ] **Step 3: Create stub README**

```markdown
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
```

- [ ] **Step 4: Create `.dockerignore`**

```
__pycache__
*.pyc
.pytest_cache
.venv
.env
```

- [ ] **Step 5: Verify package installs**

Run:
```bash
cd osm-mcp-agent
# Install with claude+azure extras to validate the provider switch in Task 7
python -m pip install -e ".[dev,claude,azure]"
python -c "import osm_agent; print(osm_agent.__version__)"
```
Expected: `0.1.0` printed.

If pip refuses the `agent-framework*>=1.0.0b1` constraint, pre-releases are blocked on this Python install — re-run with `--pre`:
```bash
python -m pip install --pre -e ".[dev,claude,azure]"
```

- [ ] **Step 6: Commit**

```bash
git add osm-mcp-agent/pyproject.toml osm-mcp-agent/src/osm_agent/__init__.py osm-mcp-agent/README.md osm-mcp-agent/.dockerignore
git commit -m "feat(agent): scaffold osm-mcp-agent Python package skeleton"
```

---

## Task 2: Pydantic contracts + Settings

**Files:**
- Create: `osm-mcp-agent/src/osm_agent/contracts.py`
- Create: `osm-mcp-agent/src/osm_agent/config.py`
- Create: `osm-mcp-agent/tests/__init__.py`
- Create: `osm-mcp-agent/tests/test_contracts.py`
- Create: `osm-mcp-agent/tests/fixtures/ckan_response.json`

- [ ] **Step 1: Write the failing test for contracts**

```python
# osm-mcp-agent/tests/test_contracts.py
"""Verify Resource/ChatResponse mirror the ckan-mcp-agent JSON shape."""
import json
from pathlib import Path

from osm_agent.contracts import ChatResponse, ComposeMapRequest, Resource

FIXTURE = Path(__file__).parent / "fixtures" / "ckan_response.json"


def test_resource_accepts_ckan_shape():
    payload = {"name": "Bus stops", "url": "https://example/x.geojson",
               "format": "GEOJSON", "content": '{"type":"FeatureCollection","features":[]}'}
    r = Resource(**payload)
    assert r.format == "GEOJSON"
    assert r.content.startswith("{")


def test_resource_optional_url_and_content():
    r = Resource(name="x", format="PDF")
    assert r.url is None
    assert r.content is None


def test_chat_response_roundtrip_from_ckan_fixture():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    resp = ChatResponse(**raw)
    assert resp.text
    assert len(resp.resources) >= 2
    assert any(r.format.upper() == "GEOJSON" for r in resp.resources)


def test_compose_map_request_accepts_chat_response():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    req = ComposeMapRequest(**raw)
    assert req.text == raw["text"]
    assert len(req.resources) == len(raw["resources"])
```

- [ ] **Step 2: Create the fixture file**

```json
// osm-mcp-agent/tests/fixtures/ckan_response.json
{
  "text": "Found 3 datasets about public transport in Tuscany.",
  "resources": [
    {
      "name": "Bus stops Florence",
      "url": "https://dati.toscana.it/dataset/example/fermate.geojson",
      "format": "GEOJSON",
      "content": "{\"type\":\"FeatureCollection\",\"features\":[{\"type\":\"Feature\",\"geometry\":{\"type\":\"Point\",\"coordinates\":[11.255,43.769]},\"properties\":{\"name\":\"Stazione SMN\"}},{\"type\":\"Feature\",\"geometry\":{\"type\":\"Point\",\"coordinates\":[11.262,43.776]},\"properties\":{\"name\":\"Piazza San Marco\"}}]}"
    },
    {
      "name": "Tramway lines",
      "url": "https://dati.toscana.it/dataset/example/tramvia.geojson",
      "format": "GEOJSON",
      "content": "{\"type\":\"FeatureCollection\",\"features\":[{\"type\":\"Feature\",\"geometry\":{\"type\":\"LineString\",\"coordinates\":[[11.20,43.77],[11.30,43.78]]},\"properties\":{\"line\":\"T1\"}}]}"
    },
    {
      "name": "Schedule PDF",
      "url": "https://dati.toscana.it/dataset/example/schedule.pdf",
      "format": "PDF",
      "content": null
    }
  ]
}
```

- [ ] **Step 3: Run tests — confirm they fail with ImportError**

Run: `cd osm-mcp-agent && pytest tests/test_contracts.py -v`
Expected: FAIL — `ImportError: cannot import name 'Resource' from 'osm_agent.contracts'`

- [ ] **Step 4: Implement `contracts.py`**

```python
# osm-mcp-agent/src/osm_agent/contracts.py
"""Stable JSON-shape contracts for inter-agent composition.

These mirror the shape emitted by ckan-mcp-agent (see ckan_agent.api.Resource /
ChatResponse). The contract is the JSON shape, not the Python class — we don't
share a library with ckan-mcp-agent on purpose so each agent can evolve fields
independently.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class Resource(BaseModel):
    """A resource produced by an agent. Mirrors ckan-mcp-agent.api.Resource."""

    name: str
    url: str | None = None
    format: str
    content: str | None = None


class ChatResponse(BaseModel):
    """Universal agent reply: narrative text + heterogeneous resources."""

    text: str
    resources: list[Resource] = Field(default_factory=list)


class ChatRequest(BaseModel):
    """Body of POST /chat and POST /chat/stream."""

    query: str


class ComposeMapRequest(BaseModel):
    """Body of POST /compose-map. Accepts the same shape as ChatResponse plus
    optional rendering hints."""

    text: str = ""
    resources: list[Resource]
    title: str | None = None
    center: list[float] | None = None  # [lat, lon]
    zoom: int | None = None
```

- [ ] **Step 5: Run tests — verify pass**

Run: `cd osm-mcp-agent && pytest tests/test_contracts.py -v`
Expected: 4 PASS.

- [ ] **Step 6: Implement `config.py`**

```python
# osm-mcp-agent/src/osm_agent/config.py
"""Pydantic Settings — env-driven configuration for osm-mcp-agent."""
from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ── LLM provider switch ──
    llm_provider: Literal["ollama", "claude", "azure_foundry"] = "ollama"

    # Ollama
    ollama_base_url: str = "http://osm-ollama:11434"
    ollama_llm_model: str = "qwen2.5:16k"
    ollama_num_ctx: int = 16384

    # Claude (Anthropic)
    anthropic_api_key: str | None = None
    claude_model: str = "claude-sonnet-4-6"

    # Azure AI Foundry
    azure_ai_project_endpoint: str | None = None
    azure_ai_model_deployment_name: str | None = None

    # ── osm-mcp upstream ──
    mcp_server_url: str = "http://osm-mcp:8080/mcp"
    mcp_server_name: str = "osm-mcp"
    mcp_approval_mode: Literal["never_require", "always_require"] = "never_require"

    # ── Agent identity ──
    agent_name: str = "OsmAgent"

    # ── REST API ──
    api_host: str = "0.0.0.0"
    api_port: int = 8002

    # ── MCP surface ──
    mcp_surface_enabled: bool = True
    mcp_surface_host: str = "0.0.0.0"
    mcp_surface_port: int = 8003
    mcp_surface_path: str = "/mcp"

    # ── Misc ──
    log_level: str = "INFO"


def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 7: Smoke test config**

Run:
```bash
cd osm-mcp-agent && python -c "from osm_agent.config import get_settings; s=get_settings(); print(s.llm_provider, s.api_port, s.mcp_surface_port)"
```
Expected: `ollama 8002 8003`

- [ ] **Step 8: Commit**

```bash
git add osm-mcp-agent/src/osm_agent/contracts.py osm-mcp-agent/src/osm_agent/config.py osm-mcp-agent/tests/__init__.py osm-mcp-agent/tests/test_contracts.py osm-mcp-agent/tests/fixtures/ckan_response.json
git commit -m "feat(agent): add pydantic contracts + Settings (mirror of ckan shape)"
```

---

## Task 3: `osm-mcp` config extension + dependencies

**Files:**
- Modify: `osm-mcp/pyproject.toml`
- Modify: `osm-mcp/src/osm_mcp/config.py`

- [ ] **Step 1: Read current `pyproject.toml` and `config.py`**

Run:
```bash
cat osm-mcp/pyproject.toml
cat osm-mcp/src/osm_mcp/config.py
```
Note current dependencies and config fields — preserve them.

- [ ] **Step 2: Add deps to `osm-mcp/pyproject.toml`**

Add to `[project] dependencies`:
```toml
"jinja2 >=3.1",
"geojson >=3.0",
```

(Keep all existing deps unchanged.)

- [ ] **Step 3: Extend `osm-mcp/src/osm_mcp/config.py`**

Append (or merge into the existing Settings class) the new fields:

```python
# Map rendering settings
MAP_TILE_URL: str = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
MAP_ATTRIBUTION: str = (
    '&copy; <a href="https://www.openstreetmap.org/copyright">'
    "OpenStreetMap</a> contributors"
)
MAP_DEFAULT_ZOOM: int = 13
MAP_MAX_FEATURES_PER_LAYER: int = 5000
```

(Use the same pydantic-settings pattern already in the file. If config is a module-level dict, follow that style instead.)

- [ ] **Step 4: Reinstall**

Run: `cd osm-mcp && pip install -e ".[dev]"`
Expected: success.

- [ ] **Step 5: Smoke test**

Run: `cd osm-mcp && python -c "from osm_mcp.config import get_settings; s=get_settings(); print(s.MAP_TILE_URL, s.MAP_DEFAULT_ZOOM)"`
Expected: `https://tile.openstreetmap.org/{z}/{x}/{y}.png 13`

(Adapt command if config.py exposes settings differently — e.g., `from osm_mcp import config; print(config.MAP_TILE_URL)`.)

- [ ] **Step 6: Commit**

```bash
git add osm-mcp/pyproject.toml osm-mcp/src/osm_mcp/config.py
git commit -m "feat(mcp): add MAP_* config and jinja2/geojson deps"
```

---

## Task 4: GeoJSON builder module (TDD)

**Files:**
- Create: `osm-mcp/src/osm_mcp/geojson_builder.py`
- Create: `osm-mcp/tests/test_geojson_builder.py`

- [ ] **Step 1: Write the failing tests**

```python
# osm-mcp/tests/test_geojson_builder.py
"""Unit tests for geojson_builder — pure-Python validation, no I/O."""
import json

import pytest

from osm_mcp.geojson_builder import (
    assign_layer_styles,
    compute_bounds,
    parse_geojson,
)


def test_parse_feature_collection_passthrough():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": [12.5, 41.9]},
             "properties": {"name": "Rome"}}
        ],
    }
    out = parse_geojson(fc)
    assert out["type"] == "FeatureCollection"
    assert len(out["features"]) == 1


def test_parse_single_feature_wraps_into_collection():
    feature = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [11.25, 43.77]},
        "properties": {},
    }
    out = parse_geojson(feature)
    assert out["type"] == "FeatureCollection"
    assert out["features"][0]["geometry"]["coordinates"] == [11.25, 43.77]


def test_parse_geometry_only_wraps_into_feature_collection():
    geom = {"type": "Point", "coordinates": [9.19, 45.46]}
    out = parse_geojson(geom)
    assert out["type"] == "FeatureCollection"
    assert out["features"][0]["geometry"] == geom


def test_parse_string_input_decoded_as_json():
    raw = '{"type":"FeatureCollection","features":[]}'
    out = parse_geojson(raw)
    assert out["features"] == []


def test_parse_rejects_malformed_string():
    with pytest.raises(ValueError, match="invalid|malformed|JSON"):
        parse_geojson("not json")


def test_parse_drops_invalid_features_silently():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]},
             "properties": {}},
            {"type": "Feature", "geometry": None, "properties": {}},  # invalid
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 1]},
             "properties": {}},
        ],
    }
    out = parse_geojson(fc)
    assert len(out["features"]) == 2


def test_compute_bounds_for_points():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [10.0, 40.0]}, "properties": {}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [12.0, 42.0]}, "properties": {}},
        ],
    }
    south, west, north, east = compute_bounds(fc)
    assert south == 40.0 and north == 42.0
    assert west == 10.0 and east == 12.0


def test_compute_bounds_empty_returns_italy_default():
    south, west, north, east = compute_bounds({"type": "FeatureCollection", "features": []})
    # Italy bbox approx: 35.5, 6.6, 47.1, 18.5
    assert 35 < south < 38 and 45 < north < 48
    assert 6 < west < 8 and 17 < east < 19


def test_assign_layer_styles_returns_distinct_colors():
    styles = assign_layer_styles(5)
    assert len(styles) == 5
    colors = [s["color"] for s in styles]
    assert len(set(colors)) == 5


def test_assign_layer_styles_cycles_when_more_than_palette():
    styles = assign_layer_styles(20)
    assert len(styles) == 20
```

- [ ] **Step 2: Run tests — confirm they fail**

Run: `cd osm-mcp && pytest tests/test_geojson_builder.py -v`
Expected: ImportError on `from osm_mcp.geojson_builder import ...`.

- [ ] **Step 3: Implement `geojson_builder.py`**

```python
# osm-mcp/src/osm_mcp/geojson_builder.py
"""GeoJSON parsing, validation, normalization and styling utilities.

Pure Python, no I/O, no network. All functions are deterministic and side-effect
free. The module sits between the OSM tool layer (which produces raw
JSON dicts) and the rendering layer (which expects FeatureCollections + styles).

CRS policy: GeoJSON RFC 7946 mandates WGS84 (EPSG:4326). Inputs declaring a
different CRS via the (deprecated) "crs" member are rejected with a clear
ValueError. Automatic reprojection is out of scope.
"""
from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)

# Italy default bbox used when an empty FeatureCollection is given to
# compute_bounds. Avoids div-by-zero when callers blindly fitBounds().
_ITALY_BBOX: tuple[float, float, float, float] = (35.5, 6.6, 47.1, 18.5)

# 12-color palette (high-contrast, color-blind friendly).
_PALETTE: list[str] = [
    "#e6194B", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4",
    "#f032e6", "#469990", "#9A6324", "#800000", "#808000", "#000075",
]


def parse_geojson(raw: str | dict[str, Any]) -> dict[str, Any]:
    """Parse and normalize a GeoJSON input into a FeatureCollection dict.

    Accepts JSON strings, FeatureCollection dicts, single Feature dicts, and
    raw Geometry dicts. Wraps non-collection inputs as needed.

    Strips features whose geometry is None or invalid (logs a warning with the
    count). Rejects non-WGS84 CRS declarations with ValueError.
    """
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid GeoJSON string: {exc}") from exc
    else:
        data = raw

    if not isinstance(data, dict):
        raise ValueError(f"GeoJSON must be a JSON object, got {type(data).__name__}")

    _reject_non_wgs84(data)

    gtype = data.get("type")
    if gtype == "FeatureCollection":
        fc = data
    elif gtype == "Feature":
        fc = {"type": "FeatureCollection", "features": [data]}
    elif gtype in {"Point", "LineString", "Polygon", "MultiPoint",
                   "MultiLineString", "MultiPolygon", "GeometryCollection"}:
        fc = {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": data, "properties": {}}],
        }
    else:
        raise ValueError(f"unsupported GeoJSON type: {gtype!r}")

    raw_features = list(fc.get("features") or [])
    valid = [f for f in raw_features if _is_valid_feature(f)]
    dropped = len(raw_features) - len(valid)
    if dropped:
        log.warning("geojson_builder: dropped %d invalid features", dropped)
    return {"type": "FeatureCollection", "features": valid}


def _reject_non_wgs84(data: dict[str, Any]) -> None:
    crs = data.get("crs")
    if not crs:
        return
    name = (crs.get("properties") or {}).get("name") or ""
    if "CRS84" in name or "4326" in name or "WGS" in name.upper():
        return
    raise ValueError(
        f"non-WGS84 CRS not supported (got {name!r}); "
        "please reproject to EPSG:4326 (RFC 7946)"
    )


def _is_valid_feature(feature: dict[str, Any]) -> bool:
    if feature.get("type") != "Feature":
        return False
    geom = feature.get("geometry")
    if not isinstance(geom, dict):
        return False
    coords = geom.get("coordinates")
    if coords is None and geom.get("type") != "GeometryCollection":
        return False
    return True


def compute_bounds(geojson: dict[str, Any]) -> tuple[float, float, float, float]:
    """Return (south, west, north, east) bbox of a FeatureCollection.

    For empty collections returns Italy's default bbox so map fits gracefully.
    """
    south = +90.0
    north = -90.0
    west = +180.0
    east = -180.0
    has_any = False
    for feat in geojson.get("features", []):
        for lon, lat in _iter_coords(feat.get("geometry") or {}):
            has_any = True
            if lat < south:
                south = lat
            if lat > north:
                north = lat
            if lon < west:
                west = lon
            if lon > east:
                east = lon
    if not has_any:
        return _ITALY_BBOX
    return (south, west, north, east)


def _iter_coords(geom: dict[str, Any]):
    """Yield (lon, lat) pairs from any GeoJSON geometry."""
    gtype = geom.get("type")
    coords = geom.get("coordinates")
    if gtype == "Point" and coords is not None:
        yield (coords[0], coords[1])
    elif gtype in {"LineString", "MultiPoint"}:
        for c in coords or []:
            yield (c[0], c[1])
    elif gtype in {"Polygon", "MultiLineString"}:
        for ring in coords or []:
            for c in ring:
                yield (c[0], c[1])
    elif gtype == "MultiPolygon":
        for poly in coords or []:
            for ring in poly:
                for c in ring:
                    yield (c[0], c[1])
    elif gtype == "GeometryCollection":
        for g in geom.get("geometries", []):
            yield from _iter_coords(g)


def assign_layer_styles(count: int) -> list[dict[str, Any]]:
    """Return N distinct Leaflet style dicts. Cycles palette if N > 12."""
    return [
        {"color": _PALETTE[i % len(_PALETTE)],
         "weight": 2,
         "fillOpacity": 0.5,
         "radius": 6}
        for i in range(count)
    ]
```

- [ ] **Step 4: Run tests — verify pass**

Run: `cd osm-mcp && pytest tests/test_geojson_builder.py -v`
Expected: 10 PASS.

- [ ] **Step 5: Commit**

```bash
git add osm-mcp/src/osm_mcp/geojson_builder.py osm-mcp/tests/test_geojson_builder.py
git commit -m "feat(mcp): add geojson_builder (parse, bounds, palette)"
```

---

## Task 5: HTML renderer + Jinja2 template (TDD)

**Files:**
- Create: `osm-mcp/templates/map.html.j2`
- Create: `osm-mcp/src/osm_mcp/html_renderer.py`
- Create: `osm-mcp/tests/test_html_renderer.py`

- [ ] **Step 1: Write the failing tests**

```python
# osm-mcp/tests/test_html_renderer.py
"""HTML rendering tests — verify output is valid, self-contained, and embeds GeoJSON."""
import json

import pytest

from osm_mcp.html_renderer import MapLayer, render_map


@pytest.fixture
def sample_layers():
    return [
        MapLayer(
            name="Bus stops",
            geojson={"type": "FeatureCollection", "features": [
                {"type": "Feature",
                 "geometry": {"type": "Point", "coordinates": [11.25, 43.77]},
                 "properties": {"name": "Stazione SMN"}},
            ]},
            style={"color": "#e6194B", "weight": 2, "fillOpacity": 0.5, "radius": 6},
        ),
        MapLayer(
            name="Tram lines",
            geojson={"type": "FeatureCollection", "features": [
                {"type": "Feature",
                 "geometry": {"type": "LineString", "coordinates": [[11.20, 43.77], [11.30, 43.78]]},
                 "properties": {"line": "T1"}},
            ]},
            style={"color": "#3cb44b", "weight": 3, "fillOpacity": 0.5, "radius": 6},
        ),
    ]


def test_render_map_produces_valid_html(sample_layers):
    html = render_map(sample_layers, title="Test")
    assert html.startswith("<!doctype html>") or html.startswith("<!DOCTYPE html>")
    assert "</html>" in html
    assert "<title>Test</title>" in html


def test_render_map_embeds_layer_names(sample_layers):
    html = render_map(sample_layers, title="Test")
    assert "Bus stops" in html
    assert "Tram lines" in html


def test_render_map_includes_leaflet_cdn(sample_layers):
    html = render_map(sample_layers)
    assert "unpkg.com/leaflet" in html


def test_render_map_uses_default_osm_tile_url(sample_layers):
    html = render_map(sample_layers)
    assert "tile.openstreetmap.org" in html


def test_render_map_embeds_geojson_coordinates(sample_layers):
    html = render_map(sample_layers)
    # Coordinates should appear in the embedded JSON
    assert "11.25" in html
    assert "43.77" in html


def test_render_map_with_explicit_center_and_zoom(sample_layers):
    html = render_map(sample_layers, center=(41.9, 12.5), zoom=10)
    assert "41.9" in html and "12.5" in html
    assert "10" in html


def test_render_map_escapes_title_special_chars(sample_layers):
    html = render_map(sample_layers, title='"X" & <script>alert(1)</script>')
    # Jinja2 |e filter should escape these
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html or "&amp;" in html
```

- [ ] **Step 2: Create the Jinja2 template**

```jinja2
{# osm-mcp/templates/map.html.j2 #}
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{{ title|e or "OSM Map" }}</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
        integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
  <style>
    body { margin: 0; font-family: system-ui, sans-serif; }
    #map { height: 100vh; width: 100%; }
    .legend { background: #fff; padding: 8px 10px; border-radius: 4px;
              box-shadow: 0 0 6px rgba(0,0,0,.2); font: 12px sans-serif; max-width: 240px; }
    .legend i { width: 12px; height: 12px; display: inline-block;
                margin-right: 6px; vertical-align: middle; border-radius: 2px; }
    .legend b { display: block; margin-bottom: 4px; }
  </style>
</head>
<body>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
        integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<script>
  const map = L.map('map'){% if center %}.setView([{{ center[0] }}, {{ center[1] }}], {{ zoom or default_zoom }}){% endif %};
  L.tileLayer({{ tile_url|tojson }}, {
    attribution: {{ attribution|tojson }},
    maxZoom: 19
  }).addTo(map);

  const layers = {{ layers_json|safe }};
  const bounds = L.latLngBounds([]);
  const overlays = {};
  layers.forEach(l => {
    const layer = L.geoJSON(l.geojson, {
      style: l.style,
      pointToLayer: (f, latlng) => L.circleMarker(latlng, l.style),
      onEachFeature: (f, lyr) => {
        const props = f.properties || {};
        const html = Object.entries(props).slice(0, 8).map(([k, v]) =>
          `<b>${k}</b>: ${String(v).slice(0, 80)}`).join('<br>');
        if (html) lyr.bindPopup(html);
      }
    }).addTo(map);
    overlays[l.name] = layer;
    if (layer.getBounds && layer.getBounds().isValid()) bounds.extend(layer.getBounds());
  });
  if (bounds.isValid() && !{{ "true" if center else "false" }}) {
    map.fitBounds(bounds.pad(0.1));
  }

  const legend = L.control({position: 'bottomright'});
  legend.onAdd = () => {
    const div = L.DomUtil.create('div', 'legend');
    div.innerHTML = '<b>' + {{ (title|e or "Layers")|tojson }} + '</b>' +
      layers.map(l => `<i style="background:${l.style.color}"></i>${l.name}`).join('<br>');
    return div;
  };
  legend.addTo(map);
  L.control.layers(null, overlays, {collapsed: false}).addTo(map);
</script>
</body>
</html>
```

- [ ] **Step 3: Implement `html_renderer.py`**

```python
# osm-mcp/src/osm_mcp/html_renderer.py
"""Render a self-contained Leaflet HTML map from one or more GeoJSON layers.

Output is a complete <!doctype html>...</html> string with Leaflet from CDN
and OSM raster tiles. No external assets to host. ~5-50 KB depending on
embedded GeoJSON size.

Style/layer dataclass is intentionally minimal — paint logic lives in the
template, not in Python.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from osm_mcp import config

_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates"
_env = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(["html", "j2"]),
)


@dataclass
class MapLayer:
    name: str
    geojson: dict[str, Any]
    style: dict[str, Any] | None = None


_DEFAULT_STYLE: dict[str, Any] = {"color": "#3388ff", "weight": 2, "fillOpacity": 0.4, "radius": 6}


def render_map(
    layers: list[MapLayer],
    title: str | None = None,
    center: tuple[float, float] | None = None,
    zoom: int | None = None,
    attribution: str | None = None,
) -> str:
    """Render a Leaflet HTML map embedding all layers inline."""
    settings = config.get_settings() if hasattr(config, "get_settings") else config

    payload = [
        {
            "name": l.name,
            "geojson": l.geojson,
            "style": l.style or _DEFAULT_STYLE,
        }
        for l in layers
    ]
    template = _env.get_template("map.html.j2")
    return template.render(
        title=title,
        layers_json=json.dumps(payload, ensure_ascii=False),
        center=list(center) if center else None,
        zoom=zoom,
        default_zoom=getattr(settings, "MAP_DEFAULT_ZOOM", 13),
        tile_url=getattr(settings, "MAP_TILE_URL",
                         "https://tile.openstreetmap.org/{z}/{x}/{y}.png"),
        attribution=attribution or getattr(settings, "MAP_ATTRIBUTION",
            '&copy; OpenStreetMap contributors'),
    )
```

- [ ] **Step 4: Run tests — verify pass**

Run: `cd osm-mcp && pytest tests/test_html_renderer.py -v`
Expected: 7 PASS.

If `config.get_settings()` doesn't exist in `osm_mcp.config`, adapt the import in `html_renderer.py` to read attributes directly: `from osm_mcp import config` then `getattr(config, "MAP_TILE_URL", ...)`.

- [ ] **Step 5: Commit**

```bash
git add osm-mcp/templates/map.html.j2 osm-mcp/src/osm_mcp/html_renderer.py osm-mcp/tests/test_html_renderer.py
git commit -m "feat(mcp): add Leaflet HTML renderer with Jinja2 template"
```

---

## Task 6: Three new MCP tools — `render_geojson_map`, `render_multi_layer_map`, `compose_map_from_resources` (TDD)

**Files:**
- Modify: `osm-mcp/src/osm_mcp/tools.py`
- Create: `osm-mcp/tests/test_compose_resources.py`
- Create: `osm-mcp/tests/fixtures/ckan_response.json` (copy from osm-mcp-agent fixture)

- [ ] **Step 1: Copy fixture from agent**

Run:
```bash
mkdir -p osm-mcp/tests/fixtures
cp osm-mcp-agent/tests/fixtures/ckan_response.json osm-mcp/tests/fixtures/ckan_response.json
```

- [ ] **Step 2: Write the failing tests**

```python
# osm-mcp/tests/test_compose_resources.py
"""End-to-end tests for the 3 new MCP tools.

These tests exercise the public functions registered as MCP tools — but call
them directly as async Python functions (the FastMCP decorator returns the
underlying coroutine).
"""
import json
from pathlib import Path

import pytest

from osm_mcp.tools import (
    compose_map_from_resources,
    render_geojson_map,
    render_multi_layer_map,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ckan_response.json"


def _extract_text_block(blocks):
    """Helper: tools return a list[ContentBlock]. Extract the text JSON."""
    for b in blocks:
        if getattr(b, "type", None) == "text" or (isinstance(b, dict) and b.get("type") == "text"):
            return json.loads(b.text if hasattr(b, "text") else b["text"])
    raise AssertionError("no text content block found")


def _extract_html_block(blocks):
    for b in blocks:
        if getattr(b, "type", None) == "resource" or (isinstance(b, dict) and b.get("type") == "resource"):
            res = b.resource if hasattr(b, "resource") else b["resource"]
            return res.get("text") if isinstance(res, dict) else getattr(res, "text", None)
    raise AssertionError("no resource content block found")


@pytest.mark.asyncio
async def test_render_geojson_map_single_feature():
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [12.5, 41.9]},
         "properties": {"name": "Roma"}},
    ]}
    blocks = await render_geojson_map(geojson=fc, title="Test")
    summary = _extract_text_block(blocks)
    assert summary["feature_count"] == 1
    html = _extract_html_block(blocks)
    assert "<!doctype html>" in html.lower() or "<!DOCTYPE html>" in html
    assert "Roma" in html


@pytest.mark.asyncio
async def test_render_multi_layer_map_two_layers():
    layers = [
        {"name": "L1", "geojson": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [11, 43]}, "properties": {}}]}},
        {"name": "L2", "geojson": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [12, 44]}, "properties": {}}]}},
    ]
    blocks = await render_multi_layer_map(layers=layers, title="Multi")
    summary = _extract_text_block(blocks)
    assert summary["layer_count"] == 2
    html = _extract_html_block(blocks)
    assert "L1" in html and "L2" in html


@pytest.mark.asyncio
async def test_compose_map_filters_non_geojson():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    blocks = await compose_map_from_resources(
        text=payload["text"],
        resources=payload["resources"],
    )
    summary = _extract_text_block(blocks)
    assert summary["layer_count"] == 2  # 2 GEOJSON, 1 PDF skipped
    assert len(summary["skipped"]) == 1
    assert summary["skipped"][0]["format"] == "PDF"
    html = _extract_html_block(blocks)
    assert "Bus stops Florence" in html
    assert "Tramway lines" in html


@pytest.mark.asyncio
async def test_compose_map_returns_error_when_no_geojson():
    blocks = await compose_map_from_resources(
        text="all skipped",
        resources=[
            {"name": "x", "format": "PDF", "url": "https://example/x.pdf"},
        ],
    )
    summary = _extract_text_block(blocks)
    assert "error" in summary
```

- [ ] **Step 3: Read current `tools.py`**

```bash
cat osm-mcp/src/osm_mcp/tools.py | head -50
```
Note the FastMCP registration pattern (whether tools are decorated with `@mcp.tool()` or registered via `register_tools(mcp)`).

- [ ] **Step 4: Append the 3 new tools to `tools.py`**

Add at the bottom of `osm-mcp/src/osm_mcp/tools.py` (preserving all existing tools):

```python
# ──────────────────────────────────────────────────────────────────────────
# Map rendering tools (added in Task 6)
# ──────────────────────────────────────────────────────────────────────────
import uuid as _uuid
from typing import Any as _Any

from osm_mcp import geojson_builder as _gjb
from osm_mcp import html_renderer as _hr


def _build_summary_block(text: str) -> dict[str, _Any]:
    """Return a TextContent-shaped dict.

    FastMCP accepts dicts with type/text keys for content blocks. If the rest
    of the file uses mcp.types.TextContent, swap to that import and constructor.
    """
    return {"type": "text", "text": text}


def _build_resource_block(html: str, kind: str = "map") -> dict[str, _Any]:
    """Return an EmbeddedResource-shaped dict with text/html mimeType."""
    return {
        "type": "resource",
        "resource": {
            "uri": f"osm://maps/{kind}-{_uuid.uuid4().hex[:8]}",
            "mimeType": "text/html",
            "text": html,
        },
    }


async def render_geojson_map(
    geojson: dict[str, _Any] | str,
    title: str | None = None,
    center: list[float] | None = None,
    zoom: int | None = None,
) -> list[dict[str, _Any]]:
    """Render a single-layer Leaflet HTML map from a GeoJSON Feature/FeatureCollection.

    Returns multi-content blocks: a text summary (feature count, bounds) and an
    HTML resource (mimeType: text/html) containing the full self-contained map.
    Compatible viewers (Claude Desktop, VS Code MCP) render the HTML inline.

    Args:
        geojson: A GeoJSON object (Feature, FeatureCollection, Geometry) or JSON string.
        title: Optional map title shown in the legend.
        center: Optional initial [lat, lon]; auto-fits bounds if omitted.
        zoom: Optional initial zoom (1-19); auto-fits if omitted.
    """
    fc = _gjb.parse_geojson(geojson)
    style = _gjb.assign_layer_styles(1)[0]
    layer = _hr.MapLayer(name=title or "Layer", geojson=fc, style=style)
    bounds = _gjb.compute_bounds(fc)
    summary = {
        "type": "single_layer_map",
        "feature_count": len(fc["features"]),
        "bounds": list(bounds),
        "title": title,
    }
    html = _hr.render_map(
        [layer], title=title,
        center=tuple(center) if center else None, zoom=zoom,
    )
    import json as _json
    return [_build_summary_block(_json.dumps(summary, ensure_ascii=False)),
            _build_resource_block(html, kind="single")]


async def render_multi_layer_map(
    layers: list[dict[str, _Any]],
    title: str | None = None,
    center: list[float] | None = None,
    zoom: int | None = None,
) -> list[dict[str, _Any]]:
    """Render an HTML map with multiple GeoJSON layers, each with its own
    name and (optional) style. Auto-assigns colors if `style` is omitted.

    Args:
        layers: List of {"name": str, "geojson": dict, "style"?: dict}.
        title, center, zoom: see render_geojson_map.
    """
    palette = _gjb.assign_layer_styles(len(layers))
    map_layers: list[_hr.MapLayer] = []
    feat_counts: list[dict[str, _Any]] = []
    for i, l in enumerate(layers):
        fc = _gjb.parse_geojson(l["geojson"])
        style = l.get("style") or palette[i]
        name = l.get("name") or f"Layer {i + 1}"
        map_layers.append(_hr.MapLayer(name=name, geojson=fc, style=style))
        feat_counts.append({"name": name, "features": len(fc["features"])})

    summary = {
        "type": "multi_layer_map",
        "layer_count": len(map_layers),
        "total_features": sum(c["features"] for c in feat_counts),
        "layers": feat_counts,
    }
    html = _hr.render_map(map_layers, title=title,
                          center=tuple(center) if center else None, zoom=zoom)
    import json as _json
    return [_build_summary_block(_json.dumps(summary, ensure_ascii=False)),
            _build_resource_block(html, kind="multi")]


async def compose_map_from_resources(
    text: str,
    resources: list[dict[str, _Any]],
    title: str | None = None,
    center: list[float] | None = None,
    zoom: int | None = None,
) -> list[dict[str, _Any]]:
    """Take a CKAN-agent-style payload (text + resources list) and render a
    multi-layer Leaflet map of every embedded GeoJSON resource.

    Filters resources where format == 'GEOJSON' (case-insensitive) and content
    is non-empty. Each becomes a styled layer. Non-GeoJSON resources are
    listed in the summary's `skipped` field.

    Compatible end-to-end with the output of ckan-mcp-agent's POST /chat.
    Stateless, deterministic, no LLM.
    """
    import json as _json

    palette_size = sum(
        1 for r in resources
        if (r.get("format") or "").upper() == "GEOJSON" and r.get("content")
    )
    palette = _gjb.assign_layer_styles(max(palette_size, 1))

    layers: list[_hr.MapLayer] = []
    skipped: list[dict[str, _Any]] = []
    pi = 0
    for r in resources:
        fmt = (r.get("format") or "").upper()
        if fmt != "GEOJSON" or not r.get("content"):
            skipped.append({
                "name": r.get("name"), "format": fmt or None,
                "url": r.get("url"),
            })
            continue
        try:
            fc = _gjb.parse_geojson(r["content"])
        except ValueError as exc:
            skipped.append({"name": r.get("name"), "format": fmt, "error": str(exc)})
            continue
        layers.append(_hr.MapLayer(
            name=r.get("name") or f"Layer {pi + 1}",
            geojson=fc,
            style=palette[pi],
        ))
        pi += 1

    if not layers:
        return [_build_summary_block(_json.dumps({
            "error": "no valid GeoJSON layers found",
            "skipped": skipped,
        }))]

    summary = {
        "type": "composed_map",
        "layer_count": len(layers),
        "total_features": sum(len(l.geojson.get("features", [])) for l in layers),
        "skipped": skipped,
        "layers": [
            {"name": l.name, "features": len(l.geojson.get("features", []))}
            for l in layers
        ],
    }
    html = _hr.render_map(
        layers,
        title=title or (text[:80] if text else "Composed Map"),
        center=tuple(center) if center else None,
        zoom=zoom,
    )
    return [
        _build_summary_block(_json.dumps(summary, ensure_ascii=False)),
        _build_resource_block(html, kind="composed"),
    ]
```

- [ ] **Step 5: Register the new tools with FastMCP**

Find the `register_tools(mcp)` function (or wherever existing tools are decorated/registered) in `tools.py` and add:

```python
mcp.tool()(render_geojson_map)
mcp.tool()(render_multi_layer_map)
mcp.tool()(compose_map_from_resources)
```

If existing tools use the `@mcp.tool()` decorator pattern at module level, instead apply the decorator directly above each new function:

```python
@mcp.tool()
async def render_geojson_map(...): ...

@mcp.tool()
async def render_multi_layer_map(...): ...

@mcp.tool()
async def compose_map_from_resources(...): ...
```

(The test in step 6 imports them as plain async functions — registration with FastMCP doesn't break direct invocation.)

- [ ] **Step 6: Run tests**

Run: `cd osm-mcp && pytest tests/test_compose_resources.py -v`
Expected: 4 PASS.

If `mcp.types.TextContent` / `EmbeddedResource` are required (instead of plain dicts), adjust `_build_summary_block`/`_build_resource_block` accordingly and update the test extractors. The dict shape is the safe fallback if the FastMCP version returns dicts as-is.

- [ ] **Step 7: Run all osm-mcp tests**

Run: `cd osm-mcp && pytest -v`
Expected: all existing + 4 new PASS.

- [ ] **Step 8: Commit**

```bash
git add osm-mcp/src/osm_mcp/tools.py osm-mcp/tests/test_compose_resources.py osm-mcp/tests/fixtures/ckan_response.json
git commit -m "feat(mcp): add render_geojson_map, render_multi_layer_map, compose_map_from_resources tools"
```

---

## Task 7: Agent factory (provider switch + AgentSession) (TDD)

**Files:**
- Create: `osm-mcp-agent/src/osm_agent/factory.py`
- Create: `osm-mcp-agent/tests/test_factory.py`

- [ ] **Step 1: Write failing tests**

```python
# osm-mcp-agent/tests/test_factory.py
"""Provider switch unit tests with mocked clients (no network)."""
from unittest.mock import patch

import pytest

from osm_agent.config import Settings
from osm_agent.factory import build_chat_client


def _settings(**kw) -> Settings:
    base = {"llm_provider": "ollama"}
    base.update(kw)
    return Settings(**base)


def test_ollama_provider_returns_ollama_client():
    s = _settings(llm_provider="ollama",
                  ollama_base_url="http://x:11434", ollama_llm_model="qwen2.5:7b")
    with patch("agent_framework_ollama.OllamaChatClient") as mock:
        build_chat_client(s)
    mock.assert_called_once()
    kw = mock.call_args.kwargs
    assert kw["host"] == "http://x:11434"
    assert kw["model"] == "qwen2.5:7b"


def test_claude_provider_requires_api_key():
    s = _settings(llm_provider="claude", anthropic_api_key=None)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        build_chat_client(s)


def test_claude_provider_returns_anthropic_client():
    s = _settings(llm_provider="claude", anthropic_api_key="sk-test",
                  claude_model="claude-sonnet-4-6")
    with patch("agent_framework_anthropic.AnthropicClient") as mock:
        build_chat_client(s)
    mock.assert_called_once()
    kw = mock.call_args.kwargs
    assert kw["api_key"] == "sk-test"
    assert kw["model"] == "claude-sonnet-4-6"


def test_azure_foundry_requires_endpoint_and_deployment():
    s = _settings(llm_provider="azure_foundry",
                  azure_ai_project_endpoint=None,
                  azure_ai_model_deployment_name=None)
    with pytest.raises(RuntimeError, match="AZURE_AI_PROJECT_ENDPOINT|AZURE_AI_MODEL_DEPLOYMENT_NAME"):
        build_chat_client(s)


def test_azure_foundry_returns_foundry_client():
    s = _settings(
        llm_provider="azure_foundry",
        azure_ai_project_endpoint="https://x.services.ai.azure.com/api/projects/p",
        azure_ai_model_deployment_name="gpt-4o-mini",
    )
    with patch("agent_framework_foundry.FoundryChatClient") as mock_fc, \
         patch("azure.identity.aio.DefaultAzureCredential") as mock_cred:
        build_chat_client(s)
    mock_fc.assert_called_once()
    kw = mock_fc.call_args.kwargs
    assert kw["project_endpoint"] == "https://x.services.ai.azure.com/api/projects/p"
    assert kw["model"] == "gpt-4o-mini"


def test_unsupported_provider_raises():
    s = _settings()
    s.llm_provider = "unknown"  # type: ignore[assignment]
    with pytest.raises(RuntimeError, match="Unsupported"):
        build_chat_client(s)
```

- [ ] **Step 2: Run tests — confirm they fail**

Run: `cd osm-mcp-agent && pytest tests/test_factory.py -v`
Expected: ImportError for `from osm_agent.factory import build_chat_client`.

- [ ] **Step 3: Implement `factory.py`**

```python
# osm-mcp-agent/src/osm_agent/factory.py
"""Factories for the chat client and the AgentSession.

Architecture: single ChatAgent with MCP tools sourced from osm-mcp.
No regional pre-routing (unlike ckan-mcp-agent's regex router) — OSM upstreams
are global and don't have region-specific portals.
"""
from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from typing import Any

from agent_framework import Agent, MCPStreamableHTTPTool

from .config import Settings

log = logging.getLogger("osm-agent.factory")

AGENT_INSTRUCTIONS = """\
You are an OpenStreetMap-aware geographic assistant. Answer user questions about
places, addresses, routing, points of interest, and neighborhoods by calling the
available MCP tools. Prefer tools over guessing.

Distance in km, durations in minutes. Be concise.

Map rendering: when the user asks for a map, or you receive structured GeoJSON
data (in the prompt or via a tool result), call one of:

  - render_geojson_map(geojson=<dict>, title=?, center=?, zoom=?)
  - render_multi_layer_map(layers=[{name, geojson, style?}, ...], title=?, ...)
  - compose_map_from_resources(text=?, resources=[...], title=?, ...)

The map tools return a text summary AND an HTML resource block. Tell the user
the map is available — the client renders the HTML inline.

End your answer with this block (replace [] with the actual list of resources
the tools returned, empty array if no resource was produced):

<!--RESOURCES_JSON-->
[]
<!--/RESOURCES_JSON-->
"""


def build_chat_client(settings: Settings) -> Any:
    """Return an agent_framework chat client for the configured provider.

    Mirrors ckan-mcp-agent.factory.build_chat_client. Lazy imports keep
    optional providers from being required at startup.
    """
    p = settings.llm_provider
    log.info("Building chat client for provider=%s", p)

    if p == "ollama":
        from agent_framework_ollama import OllamaChatClient
        return OllamaChatClient(
            host=settings.ollama_base_url,
            model=settings.ollama_llm_model,
        )

    if p == "claude":
        if not settings.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is required when LLM_PROVIDER=claude"
            )
        from agent_framework_anthropic import AnthropicClient
        return AnthropicClient(
            api_key=settings.anthropic_api_key,
            model=settings.claude_model,
        )

    if p == "azure_foundry":
        if not settings.azure_ai_project_endpoint:
            raise RuntimeError(
                "AZURE_AI_PROJECT_ENDPOINT is required when LLM_PROVIDER=azure_foundry"
            )
        if not settings.azure_ai_model_deployment_name:
            raise RuntimeError(
                "AZURE_AI_MODEL_DEPLOYMENT_NAME is required when LLM_PROVIDER=azure_foundry"
            )
        from agent_framework_foundry import FoundryChatClient
        from azure.identity.aio import DefaultAzureCredential
        return FoundryChatClient(
            project_endpoint=settings.azure_ai_project_endpoint,
            model=settings.azure_ai_model_deployment_name,
            credential=DefaultAzureCredential(),
        )

    raise RuntimeError(f"Unsupported LLM_PROVIDER={p!r}")


class AgentSession:
    """Long-lived ChatAgent with MCP tool, safe under FastAPI lifespan.

    Usage:
        async with AgentSession(settings) as session:
            text = await session.run("ristoranti vicino al Colosseo")
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._stack = AsyncExitStack()
        self._agent: Agent | None = None

    async def __aenter__(self) -> "AgentSession":
        log.info("Connecting to MCP server at %s", self._settings.mcp_server_url)
        mcp_tool = MCPStreamableHTTPTool(
            name=self._settings.mcp_server_name,
            url=self._settings.mcp_server_url,
            description="OpenStreetMap tools: geocoding, routing, POI search, map rendering.",
            approval_mode=self._settings.mcp_approval_mode,
        )
        await self._stack.enter_async_context(mcp_tool)

        chat_client = build_chat_client(self._settings)
        default_options: dict[str, Any] = {}
        if self._settings.llm_provider == "ollama":
            default_options["num_ctx"] = self._settings.ollama_num_ctx

        agent = Agent(
            chat_client,
            instructions=AGENT_INSTRUCTIONS,
            name=self._settings.agent_name,
            tools=[mcp_tool],
            default_options=default_options or None,
        )
        await self._stack.enter_async_context(agent)
        self._agent = agent
        log.info("Agent '%s' ready", self._settings.agent_name)
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._agent = None
        await self._stack.aclose()

    @property
    def agent(self) -> Agent:
        if self._agent is None:
            raise RuntimeError("AgentSession not entered")
        return self._agent

    async def run(self, query: str) -> str:
        if self._agent is None:
            raise RuntimeError("AgentSession not entered")
        result = await self._agent.run(query)
        text = getattr(result, "text", None)
        return text if text is not None else str(result)
```

- [ ] **Step 4: Run tests — verify pass**

Run: `cd osm-mcp-agent && pytest tests/test_factory.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add osm-mcp-agent/src/osm_agent/factory.py osm-mcp-agent/tests/test_factory.py
git commit -m "feat(agent): add factory.build_chat_client + AgentSession (provider switch)"
```

---

## Task 8: FastAPI surface — `/health`, `/chat`, `/chat/stream`

**Files:**
- Create: `osm-mcp-agent/src/osm_agent/api.py` (initial version, no `/compose-map` or `/chat/with-geojson` yet — those are Tasks 9–10)

- [ ] **Step 1: Implement `api.py` (skeleton)**

```python
# osm-mcp-agent/src/osm_agent/api.py
"""FastAPI surface for the agent.

Endpoints (this task — Tasks 9–10 add the rest):
  GET  /health
  POST /chat
  POST /chat/stream  (SSE)

Reuses the ckan-mcp-agent <!--RESOURCES_JSON--> marker pattern so the response
shape is identical and composable.
"""
from __future__ import annotations

import json
import logging
import re
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from .config import Settings, get_settings
from .contracts import ChatRequest, ChatResponse, Resource
from .factory import AgentSession

log = logging.getLogger("osm-agent.api")

_RESOURCES_RE = re.compile(
    r"<!--RESOURCES_JSON-->\s*(.*?)\s*<!--/RESOURCES_JSON-->", re.DOTALL
)
_RESOURCES_MARKER_PROMPT = (
    "\n\n[SYSTEM REMINDER] After your answer, you MUST append this block "
    "(replace [] with the actual resources array — empty array [] if none):\n"
    "<!--RESOURCES_JSON-->\n[]\n<!--/RESOURCES_JSON-->"
)


def _parse_resources_block(raw: str) -> tuple[str, list[Resource]]:
    """Extract the resources JSON block and return (clean_text, resources).

    Falls back to (raw, []) if the block is absent or malformed.
    """
    match = _RESOURCES_RE.search(raw)
    if not match:
        return raw, []
    try:
        items = json.loads(match.group(1))
        if isinstance(items, dict):
            for key in ("resources", "data", "items", "results"):
                if isinstance(items.get(key), list):
                    items = items[key]
                    break
        if not isinstance(items, list):
            return raw, []
        resources = [Resource(**i) for i in items]
    except Exception:
        log.warning("could not parse resources block", exc_info=True)
        return raw, []
    text = _RESOURCES_RE.sub("", raw).strip()
    return text, resources


_session: AgentSession | None = None
_settings: Settings | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _session, _settings
    _settings = get_settings()
    log.info("Starting osm-agent with provider=%s", _settings.llm_provider)
    _session = AgentSession(_settings)
    await _session.__aenter__()
    try:
        yield
    finally:
        if _session is not None:
            await _session.__aexit__(None, None, None)
            _session = None


app = FastAPI(title="OSM Agent API", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    if _settings is None:
        return {"status": "starting"}
    return {"status": "ok", "provider": _settings.llm_provider}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    if _session is None:
        raise HTTPException(503, "Agent session not initialised")
    raw = await _session.run(req.query + _RESOURCES_MARKER_PROMPT)
    text, resources = _parse_resources_block(raw)
    return ChatResponse(text=text, resources=resources)


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    if _session is None:
        raise HTTPException(503, "Agent session not initialised")

    async def gen() -> AsyncIterator[bytes]:
        try:
            async for update in _session.agent.run_streaming(
                req.query + _RESOURCES_MARKER_PROMPT
            ):
                payload = json.dumps({"text": str(update)}, ensure_ascii=False)
                yield f"data: {payload}\n\n".encode("utf-8")
        except AttributeError:
            # Fallback when run_streaming isn't available: emit final response
            text = await _session.run(req.query + _RESOURCES_MARKER_PROMPT)
            yield f"data: {json.dumps({'text': text})}\n\n".encode("utf-8")
        yield b"event: done\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
```

- [ ] **Step 2: Smoke test imports**

Run: `cd osm-mcp-agent && python -c "from osm_agent.api import app; print(app.title)"`
Expected: `OSM Agent API`

- [ ] **Step 3: Commit**

```bash
git add osm-mcp-agent/src/osm_agent/api.py
git commit -m "feat(agent): add FastAPI app with /health and /chat endpoints"
```

---

## Task 9: `/compose-map` endpoint — bypass-LLM via raw MCP call (TDD)

**Files:**
- Modify: `osm-mcp-agent/src/osm_agent/api.py`
- Create: `osm-mcp-agent/tests/test_compose_endpoint.py`

- [ ] **Step 1: Write failing test using respx mock for MCP**

```python
# osm-mcp-agent/tests/test_compose_endpoint.py
"""Verify POST /compose-map calls osm-mcp directly via httpx and parses
the multi-content response into ChatResponse shape."""
import json
from pathlib import Path

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from osm_agent import api as api_module

FIXTURE = Path(__file__).parent / "fixtures" / "ckan_response.json"


@pytest.fixture
def mock_settings(monkeypatch):
    """Force a known MCP URL and skip the AgentSession startup."""
    monkeypatch.setenv("MCP_SERVER_URL", "http://test-mcp:8080/mcp")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    # Bypass lifespan agent startup (no real Ollama in unit tests).
    monkeypatch.setattr(api_module, "_session", object())
    from osm_agent.config import get_settings
    monkeypatch.setattr(api_module, "_settings", get_settings())


@respx.mock
def test_compose_map_calls_mcp_and_returns_html(mock_settings):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    # Mock osm-mcp tools/call response
    mock_response = {
        "result": {
            "content": [
                {"type": "text", "text": json.dumps({"layer_count": 2, "total_features": 3})},
                {"type": "resource", "resource": {
                    "uri": "osm://maps/composed-abc",
                    "mimeType": "text/html",
                    "text": "<!doctype html><html>...mapped...</html>",
                }},
            ]
        }
    }
    respx.post("http://test-mcp:8080/mcp").mock(return_value=Response(200, json=mock_response))

    with TestClient(api_module.app) as client:
        resp = client.post("/compose-map", json=fixture)

    assert resp.status_code == 200
    body = resp.json()
    assert "text" in body
    assert len(body["resources"]) == 1
    r = body["resources"][0]
    assert r["format"] == "HTML"
    assert "<!doctype html>" in r["content"]


@respx.mock
def test_compose_map_handles_error_response(mock_settings):
    err = {
        "result": {
            "content": [
                {"type": "text", "text": json.dumps({"error": "no valid GeoJSON"})}
            ]
        }
    }
    respx.post("http://test-mcp:8080/mcp").mock(return_value=Response(200, json=err))

    with TestClient(api_module.app) as client:
        resp = client.post("/compose-map", json={
            "text": "skipped all",
            "resources": [{"name": "x", "format": "PDF"}],
        })
    assert resp.status_code == 200
    body = resp.json()
    assert "error" in body["text"]
    assert body["resources"] == []
```

- [ ] **Step 2: Run test — confirm it fails (no /compose-map endpoint)**

Run: `cd osm-mcp-agent && pytest tests/test_compose_endpoint.py -v`
Expected: 404 from FastAPI for `/compose-map`.

- [ ] **Step 3: Add `/compose-map` to `api.py`**

Append to `osm-mcp-agent/src/osm_agent/api.py`:

```python
import httpx

from .contracts import ComposeMapRequest


def _mcp_content_to_chat_response(blocks: list[dict]) -> ChatResponse:
    """Translate osm-mcp tool result content blocks into the ChatResponse shape.

    Heuristic: text blocks become `text` (joined), resource blocks become
    Resource entries with format inferred from mimeType. Maps that ended in
    error return the error JSON in `text` and no resources.
    """
    text_parts: list[str] = []
    resources: list[Resource] = []
    for block in blocks:
        btype = block.get("type")
        if btype == "text":
            text_parts.append(block.get("text", ""))
        elif btype == "resource":
            res = block.get("resource") or {}
            mime = res.get("mimeType", "")
            fmt = "HTML" if "html" in mime else mime.split("/")[-1].upper() or "BIN"
            resources.append(Resource(
                name=(res.get("uri") or "").split("/")[-1] or "map",
                url=res.get("uri"),
                format=fmt,
                content=res.get("text"),
            ))
    return ChatResponse(text="\n".join(text_parts).strip(), resources=resources)


@app.post("/compose-map", response_model=ChatResponse)
async def compose_map(req: ComposeMapRequest) -> ChatResponse:
    """Deterministic ckan→osm composition. Calls osm-mcp directly via httpx
    (no LLM cost, no token usage). Accepts the ckan-mcp-agent ChatResponse
    shape and returns the same shape with an HTML resource added.
    """
    if _settings is None:
        raise HTTPException(503, "Settings not initialised")

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "compose_map_from_resources",
            "arguments": req.model_dump(exclude_none=True),
        },
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(_settings.mcp_server_url, json=payload)
    if resp.status_code != 200:
        raise HTTPException(502, f"osm-mcp returned {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    if "error" in data:
        raise HTTPException(502, f"osm-mcp error: {data['error']}")

    blocks = (data.get("result") or {}).get("content") or []
    return _mcp_content_to_chat_response(blocks)
```

- [ ] **Step 4: Run tests — verify pass**

Run: `cd osm-mcp-agent && pytest tests/test_compose_endpoint.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Copy fixture for agent tests**

Run:
```bash
ls osm-mcp-agent/tests/fixtures/ckan_response.json   # ensure exists from Task 2
```

- [ ] **Step 6: Commit**

```bash
git add osm-mcp-agent/src/osm_agent/api.py osm-mcp-agent/tests/test_compose_endpoint.py
git commit -m "feat(agent): add POST /compose-map (bypass-LLM via raw MCP call)"
```

---

## Task 10: `/chat/with-geojson` multipart endpoint (TDD)

**Files:**
- Modify: `osm-mcp-agent/src/osm_agent/api.py`
- Create: `osm-mcp-agent/tests/test_chat_with_geojson.py`

- [ ] **Step 1: Write failing test (mocked agent run)**

```python
# osm-mcp-agent/tests/test_chat_with_geojson.py
"""Verify multipart geojson upload prepends the file content to the prompt."""
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from osm_agent import api as api_module


@pytest.fixture
def mock_session(monkeypatch):
    """Replace _session with an AsyncMock that captures the prompt."""
    fake = AsyncMock()
    fake.run = AsyncMock(return_value=(
        "Map produced.\n<!--RESOURCES_JSON-->\n["
        '{"name":"map.html","format":"HTML","content":"<html>...</html>"}'
        "]\n<!--/RESOURCES_JSON-->"
    ))
    monkeypatch.setattr(api_module, "_session", fake)
    from osm_agent.config import get_settings
    monkeypatch.setattr(api_module, "_settings", get_settings())
    return fake


def test_chat_with_geojson_prepends_file_content_to_prompt(mock_session):
    geojson_str = '{"type":"FeatureCollection","features":[]}'
    files = {
        "geojson_file": ("track.geojson", geojson_str, "application/geo+json"),
    }
    data = {"message": "Render this on a map"}
    with TestClient(api_module.app) as client:
        resp = client.post("/chat/with-geojson", data=data, files=files)
    assert resp.status_code == 200
    body = resp.json()
    assert body["resources"][0]["format"] == "HTML"

    sent = mock_session.run.await_args.args[0]
    assert "USER QUERY: Render this on a map" in sent
    assert "ATTACHED GEOJSON" in sent
    assert geojson_str in sent
```

- [ ] **Step 2: Run test — confirm 404**

Run: `cd osm-mcp-agent && pytest tests/test_chat_with_geojson.py -v`
Expected: 404 (endpoint not yet defined).

- [ ] **Step 3: Add `/chat/with-geojson` to `api.py`**

Append:

```python
from fastapi import File, Form, UploadFile

_GEOJSON_MAX_INLINE = 50_000  # bytes pasted into the prompt


@app.post("/chat/with-geojson", response_model=ChatResponse)
async def chat_with_geojson(
    message: str = Form(...),
    geojson_file: UploadFile = File(...),
) -> ChatResponse:
    """Accept a multipart upload with a GeoJSON file and a message. Prepends
    the file content to the agent prompt so the LLM can call
    render_geojson_map directly with the user's data."""
    if _session is None:
        raise HTTPException(503, "Agent session not initialised")

    raw = (await geojson_file.read()).decode("utf-8", errors="replace")
    truncated = len(raw) > _GEOJSON_MAX_INLINE
    embed = raw[:_GEOJSON_MAX_INLINE]

    enriched = (
        f"USER QUERY: {message}\n\n"
        f"ATTACHED GEOJSON (file: {geojson_file.filename}"
        f"{', truncated' if truncated else ''}):\n"
        f"```geojson\n{embed}\n```\n\n"
        "If the user asks for a map, call render_geojson_map with this GeoJSON."
        + _RESOURCES_MARKER_PROMPT
    )
    text_raw = await _session.run(enriched)
    text, resources = _parse_resources_block(text_raw)
    return ChatResponse(text=text, resources=resources)
```

- [ ] **Step 4: Run tests — verify pass**

Run: `cd osm-mcp-agent && pytest tests/test_chat_with_geojson.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add osm-mcp-agent/src/osm_agent/api.py osm-mcp-agent/tests/test_chat_with_geojson.py
git commit -m "feat(agent): add POST /chat/with-geojson multipart endpoint"
```

---

## Task 11: MCP surface (`agent.as_mcp_server()`) + main entrypoint

**Files:**
- Create: `osm-mcp-agent/src/osm_agent/mcp_surface.py`
- Create: `osm-mcp-agent/src/osm_agent/main.py`

- [ ] **Step 1: Implement `mcp_surface.py`**

```python
# osm-mcp-agent/src/osm_agent/mcp_surface.py
"""Expose the running ChatAgent as a Streamable HTTP MCP server.

Uses Microsoft Agent Framework's native `agent.as_mcp_server()` capability
(see Microsoft Learn — Using MCP tools with Agents → "Exposing an Agent as
an MCP Server"). The exposed tool's name is the agent name; the description
comes from the agent instructions.

Third-party MCP-aware clients (Claude Desktop, VS Code Copilot, other agents)
can mount this as a single intelligent tool and chain it after ckan-mcp-agent
to compose ckan→osm flows.
"""
from __future__ import annotations

import logging

import uvicorn
from agent_framework import Agent

log = logging.getLogger("osm-agent.mcp-surface")


async def serve(agent: Agent, host: str, port: int, path: str) -> None:
    """Start the MCP HTTP server bound to the given agent instance.

    Implementation note: the exact integration depends on the version of the
    `mcp` package shipped with agent-framework. The pattern below uses the
    Streamable HTTP session manager with a Starlette-based ASGI app.
    """
    import contextlib

    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.routing import Mount

    mcp_server = agent.as_mcp_server()
    manager = StreamableHTTPSessionManager(app=mcp_server, json_response=False)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            yield

    asgi = Starlette(routes=[Mount(path, app=manager.handle_request)], lifespan=lifespan)
    log.info("MCP surface listening on http://%s:%s%s", host, port, path)
    config = uvicorn.Config(asgi, host=host, port=port, log_level="info", lifespan="on")
    server = uvicorn.Server(config)
    await server.serve()
```

- [ ] **Step 2: Implement `main.py`**

```python
# osm-mcp-agent/src/osm_agent/main.py
"""Entrypoint: runs FastAPI (REST :8002) and MCP surface (:8003) in parallel
in the same process, sharing one AgentSession via the FastAPI app state.
"""
from __future__ import annotations

import asyncio
import logging

import uvicorn

from .api import app as fastapi_app
from .config import get_settings
from .factory import AgentSession
from .mcp_surface import serve as serve_mcp


async def _serve_both() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    log = logging.getLogger("osm-agent.main")

    # FastAPI lifespan handles its own AgentSession; we still need a separate
    # session for the MCP surface so the two surfaces are independent.
    config = uvicorn.Config(
        fastapi_app, host=settings.api_host, port=settings.api_port,
        log_level=settings.log_level.lower(), lifespan="on",
    )
    rest_server = uvicorn.Server(config)

    tasks: list[asyncio.Task] = [asyncio.create_task(rest_server.serve(), name="rest")]

    if settings.mcp_surface_enabled:
        async def _mcp_task() -> None:
            async with AgentSession(settings) as sess:
                await serve_mcp(
                    sess.agent,
                    host=settings.mcp_surface_host,
                    port=settings.mcp_surface_port,
                    path=settings.mcp_surface_path,
                )

        tasks.append(asyncio.create_task(_mcp_task(), name="mcp"))
        log.info("MCP surface enabled at %s:%d%s",
                 settings.mcp_surface_host,
                 settings.mcp_surface_port,
                 settings.mcp_surface_path)

    await asyncio.gather(*tasks)


def run() -> None:
    asyncio.run(_serve_both())


if __name__ == "__main__":
    run()
```

- [ ] **Step 3: Smoke import test**

Run: `cd osm-mcp-agent && python -c "from osm_agent.main import run; print('ok')"`
Expected: `ok`

(Don't actually start the server — that requires a real osm-mcp + Ollama running. Full integration is verified in Task 17 via `make smoke`.)

- [ ] **Step 4: Commit**

```bash
git add osm-mcp-agent/src/osm_agent/mcp_surface.py osm-mcp-agent/src/osm_agent/main.py
git commit -m "feat(agent): expose agent as MCP server via as_mcp_server() on :8003"
```

---

## Task 12: Dockerfile for `osm-mcp-agent`

**Files:**
- Create: `osm-mcp-agent/Dockerfile`

- [ ] **Step 1: Write Dockerfile**

```dockerfile
# osm-mcp-agent/Dockerfile
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src

# Install with claude+azure extras so all three providers are available at runtime
# (provider chosen at startup via LLM_PROVIDER env var).
RUN pip install --no-cache-dir -e ".[claude,azure]"

EXPOSE 8002 8003

HEALTHCHECK --interval=30s --timeout=5s --retries=5 --start-period=20s \
  CMD curl -fsS http://localhost:8002/health || exit 1

CMD ["python", "-m", "osm_agent.main"]
```

- [ ] **Step 2: Build image locally**

Run:
```bash
cd osm-mcp-agent && docker build -t osm-mcp-agent:local .
```
Expected: build succeeds, image tagged.

- [ ] **Step 3: Commit**

```bash
git add osm-mcp-agent/Dockerfile
git commit -m "feat(agent): add Dockerfile (python:3.12-slim, expose 8002+8003)"
```

---

## Task 13: Ollama image (Modelfile + entrypoint)

**Files:**
- Modify or replace: `infra/ollama/Dockerfile`
- Create: `infra/ollama/Modelfile`
- Create: `infra/ollama/entrypoint.sh`

- [ ] **Step 1: Inspect current `infra/ollama/Dockerfile`**

Run: `cat infra/ollama/Dockerfile`. Note the base image and any logic; we'll replace it.

- [ ] **Step 2: Write `infra/ollama/Modelfile`**

```
# infra/ollama/Modelfile
FROM qwen2.5:7b-instruct
PARAMETER num_ctx 16384
PARAMETER temperature 0.2
SYSTEM """You are an OpenStreetMap-aware geographic assistant. Answer concisely. Use available tools (geocoding, routing, POI search, map rendering) instead of guessing. Distance in km, duration in minutes."""
```

- [ ] **Step 3: Write `infra/ollama/entrypoint.sh`**

```bash
#!/usr/bin/env bash
# infra/ollama/entrypoint.sh
# Bake qwen2.5:16k from qwen2.5:7b-instruct + Modelfile on first start, then keep serving.
set -euo pipefail

ollama serve &
SERVE_PID=$!

# Wait for ollama API
for i in $(seq 1 60); do
  if ollama list >/dev/null 2>&1; then break; fi
  sleep 1
done

if ! ollama list | grep -q "qwen2.5:16k"; then
  echo "▶ Baking qwen2.5:16k from Modelfile..."
  ollama pull qwen2.5:7b-instruct
  ollama create qwen2.5:16k -f /Modelfile
fi

wait "$SERVE_PID"
```

- [ ] **Step 4: Replace `infra/ollama/Dockerfile`**

```dockerfile
# infra/ollama/Dockerfile
FROM ollama/ollama:latest

COPY Modelfile /Modelfile
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
```

- [ ] **Step 5: Build and smoke test (optional, slow ~5-10 min on CPU)**

```bash
docker build -t osm-mcp-ollama:local infra/ollama
# don't run unless you want to verify the bake — it pulls ~5 GB
```

- [ ] **Step 6: Commit**

```bash
git add infra/ollama/Dockerfile infra/ollama/Modelfile infra/ollama/entrypoint.sh
git commit -m "feat(infra): bake qwen2.5:16k Ollama image (num_ctx=16384)"
```

---

## Task 14: `docker-compose.yml` rewrite + `.env.*.example` files

**Files:**
- Replace: `docker-compose.yml`
- Replace: `docker-compose.ghcr.yml`
- Replace: `.env.example`
- Create: `.env.azure.example`
- Create: `.env.dev-claude.example`

- [ ] **Step 1: Write new `docker-compose.yml`**

```yaml
# docker-compose.yml
name: osm-mcp

x-ollama-base: &ollama-base
  image: ${OLLAMA_IMAGE:-ghcr.io/agent-engineering-studio/osm-mcp-ollama:latest}
  pull_policy: ${OLLAMA_PULL_POLICY:-always}
  container_name: osm-ollama
  ports:
    - "${OLLAMA_PORT:-11434}:11434"
  volumes:
    - ollama_data:/root/.ollama
  restart: unless-stopped
  healthcheck:
    test: ["CMD", "ollama", "list"]
    interval: 15s
    timeout: 5s
    retries: 10
    start_period: 30s

services:
  ollama-gpu:
    <<: *ollama-base
    profiles: ["gpu"]
    deploy:
      resources:
        reservations:
          devices: [{driver: nvidia, count: all, capabilities: [gpu]}]

  ollama-cpu:
    <<: *ollama-base
    profiles: ["cpu"]

  osm-mcp:
    build:
      context: ./osm-mcp
      dockerfile: Dockerfile
    image: osm-mcp-server:local
    container_name: osm-mcp
    ports:
      - "${MCP_PORT:-8080}:8080"
    environment:
      TRANSPORT: streamable-http
      HOST: 0.0.0.0
      PORT: "8080"
      MCP_PATH: /mcp
      NOMINATIM_URL: ${NOMINATIM_URL:-https://nominatim.openstreetmap.org}
      OVERPASS_URL: ${OVERPASS_URL:-https://overpass-api.de/api/interpreter}
      OSRM_URL: ${OSRM_URL:-https://router.project-osrm.org}
      OSM_USER_AGENT: ${OSM_USER_AGENT:-osm-mcp/0.1 (agent-engineering-studio)}
      OSM_CONTACT_EMAIL: ${OSM_CONTACT_EMAIL:-}
      MAP_TILE_URL: ${MAP_TILE_URL:-https://tile.openstreetmap.org/{z}/{x}/{y}.png}
      MAP_ATTRIBUTION: ${MAP_ATTRIBUTION:-© OpenStreetMap contributors}
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
    restart: unless-stopped

  osm-mcp-agent:
    build:
      context: ./osm-mcp-agent
      dockerfile: Dockerfile
    image: osm-mcp-agent:local
    container_name: osm-mcp-agent
    ports:
      - "${AGENT_PORT:-8002}:8002"
      - "${AGENT_MCP_PORT:-8003}:8003"
    environment:
      LLM_PROVIDER: ${LLM_PROVIDER:-ollama}
      OLLAMA_BASE_URL: ${OLLAMA_BASE_URL:-http://osm-ollama:11434}
      OLLAMA_LLM_MODEL: ${OLLAMA_LLM_MODEL:-qwen2.5:16k}
      OLLAMA_NUM_CTX: ${OLLAMA_NUM_CTX:-16384}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}
      CLAUDE_MODEL: ${CLAUDE_MODEL:-claude-sonnet-4-6}
      AZURE_AI_PROJECT_ENDPOINT: ${AZURE_AI_PROJECT_ENDPOINT:-}
      AZURE_AI_MODEL_DEPLOYMENT_NAME: ${AZURE_AI_MODEL_DEPLOYMENT_NAME:-}
      MCP_SERVER_URL: ${MCP_SERVER_URL:-http://osm-mcp:8080/mcp}
      MCP_SERVER_NAME: osm-mcp
      MCP_APPROVAL_MODE: ${MCP_APPROVAL_MODE:-never_require}
      API_HOST: 0.0.0.0
      API_PORT: "8002"
      MCP_SURFACE_ENABLED: "true"
      MCP_SURFACE_HOST: 0.0.0.0
      MCP_SURFACE_PORT: "8003"
      MCP_SURFACE_PATH: /mcp
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
    depends_on:
      osm-mcp:
        condition: service_started
      ollama-cpu:
        condition: service_healthy
        required: false
      ollama-gpu:
        condition: service_healthy
        required: false
    restart: unless-stopped

volumes:
  ollama_data:
    name: osm-ollama-data
```

- [ ] **Step 2: Write `docker-compose.ghcr.yml` (pull-only variant)**

```yaml
# docker-compose.ghcr.yml — uses pre-built GHCR images, no local build
name: osm-mcp

services:
  osm-mcp:
    image: ghcr.io/agent-engineering-studio/osm-mcp:latest
    container_name: osm-mcp
    pull_policy: always
    ports:
      - "${MCP_PORT:-8080}:8080"
    environment:
      TRANSPORT: streamable-http
      HOST: 0.0.0.0
      PORT: "8080"
      MCP_PATH: /mcp
      NOMINATIM_URL: ${NOMINATIM_URL:-https://nominatim.openstreetmap.org}
      OVERPASS_URL: ${OVERPASS_URL:-https://overpass-api.de/api/interpreter}
      OSRM_URL: ${OSRM_URL:-https://router.project-osrm.org}
      OSM_USER_AGENT: ${OSM_USER_AGENT:-osm-mcp/0.1 (agent-engineering-studio)}
      OSM_CONTACT_EMAIL: ${OSM_CONTACT_EMAIL:-}
      MAP_TILE_URL: ${MAP_TILE_URL:-https://tile.openstreetmap.org/{z}/{x}/{y}.png}
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
    restart: unless-stopped

  osm-mcp-agent:
    image: ghcr.io/agent-engineering-studio/osm-mcp-agent:latest
    container_name: osm-mcp-agent
    pull_policy: always
    ports:
      - "${AGENT_PORT:-8002}:8002"
      - "${AGENT_MCP_PORT:-8003}:8003"
    environment:
      LLM_PROVIDER: ${LLM_PROVIDER:-claude}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}
      CLAUDE_MODEL: ${CLAUDE_MODEL:-claude-sonnet-4-6}
      AZURE_AI_PROJECT_ENDPOINT: ${AZURE_AI_PROJECT_ENDPOINT:-}
      AZURE_AI_MODEL_DEPLOYMENT_NAME: ${AZURE_AI_MODEL_DEPLOYMENT_NAME:-}
      MCP_SERVER_URL: http://osm-mcp:8080/mcp
      MCP_SERVER_NAME: osm-mcp
      MCP_APPROVAL_MODE: ${MCP_APPROVAL_MODE:-never_require}
      API_HOST: 0.0.0.0
      API_PORT: "8002"
      MCP_SURFACE_ENABLED: "true"
      MCP_SURFACE_PORT: "8003"
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
    depends_on:
      osm-mcp: { condition: service_started }
    restart: unless-stopped
```

- [ ] **Step 3: Write `.env.example`**

```bash
# .env.example — copy to .env for local dev
# Default profile: Ollama on the host (cpu/gpu containers also available via profiles)

LLM_PROVIDER=ollama

# Ports exposed on host
OLLAMA_PORT=11434
MCP_PORT=8080
AGENT_PORT=8002
AGENT_MCP_PORT=8003

# Ollama
OLLAMA_BASE_URL=http://osm-ollama:11434
OLLAMA_LLM_MODEL=qwen2.5:16k
OLLAMA_NUM_CTX=16384
OLLAMA_IMAGE=ghcr.io/agent-engineering-studio/osm-mcp-ollama:latest
OLLAMA_PULL_POLICY=if_not_present

# OSM upstreams
NOMINATIM_URL=https://nominatim.openstreetmap.org
OVERPASS_URL=https://overpass-api.de/api/interpreter
OSRM_URL=https://router.project-osrm.org
OSM_USER_AGENT=osm-mcp/0.1 (agent-engineering-studio)
OSM_CONTACT_EMAIL=

# Map rendering
MAP_TILE_URL=https://tile.openstreetmap.org/{z}/{x}/{y}.png
MAP_ATTRIBUTION=© OpenStreetMap contributors

# MCP wiring (compose-internal)
MCP_SERVER_URL=http://osm-mcp:8080/mcp
MCP_APPROVAL_MODE=never_require

LOG_LEVEL=INFO
```

- [ ] **Step 4: Write `.env.dev-claude.example`**

```bash
# .env.dev-claude.example — local dev with Anthropic Claude
# Copy to .env and fill ANTHROPIC_API_KEY

LLM_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
CLAUDE_MODEL=claude-sonnet-4-6

MCP_PORT=8080
AGENT_PORT=8002
AGENT_MCP_PORT=8003
MCP_SERVER_URL=http://osm-mcp:8080/mcp
MCP_APPROVAL_MODE=never_require

# Ollama is not started — these vars are ignored when LLM_PROVIDER=claude.
LOG_LEVEL=INFO
```

- [ ] **Step 5: Write `.env.azure.example`**

```bash
# .env.azure.example — production target: Azure AI Foundry
# Copy to .env (or use as deploy parameters source)

LLM_PROVIDER=azure_foundry
AZURE_AI_PROJECT_ENDPOINT=https://<your-project>.services.ai.azure.com/api/projects/<project-id>
AZURE_AI_MODEL_DEPLOYMENT_NAME=gpt-4o-mini

# Azure deploy targets (used by infra/scripts/deploy.sh)
AZURE_SUBSCRIPTION_ID=
AZURE_RESOURCE_GROUP=rg-osm-mcp-dev
AZURE_LOCATION=westeurope
ENVIRONMENT=dev

MCP_PORT=8080
AGENT_PORT=8002
AGENT_MCP_PORT=8003
MCP_SERVER_URL=http://osm-mcp:8080/mcp
MCP_APPROVAL_MODE=never_require

LOG_LEVEL=INFO
```

- [ ] **Step 6: Verify compose files parse**

Run:
```bash
docker compose config --quiet
docker compose -f docker-compose.ghcr.yml config --quiet
```
Expected: no output (success).

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml docker-compose.ghcr.yml .env.example .env.azure.example .env.dev-claude.example
git commit -m "feat(infra): rewrite docker-compose for Python agent + add env profiles"
```

---

## Task 15: Bicep IaC modules

**Files:**
- Create: `infra/bicep/main.bicep`
- Create: `infra/bicep/main.parameters.json`
- Create: `infra/bicep/modules/log-analytics.bicep`
- Create: `infra/bicep/modules/container-app-env.bicep`
- Create: `infra/bicep/modules/container-app-mcp.bicep`
- Create: `infra/bicep/modules/container-app-agent.bicep`
- Create: `infra/bicep/modules/identity.bicep`

- [ ] **Step 1: Write `modules/log-analytics.bicep`**

```bicep
@description('Log Analytics workspace for Container Apps logs.')
param name string
param location string

resource ws 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: name
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

output customerId string = ws.properties.customerId
output primarySharedKey string = ws.listKeys().primarySharedKey
```

- [ ] **Step 2: Write `modules/identity.bicep`**

```bicep
@description('User-assigned managed identity for the agent (Foundry auth).')
param name string
param location string

resource id 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: name
  location: location
}

output id string = id.id
output clientId string = id.properties.clientId
output principalId string = id.properties.principalId
```

- [ ] **Step 3: Write `modules/container-app-env.bicep`**

```bicep
@description('Container Apps Environment hosting osm-mcp + osm-mcp-agent.')
param name string
param location string
param logAnalyticsCustomerId string
@secure()
param logAnalyticsKey string

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: name
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsCustomerId
        sharedKey: logAnalyticsKey
      }
    }
  }
}

output id string = env.id
```

- [ ] **Step 4: Write `modules/container-app-mcp.bicep`**

```bicep
@description('osm-mcp Container App. Internal-only ingress (only the agent reaches it).')
param name string
param location string
param environmentId string
param image string
param osmContactEmail string = ''

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  properties: {
    environmentId: environmentId
    configuration: {
      ingress: {
        external: false
        targetPort: 8080
        transport: 'auto'
        allowInsecure: false
      }
    }
    template: {
      containers: [
        {
          name: name
          image: image
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'TRANSPORT', value: 'streamable-http' }
            { name: 'HOST', value: '0.0.0.0' }
            { name: 'PORT', value: '8080' }
            { name: 'MCP_PATH', value: '/mcp' }
            { name: 'OSM_CONTACT_EMAIL', value: osmContactEmail }
            { name: 'NOMINATIM_URL', value: 'https://nominatim.openstreetmap.org' }
            { name: 'OVERPASS_URL', value: 'https://overpass-api.de/api/interpreter' }
            { name: 'OSRM_URL', value: 'https://router.project-osrm.org' }
            { name: 'MAP_TILE_URL', value: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png' }
            { name: 'LOG_LEVEL', value: 'INFO' }
          ]
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 3 }
    }
  }
}

output internalFqdn string = app.properties.configuration.ingress.fqdn
```

- [ ] **Step 5: Write `modules/container-app-agent.bicep`**

```bicep
@description('osm-mcp-agent Container App. Public ingress on REST :8002 + MCP :8003.')
param name string
param location string
param environmentId string
param identityId string
param image string
param mcpUrl string
param llmProvider string

@secure()
param anthropicApiKey string = ''

param azureAiProjectEndpoint string = ''
param azureAiModelDeploymentName string = ''

var hasAnthropicKey = !empty(anthropicApiKey)
var secrets = hasAnthropicKey ? [
  { name: 'anthropic-key', value: anthropicApiKey }
] : []

var baseEnv = [
  { name: 'LLM_PROVIDER', value: llmProvider }
  { name: 'MCP_SERVER_URL', value: mcpUrl }
  { name: 'MCP_SERVER_NAME', value: 'osm-mcp' }
  { name: 'API_HOST', value: '0.0.0.0' }
  { name: 'API_PORT', value: '8002' }
  { name: 'MCP_SURFACE_ENABLED', value: 'true' }
  { name: 'MCP_SURFACE_PORT', value: '8003' }
  { name: 'AZURE_AI_PROJECT_ENDPOINT', value: azureAiProjectEndpoint }
  { name: 'AZURE_AI_MODEL_DEPLOYMENT_NAME', value: azureAiModelDeploymentName }
  { name: 'LOG_LEVEL', value: 'INFO' }
]

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identityId}': {} }
  }
  properties: {
    environmentId: environmentId
    configuration: {
      secrets: secrets
      ingress: {
        external: true
        targetPort: 8002
        transport: 'auto'
        allowInsecure: false
        additionalPortMappings: [
          { external: true, targetPort: 8003, exposedPort: 8003 }
        ]
      }
    }
    template: {
      containers: [
        {
          name: name
          image: image
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: hasAnthropicKey
            ? concat(baseEnv, [{ name: 'ANTHROPIC_API_KEY', secretRef: 'anthropic-key' }])
            : baseEnv
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 5 }
    }
  }
}

output fqdn string = app.properties.configuration.ingress.fqdn
```

- [ ] **Step 6: Write `infra/bicep/main.bicep`**

```bicep
@description('Azure region for all resources')
param location string = resourceGroup().location

@description('Environment short name, used in resource names')
@allowed(['dev', 'prod'])
param environment string = 'dev'

@description('GHCR image for osm-mcp server')
param mcpImage string = 'ghcr.io/agent-engineering-studio/osm-mcp:latest'

@description('GHCR image for osm-mcp-agent')
param agentImage string = 'ghcr.io/agent-engineering-studio/osm-mcp-agent:latest'

@allowed(['ollama', 'claude', 'azure_foundry'])
param llmProvider string = 'azure_foundry'

@secure()
param anthropicApiKey string = ''

param azureAiProjectEndpoint string = ''
param azureAiModelDeploymentName string = ''

@description('OpenStreetMap policy contact email')
param osmContactEmail string = ''

var prefix = 'osm-mcp-${environment}'

module logs 'modules/log-analytics.bicep' = {
  name: 'logs'
  params: { name: 'log-${prefix}', location: location }
}

module identity 'modules/identity.bicep' = {
  name: 'identity'
  params: { name: 'id-${prefix}', location: location }
}

module env 'modules/container-app-env.bicep' = {
  name: 'cae'
  params: {
    name: 'cae-${prefix}'
    location: location
    logAnalyticsCustomerId: logs.outputs.customerId
    logAnalyticsKey: logs.outputs.primarySharedKey
  }
}

module mcp 'modules/container-app-mcp.bicep' = {
  name: 'mcp'
  params: {
    name: 'osm-mcp'
    location: location
    environmentId: env.outputs.id
    image: mcpImage
    osmContactEmail: osmContactEmail
  }
}

module agent 'modules/container-app-agent.bicep' = {
  name: 'agent'
  params: {
    name: 'osm-mcp-agent'
    location: location
    environmentId: env.outputs.id
    identityId: identity.outputs.id
    image: agentImage
    mcpUrl: 'https://${mcp.outputs.internalFqdn}/mcp'
    llmProvider: llmProvider
    anthropicApiKey: anthropicApiKey
    azureAiProjectEndpoint: azureAiProjectEndpoint
    azureAiModelDeploymentName: azureAiModelDeploymentName
  }
}

output agentFqdn string = agent.outputs.fqdn
output mcpInternalFqdn string = mcp.outputs.internalFqdn
output managedIdentityClientId string = identity.outputs.clientId
```

- [ ] **Step 7: Write `infra/bicep/main.parameters.json`**

```json
{
  "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
  "contentVersion": "1.0.0.0",
  "parameters": {
    "environment": { "value": "dev" },
    "llmProvider": { "value": "azure_foundry" },
    "mcpImage": { "value": "ghcr.io/agent-engineering-studio/osm-mcp:latest" },
    "agentImage": { "value": "ghcr.io/agent-engineering-studio/osm-mcp-agent:latest" },
    "osmContactEmail": { "value": "" }
  }
}
```

- [ ] **Step 8: Lint Bicep (optional but recommended)**

If `az` CLI and Bicep are installed:
```bash
az bicep build -f infra/bicep/main.bicep --stdout > /dev/null
```
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add infra/bicep
git commit -m "feat(infra): add Bicep IaC (CAE + Container Apps + Log Analytics + Managed Identity)"
```

---

## Task 16: Deploy scripts (sh/ps1) + OIDC setup

**Files:**
- Create: `infra/scripts/deploy.sh`
- Create: `infra/scripts/deploy.ps1`
- Create: `infra/scripts/destroy.sh`
- Create: `infra/scripts/destroy.ps1`
- Create: `infra/scripts/setup-github-oidc.sh`

- [ ] **Step 1: Write `infra/scripts/deploy.sh`**

```bash
#!/usr/bin/env bash
# infra/scripts/deploy.sh — provision RG + Bicep deployment
set -euo pipefail

ENV="${ENVIRONMENT:-dev}"
LOCATION="${AZURE_LOCATION:-westeurope}"
RG="${AZURE_RESOURCE_GROUP:-rg-osm-mcp-${ENV}}"
SUBSCRIPTION="${AZURE_SUBSCRIPTION_ID:?AZURE_SUBSCRIPTION_ID is required}"

az account set -s "$SUBSCRIPTION"
az group create -n "$RG" -l "$LOCATION" -o none

echo "▶ Deploying Bicep main.bicep to $RG..."
az deployment group create \
  -g "$RG" \
  -f infra/bicep/main.bicep \
  -p infra/bicep/main.parameters.json \
  -p environment="$ENV" \
  -p anthropicApiKey="${ANTHROPIC_API_KEY:-}" \
  -p azureAiProjectEndpoint="${AZURE_AI_PROJECT_ENDPOINT:-}" \
  -p azureAiModelDeploymentName="${AZURE_AI_MODEL_DEPLOYMENT_NAME:-}" \
  -p osmContactEmail="${OSM_CONTACT_EMAIL:-}" \
  -o table

FQDN=$(az containerapp show -g "$RG" -n osm-mcp-agent --query properties.configuration.ingress.fqdn -o tsv)
echo
echo "✅ Agent: https://$FQDN"
echo "   Health:      curl https://$FQDN/health"
echo "   MCP surface: https://$FQDN:8003/mcp"
```

- [ ] **Step 2: Write `infra/scripts/deploy.ps1`**

```powershell
# infra/scripts/deploy.ps1
[CmdletBinding()]
param(
  [string]$Environment = $env:ENVIRONMENT ?? 'dev',
  [string]$Location    = $env:AZURE_LOCATION ?? 'westeurope'
)
$ErrorActionPreference = 'Stop'

if (-not $env:AZURE_SUBSCRIPTION_ID) { throw "AZURE_SUBSCRIPTION_ID is required" }
$RG = $env:AZURE_RESOURCE_GROUP ?? "rg-osm-mcp-$Environment"

az account set -s $env:AZURE_SUBSCRIPTION_ID
az group create -n $RG -l $Location -o none

Write-Host "▶ Deploying Bicep to $RG..." -ForegroundColor Cyan
az deployment group create `
  -g $RG `
  -f infra/bicep/main.bicep `
  -p infra/bicep/main.parameters.json `
  -p environment=$Environment `
  -p anthropicApiKey="$($env:ANTHROPIC_API_KEY)" `
  -p azureAiProjectEndpoint="$($env:AZURE_AI_PROJECT_ENDPOINT)" `
  -p azureAiModelDeploymentName="$($env:AZURE_AI_MODEL_DEPLOYMENT_NAME)" `
  -p osmContactEmail="$($env:OSM_CONTACT_EMAIL)" `
  -o table

$Fqdn = az containerapp show -g $RG -n osm-mcp-agent --query properties.configuration.ingress.fqdn -o tsv
Write-Host ""
Write-Host "✅ Agent: https://$Fqdn" -ForegroundColor Green
Write-Host "   Health:      curl https://$Fqdn/health"
Write-Host "   MCP surface: https://$Fqdn`:8003/mcp"
```

- [ ] **Step 3: Write `infra/scripts/destroy.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
ENV="${ENVIRONMENT:-dev}"
RG="${AZURE_RESOURCE_GROUP:-rg-osm-mcp-${ENV}}"
read -p "Delete resource group $RG? [y/N] " confirm
[[ "$confirm" == [yY] ]] || { echo "Aborted."; exit 1; }
az group delete -n "$RG" --yes --no-wait
echo "▶ Resource group $RG deletion started (no-wait)"
```

- [ ] **Step 4: Write `infra/scripts/destroy.ps1`**

```powershell
[CmdletBinding()]
param([string]$Environment = $env:ENVIRONMENT ?? 'dev')
$RG = $env:AZURE_RESOURCE_GROUP ?? "rg-osm-mcp-$Environment"
$confirm = Read-Host "Delete resource group $RG? [y/N]"
if ($confirm -ne 'y' -and $confirm -ne 'Y') { Write-Host "Aborted."; exit 1 }
az group delete -n $RG --yes --no-wait
Write-Host "▶ Resource group $RG deletion started (no-wait)"
```

- [ ] **Step 5: Write `infra/scripts/setup-github-oidc.sh`**

```bash
#!/usr/bin/env bash
# Set up OIDC federation for GitHub Actions to deploy this repo to Azure.
# Idempotent: safe to re-run.
set -euo pipefail

REPO="${GITHUB_REPO:-agent-engineering-studio/mcp-osm}"
APP_NAME="${APP_NAME:-osm-mcp-github-deployer}"
SUBSCRIPTION="${AZURE_SUBSCRIPTION_ID:?AZURE_SUBSCRIPTION_ID required}"

az account set -s "$SUBSCRIPTION"

# 1. Create or get the AAD app
APP_ID=$(az ad app list --display-name "$APP_NAME" --query "[0].appId" -o tsv || true)
if [[ -z "$APP_ID" ]]; then
  APP_ID=$(az ad app create --display-name "$APP_NAME" --query appId -o tsv)
  echo "▶ Created AAD app $APP_NAME (appId=$APP_ID)"
else
  echo "▶ Reusing AAD app $APP_NAME (appId=$APP_ID)"
fi

SP_OID=$(az ad sp list --filter "appId eq '$APP_ID'" --query "[0].id" -o tsv || true)
if [[ -z "$SP_OID" ]]; then
  SP_OID=$(az ad sp create --id "$APP_ID" --query id -o tsv)
  echo "▶ Created service principal (objectId=$SP_OID)"
fi

# 2. Federated credentials for branch=main and tag=v*
for SUBJECT in "repo:$REPO:ref:refs/heads/main" "repo:$REPO:ref:refs/tags/v*" "repo:$REPO:environment:dev" "repo:$REPO:environment:prod"; do
  NAME="$(echo "$SUBJECT" | tr ':/' '-' | tr -cd '[:alnum:]-' | cut -c1-120)"
  if ! az ad app federated-credential list --id "$APP_ID" --query "[?name=='$NAME']" -o tsv | grep -q "$NAME"; then
    az ad app federated-credential create --id "$APP_ID" --parameters "$(cat <<EOF
{
  "name": "$NAME",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "$SUBJECT",
  "audiences": ["api://AzureADTokenExchange"]
}
EOF
)"
    echo "▶ Added federated credential: $SUBJECT"
  else
    echo "  (skip — federated credential already exists for $SUBJECT)"
  fi
done

# 3. Role assignment (Contributor on subscription scope by default; adjust to RG for tighter scope)
SCOPE="/subscriptions/$SUBSCRIPTION"
az role assignment create --assignee "$SP_OID" --role Contributor --scope "$SCOPE" -o none || true
echo "▶ Granted Contributor on $SCOPE"

TENANT=$(az account show --query tenantId -o tsv)
echo
echo "✅ Add these to your GitHub repo secrets / variables:"
echo "   AZURE_CLIENT_ID       = $APP_ID"
echo "   AZURE_TENANT_ID       = $TENANT"
echo "   AZURE_SUBSCRIPTION_ID = $SUBSCRIPTION"
```

- [ ] **Step 6: Make scripts executable**

Run:
```bash
chmod +x infra/scripts/deploy.sh infra/scripts/destroy.sh infra/scripts/setup-github-oidc.sh
```

- [ ] **Step 7: Commit**

```bash
git add infra/scripts
git commit -m "feat(infra): add deploy/destroy scripts (sh+ps1) and GitHub OIDC setup"
```

---

## Task 17: Test artifacts — `.http`, Postman collection, newman runners

**Files:**
- Create: `requests/agent-chat.http`
- Create: `requests/postman/osm-mcp-agent.postman_collection.json`
- Create: `requests/postman/test-agent-chat.sh`
- Create: `requests/postman/test-agent-chat.ps1`

- [ ] **Step 1: Write `requests/agent-chat.http`**

(This file mirrors the layout of mcp-ckan/requests/agent-chat.http. Sections 1–9 as listed in spec §8.1. Variables resolve from VS Code REST Client `@host` directives.)

```http
# osm-mcp-agent — REST Client requests
# https://marketplace.visualstudio.com/items?itemName=humao.rest-client
#
# Variables can be overridden via .vscode/settings.json:
#   "rest-client.environmentVariables": { "$shared": { "host": "..." } }

@host = http://localhost:8002
@mcp_host = http://localhost:8003
@osm_mcp_host = http://localhost:8080

### ─── 1. Health & smoke ────────────────────────────────────────────────
GET {{host}}/health


### ─── 2. Geocoding (single tool call) ──────────────────────────────────
POST {{host}}/chat
Content-Type: application/json

{ "query": "Trova il Colosseo a Roma" }


### ─── 3. POI nearby (find_nearby + render_geojson_map) ────────────────
POST {{host}}/chat
Content-Type: application/json

{ "query": "Mostrami su una mappa i ristoranti entro 500m dal Pantheon" }


### ─── 4. Routing multimodale ──────────────────────────────────────────
POST {{host}}/chat
Content-Type: application/json

{ "query": "Calcola il percorso in auto e in bici da Piazza Duomo Milano a Stazione Centrale, mostra entrambi su mappa" }


### ─── 5. Stream SSE ───────────────────────────────────────────────────
POST {{host}}/chat/stream
Content-Type: application/json

{ "query": "Quali stazioni di ricarica EV ci sono a Bologna?" }


### ─── 6. Upload GeoJSON utente (multipart) ────────────────────────────
POST {{host}}/chat/with-geojson
Content-Type: multipart/form-data; boundary=----osm

------osm
Content-Disposition: form-data; name="message"

Mostrami questa traccia su mappa con i ristoranti vicini ai punti
------osm
Content-Disposition: form-data; name="geojson_file"; filename="track.geojson"
Content-Type: application/geo+json

{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"LineString","coordinates":[[12.49,41.89],[12.50,41.90]]},"properties":{"name":"My route"}}]}
------osm--


### ─── 7. ⭐ Composizione ckan→osm (deterministico, /compose-map) ──────
POST {{host}}/compose-map
Content-Type: application/json

{
  "text": "Trovati 2 dataset geografici sul trasporto pubblico in Toscana",
  "resources": [
    {
      "name": "Fermate autobus Firenze",
      "url": "https://dati.toscana.it/dataset/example/fermate.geojson",
      "format": "GEOJSON",
      "content": "{\"type\":\"FeatureCollection\",\"features\":[{\"type\":\"Feature\",\"geometry\":{\"type\":\"Point\",\"coordinates\":[11.255,43.769]},\"properties\":{\"name\":\"Stazione SMN\"}}]}"
    },
    {
      "name": "Linee tramviarie",
      "url": "https://dati.toscana.it/dataset/example/tramvia.geojson",
      "format": "GEOJSON",
      "content": "{\"type\":\"FeatureCollection\",\"features\":[{\"type\":\"Feature\",\"geometry\":{\"type\":\"LineString\",\"coordinates\":[[11.20,43.77],[11.30,43.78]]},\"properties\":{\"linea\":\"T1\"}}]}"
    }
  ],
  "title": "Trasporto pubblico Toscana"
}


### ─── 8. MCP surface dell'agent (per coordinator MCP esterni) ─────────
POST {{mcp_host}}/mcp
Content-Type: application/json
Accept: application/json

{ "jsonrpc": "2.0", "id": 1, "method": "tools/list" }

###
POST {{mcp_host}}/mcp
Content-Type: application/json
Accept: application/json

{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "OsmAgent",
    "arguments": { "query": "Mostra i parchi entro 1km da Piazza San Marco a Venezia" }
  }
}


### ─── 9. MCP server raw (debug osm-mcp senza LLM) ─────────────────────
POST {{osm_mcp_host}}/mcp
Content-Type: application/json
Accept: application/json

{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "compose_map_from_resources",
    "arguments": {
      "text": "Test composizione",
      "resources": [
        {"name":"test","format":"GEOJSON","content":"{\"type\":\"FeatureCollection\",\"features\":[]}"}
      ]
    }
  }
}
```

- [ ] **Step 2: Write `requests/postman/osm-mcp-agent.postman_collection.json`**

```json
{
  "info": {
    "_postman_id": "osm-mcp-agent-collection",
    "name": "osm-mcp-agent",
    "description": "Postman collection mirroring requests/agent-chat.http for osm-mcp-agent. Run via newman (see test-agent-chat.sh).",
    "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
  },
  "variable": [
    { "key": "host", "value": "http://localhost:8002" },
    { "key": "mcp_host", "value": "http://localhost:8003" },
    { "key": "osm_mcp_host", "value": "http://localhost:8080" }
  ],
  "item": [
    {
      "name": "01 - Health",
      "item": [{
        "name": "GET /health",
        "request": { "method": "GET", "url": "{{host}}/health" },
        "event": [{
          "listen": "test",
          "script": { "type": "text/javascript", "exec": [
            "pm.test('200 OK', () => pm.response.to.have.status(200));",
            "pm.test('status=ok', () => pm.expect(pm.response.json().status).to.eql('ok'));"
          ]}
        }]
      }]
    },
    {
      "name": "02 - Geocoding & POI",
      "item": [
        {
          "name": "Geocode Colosseo",
          "request": {
            "method": "POST",
            "header": [{ "key": "Content-Type", "value": "application/json" }],
            "url": "{{host}}/chat",
            "body": { "mode": "raw", "raw": "{\"query\":\"Trova il Colosseo a Roma\"}" }
          },
          "event": [{ "listen": "test", "script": { "type": "text/javascript",
            "exec": ["pm.test('200', () => pm.response.to.have.status(200));"] }}]
        },
        {
          "name": "POI nearby (with map)",
          "request": {
            "method": "POST",
            "header": [{ "key": "Content-Type", "value": "application/json" }],
            "url": "{{host}}/chat",
            "body": { "mode": "raw", "raw": "{\"query\":\"Mostrami su una mappa i ristoranti entro 500m dal Pantheon\"}" }
          }
        }
      ]
    },
    {
      "name": "03 - Routing",
      "item": [{
        "name": "Multimodal route",
        "request": {
          "method": "POST",
          "header": [{ "key": "Content-Type", "value": "application/json" }],
          "url": "{{host}}/chat",
          "body": { "mode": "raw", "raw": "{\"query\":\"Calcola il percorso da Piazza Duomo Milano a Stazione Centrale, in auto e in bici, mostra entrambi su mappa\"}" }
        }
      }]
    },
    {
      "name": "04 - Streaming",
      "item": [{
        "name": "Stream EV stations",
        "request": {
          "method": "POST",
          "header": [{ "key": "Content-Type", "value": "application/json" }],
          "url": "{{host}}/chat/stream",
          "body": { "mode": "raw", "raw": "{\"query\":\"Quali stazioni EV ci sono a Bologna?\"}" }
        }
      }]
    },
    {
      "name": "05 - GeoJSON upload",
      "item": [{
        "name": "Upload track.geojson",
        "request": {
          "method": "POST",
          "url": "{{host}}/chat/with-geojson",
          "body": {
            "mode": "formdata",
            "formdata": [
              { "key": "message", "value": "Mostrami questa traccia su mappa con ristoranti vicini", "type": "text" },
              { "key": "geojson_file", "type": "file", "src": [] }
            ]
          }
        }
      }]
    },
    {
      "name": "06 - Composition (ckan→osm)",
      "item": [{
        "name": "POST /compose-map (deterministic)",
        "request": {
          "method": "POST",
          "header": [{ "key": "Content-Type", "value": "application/json" }],
          "url": "{{host}}/compose-map",
          "body": { "mode": "raw", "raw": "{\"text\":\"Test\",\"resources\":[{\"name\":\"L1\",\"format\":\"GEOJSON\",\"content\":\"{\\\"type\\\":\\\"FeatureCollection\\\",\\\"features\\\":[{\\\"type\\\":\\\"Feature\\\",\\\"geometry\\\":{\\\"type\\\":\\\"Point\\\",\\\"coordinates\\\":[11.25,43.77]},\\\"properties\\\":{}}]}\"}]}" }
        },
        "event": [{ "listen": "test", "script": { "type": "text/javascript",
          "exec": [
            "pm.test('200', () => pm.response.to.have.status(200));",
            "const b = pm.response.json();",
            "pm.test('has HTML resource', () => pm.expect(b.resources[0].format).to.eql('HTML'));"
          ] }}]
      }]
    },
    {
      "name": "07 - MCP surface (agent)",
      "item": [{
        "name": "tools/list",
        "request": {
          "method": "POST",
          "header": [
            { "key": "Content-Type", "value": "application/json" },
            { "key": "Accept", "value": "application/json" }
          ],
          "url": "{{mcp_host}}/mcp",
          "body": { "mode": "raw", "raw": "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}" }
        }
      }]
    },
    {
      "name": "08 - MCP raw (osm-mcp)",
      "item": [{
        "name": "compose_map_from_resources direct",
        "request": {
          "method": "POST",
          "header": [
            { "key": "Content-Type", "value": "application/json" },
            { "key": "Accept", "value": "application/json" }
          ],
          "url": "{{osm_mcp_host}}/mcp",
          "body": { "mode": "raw", "raw": "{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/call\",\"params\":{\"name\":\"compose_map_from_resources\",\"arguments\":{\"text\":\"test\",\"resources\":[{\"name\":\"test\",\"format\":\"GEOJSON\",\"content\":\"{\\\"type\\\":\\\"FeatureCollection\\\",\\\"features\\\":[]}\"}]}}}" }
        }
      }]
    }
  ]
}
```

- [ ] **Step 3: Write `requests/postman/test-agent-chat.sh`**

```bash
#!/usr/bin/env bash
# requests/postman/test-agent-chat.sh — newman runner
set -euo pipefail
HOST="${HOST:-http://localhost:8002}"
MCP_HOST="${MCP_HOST:-http://localhost:8003}"
OSM_MCP_HOST="${OSM_MCP_HOST:-http://localhost:8080}"
COLLECTION="$(dirname "$0")/osm-mcp-agent.postman_collection.json"

echo "▶ Waiting for agent at $HOST..."
for i in $(seq 1 30); do
  if curl -fsS "$HOST/health" >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fsS "$HOST/health" >/dev/null || { echo "Agent never became healthy"; exit 1; }

echo "▶ Running collection via newman..."
newman run "$COLLECTION" \
  --env-var "host=$HOST" \
  --env-var "mcp_host=$MCP_HOST" \
  --env-var "osm_mcp_host=$OSM_MCP_HOST" \
  --reporters cli,json \
  --reporter-json-export "$(dirname "$0")/last-run.json"
```

- [ ] **Step 4: Write `requests/postman/test-agent-chat.ps1`**

```powershell
# requests/postman/test-agent-chat.ps1 — newman runner (PowerShell)
[CmdletBinding()]
param(
  [string]$Host_      = $env:HOST          ?? 'http://localhost:8002',
  [string]$McpHost    = $env:MCP_HOST      ?? 'http://localhost:8003',
  [string]$OsmMcpHost = $env:OSM_MCP_HOST  ?? 'http://localhost:8080'
)
$ErrorActionPreference = 'Stop'
$Collection = Join-Path $PSScriptRoot 'osm-mcp-agent.postman_collection.json'

Write-Host "▶ Waiting for agent at $Host_..."
for ($i = 0; $i -lt 30; $i++) {
  try { Invoke-WebRequest "$Host_/health" -UseBasicParsing -TimeoutSec 2 | Out-Null; break } catch { Start-Sleep 2 }
}

Write-Host "▶ Running collection via newman..."
newman run $Collection `
  --env-var "host=$Host_" `
  --env-var "mcp_host=$McpHost" `
  --env-var "osm_mcp_host=$OsmMcpHost" `
  --reporters cli,json `
  --reporter-json-export (Join-Path $PSScriptRoot 'last-run.json')
```

- [ ] **Step 5: Make sh executable**

```bash
chmod +x requests/postman/test-agent-chat.sh
```

- [ ] **Step 6: Commit**

```bash
git add requests
git commit -m "feat(test): add agent-chat.http + Postman collection + newman runners"
```

---

## Task 18: GitHub Actions — 4 workflows

**Files:**
- Replace: `.github/workflows/ci.yml`
- Create: `.github/workflows/docker-publish.yml`
- Create: `.github/workflows/publish-ollama.yml`
- Replace: `.github/workflows/deploy-azure.yml`
- Delete: `.github/workflows/release-docker.yml`

- [ ] **Step 1: Replace `ci.yml`**

```yaml
# .github/workflows/ci.yml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read

jobs:
  python-mcp-server:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12", cache: "pip" }
      - run: cd osm-mcp && pip install -e ".[dev]"
      - run: cd osm-mcp && python -m ruff check src tests
      - run: cd osm-mcp && pytest -v

  python-agent:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12", cache: "pip" }
      - run: cd osm-mcp-agent && pip install -e ".[dev]"
      - run: cd osm-mcp-agent && python -m ruff check src tests
      - run: cd osm-mcp-agent && pytest -v

  smoke-integration:
    runs-on: ubuntu-latest
    needs: [python-mcp-server, python-agent]
    steps:
      - uses: actions/checkout@v4
      - name: Build images
        run: docker compose build osm-mcp osm-mcp-agent
      - name: Start stack (no LLM provider needed for /compose-map)
        env:
          LLM_PROVIDER: ollama
          OLLAMA_BASE_URL: http://example-not-used:11434
        run: |
          docker compose up -d osm-mcp osm-mcp-agent
      - name: Wait for /health
        run: |
          for i in $(seq 1 30); do
            if curl -fsS http://localhost:8002/health; then exit 0; fi
            sleep 2
          done
          docker compose logs osm-mcp osm-mcp-agent
          exit 1
      - name: Test deterministic compose endpoint
        run: |
          curl -fsS -X POST http://localhost:8002/compose-map \
            -H "Content-Type: application/json" \
            --data @osm-mcp/tests/fixtures/ckan_response.json \
            -o response.json
          python - <<'PY'
          import json, sys
          r = json.load(open("response.json"))
          assert r["resources"], "no resources returned"
          assert r["resources"][0]["format"] == "HTML", r
          assert "<!doctype html>" in r["resources"][0]["content"].lower() \
              or "<!DOCTYPE html>" in r["resources"][0]["content"]
          print("OK")
          PY
      - if: always()
        run: docker compose down -v
```

- [ ] **Step 2: Write `docker-publish.yml`**

```yaml
# .github/workflows/docker-publish.yml
name: Publish container images
on:
  push:
    branches: [main]
    tags: ["v*"]
  workflow_dispatch:

permissions:
  contents: read
  packages: write

jobs:
  build-push:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        include:
          - { service: osm-mcp,       context: ./osm-mcp }
          - { service: osm-mcp-agent, context: ./osm-mcp-agent }
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-qemu-action@v3
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - id: meta
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/${{ github.repository_owner }}/${{ matrix.service }}
          tags: |
            type=ref,event=branch
            type=ref,event=pr
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=raw,value=latest,enable={{is_default_branch}}
            type=sha,format=short
      - uses: docker/build-push-action@v5
        with:
          context: ${{ matrix.context }}
          platforms: linux/amd64,linux/arm64
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha,scope=${{ matrix.service }}
          cache-to: type=gha,mode=max,scope=${{ matrix.service }}
```

- [ ] **Step 3: Write `publish-ollama.yml`**

```yaml
# .github/workflows/publish-ollama.yml
name: Publish Ollama image (osm-mcp-ollama)
on:
  push:
    branches: [main]
    paths:
      - 'infra/ollama/**'
      - '.github/workflows/publish-ollama.yml'
  workflow_dispatch:
    inputs:
      base_model:
        description: "Base Ollama model"
        default: "qwen2.5:7b-instruct"

permissions:
  contents: read
  packages: write

jobs:
  bake-and-push:
    runs-on: ubuntu-latest
    timeout-minutes: 90
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build base Ollama image
        run: docker build -t osm-mcp-ollama:bake infra/ollama

      - name: Bake model
        run: |
          docker run -d --name bake -v ollama_bake:/root/.ollama \
            --entrypoint /bin/bash osm-mcp-ollama:bake \
            -c "ollama serve & sleep 5 && \
                ollama pull ${{ inputs.base_model || 'qwen2.5:7b-instruct' }} && \
                ollama create qwen2.5:16k -f /Modelfile && \
                tail -f /dev/null"
          for i in $(seq 1 60); do
            docker exec bake bash -c "ollama list 2>/dev/null | grep -q 'qwen2.5:16k'" && break
            sleep 10
          done
          docker exec bake bash -c "ollama list" | tee
          docker stop bake
          docker commit bake ghcr.io/${{ github.repository_owner }}/osm-mcp-ollama:latest

      - name: Push image
        run: docker push ghcr.io/${{ github.repository_owner }}/osm-mcp-ollama:latest
```

- [ ] **Step 4: Replace `deploy-azure.yml`**

```yaml
# .github/workflows/deploy-azure.yml
name: Deploy to Azure Container Apps
on:
  workflow_dispatch:
    inputs:
      environment:
        description: "Target environment"
        default: "dev"
        type: choice
        options: [dev, prod]
  push:
    tags: ["v*"]

permissions:
  id-token: write
  contents: read

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: ${{ inputs.environment || 'dev' }}
    env:
      AZURE_LOCATION: ${{ vars.AZURE_LOCATION || 'westeurope' }}
      AZURE_RESOURCE_GROUP: rg-osm-mcp-${{ inputs.environment || 'dev' }}
    steps:
      - uses: actions/checkout@v4

      - uses: azure/login@v2
        with:
          client-id:       ${{ secrets.AZURE_CLIENT_ID }}
          tenant-id:       ${{ secrets.AZURE_TENANT_ID }}
          subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}

      - id: tag
        run: echo "tag=${GITHUB_REF_NAME#v}" >> "$GITHUB_OUTPUT"

      - name: Ensure resource group
        run: |
          az group create -n "$AZURE_RESOURCE_GROUP" -l "$AZURE_LOCATION" -o none

      - uses: azure/arm-deploy@v2
        with:
          scope: resourcegroup
          resourceGroupName: ${{ env.AZURE_RESOURCE_GROUP }}
          template: infra/bicep/main.bicep
          parameters: >
            environment=${{ inputs.environment || 'dev' }}
            mcpImage=ghcr.io/${{ github.repository_owner }}/osm-mcp:${{ steps.tag.outputs.tag || 'latest' }}
            agentImage=ghcr.io/${{ github.repository_owner }}/osm-mcp-agent:${{ steps.tag.outputs.tag || 'latest' }}
            llmProvider=${{ vars.LLM_PROVIDER || 'azure_foundry' }}
            anthropicApiKey=${{ secrets.ANTHROPIC_API_KEY }}
            azureAiProjectEndpoint=${{ vars.AZURE_AI_PROJECT_ENDPOINT }}
            azureAiModelDeploymentName=${{ vars.AZURE_AI_MODEL_DEPLOYMENT_NAME }}
          failOnStdErr: false

      - name: Smoke test deployed agent
        run: |
          FQDN=$(az containerapp show -g "$AZURE_RESOURCE_GROUP" -n osm-mcp-agent \
            --query properties.configuration.ingress.fqdn -o tsv)
          echo "Agent: https://$FQDN"
          curl -fsS "https://$FQDN/health" | tee
```

- [ ] **Step 5: Delete old workflow**

Run:
```bash
git rm .github/workflows/release-docker.yml
```

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/ci.yml .github/workflows/docker-publish.yml .github/workflows/publish-ollama.yml .github/workflows/deploy-azure.yml
git commit -m "ci: replace 3 workflows with 4 (ci, docker-publish, publish-ollama, deploy-azure)"
```

---

## Task 19: Makefile rewrite + README rewrite

**Files:**
- Replace: `Makefile`
- Replace: `README.md`

- [ ] **Step 1: Write new `Makefile`**

```makefile
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

mcp-run:        ## Run osm-mcp locally (streamable-http on :8080)
	cd osm-mcp && TRANSPORT=streamable-http HOST=0.0.0.0 PORT=8080 python -m osm_mcp.server

mcp-inspector:  ## Open the MCP Inspector against osm-mcp (stdio)
	cd osm-mcp && npx @modelcontextprotocol/inspector python -m osm_mcp.server

# ── Agent (Python) ──────────────────────────────────────────────────────
agent-install:  ## Install osm-mcp-agent with dev extras
	cd osm-mcp-agent && pip install -e ".[dev]"

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
```

- [ ] **Step 2: Write new `README.md`**

```markdown
# mcp-osm — OpenStreetMap MCP server + Python Agent

[![CI](https://github.com/agent-engineering-studio/mcp-osm/actions/workflows/ci.yml/badge.svg)](https://github.com/agent-engineering-studio/mcp-osm/actions)
[![Docker](https://github.com/agent-engineering-studio/mcp-osm/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/agent-engineering-studio/mcp-osm/actions/workflows/docker-publish.yml)

A self-hosted **MCP server for OpenStreetMap** (Python FastMCP) plus a **Python
agent** with switchable LLM provider (Ollama / Claude / Azure AI Foundry) and
**dual REST + MCP surface** so it's directly composable with `mcp-ckan` and
other MCP-aware coordinators.

> **Why this exists:** an OSM-aware assistant you can plug into your own data
> pipelines, that produces standalone HTML maps and doesn't depend on
> proprietary tile providers — Leaflet + tile.openstreetmap.org by default.

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
                           ▼ /mcp
            ┌──────────────────────────────────┐
            │  osm-mcp  (FastMCP, Python)      │
            │  11 tools: geocoding, routing,   │
            │  POI, EV, commute,               │
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

## OSM tools (11)

8 existing geo tools (`geocode_address`, `reverse_geocode`, `find_nearby_places`,
`search_category_in_bbox`, `get_route`, `suggest_meeting_point`, `explore_area`,
`find_ev_charging_stations`, `analyze_commute`) plus 3 map renderers:

- **`render_geojson_map(geojson, title?, center?, zoom?)`** — single-layer Leaflet map.
- **`render_multi_layer_map(layers, title?, center?, zoom?)`** — multi-layer with legend and toggle.
- **`compose_map_from_resources(text, resources, title?, center?, zoom?)`** ⭐ — accepts
  the `{text, resources[]}` shape emitted by `ckan-mcp-agent` and renders all GeoJSON
  resources on a single map.

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
near the Pantheon on a map") and gets back map HTML.

## Testing

```bash
make mcp-test       # pytest on osm-mcp
make agent-test     # pytest on osm-mcp-agent
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
```

- [ ] **Step 3: Verify Makefile targets**

Run:
```bash
make help
```
Expected: lists all the targets.

- [ ] **Step 4: Commit**

```bash
git add Makefile README.md
git commit -m "docs: rewrite README and Makefile for the Python agent + composition pattern"
```

---

## Task 20: Cleanup — remove `osm-agent/` (.NET) and obsolete scripts

**Files:**
- Delete: entire `osm-agent/` directory (.NET project)
- Delete: `scripts/deploy-azure.sh`
- Delete: `scripts/deploy-azure.ps1`

- [ ] **Step 1: Verify no remaining references**

Run:
```bash
grep -rn "osm-agent" \
  --include='*.yml' --include='*.yaml' --include='Makefile' \
  --include='*.md' --include='*.bicep' --include='*.json' \
  -- . ':(exclude)docs' ':(exclude).git' || echo "clean"
```
Expected: any matches must refer to `osm-mcp-agent` (with the `mcp` infix), not `osm-agent` standalone. If any remain, fix them in this commit.

- [ ] **Step 2: Delete the .NET directory**

```bash
git rm -r osm-agent
```

- [ ] **Step 3: Delete obsolete scripts**

```bash
git rm scripts/deploy-azure.sh scripts/deploy-azure.ps1
rmdir scripts 2>/dev/null || true
```

- [ ] **Step 4: Run full test suite + smoke**

```bash
make mcp-test
make agent-test
make build
make up
sleep 10
curl -fsS http://localhost:8002/health
make down
```
Expected: tests green, agent /health returns `{"status":"ok",...}`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: remove .NET osm-agent and obsolete deploy scripts"
```

---

## Task 21: Final integration smoke test (manual)

**No files** — manual verification of acceptance criteria from spec §14.

- [ ] **Step 1: Verify acceptance criteria checklist**

```bash
# Start the full stack
make up-cpu    # or 'make up' if running Ollama on host

# Wait for health
for svc in osm-mcp:8080 osm-mcp-agent:8002; do
  host=${svc%%:*}; port=${svc##*:}
  curl -fsS http://localhost:$port/health || curl -fsS http://localhost:$port/ \
    || echo "$svc not ready"
done

# Run smoke (newman against Postman collection)
make smoke

# Verify /compose-map returns HTML
curl -fsS -X POST http://localhost:8002/compose-map \
  -H "Content-Type: application/json" \
  --data @osm-mcp/tests/fixtures/ckan_response.json \
  | python -c "import json,sys; r=json.load(sys.stdin); \
    assert r['resources'][0]['format']=='HTML' and '<!doctype' in r['resources'][0]['content'].lower(); \
    print('✅ compose-map OK,', len(r['resources'][0]['content']), 'bytes of HTML')"

# Verify MCP surface
curl -fsS -X POST http://localhost:8003/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | head -c 500
```

Expected:
- All `/health` endpoints return 200
- `make smoke` exits 0 with all newman tests green
- `/compose-map` produces valid HTML
- MCP surface lists at least one tool (named `OsmAgent` or similar)

- [ ] **Step 2: If anything fails, fix it before merging**

Failure modes to look for:
1. **`compose_map_from_resources` not registered** → check Task 6, Step 5 (decorator wiring)
2. **`/compose-map` 502** → check `MCP_SERVER_URL` env reaches the right host inside the agent container
3. **MCP surface :8003 not listening** → verify `mcp_surface.py` uses the right `StreamableHTTPSessionManager` API for the installed `mcp` package version (the spec notes this may need adaptation)
4. **`agent.as_mcp_server()` returns AttributeError** → confirm `mcp[ws] --pre` is installed in the agent image

- [ ] **Step 3: Final commit (if any fixes were needed)**

```bash
git add -A
git commit -m "fix: integration smoke fixes from final verification"
```

- [ ] **Step 4: Tag the release (optional)**

```bash
git tag -a v0.2.0 -m "Python agent parity with mcp-ckan + GeoJSON/HTML maps"
git push origin v0.2.0
```

This triggers `docker-publish.yml` (multi-arch build to GHCR) and `deploy-azure.yml`
(if you've set up OIDC).

---

## Self-Review

**Spec coverage check:** Each spec section maps to a task:

| Spec § | Topic | Tasks |
|---|---|---|
| 3.1 — Architecture levels | L1/L2/L3 layout | Task 4–11 (L2+L3) |
| 3.2 — Composition multi-MCP | Coordinator pattern | Task 6 (L2 tool) + Task 9 (L3 endpoint) |
| 3.3 — Contract `{text, resources[]}` | pydantic mirrors | Task 2 |
| 3.4 — No MAF orchestration | YAGNI documented | (no task — design decision only) |
| 4 — Layout repo | Files created | Tasks 1–20 (all) |
| 5.1 — `geojson_builder.py` | Module | Task 4 |
| 5.2 — `html_renderer.py` | Module + template | Task 5 |
| 5.3 — 3 new MCP tools | Implementation | Task 6 |
| 5.4 — `config.py` extension | MAP_* settings | Task 3 |
| 6.1–6.6 — Agent details | All Python agent files | Tasks 1, 2, 7, 8, 9, 10, 11 |
| 7 — Docker + Ollama | compose, Dockerfile, Modelfile | Tasks 12, 13, 14 |
| 8 — Tests (.http + Postman + pytest) | All test artifacts | Tasks 4, 5, 6, 7, 9, 10, 17 |
| 9 — 4 GHA workflows | CI/CD | Task 18 |
| 10 — Bicep IaC | All modules + scripts | Tasks 15, 16 |
| 11 — README sections | Docs | Task 19 |
| 12 — Non-goals | Documented in README | Task 19 |
| 13 — Migration & rollout | Branch strategy + cleanup | Task 20 |
| 14 — Acceptance criteria | Manual verification | Task 21 |

No gaps.

**Placeholder scan:** No "TBD", "TODO", "implement later", "fill in details", "similar to Task N", or steps describing what without showing how. All code blocks are complete.

**Type consistency:**
- `Resource` shape `{name, url, format, content}` consistent across Tasks 2, 6, 9, 17
- `compose_map_from_resources(text, resources, title?, center?, zoom?)` consistent in Tasks 6 (server side), 9 (agent calls it), 17 (.http calls it), 18 (CI tests it)
- `MapLayer` dataclass uses `name, geojson, style?` in Tasks 5 and 6 — consistent
- Port numbers `:8002` (REST), `:8003` (MCP), `:8080` (osm-mcp) consistent across Tasks 1, 8, 11, 12, 14, 15, 17, 18, 19
- Env var names: `LLM_PROVIDER`, `MCP_SERVER_URL`, `MCP_APPROVAL_MODE`, `MCP_SURFACE_*`, `OLLAMA_*`, `ANTHROPIC_API_KEY`, `AZURE_AI_*` consistent across config.py (Task 2), docker-compose.yml (Task 14), Bicep (Task 15), workflows (Task 18), env files (Task 14)

No inconsistencies found.
