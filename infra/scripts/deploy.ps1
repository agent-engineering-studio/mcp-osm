# infra/scripts/deploy.ps1
[CmdletBinding()]
param(
  [string]$Environment = $(if ($env:ENVIRONMENT) { $env:ENVIRONMENT } else { 'dev' }),
  [string]$Location    = $(if ($env:AZURE_LOCATION) { $env:AZURE_LOCATION } else { 'westeurope' })
)
$ErrorActionPreference = 'Stop'

if (-not $env:AZURE_SUBSCRIPTION_ID) { throw "AZURE_SUBSCRIPTION_ID is required" }
$RG = if ($env:AZURE_RESOURCE_GROUP) { $env:AZURE_RESOURCE_GROUP } else { "rg-osm-mcp-$Environment" }

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
Write-Host "   MCP surface: https://${Fqdn}:8003/mcp"
