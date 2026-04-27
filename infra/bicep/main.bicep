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
    mcpUrl: 'https://${mcp.outputs.internalFqdn}/sse'
    llmProvider: llmProvider
    anthropicApiKey: anthropicApiKey
    azureAiProjectEndpoint: azureAiProjectEndpoint
    azureAiModelDeploymentName: azureAiModelDeploymentName
  }
}

output agentFqdn string = agent.outputs.fqdn
output mcpInternalFqdn string = mcp.outputs.internalFqdn
output managedIdentityClientId string = identity.outputs.clientId
