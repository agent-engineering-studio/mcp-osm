[CmdletBinding()]
param([string]$Environment = $(if ($env:ENVIRONMENT) { $env:ENVIRONMENT } else { 'dev' }))
$RG = if ($env:AZURE_RESOURCE_GROUP) { $env:AZURE_RESOURCE_GROUP } else { "rg-osm-mcp-$Environment" }
$confirm = Read-Host "Delete resource group $RG? [y/N]"
if ($confirm -ne 'y' -and $confirm -ne 'Y') { Write-Host "Aborted."; exit 1 }
az group delete -n $RG --yes --no-wait
Write-Host "▶ Resource group $RG deletion started (no-wait)"
