# mcp-osm

**MCP server per OpenStreetMap + agente Microsoft Agent Framework (C# GA 1.2.0) con Ollama**, impacchettato in Docker Compose e deployabile su Azure Container Apps via GitHub Actions / script bash / script PowerShell.

Ispirato a [`jagan-shanmugam/open-streetmap-mcp`](https://github.com/jagan-shanmugam/open-streetmap-mcp) (versione Python originale dei tool OSM) e allineato ai pattern del progetto interno [`agent-engineering-studio/knowledge-graph`](../knowledge-graph) (stessi profili Compose, entrypoint Ollama auto-pull, layout multi-servizio).

Documentazione ufficiale Microsoft di riferimento:

- **Using MCP Tools (C#)** – <https://learn.microsoft.com/en-us/agent-framework/agents/tools/local-mcp-tools?pivots=programming-language-csharp>
- **Microsoft Agent Framework** – <https://github.com/microsoft/agent-framework>
- **MCP C# SDK** – <https://github.com/modelcontextprotocol/csharp-sdk>

---

## Indice

1. [Architettura](#architettura)
2. [MCP tools esposti](#mcp-tools-esposti)
3. [Quick start (Docker)](#quick-start-docker)
4. [Quick start (locale senza Docker)](#quick-start-locale-senza-docker)
5. [Come funziona l'integrazione MS Agent Framework](#come-funziona-lintegrazione-ms-agent-framework)
6. [API HTTP dell'agent](#api-http-dellagent)
7. [Configurazione (`.env`)](#configurazione-env)
8. [Deploy su Azure](#deploy-su-azure)
9. [CI / GitHub Actions](#ci--github-actions)
10. [Uso del solo MCP server (Claude Desktop / Cursor / VS Code)](#uso-del-solo-mcp-server)
11. [Testing](#testing)
12. [Struttura del progetto](#struttura-del-progetto)
13. [Versioni dei pacchetti](#versioni-dei-pacchetti)
14. [Troubleshooting](#troubleshooting)
15. [Licenza e attribuzione dati](#licenza-e-attribuzione-dati)

---

## Architettura

```
                   ┌─────────────────────┐
   user / API  ───▶│   osm-agent (C#)    │  Microsoft.Agents.AI 1.2.0
                   │  ASP.NET Core :8090 │  + ModelContextProtocol 1.2.0
                   └─────────┬───────────┘  + Microsoft.Extensions.AI 10.5
                             │ OpenAI-compat HTTP         ┌─────────────┐
                             ├──────────────────────────▶│   Ollama    │
                             │   /v1/chat/completions     │  :11434     │
                             │                            └─────────────┘
                             │ MCP over HTTP/SSE
                             ▼
                   ┌─────────────────────┐   ┌─► Nominatim (geocoding)
                   │   osm-mcp (Python)  │───┼─► Overpass  (POI queries)
                   │   FastMCP    :8080  │   └─► OSRM      (routing)
                   └─────────────────────┘
```

### Sequence — una richiesta utente

```
user → POST /chat  ──▶  osm-agent
                            │  1. Recupera o crea un AgentSession
                            │  2. Invia il prompt + tool MCP al LLM Ollama (OpenAI-compat)
                            │  3. LLM decide di invocare find_nearby_places(...)
                            ├───────── MCP CallToolAsync ──▶ osm-mcp
                            │                                    │
                            │                                    ├──▶ Overpass API
                            │                                    │
                            │ ◀─── JSON results ─────────────────┘
                            │  4. Ritorna i risultati al LLM
                            │  5. LLM compone la risposta finale
                            ▼
                        AgentResponse.Text
```

### Servizi

| Servizio     | Linguaggio / framework       | Porta | Ruolo                                     |
|--------------|------------------------------|-------|-------------------------------------------|
| `osm-mcp`    | Python 3.11 + FastMCP        | 8080  | MCP server (SSE) con i tool OSM           |
| `osm-agent`  | .NET 9 / C# (MS Agent 1.2.0) | 8090  | Agent + REST API (`/chat`, `/tools`, ...) |
| `ollama-cpu` / `ollama-gpu` | Ollama | 11434 | Runtime LLM locale (profili opzionali)    |

---

## MCP tools esposti

Tutti i tool restituiscono una stringa JSON. Il server è implementato con `FastMCP` (SDK ufficiale `mcp[cli]`).

| Tool                        | Parametri chiave                                                                           |
|-----------------------------|--------------------------------------------------------------------------------------------|
| `geocode_address`           | `address: str`, `limit: int = 5`                                                           |
| `reverse_geocode`           | `lat: float`, `lon: float`, `zoom: int = 18`                                               |
| `find_nearby_places`        | `lat`, `lon`, `radius_m = 1000`, `category = "restaurant"`, `limit = 20`                   |
| `search_category_in_bbox`   | `south`, `west`, `north`, `east`, `category`, `limit = 50`                                 |
| `get_route`                 | `start_lat/lon`, `end_lat/lon`, `profile ∈ {driving, walking, cycling}`, `steps = true`    |
| `suggest_meeting_point`     | `points: list[[lat, lon]]`, `profile` — ottimizza il **max travel time** dei partecipanti |
| `explore_area`              | `lat`, `lon`, `radius_m = 800` — digest di categorie POI nell'intorno                      |
| `find_ev_charging_stations` | `lat`, `lon`, `radius_m = 5000`, `limit = 30` — con connettori / kW / operator             |
| `analyze_commute`           | `home_lat/lon`, `work_lat/lon` — confronto tempi driving / walking / cycling               |
| `osm_health`                | — ping di Nominatim, Overpass, OSRM                                                        |

**Categorie** supportate da `find_nearby_places` / `search_category_in_bbox`:

```
restaurant, cafe, bar, hotel, hospital, pharmacy, school, university,
supermarket, parking, fuel, ev_charging, atm, bank, park, museum,
attraction, bus_station, train_station
```

— oppure qualunque valore `amenity=*` di OSM come stringa grezza (es. `"library"`, `"cinema"`).

---

## Quick start (Docker)

### Prerequisiti

- Docker Desktop (Windows/macOS) o Docker Engine (Linux) con BuildKit
- Per la profile `gpu`: NVIDIA Container Toolkit
- Per la profile default (senza container Ollama): Ollama installato sull'host

### Avvio

```bash
cp .env.example .env
# modifica .env se vuoi cambiare modello LLM, endpoint OSM custom, ecc.

# A) Full stack, Ollama già attivo sull'host → http://host.docker.internal:11434
make up

# B) Full stack + Ollama CPU-only in container (niente GPU richiesta)
make up-cpu

# C) Full stack + Ollama su GPU NVIDIA in container
make up-gpu
```

### Verifica

```bash
# Health checks
curl http://localhost:8090/health
curl http://localhost:8080/   # il server MCP non ha root HTTP; verifica con:
docker compose logs osm-mcp | head -20

# Elenco tool disponibili sull'agent
curl http://localhost:8090/tools | jq

# Chat multi-turno
curl -X POST http://localhost:8090/chat \
  -H 'Content-Type: application/json' \
  -d '{
        "message": "Trova i 5 ristoranti più vicini a Piazza Duomo, Milano entro 500m",
        "sessionId": "s1"
      }' | jq

curl -X POST http://localhost:8090/chat \
  -H 'Content-Type: application/json' \
  -d '{
        "message": "Ok, come arrivo a piedi al primo dalla stazione Centrale?",
        "sessionId": "s1"
      }' | jq
```

### Streaming (SSE)

```bash
curl -N -X POST http://localhost:8090/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"message":"Pianifica un giro di 3 musei nel centro di Firenze","sessionId":"tour1"}'
```

### Stop

```bash
make down
```

---

## Quick start (locale senza Docker)

### MCP server (SSE su :8080)

```bash
make mcp-install   # pip install -e ".[dev]"
make mcp-run-sse   # MCP_TRANSPORT=sse python -m osm_mcp.server
```

Oppure in modalità **stdio** per Claude Desktop / Claude Code / Cursor:

```bash
make mcp-run       # MCP_TRANSPORT=stdio python -m osm_mcp.server
```

### .NET agent

Richiede:

- Ollama in ascolto su `:11434` (o `OLLAMA_BASE_URL` puntato altrove)
- osm-mcp in SSE su `:8080` (o `MCP_SERVER_URL` custom)

```bash
make agent-build   # dotnet build -c Release
make agent-run     # dotnet run
```

### MCP Inspector

Per debug interattivo del server MCP (browser UI):

```bash
make mcp-inspector
```

---

## Come funziona l'integrazione MS Agent Framework

Il file [`osm-agent/Program.cs`](osm-agent/Program.cs) segue il pattern della doc ufficiale Microsoft, **adattato alle API GA 1.2.0** (che hanno rinominato alcuni tipi rispetto alle preview che girano ancora in rete).

### Pipeline

1. **Crea l'`McpClient`** con `McpClient.CreateAsync(...)` + `HttpClientTransport` in modalità SSE:

   ```csharp
   var mcpClient = await McpClient.CreateAsync(
       new HttpClientTransport(new HttpClientTransportOptions
       {
           Name = "osm-mcp",
           Endpoint = new Uri(mcpUrl),            // es. http://osm-mcp:8080/sse
           TransportMode = HttpTransportMode.Sse,  // o StreamableHttp
       }));
   ```

2. **Recupera i tool** con `ListToolsAsync()`:

   ```csharp
   var mcpTools = await mcpClient.ListToolsAsync();   // IReadOnlyList<McpClientTool>
   ```

3. **Costruisce un `IChatClient` su Ollama** sfruttando l'endpoint OpenAI-compatibile `${OLLAMA_BASE_URL}/v1`:

   ```csharp
   var openAiClient = new OpenAIClient(
       new ApiKeyCredential("ollama"),
       new OpenAIClientOptions { Endpoint = new Uri($"{ollamaBaseUrl}/v1") });
   IChatClient chatClient = openAiClient.GetChatClient(ollamaModel).AsIChatClient();
   ```

4. **Trasforma il chat client in un `AIAgent`** passando i tool MCP:

   ```csharp
   AIAgent agent = chatClient.AsAIAgent(
       instructions: instructions,
       name: "OsmAgent",
       tools: mcpTools.Cast<AITool>().ToList());
   ```

5. **Gestisce sessioni multi-turno** con `AgentSession` (novità GA — nella preview era `AgentThread`):

   ```csharp
   var session = await agent.CreateSessionAsync(cancellationToken);
   AgentResponse result = await agent.RunAsync(userMessage, session, cancellationToken: ct);
   string answer = result.Text;
   ```

6. **Streaming** via `RunStreamingAsync` → `IAsyncEnumerable<AgentResponseUpdate>`, esposto come HTTP SSE.

> ⚠️ **Cosa è cambiato vs. la doc MS**: alla data del 23/04/2026 i pacchetti NuGet sono **GA** (1.2.0). Alcuni esempi online sono ancora su preview e usano nomi diversi:
>
> | Preview (2025)                         | GA 1.2.0 (usata qui)                           |
> |----------------------------------------|------------------------------------------------|
> | `McpClientFactory.CreateAsync`         | `McpClient.CreateAsync`                        |
> | `SseClientTransport`                   | `HttpClientTransport` + `HttpTransportMode.Sse`|
> | `AgentThread` / `agent.GetNewThread()` | `AgentSession` / `agent.CreateSessionAsync()`  |
> | `chatClient.CreateAIAgent(...)`        | `chatClient.AsAIAgent(instructions, name, …)`  |
> | `AIAgentResponse` / `.ToString()`      | `AgentResponse.Text`                           |

---

## API HTTP dell'agent

Base URL locale: `http://localhost:8090`

| Metodo | Path            | Body                                       | Descrizione                                          |
|--------|-----------------|--------------------------------------------|------------------------------------------------------|
| GET    | `/health`       | —                                          | `{ status, model, mcp }`                             |
| GET    | `/tools`        | —                                          | Lista dei tool MCP caricati (name + description)     |
| POST   | `/chat`         | `{ message, sessionId? }`                  | Risposta singola, `{ answer, sessionId }`            |
| POST   | `/chat/stream`  | `{ message, sessionId? }`                  | Stream SSE di `AgentResponseUpdate` (token-by-token) |

Il `sessionId` è opzionale: se omesso viene usato `"default"`. Ogni session corrisponde a un `AgentSession` in memoria che conserva la cronologia conversazionale. Per persistenza fra restart, usa `agent.SerializeSessionAsync(session, ...)` (vedi il docstring del SDK) e uno storage esterno.

---

## Configurazione (`.env`)

| Variabile                    | Default                                      | Note                                                              |
|------------------------------|----------------------------------------------|-------------------------------------------------------------------|
| `OLLAMA_BASE_URL`            | `http://host.docker.internal:11434`          | `http://ollama-cpu:11434` con profilo `cpu`, `ollama-gpu` con gpu |
| `OLLAMA_LLM_MODEL`           | `qwen2.5:7b`                                 | Qualunque modello Ollama con function-calling                     |
| `OLLAMA_MODELS`              | `qwen2.5:7b`                                 | Modelli auto-pullati all'avvio del container Ollama               |
| `MCP_SERVER_URL`             | `http://osm-mcp:8080/sse`                    | Endpoint SSE del server MCP                                       |
| `NOMINATIM_URL`              | `https://nominatim.openstreetmap.org`        | Override per istanze self-hosted                                  |
| `OVERPASS_URL`               | `https://overpass-api.de/api/interpreter`    | Idem                                                              |
| `OSRM_URL`                   | `https://router.project-osrm.org`            | Idem                                                              |
| `OSM_USER_AGENT`             | `osm-mcp/0.1 (agent-engineering-studio)`     | Richiesto dalla usage policy Nominatim                            |
| `OSM_CONTACT_EMAIL`          | —                                            | Consigliato per traffico non-trivial                              |
| `ASPNETCORE_ENVIRONMENT`     | `Production`                                 | `Development` per logging debug                                   |
| `AZURE_*`                    | — (vedi `.env.example`)                      | Usati dagli script di deploy                                      |

> ⚠️ **Policy Nominatim / Overpass pubbliche**: limite di 1 req/s per IP e User-Agent identificativo obbligatorio. Per produzione **self-hosta** Nominatim/Overpass/OSRM e punta le tre URL ai tuoi endpoint — basta cambiare `.env`.

### Scelta modello Ollama

Il function-calling richiede modelli che supportano *tool use*. Scelte consigliate:

| Modello Ollama      | RAM ~ | Note                                                          |
|---------------------|-------|---------------------------------------------------------------|
| `qwen2.5:7b`        | ~8 GB | ✅ ottimo function-calling, default                            |
| `qwen2.5:14b`       | ~16 GB| ✅ più accurato ma più lento                                  |
| `llama3.1:8b`       | ~8 GB | ✅ function-calling supportato                                |
| `mistral-nemo`      | ~8 GB | ✅ tool use, multilingua                                      |
| `gemma2:9b`         | ~9 GB | ❌ sconsigliato (function-calling poco affidabile)            |

---

## Deploy su Azure

Gli script deployano 2 Container Apps nel medesimo **Container Apps Environment**:

- **`osm-mcp`** — ingress `internal` (raggiungibile solo dall'altro container)
- **`osm-agent`** — ingress `external` (HTTPS pubblico) con `MCP_SERVER_URL` = `http://<mcp-internal-fqdn>/sse`

L'immagine dell'agent viene automaticamente configurata per raggiungere Ollama via `OLLAMA_BASE_URL` (che **deve** puntare a un Ollama gestito altrove — vedi nota sotto).

### Script bash (Linux/macOS/WSL)

```bash
cp .env.example .env
# imposta almeno AZURE_ACR_NAME e OLLAMA_BASE_URL
./scripts/deploy-azure.sh
```

### Script PowerShell (Windows)

```powershell
Copy-Item .env.example .env
# imposta almeno AZURE_ACR_NAME e OLLAMA_BASE_URL
pwsh ./scripts/deploy-azure.ps1
```

### Cosa fanno gli script

1. `az login` + `az account set --subscription $AZURE_SUBSCRIPTION_ID`
2. Installano/aggiornano l'extension `containerapp` e registrano i provider `Microsoft.App` + `Microsoft.OperationalInsights`
3. Creano (idempotente) resource group + ACR + Container Apps Environment
4. Build + push delle 2 immagini su ACR (skippabile con `--skip-build` / `-SkipBuild`)
5. `az containerapp create/update` per entrambi i container, con env vars coerenti
6. Stampano l'URL pubblico dell'agent + le endpoint di test

### Flag utili

| Flag (bash)       | Flag (PS)      | Effetto                                             |
|-------------------|----------------|-----------------------------------------------------|
| `--skip-build`    | `-SkipBuild`   | Ridesplega senza rebuildare (usa immagini esistenti)|
| `--skip-login`    | `-SkipLogin`   | Nessun `az login` (CI con OIDC già autenticato)     |

### ⚠️ Ollama in produzione

Azure Container Apps **non** è ideale per servire modelli LLM (no GPU, limiti di memoria). Opzioni consigliate:

- VM con GPU (Standard_NV / Standard_NC) con `ollama serve` esposto in una VNet privata, puntata da `OLLAMA_BASE_URL`
- Endpoint gestito compatibile OpenAI: **vLLM su AKS**, **Together AI**, **Groq**, **Azure OpenAI** — basta cambiare `OLLAMA_LLM_MODEL` e configurare la credenziale OpenAI
- Se vuoi mantenere l'endpoint "Ollama-compatibile" su Azure, usa [**llama-cpp-python** su Container Apps GPU (preview)](https://learn.microsoft.com/azure/container-apps/gpu-serverless-overview)

---

## CI / GitHub Actions

### `ci.yml`

Triggerato su ogni push / PR su `main`:

1. **Python MCP** → `ruff check` + `pytest -v`
2. **.NET Agent** → `dotnet restore` + `dotnet build -c Release`
3. **Docker smoke** → build delle 2 immagini con cache GHA (no push)

### `deploy-azure.yml`

Triggerato da:

- push di un tag `v*.*.*`
- `workflow_dispatch` (manuale) con input opzionale `image_tag`

Flusso:

1. Login OIDC ad Azure (nessuna service principal secret)
2. `az acr login`
3. Build + push immagini taggate (SHA corto o tag della release)
4. `./scripts/deploy-azure.sh --skip-build --skip-login`

**Secrets richiesti** (GitHub repo settings → Secrets):

| Nome                     | Descrizione                                               |
|--------------------------|-----------------------------------------------------------|
| `AZURE_CLIENT_ID`        | App Registration con federated credentials su `repo:*`    |
| `AZURE_TENANT_ID`        | Tenant dell'AAD                                           |
| `AZURE_SUBSCRIPTION_ID`  | Subscription target                                       |
| `OLLAMA_BASE_URL`        | URL raggiungibile dall'agent (VM/endpoint gestito)        |

**Variables richieste** (o override dei default in [scripts/deploy-azure.sh](scripts/deploy-azure.sh)):

| Nome                       | Default          |
|----------------------------|------------------|
| `AZURE_ACR_NAME`           | — (obbligatoria) |
| `AZURE_RESOURCE_GROUP`     | `rg-osm-mcp`     |
| `AZURE_LOCATION`           | `westeurope`     |
| `AZURE_CONTAINER_APP_ENV`  | `cae-osm-mcp`    |
| `AZURE_MCP_APP_NAME`       | `osm-mcp`        |
| `AZURE_AGENT_APP_NAME`     | `osm-agent`      |
| `OLLAMA_LLM_MODEL`         | `qwen2.5:7b`     |

---

## Uso del solo MCP server

L'MCP server è **indipendente** dall'agent C# — può essere consumato da qualsiasi client MCP.

### Claude Desktop / Claude Code

Aggiungi a `~/.config/claude-desktop/claude_desktop_config.json` (macOS/Linux) o `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "osm": {
      "command": "python",
      "args": ["-m", "osm_mcp.server"],
      "env": { "MCP_TRANSPORT": "stdio" }
    }
  }
}
```

### Cursor / VS Code

Per SSE remoto (container esistente):

```json
{
  "mcp": {
    "servers": {
      "osm": { "url": "http://localhost:8080/sse" }
    }
  }
}
```

### Python client (script custom)

```python
from mcp import ClientSession
from mcp.client.sse import sse_client

async with sse_client("http://localhost:8080/sse") as (read, write):
    async with ClientSession(read, write) as s:
        await s.initialize()
        tools = await s.list_tools()
        result = await s.call_tool("geocode_address", {"address": "Milano"})
```

---

## Testing

### Python MCP

```bash
make mcp-test     # pytest su osm-mcp (mock httpx con respx)
```

Output atteso:

```
tests/test_tools.py::test_geocode_address PASSED
tests/test_tools.py::test_find_nearby_places_normalises_elements PASSED
tests/test_tools.py::test_get_route_returns_distance_and_steps PASSED
```

### .NET agent

```bash
make agent-build  # dotnet build -c Release (verifica che i riferimenti NuGet e il codice compilino)
```

### Smoke end-to-end (dopo `make up-cpu`)

```bash
./scripts/smoke.sh   # (da aggiungere se necessario)
# oppure manualmente:
curl -fsS http://localhost:8080/sse >/dev/null || echo "MCP giù"
curl -fsS http://localhost:8090/health | jq
curl -fsS -XPOST http://localhost:8090/chat -H 'Content-Type: application/json' \
  -d '{"message":"Geocodifica Colosseo Roma"}' | jq .answer
```

---

## Struttura del progetto

```
mcp-osm/
├── README.md                       ← questo file
├── Makefile                        ← target di sviluppo + deploy
├── docker-compose.yml              ← profili dev / prod / gpu / cpu
├── .env.example
├── .gitignore
│
├── osm-mcp/                        ← Python MCP server (FastMCP)
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── src/osm_mcp/
│   │   ├── __init__.py
│   │   ├── config.py               ← Pydantic Settings (env/env file)
│   │   ├── osm_client.py           ← httpx wrappers (Nominatim/Overpass/OSRM)
│   │   ├── tools.py                ← business logic → JSON strings
│   │   └── server.py               ← FastMCP entrypoint + registrazione tool
│   └── tests/test_tools.py         ← pytest + respx (no network)
│
├── osm-agent/                      ← .NET 9 / C# ASP.NET Core
│   ├── Dockerfile                  ← multi-stage sdk:9.0 → aspnet:9.0
│   ├── NuGet.config                ← forza feed pubblica nuget.org
│   ├── OsmAgent.csproj             ← packages GA 1.2.0
│   ├── Program.cs                  ← pipeline: MCP client → IChatClient → AIAgent → REST
│   ├── ThreadRegistry.cs           ← mappa sessionId → AgentSession
│   ├── Models/ChatContracts.cs     ← record ChatRequest / ChatResponse
│   ├── appsettings.json
│   └── appsettings.Development.json
│
├── infra/ollama/
│   ├── Dockerfile                  ← ollama/ollama:latest + entrypoint custom
│   └── entrypoint.sh               ← auto-pull dei modelli all'avvio
│
├── scripts/
│   ├── deploy-azure.sh             ← Linux/macOS/WSL
│   └── deploy-azure.ps1            ← Windows (PowerShell 7+)
│
└── .github/workflows/
    ├── ci.yml                      ← lint/test/build su PR
    └── deploy-azure.yml            ← push tag v* → ACR + Container Apps
```

---

## Versioni dei pacchetti

### Python (`osm-mcp/pyproject.toml`)

| Pacchetto            | Versione  | Scopo                                        |
|----------------------|-----------|----------------------------------------------|
| `mcp[cli]`           | `>=1.2.0` | MCP SDK + FastMCP                            |
| `httpx`              | `>=0.27`  | Client HTTP async per Nominatim/Overpass/OSRM|
| `pydantic`           | `>=2.7`   | Modelli                                      |
| `pydantic-settings`  | `>=2.3`   | Settings da env vars                         |
| *dev:* `pytest`, `pytest-asyncio`, `respx`, `ruff` | latest | Test + lint |

### .NET (`osm-agent/OsmAgent.csproj`)

Versioni **pinned** e verificate (GA rilasciate il 21/04/2026):

| Pacchetto NuGet                    | Versione   |
|------------------------------------|------------|
| `Microsoft.Agents.AI`              | `1.2.0`    |
| `Microsoft.Agents.AI.OpenAI`       | `1.2.0`    |
| `Microsoft.Extensions.AI`          | `10.5.0`   |
| `Microsoft.Extensions.AI.OpenAI`   | `10.5.0`   |
| `ModelContextProtocol`             | `1.2.0`    |
| `OpenAI`                           | `2.10.0`   |
| `Microsoft.Extensions.Hosting`     | `10.0.5`   |
| `Microsoft.Extensions.Logging.Console` | `10.0.5` |

Target framework: `net9.0`. Il file [`osm-agent/NuGet.config`](osm-agent/NuGet.config) forza `nuget.org` come sola feed per evitare conflitti con feed aziendali private.

---

## Troubleshooting

### `NU1301: 401 Unauthorized` durante `dotnet restore`

Hai una feed NuGet privata configurata globalmente che risponde 401 per pacchetti pubblici. Soluzione: il progetto già include `osm-agent/NuGet.config` che sovrascrive le sorgenti a solo `nuget.org`. Assicurati che stia girando il restore dentro la directory `osm-agent/`.

### L'agent non chiama i tool (risponde a vuoto)

1. Verifica che `GET /tools` ritorni la lista. Se è vuota, l'MCP client non si è connesso — controlla `MCP_SERVER_URL` e che `osm-mcp` sia healthy.
2. Il modello Ollama deve supportare function-calling. Con `gemma2` non funziona — passa a `qwen2.5:7b` o `llama3.1:8b` (`OLLAMA_LLM_MODEL` in `.env`).
3. Aumenta il contesto del modello: `ollama run qwen2.5:7b` → `/set parameter num_ctx 8192`.

### Nominatim/Overpass ritornano 429 o timeout

Stai eccedendo la usage policy pubblica. Rimedi:

- aggiungi un `OSM_CONTACT_EMAIL` valido in `.env`
- riduci il traffico (serializza le richieste dall'agent)
- per produzione: self-hosta — container ufficiali di [Nominatim](https://github.com/mediagis/nominatim-docker) e [Overpass](https://github.com/wiktorn/Overpass-API), poi imposta `NOMINATIM_URL` / `OVERPASS_URL` ai tuoi endpoint

### `AgentSession` o `HttpClientTransport` non trovati (errori di compilazione)

Stai probabilmente usando versioni preview di `Microsoft.Agents.AI` o `ModelContextProtocol`. Le GA 1.2.0 hanno rinominato:

- `AgentThread` → `AgentSession`
- `SseClientTransport` → `HttpClientTransport` + `HttpTransportMode.Sse`
- `McpClientFactory.CreateAsync` → `McpClient.CreateAsync`
- `CreateAIAgent` → `AsAIAgent`

Verifica le versioni in `OsmAgent.csproj` e fai un `dotnet restore` pulito.

### Ollama non risponde dal container dell'agent

Se Ollama gira sull'host (default):

- su Linux aggiungi `--add-host=host.docker.internal:host-gateway` (già nel compose)
- su macOS/Windows `host.docker.internal` è risolto nativamente
- verifica che Ollama accetti connessioni non-loopback: `OLLAMA_HOST=0.0.0.0 ollama serve`

Se usi il profilo `cpu` / `gpu`, cambia in `.env`:

```
OLLAMA_BASE_URL=http://ollama-cpu:11434   # o ollama-gpu
```

### Il deploy Azure fallisce su "ingress internal"

L'ingress internal richiede il Container Apps Environment con VNet abilitata per alcuni pattern, ma funziona anche con environment pubblico (comunicazione tra app nello stesso environment). Se hai errori, verifica la regione e il quota — `az containerapp env show` mostra la configurazione.

---

## Licenza e attribuzione dati

I dati serviti provengono da **OpenStreetMap** (licenza [**ODbL**](https://www.openstreetmap.org/copyright)). Quando esponi l'API pubblicamente:

- Includi l'attribuzione **"© OpenStreetMap contributors"** nelle risposte o nella UI consumatrice
- Rispetta le [usage policies](https://operations.osmfoundation.org/policies/) dei servizi pubblici:
  - [Nominatim Usage Policy](https://operations.osmfoundation.org/policies/nominatim/)
  - [Overpass API Usage Policy](https://dev.overpass-api.de/overpass-doc/en/preface/commons.html)
  - [OSRM Demo Server Usage](https://github.com/Project-OSRM/osrm-backend/wiki/Demo-server)

Per uso commerciale o ad alto volume, **self-hosta** tutti e 3 i servizi.

---

*Ultimo aggiornamento: 23 aprile 2026 — allineato a Microsoft.Agents.AI 1.2.0 GA e ModelContextProtocol 1.2.0 GA.*
