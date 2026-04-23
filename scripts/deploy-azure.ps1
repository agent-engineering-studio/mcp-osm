<#
.SYNOPSIS
  Deploy osm-mcp + osm-agent to Azure Container Apps.

.DESCRIPTION
  Creates (if missing) an Azure resource group, ACR, and Container Apps
  environment; optionally builds + pushes both container images; then
  creates/updates two Container Apps and wires the agent to the MCP internal
  FQDN over HTTP/SSE.

.PARAMETER SkipBuild
  Skip docker build + push — useful when images already exist in ACR.

.PARAMETER SkipLogin
  Skip "az login" — useful inside CI where OIDC already authenticated.

.EXAMPLE
  # Full deploy (login, build, push, deploy)
  ./scripts/deploy-azure.ps1

.EXAMPLE
  # Re-deploy existing images (useful for CI with federated credentials)
  ./scripts/deploy-azure.ps1 -SkipLogin -SkipBuild
#>

[CmdletBinding()]
param(
  [switch] $SkipBuild,
  [switch] $SkipLogin
)

$ErrorActionPreference = "Stop"
$InformationPreference  = "Continue"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir   = Resolve-Path (Join-Path $ScriptDir "..")
Push-Location $RootDir
try {
  # ── Load .env ────────────────────────────────────────────────────────────
  $envFile = Join-Path $RootDir ".env"
  if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
      if ($_ -match '^\s*#' -or -not $_.Trim()) { return }
      $parts = $_ -split '=', 2
      if ($parts.Length -eq 2) {
        $key = $parts[0].Trim()
        $val = $parts[1].Trim().Trim('"')
        if (-not [Environment]::GetEnvironmentVariable($key)) {
          [Environment]::SetEnvironmentVariable($key, $val)
        }
      }
    }
  }

  function Get-Var($name, $default = $null) {
    $v = [Environment]::GetEnvironmentVariable($name)
    if (-not [string]::IsNullOrWhiteSpace($v)) { return $v }
    return $default
  }
  function Require-Var($name) {
    $v = Get-Var $name
    if (-not $v) { throw "Required env var $name is not set." }
    return $v
  }

  $AZURE_RESOURCE_GROUP     = Get-Var 'AZURE_RESOURCE_GROUP'      'rg-osm-mcp'
  $AZURE_LOCATION           = Get-Var 'AZURE_LOCATION'            'westeurope'
  $AZURE_CONTAINER_APP_ENV  = Get-Var 'AZURE_CONTAINER_APP_ENV'   'cae-osm-mcp'
  $AZURE_MCP_APP_NAME       = Get-Var 'AZURE_MCP_APP_NAME'        'osm-mcp'
  $AZURE_AGENT_APP_NAME     = Get-Var 'AZURE_AGENT_APP_NAME'      'osm-agent'
  $IMAGE_TAG                = Get-Var 'IMAGE_TAG'                 'latest'
  $OLLAMA_LLM_MODEL         = Get-Var 'OLLAMA_LLM_MODEL'          'qwen2.5:7b'
  $AZURE_ACR_NAME           = Require-Var 'AZURE_ACR_NAME'
  $OLLAMA_BASE_URL          = Require-Var 'OLLAMA_BASE_URL'
  $AZURE_SUBSCRIPTION_ID    = Get-Var 'AZURE_SUBSCRIPTION_ID'

  function Log($msg) { Write-Host "[deploy] $msg" -ForegroundColor Cyan }

  # ── 1. Azure login / subscription ───────────────────────────────────────
  if (-not $SkipLogin) {
    Log "Azure login"
    az login --output none
  }
  if ($AZURE_SUBSCRIPTION_ID) {
    az account set --subscription $AZURE_SUBSCRIPTION_ID
  }

  Log "Ensure containerapp extension + providers"
  az extension add --name containerapp --upgrade --only-show-errors | Out-Null
  az provider register --namespace Microsoft.App --wait | Out-Null
  az provider register --namespace Microsoft.OperationalInsights --wait | Out-Null

  # ── 2. Resource group + ACR + CAE ────────────────────────────────────────
  Log "Resource group: $AZURE_RESOURCE_GROUP ($AZURE_LOCATION)"
  az group create -n $AZURE_RESOURCE_GROUP -l $AZURE_LOCATION --output none

  Log "Azure Container Registry: $AZURE_ACR_NAME"
  $acrExists = az acr show -n $AZURE_ACR_NAME -g $AZURE_RESOURCE_GROUP --only-show-errors 2>$null
  if (-not $acrExists) {
    az acr create -n $AZURE_ACR_NAME -g $AZURE_RESOURCE_GROUP `
      -l $AZURE_LOCATION --sku Basic --admin-enabled true --output none
  }
  $ACR_LOGIN_SERVER = az acr show -n $AZURE_ACR_NAME --query loginServer -o tsv

  Log "Container Apps environment: $AZURE_CONTAINER_APP_ENV"
  $caeExists = az containerapp env show -n $AZURE_CONTAINER_APP_ENV -g $AZURE_RESOURCE_GROUP --only-show-errors 2>$null
  if (-not $caeExists) {
    az containerapp env create `
      -n $AZURE_CONTAINER_APP_ENV `
      -g $AZURE_RESOURCE_GROUP `
      -l $AZURE_LOCATION --output none
  }

  $MCP_IMAGE   = "$ACR_LOGIN_SERVER/$AZURE_MCP_APP_NAME`:$IMAGE_TAG"
  $AGENT_IMAGE = "$ACR_LOGIN_SERVER/$AZURE_AGENT_APP_NAME`:$IMAGE_TAG"

  if (-not $SkipBuild) {
    Log "ACR login (docker)"
    az acr login --name $AZURE_ACR_NAME

    Log "Build + push MCP image: $MCP_IMAGE"
    docker build -t $MCP_IMAGE ./osm-mcp
    if ($LASTEXITCODE -ne 0) { throw "docker build (osm-mcp) failed" }
    docker push $MCP_IMAGE
    if ($LASTEXITCODE -ne 0) { throw "docker push (osm-mcp) failed" }

    Log "Build + push Agent image: $AGENT_IMAGE"
    docker build -t $AGENT_IMAGE ./osm-agent
    if ($LASTEXITCODE -ne 0) { throw "docker build (osm-agent) failed" }
    docker push $AGENT_IMAGE
    if ($LASTEXITCODE -ne 0) { throw "docker push (osm-agent) failed" }
  }

  $ACR_USERNAME = az acr credential show -n $AZURE_ACR_NAME --query username -o tsv
  $ACR_PASSWORD = az acr credential show -n $AZURE_ACR_NAME --query 'passwords[0].value' -o tsv

  # ── 4. MCP Container App (internal ingress) ─────────────────────────────
  Log "Deploying MCP app: $AZURE_MCP_APP_NAME"
  $mcpExists = az containerapp show -n $AZURE_MCP_APP_NAME -g $AZURE_RESOURCE_GROUP --only-show-errors 2>$null
  if ($mcpExists) {
    az containerapp update `
      -n $AZURE_MCP_APP_NAME -g $AZURE_RESOURCE_GROUP `
      --image $MCP_IMAGE `
      --set-env-vars MCP_TRANSPORT=sse MCP_HOST=0.0.0.0 MCP_PORT=8080 `
      --output none
  } else {
    az containerapp create `
      -n $AZURE_MCP_APP_NAME -g $AZURE_RESOURCE_GROUP `
      --environment $AZURE_CONTAINER_APP_ENV `
      --image $MCP_IMAGE `
      --target-port 8080 `
      --ingress internal `
      --min-replicas 1 --max-replicas 3 `
      --cpu 0.5 --memory 1.0Gi `
      --registry-server $ACR_LOGIN_SERVER `
      --registry-username $ACR_USERNAME `
      --registry-password $ACR_PASSWORD `
      --env-vars MCP_TRANSPORT=sse MCP_HOST=0.0.0.0 MCP_PORT=8080 `
      --output none
  }

  $MCP_INTERNAL_FQDN = az containerapp show -n $AZURE_MCP_APP_NAME -g $AZURE_RESOURCE_GROUP `
    --query properties.configuration.ingress.fqdn -o tsv
  $MCP_URL = "http://$MCP_INTERNAL_FQDN/sse"
  Log "MCP reachable at: $MCP_URL"

  # ── 5. Agent Container App (external ingress) ───────────────────────────
  Log "Deploying Agent app: $AZURE_AGENT_APP_NAME"
  $agentExists = az containerapp show -n $AZURE_AGENT_APP_NAME -g $AZURE_RESOURCE_GROUP --only-show-errors 2>$null
  if ($agentExists) {
    az containerapp update `
      -n $AZURE_AGENT_APP_NAME -g $AZURE_RESOURCE_GROUP `
      --image $AGENT_IMAGE `
      --set-env-vars `
        OLLAMA_BASE_URL=$OLLAMA_BASE_URL `
        OLLAMA_LLM_MODEL=$OLLAMA_LLM_MODEL `
        MCP_SERVER_URL=$MCP_URL `
      --output none
  } else {
    az containerapp create `
      -n $AZURE_AGENT_APP_NAME -g $AZURE_RESOURCE_GROUP `
      --environment $AZURE_CONTAINER_APP_ENV `
      --image $AGENT_IMAGE `
      --target-port 8090 `
      --ingress external `
      --min-replicas 1 --max-replicas 5 `
      --cpu 1.0 --memory 2.0Gi `
      --registry-server $ACR_LOGIN_SERVER `
      --registry-username $ACR_USERNAME `
      --registry-password $ACR_PASSWORD `
      --env-vars `
        OLLAMA_BASE_URL=$OLLAMA_BASE_URL `
        OLLAMA_LLM_MODEL=$OLLAMA_LLM_MODEL `
        MCP_SERVER_URL=$MCP_URL `
      --output none
  }

  $AGENT_FQDN = az containerapp show -n $AZURE_AGENT_APP_NAME -g $AZURE_RESOURCE_GROUP `
    --query properties.configuration.ingress.fqdn -o tsv

  Log ("─" * 64)
  Log "Deployment complete."
  Log "Agent URL : https://$AGENT_FQDN"
  Log "Health    : https://$AGENT_FQDN/health"
  Log "Tools     : https://$AGENT_FQDN/tools"
  Log "Chat      : POST https://$AGENT_FQDN/chat  { `"message`": `"...`" }"
  Log ("─" * 64)
}
finally {
  Pop-Location
}
