@description('Log Analytics workspace for Container Apps logs.')
param name string
param location string

resource ws 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: name
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

output customerId string = ws.properties.customerId
output primarySharedKey string = ws.listKeys().primarySharedKey
