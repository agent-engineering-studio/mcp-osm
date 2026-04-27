# requests/postman/test-agent-chat.ps1 — newman runner (PowerShell)
[CmdletBinding()]
param(
  [string]$ApiHost    = $(if ($env:HOST)         { $env:HOST }         else { 'http://localhost:8002' }),
  [string]$McpHost    = $(if ($env:MCP_HOST)     { $env:MCP_HOST }     else { 'http://localhost:8003' }),
  [string]$OsmMcpHost = $(if ($env:OSM_MCP_HOST) { $env:OSM_MCP_HOST } else { 'http://localhost:8080' })
)
$ErrorActionPreference = 'Stop'
$Collection = Join-Path $PSScriptRoot 'osm-mcp-agent.postman_collection.json'

Write-Host "▶ Waiting for agent at $ApiHost..."
for ($i = 0; $i -lt 30; $i++) {
  try { Invoke-WebRequest "$ApiHost/health" -UseBasicParsing -TimeoutSec 2 | Out-Null; break } catch { Start-Sleep 2 }
}

Write-Host "▶ Running collection via newman..."
newman run $Collection `
  --env-var "host=$ApiHost" `
  --env-var "mcp_host=$McpHost" `
  --env-var "osm_mcp_host=$OsmMcpHost" `
  --reporters cli,json `
  --reporter-json-export (Join-Path $PSScriptRoot 'last-run.json')
