@description('osm-mcp Container App. Internal-only ingress (only the agent reaches it).')
param name string
param location string
param environmentId string
param image string
param osmContactEmail string = ''

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  properties: {
    environmentId: environmentId
    configuration: {
      ingress: {
        external: false
        targetPort: 8080
        transport: 'auto'
        allowInsecure: false
      }
    }
    template: {
      containers: [
        {
          name: name
          image: image
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'MCP_TRANSPORT', value: 'sse' }
            { name: 'MCP_HOST', value: '0.0.0.0' }
            { name: 'MCP_PORT', value: '8080' }
            { name: 'OSM_CONTACT_EMAIL', value: osmContactEmail }
            { name: 'NOMINATIM_URL', value: 'https://nominatim.openstreetmap.org' }
            { name: 'OVERPASS_URL', value: 'https://overpass-api.de/api/interpreter' }
            { name: 'OSRM_URL', value: 'https://router.project-osrm.org' }
            { name: 'MAP_TILE_URL', value: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png' }
          ]
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 3 }
    }
  }
}

output internalFqdn string = app.properties.configuration.ingress.fqdn
