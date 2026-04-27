# mcp-osm — parity con mcp-ckan + GeoJSON/HTML map rendering

**Status**: Draft
**Date**: 2026-04-27
**Author**: Giuseppe Zileni (with Claude)
**Target**: `C:\Users\GiuseppeZileni\Git\agent-engineering-studio\mcp-osm`

## 1. Obiettivo

Portare `mcp-osm` a parità infrastrutturale con `mcp-ckan` (già in produzione) ed estenderlo con la
capacità di **generare mappe HTML self-contained** (Leaflet + OSM raster tiles) a partire da
GeoJSON, sia generato dai tool OSM sia fornito dall'utente, sia ricevuto da un altro agent MCP
(es. `ckan-mcp-agent`) come parte della response standard `{text, resources[]}`.

L'agent risultante:
- è scritto in **Python** con `agent_framework` (sostituisce l'attuale C#/.NET)
- supporta switch del provider LLM tra **Ollama**, **Claude (Anthropic)**, **Azure AI Foundry**
- è esposto sia come **REST API** (FastAPI, parità con ckan-mcp-agent) sia come **MCP server**
  (via `agent.as_mcp_server()`) per essere consumato come tool da altri client MCP-aware
- accetta in input GeoJSON arbitrario (file upload, payload JSON) e produce mappe HTML
  multi-layer pronte da renderizzare inline in viewer compatibili
- è componibile con `ckan-mcp-agent`: la response shape `{text, resources[]}` è stabile e
  l'endpoint `/compose-map` accetta il payload as-is per produrre la mappa risultante

## 2. Stato attuale e gap

### 2.1 Stato `mcp-osm`

- MCP server Python `osm-mcp/` con 8 tool (geocoding, routing, POI, EV, commute) — non genera
  GeoJSON né HTML
- Agent **C#/.NET** `osm-agent/` con Microsoft Agent Framework (.NET), **solo Ollama**
  hardcoded, niente provider switch
- Docker compose ok (profile dev/prod/cpu/gpu), 3 workflow GitHub Actions
- **Mancanze**: Bicep IaC, `requests/` (.http + Postman), `.env.azure.example`,
  `.env.dev-claude.example`, immagine Ollama pre-baked

### 2.2 Reference `mcp-ckan`

- MCP server e agent **entrambi Python**
- Agent con `factory.py` che istanzia il chat client per i 3 provider
- 4 workflow GHA: `ci`, `deploy-azure`, `docker-publish`, `publish-ollama`
- `infra/bicep/` (Container Apps + ACR + Log Analytics), scripts deploy.sh/destroy.sh/setup-oidc.sh
- `requests/agent-chat.http` (~26 KB) + collection Postman + script newman
- Multipli `.env.*.example` per ambienti diversi
- Docker compose unificato con profili Ollama cpu/gpu

### 2.3 Decisioni di disambiguazione (da brainstorming)

| Decisione | Scelta |
|---|---|
| Stack agent | Riscritto in **Python** (sostituisce .NET); rinominato `osm-agent/` → `osm-mcp-agent/` |
| Logica GeoJSON/HTML | Nel **MCP server** (livello 2), non nell'agent |
| Libreria mappa | **Leaflet** + tile **OSM raster** (no MapLibre, no provider terzi) |
| HTML delivery | **Inline** nei tool MCP via content multi-block (text + resource `text/html`) |
| Composizione ckan→osm | Tool `compose_map_from_resources` nel MCP server + endpoint REST `/compose-map` nell'agent |
| Surface dell'agent | Dual: **REST** :8002 + **MCP** `as_mcp_server()` :8003 |
| Orchestrazione MAF | **Nessuna** (single ChatAgent — Magentic/Sequential/Concurrent over-engineering per single domain) |
| Provider switching | Factory pattern 1:1 con `ckan-mcp-agent` (Ollama / Claude / Azure Foundry) |
| Test | `.http` + Postman + pytest, smoke target `make smoke` |
| CI/CD | 4 workflow GHA replicati da mcp-ckan |
| IaC | Bicep replicato da mcp-ckan, adattato a `osm-*` |

## 3. Architettura

### 3.1 Tre livelli

```
┌──────────────────────────────────────────────────────────────────┐
│ LIVELLO 3 — osm-mcp-agent (NEW)                                   │
│   Python + agent_framework.Agent                                  │
│                                                                    │
│   Surface esposte:                                                 │
│    • REST/HTTP (FastAPI) :8002                                     │
│        POST /chat                  → {text, resources[]}          │
│        POST /chat/stream           SSE                            │
│        POST /chat/with-geojson     multipart upload               │
│        POST /compose-map           ⭐ DETERMINISTICO              │
│        GET  /health                                               │
│                                                                    │
│    • MCP via agent.as_mcp_server()                                │
│      Streamable HTTP :8003 path /mcp                              │
│      Espone l'agent come tool MCP "OsmAgent"                      │
│                                                                    │
│   Tool interni:                                                    │
│    • MCPStreamableHTTPTool(osm-mcp)                                │
└──────────────────────────────────────────────────────────────────┘
                               │ MCPStreamableHTTPTool
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│ LIVELLO 2 — osm-mcp (esistente, esteso)                           │
│   Python FastMCP, stateless, transport: streamable-http :8080     │
│                                                                    │
│   Tool esistenti (8): geocode_address, reverse_geocode,           │
│     find_nearby_places, search_category_in_bbox, get_route,       │
│     suggest_meeting_point, explore_area,                          │
│     find_ev_charging_stations, analyze_commute                    │
│                                                                    │
│   Tool nuovi (3):                                                  │
│    • render_geojson_map(geojson, title?, center?, zoom?)          │
│    • render_multi_layer_map(layers, title?, center?, zoom?)       │
│    • compose_map_from_resources(text, resources, title?, ...)     │
│      → tutti ritornano content multi-block:                        │
│        [TextContent(summary), EmbeddedResource(text/html)]        │
└──────────────────────────────────────────────────────────────────┘
                               │ HTTP API
                               ▼
            Nominatim · Overpass · OSRM · OSM tile
```

### 3.2 Composizione multi-MCP (use case third-party coordinator)

Lo scenario chiave che il design abilita: un agent di terzi monta **due** MCP tool e compone
la pipeline `ckan-mcp-agent → osm-mcp-agent`.

```
Coordinator (third-party agent)
  ├── tools[0] = MCPStreamableHTTPTool(name="ckan", url=ckan-mcp-agent /mcp)
  └── tools[1] = MCPStreamableHTTPTool(name="osm",  url=osm-mcp-agent /mcp)
```

Flusso:

1. Coordinator chiama `ckan-mcp-agent` con NL ("trova dataset trasporto Toscana")
2. `ckan-mcp-agent` ritorna:
   ```json
   { "text": "Trovati 3 dataset...",
     "resources": [
       {"name": "Fermate", "url": "...", "format": "GEOJSON",
        "content": "<full geojson string>"}, ...
     ] }
   ```
3. Coordinator passa questo **payload as-is** a `osm-mcp-agent`. Due strategie:

| Path | Endpoint | LLM coinvolto? | Quando |
|---|---|---|---|
| **Deterministico** | `POST /compose-map` (REST) o tool MCP `compose_map_from_resources` | No (Python puro) | Composizione veloce, prevedibile, gratis. Caso 95%. |
| **Intelligente** | MCP `agent.as_mcp_server()` → query NL + payload | Sì | Coordinator vuole arricchimento (POI vicini, titolo auto, styling intelligente) |

4. `osm-mcp-agent` ritorna **stesso shape** `{text, resources[]}` ma con `resources[]` che
   contiene un singolo HTML map. **Closure del contract** ⇒ catene arbitrarie componibili.

### 3.3 Contract di interscambio (stable, JSON-shape based)

Definito in `osm-mcp-agent/src/osm_agent/contracts.py` come pydantic, **mirror** del contract
omonimo in `ckan-mcp-agent/src/ckan_agent/api.py`:

```python
class Resource(BaseModel):
    name: str
    url: str | None = None
    format: str            # "GEOJSON" | "CSV" | "JSON" | "TXT" | "HTML" | ...
    content: str | None = None    # raw text content if downloadable

class ChatResponse(BaseModel):
    text: str
    resources: list[Resource] = []
```

**Niente libreria condivisa**: il contract è il JSON shape, non la classe Python. Permette
evoluzione indipendente dei due agent (campi opzionali aggiunti unilateralmente sono ignorati).

### 3.4 Decisione: niente orchestrazione MAF

Verificate le 5 orchestration MAF (Sequential, Concurrent, Handoff, Group Chat, Magentic):

| Pattern | Si applica? | Motivo |
|---|---|---|
| Sequential | No | Geocode→search→render lo fa già l'LLM via tool calls |
| Concurrent | No | Tool OSM hanno dipendenze (search needs coords) |
| Handoff | No | Single domain, no specialist boundaries |
| Group Chat | No | Single output, niente refinement multi-perspective |
| Magentic | No | Esplicitamente per "complex open-ended tasks"; il nostro è ben definito |

Decisione: **single ChatAgent**. Riserviamo orchestration per futuro use case multi-step ambiguo
(es. "pianifica gita 3 giorni con tappe ottimizzate"). Per MVP: YAGNI.

## 4. Layout repository (post-merge)

```
mcp-osm/
├── osm-mcp/                          # MCP server Python (esistente, esteso)
│   ├── src/osm_mcp/
│   │   ├── server.py                 # invariato
│   │   ├── config.py                 # +MAP_TILE_URL, MAP_ATTRIBUTION, MAP_DEFAULT_ZOOM
│   │   ├── osm_client.py             # invariato
│   │   ├── tools.py                  # +3 tool nuovi, content multi-block
│   │   ├── geojson_builder.py        # NEW
│   │   └── html_renderer.py          # NEW
│   ├── templates/
│   │   └── map.html.j2               # NEW — Leaflet template
│   ├── tests/
│   │   ├── test_tools.py             # esistente
│   │   ├── test_geojson_builder.py   # NEW
│   │   ├── test_html_renderer.py     # NEW
│   │   ├── test_compose_resources.py # NEW
│   │   └── fixtures/ckan_response.json  # NEW
│   ├── Dockerfile, pyproject.toml
│
├── osm-mcp-agent/                    # NEW (sostituisce osm-agent C#)
│   ├── src/osm_agent/
│   │   ├── __init__.py
│   │   ├── api.py                    # FastAPI 4 endpoint
│   │   ├── config.py                 # Settings pydantic
│   │   ├── contracts.py              # NEW Resource/ChatResponse pydantic
│   │   ├── factory.py                # provider switch + AgentSession
│   │   ├── mcp_surface.py            # NEW — agent.as_mcp_server() su :8003
│   │   └── main.py                   # avvia FastAPI + MCP surface
│   ├── tests/
│   │   ├── test_factory.py
│   │   ├── test_contracts.py
│   │   ├── test_compose_endpoint.py
│   │   └── test_chat_with_geojson.py
│   ├── Dockerfile, pyproject.toml, README.md
│
├── osm-agent/                        # ⚠️ RIMOSSA (era .NET)
│
├── infra/
│   ├── ollama/                       # esistente, esteso con Modelfile
│   │   ├── Dockerfile
│   │   ├── Modelfile                 # NEW — qwen2.5:7b-instruct + num_ctx 16384
│   │   └── entrypoint.sh
│   ├── bicep/                        # NEW
│   │   ├── main.bicep
│   │   ├── main.parameters.json
│   │   └── modules/
│   │       ├── log-analytics.bicep
│   │       ├── container-app-env.bicep
│   │       ├── container-app-mcp.bicep
│   │       ├── container-app-agent.bicep
│   │       └── identity.bicep
│   └── scripts/                      # NEW
│       ├── deploy.sh, deploy.ps1
│       ├── destroy.sh, destroy.ps1
│       └── setup-github-oidc.sh
│
├── requests/                         # NEW
│   ├── agent-chat.http               # 9 sezioni, REST Client VS Code
│   └── postman/
│       ├── osm-mcp-agent.postman_collection.json
│       ├── test-agent-chat.sh
│       └── test-agent-chat.ps1
│
├── .github/workflows/
│   ├── ci.yml                        # esistente, riscritto (lint + pytest + smoke)
│   ├── deploy-azure.yml              # esistente, riscritto (Bicep + OIDC)
│   ├── docker-publish.yml            # NEW (era release-docker.yml)
│   └── publish-ollama.yml            # NEW
│
├── docs/
│   └── superpowers/specs/2026-04-27-mcp-osm-parity-design.md   # questo doc
│
├── docker-compose.yml                # riscritto (osm-mcp + osm-mcp-agent + ollama profiles)
├── docker-compose.ghcr.yml           # esistente, adattato (immagini GHCR pull-only)
├── .env.example                      # rivisto
├── .env.azure.example                # NEW
├── .env.dev-claude.example           # NEW
├── Makefile                          # esteso
├── README.md                         # riscritto
└── scripts/                          # esistente, diventa thin wrapper su infra/scripts
```

## 5. Livello MCP server — dettaglio tool nuovi

### 5.1 Modulo `geojson_builder.py`

Pure Python, no I/O, no LLM:

- `parse_geojson(raw: str | dict) -> dict`: parse + validate; accetta Feature, FeatureCollection,
  Geometry; wrappa come FeatureCollection; strippa feature invalide silently con log
- `osm_results_to_geojson(kind, payload) -> dict`: converte output dei tool esistenti
  (find_nearby, get_route, geocode) in FeatureCollection
- `compute_bounds(geojson) -> tuple[float,float,float,float]`: bbox `(s, w, n, e)`, default Italia se vuoto
- `assign_layer_styles(n: int) -> list[dict]`: palette di 12 colori distinti, cicla se n > 12

CRS non-WGS84 → `ValueError("non-WGS84 CRS not supported, please reproject to EPSG:4326")`.
GeoJSON RFC 7946 impone WGS84; la reproiezione automatica è **scope futuro** (richiederebbe
`pyproj` ~50 MB di dipendenze).

### 5.2 Modulo `html_renderer.py`

```python
@dataclass
class MapLayer:
    name: str
    geojson: dict
    style: dict | None  # {color, weight, fillOpacity}; defaults se None

def render_map(
    layers: list[MapLayer],
    title: str | None = None,
    center: tuple[float, float] | None = None,
    zoom: int | None = None,
    attribution: str | None = None,
) -> str: ...
```

Output: stringa `<!doctype html>...</html>` self-contained con Leaflet 1.9.4 da CDN unpkg, OSM
raster tile, layer toggle, popup con properties (prime 8 chiavi, value troncato a 80 char,
escape gestito da `bindPopup`), legend con colori e nomi layer, auto-fit ai bounds.
Dimensione tipica: 5–50 KB inclusi GeoJSON inline.

### 5.3 I 3 nuovi tool MCP

Tutti registrati in `tools.py` accanto agli 8 esistenti. Tutti ritornano content multi-block:
`[TextContent(summary), EmbeddedResource(text/html)]`.

**`render_geojson_map(geojson, title?, center?, zoom?)`**: rendering single-layer.

**`render_multi_layer_map(layers: list[{name, geojson, style?}], title?, center?, zoom?)`**:
multi-layer con toggle UI e legend, palette auto-assegnata se `style` omesso.

**`compose_map_from_resources(text, resources, title?, center?, zoom?)`** ⭐:
- Accetta il contract `{text, resources: [{name, url, format, content}]}` di ckan-mcp-agent
- Filtra `format == "GEOJSON"` (case-insensitive) con `content` non vuoto
- Valida ogni geojson via `parse_geojson`
- Costruisce layers, assegna palette, chiama `render_map`
- Resource non-GeoJSON sono incluse nello `skipped[]` del summary text
- **Stateless, deterministico, no LLM**

### 5.4 Estensione `config.py`

```python
MAP_TILE_URL: str = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
MAP_ATTRIBUTION: str = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
MAP_DEFAULT_ZOOM: int = 13
MAP_MAX_FEATURES_PER_LAYER: int = 5000   # safety cap
```

Override via env per tile self-hosted o attribution custom.

### 5.5 Robustezza

- **Cap features per layer**: oltre `MAP_MAX_FEATURES_PER_LAYER=5000`, droppa eccedenza con
  warning nello `summary` (evita HTML enormi che bloccano il browser)
- **Sanitizzazione properties popup**: prime 8 chiavi, value `String(v).slice(0,80)`, escape
  Leaflet automatico via `bindPopup`
- **Rifiuto CRS non-WGS84**: errore esplicito anziché reproiezione silente
- **Limite `content` resource**: valori >1 MB vengono troncati nel parser geojson con warning

## 6. Livello agent — dettaglio

### 6.1 Dipendenze (`pyproject.toml`)

```
agent-framework[all] >=0.1.0
agent-framework-ollama
agent-framework-anthropic
agent-framework-foundry
azure-identity
fastapi >=0.110
uvicorn[standard] >=0.27
pydantic-settings >=2.0
httpx >=0.27
mcp[ws] --pre              # per agent.as_mcp_server()
python-multipart           # per multipart upload
geojson >=3.0              # validazione lato agent
```

### 6.2 `config.py` — Settings pydantic

Campi chiave:
- `llm_provider: Literal["ollama","claude","azure_foundry"] = "ollama"`
- `ollama_*`, `anthropic_api_key`, `claude_model`, `azure_ai_*` per i 3 provider
- `mcp_server_url`, `mcp_server_name`, `mcp_approval_mode: Literal["never_require","always_require"] = "never_require"`
- `api_host:0.0.0.0`, `api_port:8002`
- `mcp_surface_enabled:bool=true`, `mcp_surface_host:0.0.0.0`, `mcp_surface_port:8003`, `mcp_surface_path:/mcp`

### 6.3 `factory.py` — provider switch

Clone strutturale di `ckan-mcp-agent/src/ckan_agent/factory.py` con due differenze:

1. Niente regional router (l'OSM ha un solo backend, non ha senso per il dominio)
2. `AGENT_INSTRUCTIONS` adattate al dominio OSM, con istruzione esplicita: quando l'utente
   chiede una mappa o riceve GeoJSON strutturato, chiamare `render_geojson_map` /
   `render_multi_layer_map` / `compose_map_from_resources`

`AgentSession` async context manager che entra `MCPStreamableHTTPTool(osm-mcp)` + `Agent(...)`.

### 6.4 `api.py` — 4 endpoint REST

**`POST /chat`**: query NL pura. Agent decide quali tool MCP chiamare. Reuse del marker
`<!--RESOURCES_JSON-->` di ckan-mcp-agent per estrarre `resources[]` dal raw output LLM.
Stesso pattern, stesso parser, stesso shape di risposta.

**`POST /chat/stream`**: SSE, mirror del pattern ckan-mcp-agent.

**`POST /chat/with-geojson`**: multipart `message` (Form) + `geojson_file` (UploadFile).
Server legge file, prepende al prompt come blocco `ATTACHED GEOJSON (file:...): ```geojson
{content}```\n\nIf the user asks for a map, call render_geojson_map with this GeoJSON.`
Cap a 50 KB per il prompt (file più grandi: tronca con avviso). L'agent riceve il geojson nel
contesto e può chiamarlo come argomento del tool.

**`POST /compose-map`** ⭐: `ComposeMapRequest = {text, resources, title?, center?, zoom?}`.
Bypassa l'LLM: chiama via httpx il MCP server direttamente (`tools/call` per
`compose_map_from_resources`). Converte il content multi-block MCP nel `ChatResponse` shape
(text del summary + resource HTML). **Deterministico, instant, free**.

### 6.5 `mcp_surface.py` — esposizione come MCP

Wraps `agent.as_mcp_server()` su Streamable HTTP transport :8003 path `/mcp` usando
`StreamableHTTPSessionManager`. Il `main.py` avvia FastAPI :8002 (uvicorn) **e** la MCP
surface :8003 in parallelo come task asyncio nello stesso processo, condividendo l'unica
istanza `AgentSession`.

### 6.6 Riepilogo decisioni

| Decisione | Scelta | Motivazione |
|---|---|---|
| Chat surface | FastAPI :8002 | parità con ckan-mcp-agent |
| MCP surface | porta separata :8003 path `/mcp` | evita ambiguità di routing con `/chat` su :8002 |
| Provider switch | factory.py 1:1 con ckan | manutenzione costante |
| Routing logico | nessuno (no regional router) | OSM ha un solo backend |
| Parser response | stesso `<!--RESOURCES_JSON-->` di ckan | composizione ckan→osm seamless |
| `/compose-map` | bypassa LLM (chiama MCP raw via httpx) | path deterministico zero-cost |
| `/chat/with-geojson` | multipart + prompt enrichment | UX naturale per file utente |

## 7. Docker e Ollama image

### 7.1 `docker-compose.yml`

Mirror di `mcp-ckan/docker-compose.yml` con:
- Profili `cpu`/`gpu` per Ollama (anchor `x-ollama-base`, deploy nvidia per gpu)
- `osm-mcp:8080` esposto, `osm-mcp-agent:8002` (REST) + `:8003` (MCP) esposti
- Tutte le env var del provider switch via variabili di compose con default
- `depends_on` con `condition: service_healthy` opzionale per ollama (`required: false`
  permette di avviare l'agent anche se ollama non è in stack quando provider=claude/foundry)
- `restart: unless-stopped`, healthcheck su `/health` per agent e mcp

### 7.2 `docker-compose.ghcr.yml`

Variante "no build, pull-only" per quick-start senza build locale. Punta a
`ghcr.io/agent-engineering-studio/osm-mcp:latest` e `osm-mcp-agent:latest`.

### 7.3 `infra/ollama/`

```
Dockerfile          # FROM ollama/ollama:latest + COPY Modelfile /Modelfile + entrypoint
Modelfile           # FROM qwen2.5:7b-instruct + PARAMETER num_ctx 16384 + temperature 0.2
entrypoint.sh       # ollama serve & + ollama create qwen2.5:16k -f /Modelfile + wait
```

Builda un'immagine ~8 GB con il custom model `qwen2.5:16k` baked. Pubblicata su
`ghcr.io/agent-engineering-studio/osm-mcp-ollama:latest` dal workflow `publish-ollama.yml`.

### 7.4 `Dockerfile` agent

Multi-stage Python 3.12-slim. Espone 8002+8003. Healthcheck `/health`. Entry `python -m
osm_agent.main`.

### 7.5 Makefile

Target principali:
- `mcp-install`, `mcp-test`, `mcp-run`, `mcp-inspector`
- `agent-install`, `agent-test`, `agent-run`
- `build`, `up`, `up-cpu`, `up-gpu`, `up-ghcr`, `down`, `logs`
- `build-ollama`, `refresh-ollama`, `pull-models`
- `smoke` (smoke test integrato via newman)
- `deploy-azure`, `destroy-azure`

### 7.6 File `.env`

- `.env.example`: default per local dev con Ollama
- `.env.dev-claude.example`: provider=claude, ANTHROPIC_API_KEY placeholder, no Ollama
- `.env.azure.example`: provider=azure_foundry + variabili Azure deploy (RG, location, ACR)

## 8. Test

### 8.1 `requests/agent-chat.http` — 9 sezioni

1. Health & smoke
2. Geocoding semplice
3. POI nelle vicinanze
4. Routing multimodale
5. Stream SSE
6. Upload GeoJSON utente (multipart)
7. ⭐ Composizione ckan→osm deterministica (`/compose-map`)
8. MCP surface dell'agent (per coordinator MCP esterni)
9. MCP server raw `osm-mcp` (per debugging tool senza LLM)

Variables: `@host`, `@mcp_host`, `@osm_mcp_host`.

### 8.2 Postman

`requests/postman/osm-mcp-agent.postman_collection.json` — 8 folder (1:1 con sezioni .http,
sezione 9 esclusa perché MCP raw non è un caso d'uso applicativo). Tests script minimali:
status 200, presenza `resources[]` per i map endpoints. Runner `test-agent-chat.sh`/`.ps1`
via newman.

### 8.3 Pytest

**`osm-mcp/tests/`**:
- `test_tools.py` (esistente)
- `test_geojson_builder.py`: parse Feature/FeatureCollection/Geometry, malformed, bbox, palette
- `test_html_renderer.py`: output contiene `<!doctype>`, layer names, parsabile con BeautifulSoup
- `test_compose_resources.py`: feed payload ckan-style, assert layer_count, skipped non-GeoJSON

**`osm-mcp-agent/tests/`**:
- `test_factory.py`: provider switch con clienti mockati
- `test_contracts.py`: roundtrip Resource ↔ dict con example ckan
- `test_compose_endpoint.py`: POST /compose-map → MCP call → ChatResponse
- `test_chat_with_geojson.py`: multipart upload → prompt enrichment

**Fixture condivisa**: `tests/fixtures/ckan_response.json` — vera response ckan-mcp-agent
(2 GeoJSON resources reali ~10 KB + 1 PDF skipped). Usata da test pytest e da .http sezione 7.

### 8.4 Smoke test integrato — `make smoke`

`make up-cpu` → wait `/health` → `requests/postman/test-agent-chat.sh` → `last-run.json`.
Usato in CI da `ci.yml`.

## 9. CI/CD — 4 workflow GitHub Actions

### 9.1 `ci.yml`

Tre job paralleli su PR/push main:
- `python-mcp-server`: ruff + mypy + pytest su `osm-mcp/`
- `python-agent`: ruff + pytest su `osm-mcp-agent/`
- `smoke-integration` (depends on both): build images, up stack, test `/compose-map`
  (deterministico, no LLM richiesto in CI), tear down

### 9.2 `docker-publish.yml`

Multi-arch (`linux/amd64`, `linux/arm64`) build via Buildx. Matrix per `osm-mcp` e
`osm-mcp-agent`. Tag automatici: `latest` (main), `pr-N`, semver per tag `v*`, sha-short.
Push su `ghcr.io/agent-engineering-studio/{service}`.

### 9.3 `publish-ollama.yml`

Trigger ristretto: solo modifica di `infra/ollama/**` o `workflow_dispatch`. Builda l'immagine
+ esegue `ollama pull` + `ollama create` dentro un container intermedio, poi `docker commit`
+ push. Timeout 90 min (immagine ~8 GB).

### 9.4 `deploy-azure.yml`

Trigger: `workflow_dispatch` (con choice dev/prod) e tag `v*` (auto-deploy prod).
Auth: **OIDC federation** (no client secret in repo). Usa `azure/login@v2` + `azure/arm-deploy@v2`
contro `infra/bicep/main.bicep`. Step finale: smoke `curl https://<fqdn>/health`.
Secrets: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `ANTHROPIC_API_KEY`.

## 10. Bicep IaC

### 10.1 `infra/bicep/main.bicep`

Orchestratore che istanzia:
- `Log Analytics` workspace
- User-assigned Managed Identity (per autenticazione a Azure AI Foundry quando provider=foundry)
- Container Apps Environment (CAE) collegato al workspace
- `osm-mcp` Container App: ingress **interno** (`external: false`), port 8080, no managed identity
- `osm-mcp-agent` Container App: ingress **esterno**, port 8002, con `additionalPortMappings`
  per esporre :8003 (MCP surface), monta managed identity, secrets per `anthropic-key`

Output: `agentFqdn`, `mcpInternalFqdn`, `managedIdentityClientId`.

### 10.2 Security model

- `osm-mcp` non è raggiungibile da internet — solo l'agent può chiamarlo (network boundary chiara)
- Agent è il single entrypoint: REST :8002 + MCP :8003 esposti, autenticazione gestita
  application-level (header API key opzionale, da scope futuro per MVP)
- `DefaultAzureCredential` via managed identity per Foundry; nessun client secret in env var
- `ANTHROPIC_API_KEY` montato come Container App secret (encrypted at rest, mai in plaintext logs)

### 10.3 Scripts

- `infra/scripts/deploy.sh` / `.ps1`: wrapper `az deployment group create` con default sensibili
- `infra/scripts/destroy.sh` / `.ps1`: prompt confirm + `az group delete --no-wait`
- `infra/scripts/setup-github-oidc.sh`: crea AAD app + federated credentials per il repo,
  role assignment Contributor su `rg-osm-mcp-*`

## 11. README — sezioni

Il README riscritto (~30 KB target) include:

1. Quick start (3 comandi)
2. Architecture diagram (sezione 3.1)
3. Provider switching tabella + esempi `.env.dev-claude.example`
4. OSM tools reference: 8 esistenti + 3 nuovi con esempi payload
5. **Composing with ckan-mcp-agent** ⭐: pattern coordinator + esempio .http end-to-end
6. **MCP surface (agent-as-tool)**: snippet `claude_desktop_config.json` per collegare Claude Desktop
7. Testing: .http, Postman/newman, pytest, `make smoke`
8. Docker & GHCR images: tabella delle 3 immagini pubblicate
9. Deploy on Azure: prerequisiti, OIDC setup, `make deploy-azure`, FQDN output
10. Roadmap & non-goals: cosa NON fa MVP e perché

## 12. Non-goals (out of MVP scope)

- Reproiezione automatica CRS non-WGS84 (richiederebbe `pyproj` ~50 MB di dipendenze)
- Export PNG/SVG delle mappe (richiederebbe headless browser tipo Playwright)
- Orchestration MAF (Sequential/Magentic) — riservata a future use case multi-step
- MapLibre GL + vector tile (deciso: Leaflet+OSM raster, no dipendenze di terzi)
- Persistent session memory (Redis/DB) — l'agent è stateless tra request, ogni `/chat` è una
  conversazione separata; thread management pattern di ckan-mcp-agent applicato as-is
- Authentication / authorization application-level — l'agent è behind Container Apps ingress
  (HTTPS) ma non valida API key/JWT; demandato a reverse proxy o Azure Front Door in produzione
- Rate limiting interno — gli upstream OSM (Nominatim/Overpass) hanno il proprio; per agent
  layer nessun cap MVP

## 13. Migration & rollout

### 13.1 Branch strategy

- `main` resta funzionante con il .NET attuale fino al merge della PR finale
- Nuovo branch `feature/python-agent-parity` ospita tutto il lavoro
- PR singola, multi-commit, ordinata per sezioni del piano implementativo (sez. 14)

### 13.2 Rimozione del .NET agent

La cartella `osm-agent/` viene **rimossa nello stesso PR** che introduce `osm-mcp-agent/`. Lo
storico git preserva tutto (commit history visibile). Ragioni per non tenere entrambi:
- Dual maintenance burden (zero benefit dato che la decisione è A=Python only)
- Confusion sui port-mappings (8090 .NET vs 8002 Python)
- Riferimenti incrociati nel docker-compose / Makefile / README diventerebbero ambigui

### 13.3 Ordine di lavoro nel PR

Il piano implementativo dettagliato è demandato a `writing-plans` skill. A grandi linee i
gruppi di lavoro sono:

1. **Foundation**: scaffold `osm-mcp-agent/`, `pyproject.toml`, config, contracts, factory
2. **MCP server extension**: `geojson_builder.py`, `html_renderer.py`, template, 3 tool nuovi, test
3. **Agent surface**: `api.py` (4 endpoint), `mcp_surface.py`, `main.py`, test
4. **Infrastructure**: Bicep moduli, scripts, .env files
5. **CI/CD**: 4 workflow
6. **Docker compose**: riscrittura + Ollama image baked
7. **Test artifacts**: `requests/.http`, Postman collection, scripts newman, fixture
8. **README + Makefile**: refresh con i nuovi target
9. **Cleanup**: rimozione `osm-agent/` (.NET)

Ogni gruppo è un commit separato per facilitare review e bisect.

## 14. Acceptance criteria

Considerato "done" quando:

- [ ] `make up-cpu` porta su l'intero stack (osm-mcp + osm-mcp-agent + ollama-cpu) con
      `LLM_PROVIDER=ollama` e tutti i `/health` rispondono ok
- [ ] `make smoke` passa: tutti gli step Postman ritornano 200, `/compose-map` produce
      un resource HTML valido
- [ ] Test pytest 100% green: `make mcp-test && make agent-test`
- [ ] Switch provider funziona end-to-end: stesso `make smoke` con `.env.dev-claude` produce
      stessa response shape (testato manualmente con vera ANTHROPIC_API_KEY)
- [ ] CI green su PR (3 job paralleli + smoke-integration)
- [ ] `agent-chat.http` sezione 7 (composizione ckan→osm con fixture) ritorna HTML map valido
      che si apre nel browser con tutti i layer visibili
- [ ] MCP surface su :8003 è raggiungibile: `curl POST :8003/mcp tools/list` ritorna
      l'agent come tool "OsmAgent"
- [ ] Bicep deploy in `dev` riuscito, `agentFqdn` raggiungibile, `/health` 200
- [ ] README aggiornato con quick-start, esempi, deploy guide
- [ ] `osm-agent/` (.NET) rimossa, no riferimenti residui in docker-compose/Makefile/README/scripts
