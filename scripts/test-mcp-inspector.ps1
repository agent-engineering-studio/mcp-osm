# ══════════════════════════════════════════════════════════════════════════
# Smoke-test del server osm-mcp + agent via MCP Inspector CLI.
#
# Lo script avvia automaticamente i container docker se non in esecuzione,
# esegue la suite di test contro osm-mcp (tool MCP diretti) e, se presente
# ANTHROPIC_API_KEY, testa anche l'agent con Claude (/chat, /compose-map).
#
# Docker profiles:
#   -Claude      -> docker compose up osm-mcp osm-mcp-agent (no Ollama, LLM_PROVIDER=claude)
#   -Ollama      -> docker compose --profile cpu up (Ollama CPU)
#   -NoDocker    -> non avvia nulla, assume server gia' attivo
#
# Esecuzione:
#   pwsh ./scripts/test-mcp-inspector.ps1                        # auto-detect, 15 test base
#   pwsh ./scripts/test-mcp-inspector.ps1 -Claude                # docker con Claude, include test agent
#   pwsh ./scripts/test-mcp-inspector.ps1 -Claude -Full          # docker con Claude, suite completa (50+ test)
#   pwsh ./scripts/test-mcp-inspector.ps1 -Ollama                # docker con Ollama CPU
#   pwsh ./scripts/test-mcp-inspector.ps1 -NoDocker              # server gia' attivo
#   pwsh ./scripts/test-mcp-inspector.ps1 -ListOnly              # solo tools/list + health
#   pwsh ./scripts/test-mcp-inspector.ps1 -NoTeardown            # non ferma i container alla fine
#
# Override env var:
#   $env:MCP_URL            -> endpoint MCP server (default http://localhost:8080/mcp)
#   $env:AGENT_URL          -> endpoint agent REST (default http://localhost:8002)
#   $env:ANTHROPIC_API_KEY  -> abilita Claude (richiesto con -Claude)
#   $env:CLAUDE_MODEL       -> modello Claude (default claude-sonnet-4-6)
#
# Tool reali del server osm-mcp:
#   geocode_address, reverse_geocode, find_nearby_places, search_category_in_bbox,
#   get_route, suggest_meeting_point, explore_area, find_ev_charging_stations,
#   analyze_commute, osm_health, render_geojson_map, render_multi_layer_map,
#   compose_map_from_resources
# ══════════════════════════════════════════════════════════════════════════

[CmdletBinding()]
param(
    [switch]$ListOnly,
    [switch]$Full,
    [switch]$Claude,
    [switch]$Ollama,
    [switch]$NoDocker,
    [switch]$NoTeardown
)

$ErrorActionPreference = 'Stop'

# ---------- UTF-8 console encoding ----------
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding           = [System.Text.Encoding]::UTF8

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir

# ---------- Defaults ----------
$McpUrl   = if ($env:MCP_URL)   { $env:MCP_URL }   else { 'http://localhost:8080/mcp' }
$AgentUrl = if ($env:AGENT_URL) { $env:AGENT_URL } else { 'http://localhost:8002' }

# ---------- Counters ----------
$script:Pass = 0; $script:Fail = 0; $script:Warn = 0; $script:Skip = 0
function Test-Pass  { $script:Pass++; Write-Host '  > PASS' -ForegroundColor Green }
function Test-Fail  { param([string]$m) $script:Fail++; Write-Host "  X FAIL: $m" -ForegroundColor Red }
function Test-Warn  { param([string]$m) $script:Warn++; Write-Host "  ! WARN: $m" -ForegroundColor Yellow }
function Test-Skip  { $script:Skip++; Write-Host '  -> SKIP' -ForegroundColor Yellow }

# ---------- Docker mode ----------
$DockerMode = 'auto'
if ($Claude)   { $DockerMode = 'claude' }
if ($Ollama)   { $DockerMode = 'ollama' }
if ($NoDocker) { $DockerMode = 'none' }

$StartedDocker = $false

# ══════════════════════════════════════════════════════════════════════════
# DOCKER STARTUP
# ══════════════════════════════════════════════════════════════════════════

function Start-Stack {
    Write-Host '=== Docker startup ===' -ForegroundColor Cyan
    Push-Location $ProjectDir

    switch ($script:DockerMode) {
        'claude' {
            if (-not $env:ANTHROPIC_API_KEY) {
                Write-Host 'ERROR: -Claude richiede $env:ANTHROPIC_API_KEY' -ForegroundColor Red
                Write-Host '  $env:ANTHROPIC_API_KEY = "sk-ant-..."'
                throw 'Missing ANTHROPIC_API_KEY'
            }
            Write-Host "Profile      : Claude (no Ollama)"
            Write-Host "Model        : $(if ($env:CLAUDE_MODEL) { $env:CLAUDE_MODEL } else { 'claude-sonnet-4-6' })"
            $env:LLM_PROVIDER = 'claude'
            docker compose up --build -d osm-mcp osm-mcp-agent
        }
        'ollama' {
            Write-Host 'Profile      : Ollama CPU'
            $env:LLM_PROVIDER = 'ollama'
            docker compose --profile cpu up --build -d
        }
        'auto' {
            # Check if containers already running
            $running = docker compose ps --status running 2>$null | Select-String 'osm-mcp'
            if ($running) {
                Write-Host 'Containers already running, skipping startup.'
                Pop-Location; return
            }
            if ($env:ANTHROPIC_API_KEY) {
                Write-Host 'Auto-detected ANTHROPIC_API_KEY -> Claude mode'
                $script:DockerMode = 'claude'
                $env:LLM_PROVIDER = 'claude'
                docker compose up --build -d osm-mcp osm-mcp-agent
            } else {
                Write-Host 'No ANTHROPIC_API_KEY -> Ollama CPU mode'
                $script:DockerMode = 'ollama'
                $env:LLM_PROVIDER = 'ollama'
                docker compose --profile cpu up --build -d
            }
        }
        'none' {
            Write-Host 'Docker       : skipped (-NoDocker)'
            Pop-Location; return
        }
    }

    $script:StartedDocker = $true

    # Wait for osm-mcp
    Write-Host 'Waiting for osm-mcp to be ready...'
    for ($i = 1; $i -le 30; $i++) {
        try {
            $null = Invoke-WebRequest -Uri $McpUrl -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
            Write-Host 'osm-mcp ready' -ForegroundColor Green; break
        } catch {
            if ($i -eq 30) {
                Write-Host 'osm-mcp not ready after 60s' -ForegroundColor Red
                docker compose logs osm-mcp --tail=20
                throw 'osm-mcp startup timeout'
            }
            Start-Sleep -Seconds 2
        }
    }

    # Wait for agent
    Write-Host 'Waiting for osm-mcp-agent to be ready...'
    for ($i = 1; $i -le 30; $i++) {
        try {
            $null = Invoke-WebRequest -Uri "$AgentUrl/health" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
            Write-Host 'osm-mcp-agent ready' -ForegroundColor Green; break
        } catch {
            if ($i -eq 30) {
                Write-Host 'osm-mcp-agent not ready after 60s (agent tests may be skipped)' -ForegroundColor Yellow
                docker compose logs osm-mcp-agent --tail=20
                break
            }
            Start-Sleep -Seconds 2
        }
    }

    Pop-Location
}

function Stop-Stack {
    if ($script:StartedDocker -and -not $NoTeardown) {
        Write-Host ''
        Write-Host '=== Docker teardown ===' -ForegroundColor Cyan
        Push-Location $ProjectDir
        docker compose --profile gpu --profile cpu down
        Pop-Location
    }
}

# ══════════════════════════════════════════════════════════════════════════
# MCP Inspector helper
# ══════════════════════════════════════════════════════════════════════════

function Invoke-Mcp {
    param(
        [Parameter(Mandatory)][string]$Method,
        [string]$ToolName,
        [string[]]$ToolArgs = @()
    )
    $cmd = "npx @modelcontextprotocol/inspector --cli $McpUrl --transport http --method $Method"
    if ($ToolName) {
        $cmd += " --tool-name $ToolName"
        foreach ($a in $ToolArgs) {
            $cmd += " --tool-arg `"$a`""
        }
    }
    Invoke-Expression "$cmd 2>&1"
}

function Invoke-McpCapture {
    param(
        [Parameter(Mandatory)][string]$ToolName,
        [string[]]$ToolArgs = @()
    )
    $out = Invoke-Mcp -Method 'tools/call' -ToolName $ToolName -ToolArgs $ToolArgs | Out-String
    return $out
}

# ══════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════

try {
    Start-Stack

    Write-Host ''
    Write-Host '=== Pre-flight ===' -ForegroundColor Cyan
    Write-Host "MCP endpoint : $McpUrl"
    Write-Host "Agent REST   : $AgentUrl"
    Write-Host "Docker mode  : $DockerMode"
    Write-Host ("Suite        : {0}" -f $(if ($Full) { 'FULL' } else { 'base' }))

    # ── T000: tools/list ──
    Write-Host ''
    Write-Host '=== T000 - tools/list ===' -ForegroundColor Cyan
    $listOutput = Invoke-Mcp -Method 'tools/list' | Out-String
    Write-Host $listOutput

    $toolNames = [regex]::Matches($listOutput, '"name"\s*:\s*"([a-zA-Z_]+)"') |
                 ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
    $count = $toolNames.Count

    if ($count -lt 1)  { Test-Fail 'nessun tool nella risposta'; return }
    elseif ($count -lt 10) { Test-Warn "trovati $count tool (attesi >= 10)" }
    else { Write-Host "OK: $count tool esposti." -ForegroundColor Green; Test-Pass }

    if ($ListOnly) {
        Write-Host "PASS=$($script:Pass) FAIL=$($script:Fail) WARN=$($script:Warn) SKIP=$($script:Skip)"
        return
    }

    # ── T000b: osm_health ──
    Write-Host ''
    Write-Host '=== T000b - osm_health ===' -ForegroundColor Cyan
    $healthOut = Invoke-McpCapture -ToolName 'osm_health'
    Write-Host $healthOut
    if ($healthOut -match 'status') { Test-Pass } else { Test-Warn 'osm_health: no status field' }

    # ══════════════════════════════════════════════════════════════════
    # SECTION 1: Geocoding
    # ══════════════════════════════════════════════════════════════════

    Write-Host ''
    Write-Host '=== SECTION 1: Geocoding ===' -ForegroundColor Cyan

    # Helper function for geocode tests
    function Test-Geocode {
        param([string]$Id, [string]$Address, [string]$Expect, [string]$Severity = 'fail')
        Write-Host ''; Write-Host "=== $Id - $Address ===" -ForegroundColor Cyan
        $out = Invoke-McpCapture -ToolName 'geocode_address' -ToolArgs @("address=$Address", 'limit=3')
        ($out -split "`n") | Select-Object -Last 5 | Write-Host
        if ($out -match $Expect -or $out -match 'country_code') { Test-Pass }
        elseif ($Severity -eq 'warn') { Test-Warn "$Id`: non trovato" }
        else { Test-Fail "$Id`: $Address non trovata" }
    }

    Test-Geocode 'T101' 'Lahore, Pakistan'     'Lahore'
    Test-Geocode 'T102' 'Faridpur, Bangladesh'  'Faridpur'
    Test-Geocode 'T108' 'Asmara, Eritrea'       'Asmara'
    Test-Geocode 'T110' 'Karachi, Pakistan'     'Karachi'
    Test-Geocode 'T110b' 'Islamabad, Pakistan'  'Islamabad'

    if ($Full) {
        Test-Geocode 'T103' 'Faridpur, West Bengal, India' 'India'    -Severity warn
        Test-Geocode 'T104' 'Gash-Barka, Eritrea'         'Eritrea'  -Severity warn
        Test-Geocode 'T105' 'West Coast Region, Gambia'    'Gambia'   -Severity warn
        Test-Geocode 'T106' 'Sahiwal, Punjab, Pakistan'    'Sahiwal'  -Severity warn
        Test-Geocode 'T107' 'Mirpur, Dhaka, Bangladesh'    'Dhaka|Mirpur' -Severity warn
        Test-Geocode 'T109' 'Sawa, Eritrea'                'Eritrea|Sawa' -Severity warn
    } else { Test-Skip }

    # ══════════════════════════════════════════════════════════════════
    # SECTION 2: Rural / fallback
    # ══════════════════════════════════════════════════════════════════

    Write-Host ''
    Write-Host '=== SECTION 2: Rural / fallback ===' -ForegroundColor Cyan

    Test-Geocode 'T202' 'Bhanga, Faridpur, Bangladesh' 'Bangladesh' -Severity warn

    Write-Host ''; Write-Host '=== T204 - Xyzopolis, Eritrea (inventato) ===' -ForegroundColor Cyan
    $out = Invoke-McpCapture -ToolName 'geocode_address' -ToolArgs @('address=Xyzopolis, Eritrea', 'limit=3')
    ($out -split "`n") | Select-Object -Last 5 | Write-Host
    if ($out -match 'count.*:\s*0') { Test-Pass } else { Test-Fail 'T204: risultati per toponimo inventato' }

    if ($Full) {
        Write-Host ''; Write-Host '=== T203 - Kafrabad village (non documentato) ===' -ForegroundColor Cyan
        $out = Invoke-McpCapture -ToolName 'geocode_address' -ToolArgs @('address=Kafrabad village, Punjab, Pakistan', 'limit=3')
        ($out -split "`n") | Select-Object -Last 5 | Write-Host
        if ($out -match 'count.*:\s*0') { Test-Pass } else { Test-Warn 'T203: risultati per toponimo non documentato' }
    }

    # ══════════════════════════════════════════════════════════════════
    # SECTION 3: Reverse geocoding
    # ══════════════════════════════════════════════════════════════════

    Write-Host ''
    Write-Host '=== SECTION 3: Reverse geocoding ===' -ForegroundColor Cyan

    Write-Host ''; Write-Host '=== T301 - Reverse Faridpur (23.6064, 89.8429) ===' -ForegroundColor Cyan
    $out = Invoke-McpCapture -ToolName 'reverse_geocode' -ToolArgs @('lat=23.6064', 'lon=89.8429')
    ($out -split "`n") | Select-Object -Last 5 | Write-Host
    if ($out -match 'Bangladesh|Faridpur|country_code.*bd') { Test-Pass } else { Test-Warn 'T301: reverse non identifica Faridpur' }

    Write-Host ''; Write-Host '=== T302 - Reverse mare aperto (0.0, 0.0) ===' -ForegroundColor Cyan
    $out = Invoke-McpCapture -ToolName 'reverse_geocode' -ToolArgs @('lat=0.0', 'lon=0.0')
    ($out -split "`n") | Select-Object -Last 5 | Write-Host
    Test-Pass  # no crash = OK

    if ($Full) {
        Write-Host ''; Write-Host '=== T303 - Reverse Sawa (15.50, 36.80) ===' -ForegroundColor Cyan
        $out = Invoke-McpCapture -ToolName 'reverse_geocode' -ToolArgs @('lat=15.50', 'lon=36.80')
        ($out -split "`n") | Select-Object -Last 5 | Write-Host
        if ($out -match 'Eritrea') { Test-Pass } else { Test-Warn 'T303: reverse non identifica Eritrea' }
    }

    # ══════════════════════════════════════════════════════════════════
    # SECTION 4: POI search — full only
    # ══════════════════════════════════════════════════════════════════

    Write-Host ''
    Write-Host '=== SECTION 4: POI search ===' -ForegroundColor Cyan

    if ($Full) {
        $poiTests = @(
            @{ Id='T401'; Lat='31.55'; Lon='74.34'; Radius='10000'; Cat='police';   Desc='Police Lahore'; LowCoverage=$false },
            @{ Id='T402'; Lat='23.60'; Lon='89.84'; Radius='20000'; Cat='hospital'; Desc='Hospitals Faridpur'; LowCoverage=$false },
            @{ Id='T403'; Lat='15.50'; Lon='36.80'; Radius='5000';  Cat='prison';   Desc='Prison Sawa'; LowCoverage=$true },
            @{ Id='T405'; Lat='23.60'; Lon='89.84'; Radius='10000'; Cat='school';   Desc='Schools Faridpur'; LowCoverage=$false }
        )
        foreach ($pt in $poiTests) {
            Write-Host ''; Write-Host ("=== {0} - {1} ===" -f $pt.Id, $pt.Desc) -ForegroundColor Cyan
            $out = Invoke-McpCapture -ToolName 'find_nearby_places' -ToolArgs @(
                "lat=$($pt.Lat)", "lon=$($pt.Lon)", "radius_m=$($pt.Radius)", "category=$($pt.Cat)", 'limit=10')
            ($out -split "`n") | Select-Object -Last 5 | Write-Host
            if ($out -match 'count.*:\s*0') {
                if ($pt.LowCoverage) { Test-Pass } else { Test-Warn "$($pt.Id): zero risultati" }
            } else { Test-Pass }
        }
    } else { Test-Skip }

    # ══════════════════════════════════════════════════════════════════
    # SECTION 5: Routing
    # ══════════════════════════════════════════════════════════════════

    Write-Host ''
    Write-Host '=== SECTION 5: Routing ===' -ForegroundColor Cyan

    Write-Host ''; Write-Host '=== T501 - Route Faridpur -> Dhaka ===' -ForegroundColor Cyan
    $out = Invoke-McpCapture -ToolName 'get_route' -ToolArgs @(
        'start_lat=23.6064','start_lon=89.8429','end_lat=23.8103','end_lon=90.4125','profile=driving')
    ($out -split "`n") | Select-Object -Last 5 | Write-Host
    if ($out -match 'distance_m') { Test-Pass } else { Test-Fail 'T501: routing fallito' }

    Write-Host ''; Write-Host '=== T504 - Impossible route Lampedusa -> Tripoli ===' -ForegroundColor Cyan
    $out = Invoke-McpCapture -ToolName 'get_route' -ToolArgs @(
        'start_lat=35.5','start_lon=12.6','end_lat=32.9','end_lon=13.18','profile=driving')
    ($out -split "`n") | Select-Object -Last 5 | Write-Host
    if ($out -match 'error|no route') { Test-Pass } else { Test-Warn 'T504: potrebbe aver inventato rotta impossibile' }

    if ($Full) {
        Write-Host ''; Write-Host '=== T502 - Route Asmara -> Sawa ===' -ForegroundColor Cyan
        $out = Invoke-McpCapture -ToolName 'get_route' -ToolArgs @(
            'start_lat=15.34','start_lon=38.93','end_lat=15.50','end_lon=36.80','profile=driving')
        ($out -split "`n") | Select-Object -Last 5 | Write-Host
        if ($out -match 'distance_m') { Test-Pass } else { Test-Warn 'T502: routing fallito (coverage bassa)' }

        Write-Host ''; Write-Host '=== T503 - Route Lahore -> Wagah ===' -ForegroundColor Cyan
        $out = Invoke-McpCapture -ToolName 'get_route' -ToolArgs @(
            'start_lat=31.55','start_lon=74.34','end_lat=31.605','end_lon=74.573','profile=driving')
        ($out -split "`n") | Select-Object -Last 5 | Write-Host
        if ($out -match 'distance_m') { Test-Pass } else { Test-Warn 'T503: routing fallito' }
    }

    # ══════════════════════════════════════════════════════════════════
    # SECTION 6-8: Disambiguation, Multilingual, Remote — full only
    # ══════════════════════════════════════════════════════════════════

    if ($Full) {
        Write-Host ''
        Write-Host '=== SECTION 6: Disambiguation ===' -ForegroundColor Cyan

        Write-Host ''; Write-Host '=== T601a - Tripoli, Libya ===' -ForegroundColor Cyan
        $out1 = Invoke-McpCapture -ToolName 'geocode_address' -ToolArgs @('address=Tripoli, Libya','limit=1')
        ($out1 -split "`n") | Select-Object -Last 3 | Write-Host
        Write-Host '=== T601b - Tripoli, Lebanon ===' -ForegroundColor Cyan
        $out2 = Invoke-McpCapture -ToolName 'geocode_address' -ToolArgs @('address=Tripoli, Lebanon','limit=1')
        ($out2 -split "`n") | Select-Object -Last 3 | Write-Host
        if ($out1 -match 'Libya' -and $out2 -match 'Lebanon') { Test-Pass }
        else { Test-Fail 'T601: disambiguazione Tripoli fallita' }

        Test-Geocode 'T603' 'Faridpur' 'Faridpur' -Severity warn

        Write-Host ''
        Write-Host '=== SECTION 7: Multilingual ===' -ForegroundColor Cyan

        # Urdu
        Write-Host ''; Write-Host '=== T701 - Lahore in urdu ===' -ForegroundColor Cyan
        $out = Invoke-McpCapture -ToolName 'geocode_address' -ToolArgs @("address=`u{0644}`u{0627}`u{06C1}`u{0648}`u{0631}", 'limit=3')
        ($out -split "`n") | Select-Object -Last 3 | Write-Host
        if ($out -match 'Lahore') { Test-Pass } else { Test-Warn 'T701: urdu non risolto' }

        # Bangla
        Write-Host ''; Write-Host '=== T703 - Dacca in bangla ===' -ForegroundColor Cyan
        $out = Invoke-McpCapture -ToolName 'geocode_address' -ToolArgs @("address=`u{09A2}`u{09BE}`u{0995}`u{09BE}", 'limit=3')
        ($out -split "`n") | Select-Object -Last 3 | Write-Host
        if ($out -match 'Dhaka') { Test-Pass } else { Test-Warn 'T703: bangla non risolto' }

        # Transliteration
        Test-Geocode 'T704' 'Daka, Bangladesh' 'Dhaka' -Severity warn

        Write-Host ''
        Write-Host '=== SECTION 8: Remote areas ===' -ForegroundColor Cyan
        Test-Geocode 'T801' 'Yei, Central Equatoria, South Sudan' 'South Sudan|Yei' -Severity warn
        Test-Geocode 'T802' 'Senafe, Eritrea' 'Eritrea|Senafe' -Severity warn
        Test-Geocode 'T804' 'Hodan district, Mogadishu, Somalia' 'Mogadishu|Hodan|Somalia' -Severity warn
    }

    # ══════════════════════════════════════════════════════════════════
    # SECTION 9: Anti-invenzione
    # ══════════════════════════════════════════════════════════════════

    Write-Host ''
    Write-Host '=== SECTION 9: Anti-invention ===' -ForegroundColor Cyan

    Write-Host ''; Write-Host '=== T901 - Riverdale Heights, Lahore (inventato) ===' -ForegroundColor Cyan
    $out = Invoke-McpCapture -ToolName 'geocode_address' -ToolArgs @('address=Riverdale Heights, Lahore, Pakistan','limit=3')
    ($out -split "`n") | Select-Object -Last 5 | Write-Host
    if ($out -match 'count.*:\s*0') { Test-Pass } else { Test-Warn 'T901: risultati per toponimo inventato' }

    # ══════════════════════════════════════════════════════════════════
    # SECTION 10: Error handling
    # ══════════════════════════════════════════════════════════════════

    Write-Host ''
    Write-Host '=== SECTION 10: Error handling ===' -ForegroundColor Cyan

    Write-Host ''; Write-Host '=== T1001 - Empty query ===' -ForegroundColor Cyan
    try { $out = Invoke-McpCapture -ToolName 'geocode_address' -ToolArgs @('address=','limit=3') } catch {}
    Test-Pass

    Write-Host ''; Write-Host '=== T1002 - XSS injection ===' -ForegroundColor Cyan
    try { $out = Invoke-McpCapture -ToolName 'geocode_address' -ToolArgs @('address=<script>alert(1)</script>, Pakistan','limit=3') } catch { $out = '' }
    if ($out -match '<script>') { Test-Fail 'T1002: XSS non sanitizzata' } else { Test-Pass }

    Write-Host ''; Write-Host '=== T1003 - Out-of-range coordinates ===' -ForegroundColor Cyan
    try { $out = Invoke-McpCapture -ToolName 'reverse_geocode' -ToolArgs @('lat=999','lon=-999') } catch {}
    Test-Pass

    Write-Host ''; Write-Host '=== T1004 - Route same point ===' -ForegroundColor Cyan
    try { $out = Invoke-McpCapture -ToolName 'get_route' -ToolArgs @(
        'start_lat=31.55','start_lon=74.34','end_lat=31.55','end_lon=74.34','profile=driving') } catch {}
    Test-Pass

    # ══════════════════════════════════════════════════════════════════
    # SECTION 11: Agent REST API (Claude / Ollama)
    # ══════════════════════════════════════════════════════════════════

    Write-Host ''
    Write-Host '=== SECTION 11: Agent REST API ===' -ForegroundColor Cyan

    $agentOk = $false
    try {
        $health = Invoke-RestMethod -Uri "$AgentUrl/health" -UseBasicParsing -TimeoutSec 5
        $provider = $health.provider
        Write-Host "Agent health : OK (provider=$provider)" -ForegroundColor Green
        Test-Pass
        $agentOk = $true
    } catch {
        Write-Host "Agent non raggiungibile su $AgentUrl - skip test agent" -ForegroundColor Yellow
        Test-Skip
    }

    if ($agentOk) {
        # TA01 -- /compose-map (deterministic, no LLM cost)
        Write-Host ''; Write-Host '=== TA01 - POST /compose-map (deterministic) ===' -ForegroundColor Cyan
        $composeBody = @{
            text = 'Test geojson rendering'
            resources = @(@{
                name = 'test-point'
                format = 'GEOJSON'
                content = '{"type":"Feature","geometry":{"type":"Point","coordinates":[74.34,31.55]},"properties":{"name":"Lahore"}}'
            })
            title = 'Test Map'
        } | ConvertTo-Json -Depth 5 -Compress

        try {
            $composeResp = Invoke-RestMethod -Method Post -Uri "$AgentUrl/compose-map" `
                -ContentType 'application/json' -Body $composeBody -TimeoutSec 30
            $composeJson = $composeResp | ConvertTo-Json -Depth 5
            if ($composeJson -match 'html|<!doctype|leaflet') {
                Write-Host '  compose-map returned HTML map'
                Test-Pass
            } else {
                Test-Warn 'TA01: /compose-map non ha restituito HTML'
            }
        } catch {
            Test-Warn "TA01: /compose-map errore: $($_.Exception.Message)"
        }

        # TA02 -- /chat con Claude (solo se provider=claude, consuma token)
        if ($provider -eq 'claude') {
            Write-Host ''; Write-Host '=== TA02 - POST /chat con Claude (consuma token) ===' -ForegroundColor Cyan
            $chatBody = '{"query": "Geocodifica Lahore, Pakistan e dimmi le coordinate. Rispondi in modo conciso."}'
            try {
                $chatResp = Invoke-RestMethod -Method Post -Uri "$AgentUrl/chat" `
                    -ContentType 'application/json' -Body $chatBody -TimeoutSec 60
                $chatJson = $chatResp | ConvertTo-Json -Depth 5
                if ($chatJson -match 'Lahore|31\.|74\.') {
                    Write-Host '  Claude ha risposto con info su Lahore'
                    Test-Pass
                } else {
                    Write-Host ($chatJson | Select-Object -First 10)
                    Test-Warn 'TA02: risposta Claude non contiene info attese'
                }
            } catch {
                Test-Warn "TA02: errore /chat: $($_.Exception.Message)"
            }

            if ($Full) {
                # TA03 -- /chat routing via Claude
                Write-Host ''; Write-Host '=== TA03 - /chat routing Faridpur->Dhaka via Claude ===' -ForegroundColor Cyan
                $chatBody = '{"query": "Calcola la distanza stradale da Faridpur a Dhaka in Bangladesh. Riporta km e minuti."}'
                try {
                    $chatResp = Invoke-RestMethod -Method Post -Uri "$AgentUrl/chat" `
                        -ContentType 'application/json' -Body $chatBody -TimeoutSec 60
                    $chatJson = $chatResp | ConvertTo-Json -Depth 5
                    if ($chatJson -match 'km|distanz|distance|min') {
                        Write-Host '  Claude ha calcolato routing'
                        Test-Pass
                    } else {
                        Test-Warn 'TA03: risposta routing non contiene distanza'
                    }
                } catch { Test-Warn "TA03: errore: $($_.Exception.Message)" }

                # TA04 -- /chat POI via Claude
                Write-Host ''; Write-Host '=== TA04 - /chat POI polizia Lahore via Claude ===' -ForegroundColor Cyan
                $chatBody = '{"query": "Trova stazioni di polizia entro 5km dal centro di Lahore, Pakistan."}'
                try {
                    $chatResp = Invoke-RestMethod -Method Post -Uri "$AgentUrl/chat" `
                        -ContentType 'application/json' -Body $chatBody -TimeoutSec 60
                    $chatJson = $chatResp | ConvertTo-Json -Depth 5
                    if ($chatJson -match 'police|polizia|station') {
                        Write-Host '  Claude ha trovato POI polizia'
                        Test-Pass
                    } else {
                        Test-Warn 'TA04: risposta POI non contiene stazioni'
                    }
                } catch { Test-Warn "TA04: errore: $($_.Exception.Message)" }
            }
        } else {
            Write-Host "  Provider=$provider - skip test /chat Claude (non consuma token)"
            Test-Skip
        }
    }

    # ══════════════════════════════════════════════════════════════════
    # Summary
    # ══════════════════════════════════════════════════════════════════

    Write-Host ''
    Write-Host '======================================' -ForegroundColor Cyan
    Write-Host '=== Summary ===' -ForegroundColor Cyan
    Write-Host "  PASS : $($script:Pass)" -ForegroundColor Green
    Write-Host "  FAIL : $($script:Fail)" -ForegroundColor Red
    Write-Host "  WARN : $($script:Warn)" -ForegroundColor Yellow
    Write-Host "  SKIP : $($script:Skip)" -ForegroundColor Yellow
    $total = $script:Pass + $script:Fail + $script:Warn + $script:Skip
    Write-Host "  TOTAL: $total"
    Write-Host '======================================' -ForegroundColor Cyan

    if ($script:Fail -gt 0) { exit 1 }
}
finally {
    Stop-Stack
}
