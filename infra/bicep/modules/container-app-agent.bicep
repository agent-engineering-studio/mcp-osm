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
