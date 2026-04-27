@description('Container Apps Environment hosting osm-mcp + osm-mcp-agent.')
param name string
param location string
param logAnalyticsCustomerId string
@secure()
param logAnalyticsKey string

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: name
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsCustomerId
        sharedKey: logAnalyticsKey
      }
    }
  }
}

output id string = env.id
