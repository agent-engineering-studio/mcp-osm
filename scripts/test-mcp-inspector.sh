#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════
# Smoke-test del server osm-mcp + agent via MCP Inspector CLI.
#
# Lo script avvia automaticamente i container docker se non in esecuzione,
# esegue la suite di test contro osm-mcp (tool MCP diretti) e, se presente
# ANTHROPIC_API_KEY, testa anche l'agent con Claude (/chat, /compose-map).
#
# Docker profiles:
#   --claude     → docker compose up osm-mcp osm-mcp-agent (no Ollama, LLM_PROVIDER=claude)
#   --ollama     → docker compose --profile cpu up (Ollama CPU)
#   --no-docker  → non avvia nulla, assume server gia' attivo
#
# Esecuzione:
#   ./scripts/test-mcp-inspector.sh                        # auto-detect, 15 test base
#   ./scripts/test-mcp-inspector.sh --claude               # docker con Claude, include test agent
#   ./scripts/test-mcp-inspector.sh --claude --full        # docker con Claude, suite completa (50+ test)
#   ./scripts/test-mcp-inspector.sh --ollama               # docker con Ollama CPU
#   ./scripts/test-mcp-inspector.sh --no-docker            # server gia' attivo
#   ./scripts/test-mcp-inspector.sh --list-only            # solo tools/list + health
#   ./scripts/test-mcp-inspector.sh --no-teardown          # non ferma i container alla fine
#
# Override env var:
#   MCP_URL            → endpoint MCP server (default http://localhost:8080/mcp)
#   AGENT_URL          → endpoint agent REST (default http://localhost:8002)
#   ANTHROPIC_API_KEY  → abilita Claude (richiesto con --claude)
#   CLAUDE_MODEL       → modello Claude (default claude-sonnet-4-6)
#
# Tool reali del server osm-mcp:
#   geocode_address, reverse_geocode, find_nearby_places, search_category_in_bbox,
#   get_route, suggest_meeting_point, explore_area, find_ev_charging_stations,
#   analyze_commute, osm_health, render_geojson_map, render_multi_layer_map,
#   compose_map_from_resources
# ══════════════════════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------- Defaults ----------
MCP_URL="${MCP_URL:-http://localhost:8080/mcp}"
AGENT_URL="${AGENT_URL:-http://localhost:8002}"

LIST_ONLY=0
FULL=0
DOCKER_MODE="auto"  # auto | claude | ollama | none
TEARDOWN=1

for arg in "$@"; do
    case "$arg" in
        --list-only|-l)  LIST_ONLY=1 ;;
        --full|-f)       FULL=1 ;;
        --claude|-c)     DOCKER_MODE="claude" ;;
        --ollama|-o)     DOCKER_MODE="ollama" ;;
        --no-docker|-n)  DOCKER_MODE="none" ;;
        --no-teardown)   TEARDOWN=0 ;;
        *) echo "Unknown arg: $arg" >&2; exit 2 ;;
    esac
done

# ANSI color helpers
if [[ -t 1 ]]; then C_CYAN=$'\e[36m'; C_GREEN=$'\e[32m'; C_YELLOW=$'\e[33m'; C_RED=$'\e[31m'; C_BOLD=$'\e[1m'; C_RESET=$'\e[0m'
else C_CYAN=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_BOLD=""; C_RESET=""; fi

PASS=0; FAIL=0; WARN=0; SKIP=0
pass()  { PASS=$((PASS + 1)); echo "${C_GREEN}  ✓ PASS${C_RESET}"; }
fail()  { FAIL=$((FAIL + 1)); echo "${C_RED}  ✗ FAIL: $1${C_RESET}"; }
warn()  { WARN=$((WARN + 1)); echo "${C_YELLOW}  ⚠ WARN: $1${C_RESET}"; }
skip()  { SKIP=$((SKIP + 1)); echo "${C_YELLOW}  → SKIP${C_RESET}"; }

# ══════════════════════════════════════════════════════════════════════════
# DOCKER STARTUP
# ══════════════════════════════════════════════════════════════════════════

STARTED_DOCKER=0

docker_up() {
    echo "${C_CYAN}=== Docker startup ===${C_RESET}"
    cd "$PROJECT_DIR"

    case "$DOCKER_MODE" in
        claude)
            if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
                echo "${C_RED}ERROR: --claude richiede ANTHROPIC_API_KEY${C_RESET}"
                echo "  export ANTHROPIC_API_KEY=sk-ant-..."
                exit 1
            fi
            echo "Profile      : Claude (no Ollama)"
            echo "Model        : ${CLAUDE_MODEL:-claude-sonnet-4-6}"
            export LLM_PROVIDER=claude
            docker compose up --build -d osm-mcp osm-mcp-agent
            ;;
        ollama)
            echo "Profile      : Ollama CPU"
            export LLM_PROVIDER=ollama
            docker compose --profile cpu up --build -d
            ;;
        auto)
            # Check if containers already running
            if docker compose ps --status running 2>/dev/null | grep -q osm-mcp; then
                echo "Containers already running, skipping startup."
                return
            fi
            # Auto-detect: if ANTHROPIC_API_KEY is set, use Claude; else Ollama
            if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
                echo "Auto-detected ANTHROPIC_API_KEY → Claude mode"
                DOCKER_MODE="claude"
                export LLM_PROVIDER=claude
                docker compose up --build -d osm-mcp osm-mcp-agent
            else
                echo "No ANTHROPIC_API_KEY → Ollama CPU mode"
                DOCKER_MODE="ollama"
                export LLM_PROVIDER=ollama
                docker compose --profile cpu up --build -d
            fi
            ;;
        none)
            echo "Docker       : skipped (--no-docker)"
            return
            ;;
    esac

    STARTED_DOCKER=1
    echo "Waiting for osm-mcp to be ready..."
    for i in $(seq 1 30); do
        if curl -fsS "$MCP_URL" -o /dev/null 2>/dev/null; then
            echo "${C_GREEN}osm-mcp ready${C_RESET}"
            break
        fi
        if [[ $i -eq 30 ]]; then
            echo "${C_RED}osm-mcp not ready after 60s${C_RESET}"
            docker compose logs osm-mcp --tail=20
            exit 1
        fi
        sleep 2
    done

    # Wait for agent if in Claude or Ollama mode
    if [[ "$DOCKER_MODE" != "none" ]]; then
        echo "Waiting for osm-mcp-agent to be ready..."
        for i in $(seq 1 30); do
            if curl -fsS "$AGENT_URL/health" -o /dev/null 2>/dev/null; then
                echo "${C_GREEN}osm-mcp-agent ready${C_RESET}"
                break
            fi
            if [[ $i -eq 30 ]]; then
                echo "${C_YELLOW}osm-mcp-agent not ready after 60s (agent tests may be skipped)${C_RESET}"
                docker compose logs osm-mcp-agent --tail=20
                break
            fi
            sleep 2
        done
    fi
}

docker_down() {
    if [[ "$STARTED_DOCKER" -eq 1 && "$TEARDOWN" -eq 1 ]]; then
        echo ""
        echo "${C_CYAN}=== Docker teardown ===${C_RESET}"
        cd "$PROJECT_DIR"
        docker compose --profile gpu --profile cpu down
    fi
}

trap docker_down EXIT

docker_up

# ---------- Pre-flight ----------
echo ""
echo "${C_CYAN}=== Pre-flight ===${C_RESET}"
echo "MCP endpoint : $MCP_URL"
echo "Agent REST   : $AGENT_URL"
echo "Docker mode  : $DOCKER_MODE"
echo "Suite        : $(if [[ "$FULL" -eq 1 ]]; then echo 'FULL'; else echo 'base'; fi)"

# ══════════════════════════════════════════════════════════════════════════
# MCP Inspector helpers
# ══════════════════════════════════════════════════════════════════════════

run_call_capture() {
    local tool="$1"; shift
    local cmd=(npx '@modelcontextprotocol/inspector' --cli
        "$MCP_URL"
        --transport http
        --method tools/call
        --tool-name "$tool")
    while [[ $# -gt 0 ]]; do
        cmd+=(--tool-arg "$1")
        shift
    done
    "${cmd[@]}" 2>&1
}

# ══════════════════════════════════════════════════════════════════════════
# T000: tools/list + osm_health
# ══════════════════════════════════════════════════════════════════════════

echo ""
echo "${C_BOLD}${C_CYAN}=== T000 — tools/list ===${C_RESET}"
LIST_OUT=$(npx '@modelcontextprotocol/inspector' --cli \
    "$MCP_URL" \
    --transport http \
    --method tools/list 2>&1)
echo "$LIST_OUT"
COUNT=$(echo "$LIST_OUT" | grep -oE '"name"\s*:\s*"[a-zA-Z_]+"' | sort -u | wc -l | tr -d ' ')
if [[ "$COUNT" -lt 1 ]]; then
    fail "nessun tool nella risposta"; exit 1
elif [[ "$COUNT" -lt 10 ]]; then
    warn "trovati $COUNT tool (attesi >= 10)"
else
    echo "${C_GREEN}OK: $COUNT tool esposti.${C_RESET}"; pass
fi

if [[ "$LIST_ONLY" -eq 1 ]]; then
    echo ""; echo "PASS=$PASS FAIL=$FAIL WARN=$WARN SKIP=$SKIP"; exit 0
fi

echo ""
echo "${C_BOLD}${C_CYAN}=== T000b — osm_health ===${C_RESET}"
HEALTH_OUT=$(run_call_capture 'osm_health')
echo "$HEALTH_OUT"
if echo "$HEALTH_OUT" | grep -q 'status'; then pass; else warn "osm_health: no status field"; fi

# ══════════════════════════════════════════════════════════════════════════
# SECTION 1: Geocoding (T101-T110)
# ══════════════════════════════════════════════════════════════════════════

echo ""
echo "${C_BOLD}${C_CYAN}═══ SECTION 1: Geocoding ═══${C_RESET}"

echo ""; echo "${C_CYAN}=== T101 — Lahore, Pakistan ===${C_RESET}"
OUT=$(run_call_capture 'geocode_address' 'address=Lahore, Pakistan' 'limit=3')
echo "$OUT" | tail -5
if echo "$OUT" | grep -qi 'Lahore\|country_code.*pk'; then pass; else fail "T101: Lahore non trovata"; fi

echo ""; echo "${C_CYAN}=== T102 — Faridpur, Bangladesh ===${C_RESET}"
OUT=$(run_call_capture 'geocode_address' 'address=Faridpur, Bangladesh' 'limit=5')
echo "$OUT" | tail -5
if echo "$OUT" | grep -qi 'Faridpur\|country_code.*bd'; then
    if echo "$OUT" | grep -qi 'West Bengal'; then warn "T102: Faridpur indiano in cima"; else pass; fi
else fail "T102: Faridpur non trovata"; fi

echo ""; echo "${C_CYAN}=== T108 — Asmara, Eritrea ===${C_RESET}"
OUT=$(run_call_capture 'geocode_address' 'address=Asmara, Eritrea' 'limit=3')
echo "$OUT" | tail -5
if echo "$OUT" | grep -qi 'Asmara'; then pass; else fail "T108: Asmara non trovata"; fi

echo ""; echo "${C_CYAN}=== T110 — Karachi, Pakistan ===${C_RESET}"
OUT=$(run_call_capture 'geocode_address' 'address=Karachi, Pakistan' 'limit=3')
echo "$OUT" | tail -3
if echo "$OUT" | grep -qi 'Karachi\|country_code.*pk'; then pass; else fail "T110: Karachi non trovata"; fi

echo ""; echo "${C_CYAN}=== T110b — Islamabad, Pakistan ===${C_RESET}"
OUT=$(run_call_capture 'geocode_address' 'address=Islamabad, Pakistan' 'limit=3')
echo "$OUT" | tail -3
if echo "$OUT" | grep -qi 'Islamabad\|country_code.*pk'; then pass; else fail "T110b: Islamabad non trovata"; fi

if [[ "$FULL" -eq 1 ]]; then
    for tc in \
        "T103|Faridpur, West Bengal, India|India" \
        "T104|Gash-Barka, Eritrea|Eritrea" \
        "T105|West Coast Region, Gambia|Gambia" \
        "T106|Sahiwal, Punjab, Pakistan|Sahiwal" \
        "T107|Mirpur, Dhaka, Bangladesh|Dhaka\|Mirpur" \
        "T109|Sawa, Eritrea|Eritrea\|Sawa"; do
        IFS='|' read -r tid addr expect <<< "$tc"
        echo ""; echo "${C_CYAN}=== $tid — $addr ===${C_RESET}"
        OUT=$(run_call_capture 'geocode_address' "address=$addr" 'limit=3')
        echo "$OUT" | tail -5
        if echo "$OUT" | grep -qiE "$expect"; then pass; else warn "$tid: non trovato"; fi
    done
else
    echo ""; skip  # T103-T109
fi

# ══════════════════════════════════════════════════════════════════════════
# SECTION 2: Rural / fallback (T201-T204)
# ══════════════════════════════════════════════════════════════════════════

echo ""
echo "${C_BOLD}${C_CYAN}═══ SECTION 2: Rural / fallback ═══${C_RESET}"

echo ""; echo "${C_CYAN}=== T202 — Bhanga, Faridpur, Bangladesh ===${C_RESET}"
OUT=$(run_call_capture 'geocode_address' 'address=Bhanga, Faridpur, Bangladesh' 'limit=3')
echo "$OUT" | tail -5
if echo "$OUT" | grep -qi 'Bangladesh'; then pass; else warn "T202: Bhanga non trovata"; fi

echo ""; echo "${C_CYAN}=== T204 — Xyzopolis, Eritrea (inventato) ===${C_RESET}"
OUT=$(run_call_capture 'geocode_address' 'address=Xyzopolis, Eritrea' 'limit=3')
echo "$OUT" | tail -5
if echo "$OUT" | grep -qE 'count.*: *0'; then pass
else fail "T204: risultati per toponimo inventato"; fi

if [[ "$FULL" -eq 1 ]]; then
    echo ""; echo "${C_CYAN}=== T203 — Kafrabad village, Punjab, Pakistan ===${C_RESET}"
    OUT=$(run_call_capture 'geocode_address' 'address=Kafrabad village, Punjab, Pakistan' 'limit=3')
    echo "$OUT" | tail -5
    if echo "$OUT" | grep -qE 'count.*: *0'; then pass
    else warn "T203: risultati per toponimo non documentato"; fi
fi

# ══════════════════════════════════════════════════════════════════════════
# SECTION 3: Reverse geocoding (T301-T303)
# ══════════════════════════════════════════════════════════════════════════

echo ""
echo "${C_BOLD}${C_CYAN}═══ SECTION 3: Reverse geocoding ═══${C_RESET}"

echo ""; echo "${C_CYAN}=== T301 — Reverse Faridpur (23.6064, 89.8429) ===${C_RESET}"
OUT=$(run_call_capture 'reverse_geocode' 'lat=23.6064' 'lon=89.8429')
echo "$OUT" | tail -5
if echo "$OUT" | grep -qi 'Bangladesh\|Faridpur\|country_code.*bd'; then pass; else warn "T301: reverse non identifica Faridpur"; fi

echo ""; echo "${C_CYAN}=== T302 — Reverse mare aperto (0.0, 0.0) ===${C_RESET}"
OUT=$(run_call_capture 'reverse_geocode' 'lat=0.0' 'lon=0.0')
echo "$OUT" | tail -5
pass  # no crash = OK

if [[ "$FULL" -eq 1 ]]; then
    echo ""; echo "${C_CYAN}=== T303 — Reverse Sawa (15.50, 36.80) ===${C_RESET}"
    OUT=$(run_call_capture 'reverse_geocode' 'lat=15.50' 'lon=36.80')
    echo "$OUT" | tail -5
    if echo "$OUT" | grep -qi 'Eritrea'; then pass; else warn "T303: reverse non identifica Eritrea"; fi
fi

# ══════════════════════════════════════════════════════════════════════════
# SECTION 4: POI / amenities (T401-T406) — full only
# ══════════════════════════════════════════════════════════════════════════

echo ""
echo "${C_BOLD}${C_CYAN}═══ SECTION 4: POI search ═══${C_RESET}"

if [[ "$FULL" -eq 1 ]]; then
    for tc in \
        "T401|31.55|74.34|10000|police|Police Lahore" \
        "T402|23.60|89.84|20000|hospital|Hospitals Faridpur" \
        "T403|15.50|36.80|5000|prison|Prison Sawa (low coverage OK)" \
        "T405|23.60|89.84|10000|school|Schools Faridpur"; do
        IFS='|' read -r tid lat lon radius cat desc <<< "$tc"
        echo ""; echo "${C_CYAN}=== $tid — $desc ===${C_RESET}"
        OUT=$(run_call_capture 'find_nearby_places' "lat=$lat" "lon=$lon" "radius_m=$radius" "category=$cat" 'limit=10')
        echo "$OUT" | tail -5
        if echo "$OUT" | grep -qE 'count.*: *0'; then
            if [[ "$tid" == "T403" ]]; then pass  # low coverage expected
            else warn "$tid: zero risultati"; fi
        else pass; fi
    done
else
    skip  # T401-T406
fi

# ══════════════════════════════════════════════════════════════════════════
# SECTION 5: Routing (T501-T504)
# ══════════════════════════════════════════════════════════════════════════

echo ""
echo "${C_BOLD}${C_CYAN}═══ SECTION 5: Routing ═══${C_RESET}"

echo ""; echo "${C_CYAN}=== T501 — Route Faridpur → Dhaka ===${C_RESET}"
OUT=$(run_call_capture 'get_route' 'start_lat=23.6064' 'start_lon=89.8429' 'end_lat=23.8103' 'end_lon=90.4125' 'profile=driving')
echo "$OUT" | tail -5
if echo "$OUT" | grep -q 'distance_m'; then pass; else fail "T501: routing fallito"; fi

echo ""; echo "${C_CYAN}=== T504 — Impossible route Lampedusa → Tripoli ===${C_RESET}"
OUT=$(run_call_capture 'get_route' 'start_lat=35.5' 'start_lon=12.6' 'end_lat=32.9' 'end_lon=13.18' 'profile=driving')
echo "$OUT" | tail -5
if echo "$OUT" | grep -qi 'error\|no route'; then pass
else warn "T504: il router potrebbe aver inventato una rotta impossibile"; fi

if [[ "$FULL" -eq 1 ]]; then
    echo ""; echo "${C_CYAN}=== T502 — Route Asmara → Sawa ===${C_RESET}"
    OUT=$(run_call_capture 'get_route' 'start_lat=15.34' 'start_lon=38.93' 'end_lat=15.50' 'end_lon=36.80' 'profile=driving')
    echo "$OUT" | tail -5
    if echo "$OUT" | grep -q 'distance_m'; then pass; else warn "T502: routing fallito (OSM coverage bassa)"; fi

    echo ""; echo "${C_CYAN}=== T503 — Route Lahore → Wagah ===${C_RESET}"
    OUT=$(run_call_capture 'get_route' 'start_lat=31.55' 'start_lon=74.34' 'end_lat=31.605' 'end_lon=74.573' 'profile=driving')
    echo "$OUT" | tail -5
    if echo "$OUT" | grep -q 'distance_m'; then pass; else warn "T503: routing fallito"; fi
fi

# ══════════════════════════════════════════════════════════════════════════
# SECTION 6-8: Disambiguation, Multilingual, Remote — full only
# ══════════════════════════════════════════════════════════════════════════

if [[ "$FULL" -eq 1 ]]; then
    echo ""
    echo "${C_BOLD}${C_CYAN}═══ SECTION 6: Disambiguation ═══${C_RESET}"

    echo ""; echo "${C_CYAN}=== T601a — Tripoli, Libya ===${C_RESET}"
    OUT1=$(run_call_capture 'geocode_address' 'address=Tripoli, Libya' 'limit=1')
    echo "$OUT1" | tail -3
    echo "${C_CYAN}=== T601b — Tripoli, Lebanon ===${C_RESET}"
    OUT2=$(run_call_capture 'geocode_address' 'address=Tripoli, Lebanon' 'limit=1')
    echo "$OUT2" | tail -3
    if echo "$OUT1" | grep -qi 'Libya' && echo "$OUT2" | grep -qi 'Lebanon'; then pass
    else fail "T601: disambiguazione Tripoli fallita"; fi

    echo ""; echo "${C_CYAN}=== T603 — Faridpur (no country) ===${C_RESET}"
    OUT=$(run_call_capture 'geocode_address' 'address=Faridpur' 'limit=5')
    echo "$OUT" | tail -5
    pass  # annotare default

    echo ""
    echo "${C_BOLD}${C_CYAN}═══ SECTION 7: Multilingual ═══${C_RESET}"

    echo ""; echo "${C_CYAN}=== T701 — لاہور (urdu) ===${C_RESET}"
    OUT=$(run_call_capture 'geocode_address' 'address=لاہور' 'limit=3')
    echo "$OUT" | tail -3
    if echo "$OUT" | grep -qi 'Lahore'; then pass; else warn "T701: urdu non risolto"; fi

    echo ""; echo "${C_CYAN}=== T703 — ঢাকা (bangla) ===${C_RESET}"
    OUT=$(run_call_capture 'geocode_address' 'address=ঢাকা' 'limit=3')
    echo "$OUT" | tail -3
    if echo "$OUT" | grep -qi 'Dhaka'; then pass; else warn "T703: bangla non risolto"; fi

    echo ""; echo "${C_CYAN}=== T704 — Daka (translitterazione) ===${C_RESET}"
    OUT=$(run_call_capture 'geocode_address' 'address=Daka, Bangladesh' 'limit=3')
    echo "$OUT" | tail -3
    if echo "$OUT" | grep -qi 'Dhaka'; then pass; else warn "T704: fuzzy matching"; fi

    echo ""
    echo "${C_BOLD}${C_CYAN}═══ SECTION 8: Remote areas ═══${C_RESET}"

    for tc in \
        "T801|Yei, Central Equatoria, South Sudan|South Sudan\|Yei" \
        "T802|Senafe, Eritrea|Eritrea\|Senafe" \
        "T804|Hodan district, Mogadishu, Somalia|Mogadishu\|Hodan\|Somalia"; do
        IFS='|' read -r tid addr expect <<< "$tc"
        echo ""; echo "${C_CYAN}=== $tid — $addr ===${C_RESET}"
        OUT=$(run_call_capture 'geocode_address' "address=$addr" 'limit=3')
        echo "$OUT" | tail -3
        if echo "$OUT" | grep -qiE "$expect"; then pass; else warn "$tid: non trovato"; fi
    done
fi

# ══════════════════════════════════════════════════════════════════════════
# SECTION 9: Anti-invenzione (T901)
# ══════════════════════════════════════════════════════════════════════════

echo ""
echo "${C_BOLD}${C_CYAN}═══ SECTION 9: Anti-invention ═══${C_RESET}"

echo ""; echo "${C_CYAN}=== T901 — Riverdale Heights, Lahore (inventato) ===${C_RESET}"
OUT=$(run_call_capture 'geocode_address' 'address=Riverdale Heights, Lahore, Pakistan' 'limit=3')
echo "$OUT" | tail -5
if echo "$OUT" | grep -qE 'count.*: *0'; then pass
else warn "T901: risultati per toponimo inventato"; fi

# ══════════════════════════════════════════════════════════════════════════
# SECTION 10: Error handling (T1001-T1004)
# ══════════════════════════════════════════════════════════════════════════

echo ""
echo "${C_BOLD}${C_CYAN}═══ SECTION 10: Error handling ═══${C_RESET}"

echo ""; echo "${C_CYAN}=== T1001 — Empty query ===${C_RESET}"
OUT=$(run_call_capture 'geocode_address' 'address=' 'limit=3' 2>&1 || true)
echo "$OUT" | tail -5; pass  # no crash

echo ""; echo "${C_CYAN}=== T1002 — XSS injection ===${C_RESET}"
OUT=$(run_call_capture 'geocode_address' 'address=<script>alert(1)</script>, Pakistan' 'limit=3' 2>&1 || true)
echo "$OUT" | tail -5
if echo "$OUT" | grep -q '<script>'; then fail "T1002: XSS non sanitizzata"; else pass; fi

echo ""; echo "${C_CYAN}=== T1003 — Out-of-range coordinates ===${C_RESET}"
OUT=$(run_call_capture 'reverse_geocode' 'lat=999' 'lon=-999' 2>&1 || true)
echo "$OUT" | tail -5; pass  # graceful

echo ""; echo "${C_CYAN}=== T1004 — Route same point ===${C_RESET}"
OUT=$(run_call_capture 'get_route' 'start_lat=31.55' 'start_lon=74.34' 'end_lat=31.55' 'end_lon=74.34' 'profile=driving' 2>&1 || true)
echo "$OUT" | tail -5; pass

# ══════════════════════════════════════════════════════════════════════════
# SECTION 11: Agent REST tests (Claude / Ollama) — richiede agent attivo
# ══════════════════════════════════════════════════════════════════════════

echo ""
echo "${C_BOLD}${C_CYAN}═══ SECTION 11: Agent REST API ═══${C_RESET}"

AGENT_HEALTH=$(curl -fsS "$AGENT_URL/health" 2>/dev/null || echo "")
if [[ -z "$AGENT_HEALTH" ]]; then
    echo "${C_YELLOW}Agent non raggiungibile su $AGENT_URL — skip test agent${C_RESET}"
    skip
else
    PROVIDER=$(echo "$AGENT_HEALTH" | grep -oP '"provider"\s*:\s*"\K[^"]+' || echo "unknown")
    echo "Agent health : OK (provider=$PROVIDER)"
    pass

    # TA01 — /compose-map (deterministic, no LLM cost)
    echo ""; echo "${C_CYAN}=== TA01 — POST /compose-map (deterministic) ===${C_RESET}"
    COMPOSE_BODY='{
        "text": "Test geojson rendering",
        "resources": [{
            "name": "test-point",
            "format": "GEOJSON",
            "content": "{\"type\":\"Feature\",\"geometry\":{\"type\":\"Point\",\"coordinates\":[74.34,31.55]},\"properties\":{\"name\":\"Lahore\"}}"
        }],
        "title": "Test Map"
    }'
    COMPOSE_OUT=$(curl -fsS -X POST "$AGENT_URL/compose-map" \
        -H "Content-Type: application/json" \
        -d "$COMPOSE_BODY" 2>&1 || echo '{"error":"request failed"}')
    if echo "$COMPOSE_OUT" | grep -qi 'html\|<!doctype\|leaflet'; then
        echo "  compose-map returned HTML map"
        pass
    else
        echo "$COMPOSE_OUT" | tail -5
        warn "TA01: /compose-map non ha restituito HTML"
    fi

    # TA02 — /chat con Claude (solo se provider=claude, consuma token)
    if [[ "$PROVIDER" == "claude" ]]; then
        echo ""; echo "${C_CYAN}=== TA02 — POST /chat con Claude (consuma token) ===${C_RESET}"
        CHAT_BODY='{"query": "Geocodifica Lahore, Pakistan e dimmi le coordinate. Rispondi in modo conciso."}'
        CHAT_OUT=$(curl -fsS -X POST "$AGENT_URL/chat" \
            -H "Content-Type: application/json" \
            -d "$CHAT_BODY" --max-time 60 2>&1 || echo '{"error":"timeout or failure"}')
        if echo "$CHAT_OUT" | grep -qi 'lahore\|31\.\|74\.'; then
            echo "  Claude ha risposto con info su Lahore"
            pass
        else
            echo "$CHAT_OUT" | head -10
            warn "TA02: risposta Claude non contiene info attese"
        fi

        if [[ "$FULL" -eq 1 ]]; then
            # TA03 — /chat routing via Claude
            echo ""; echo "${C_CYAN}=== TA03 — /chat routing Faridpur→Dhaka via Claude ===${C_RESET}"
            CHAT_BODY='{"query": "Calcola la distanza stradale da Faridpur a Dhaka in Bangladesh. Riporta km e minuti."}'
            CHAT_OUT=$(curl -fsS -X POST "$AGENT_URL/chat" \
                -H "Content-Type: application/json" \
                -d "$CHAT_BODY" --max-time 60 2>&1 || echo '{"error":"timeout"}')
            if echo "$CHAT_OUT" | grep -qiE 'km|distanz|distance|min'; then
                echo "  Claude ha calcolato routing"
                pass
            else
                echo "$CHAT_OUT" | head -10
                warn "TA03: risposta routing non contiene distanza"
            fi

            # TA04 — /chat POI via Claude
            echo ""; echo "${C_CYAN}=== TA04 — /chat POI polizia Lahore via Claude ===${C_RESET}"
            CHAT_BODY='{"query": "Trova stazioni di polizia entro 5km dal centro di Lahore, Pakistan."}'
            CHAT_OUT=$(curl -fsS -X POST "$AGENT_URL/chat" \
                -H "Content-Type: application/json" \
                -d "$CHAT_BODY" --max-time 60 2>&1 || echo '{"error":"timeout"}')
            if echo "$CHAT_OUT" | grep -qiE 'police\|polizia\|station'; then
                echo "  Claude ha trovato POI polizia"
                pass
            else
                echo "$CHAT_OUT" | head -10
                warn "TA04: risposta POI non contiene stazioni"
            fi
        fi
    else
        echo "  Provider=$PROVIDER — skip test /chat Claude (non consuma token)"
        skip
    fi
fi

# ══════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════

echo ""
echo "${C_BOLD}${C_CYAN}══════════════════════════════════════${C_RESET}"
echo "${C_BOLD}${C_CYAN}=== Summary ===${C_RESET}"
echo "${C_GREEN}  PASS : $PASS${C_RESET}"
echo "${C_RED}  FAIL : $FAIL${C_RESET}"
echo "${C_YELLOW}  WARN : $WARN${C_RESET}"
echo "${C_YELLOW}  SKIP : $SKIP${C_RESET}"
TOTAL=$((PASS + FAIL + WARN + SKIP))
echo "  TOTAL: $TOTAL"
echo "${C_BOLD}${C_CYAN}══════════════════════════════════════${C_RESET}"

if [[ "$FAIL" -gt 0 ]]; then exit 1; fi
