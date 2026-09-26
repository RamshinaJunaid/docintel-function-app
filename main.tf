# 1. Create a Resource Group for the Project
resource "azurerm_resource_group" "rg" {
  name     = "rg-doc-intelligence-prod-v2"
  location = "Central India"

  tags = {
    Department = "IT"
  }
}

# 2. Create the Virtual Network (VNet)
resource "azurerm_virtual_network" "vnet" {
  name                = "vnet-doc-intelligence"
  address_space       = ["10.0.0.0/16"]
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name

  tags = {
    Department = "IT"
  }
}

# 3. Create Subnet for App Service (Ingress Layer)
resource "azurerm_subnet" "subnet_app" {
  name                 = "subnet-app-service"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = ["10.0.1.0/24"]
  service_endpoints    = ["Microsoft.Storage", "Microsoft.AzureCosmosDB", "Microsoft.KeyVault"]

  delegation {
    name = "app-delegation"
    service_delegation {
      name    = "Microsoft.Web/serverFarms"
      actions = ["Microsoft.Network/virtualNetworks/subnets/action"]
    }
  }
}

# 4. Create Subnet for Azure Functions
resource "azurerm_subnet" "subnet_func" {
  name                 = "subnet-functions"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = ["10.0.2.0/24"]
  service_endpoints    = ["Microsoft.Storage", "Microsoft.AzureCosmosDB", "Microsoft.KeyVault"]

  delegation {
    name = "func-delegation"
    service_delegation {
      name    = "Microsoft.Web/serverFarms"
      actions = ["Microsoft.Network/virtualNetworks/subnets/action"]
    }
  }
}

# 5. Create Network Security Group for App Service Subnet
resource "azurerm_network_security_group" "nsg_app" {
  name                = "nsg-app-service"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name

  tags = {
    Department = "IT"
  }
}

# 6. Associate NSG with App Service Subnet
resource "azurerm_subnet_network_security_group_association" "asso_app" {
  subnet_id                 = azurerm_subnet.subnet_app.id
  network_security_group_id = azurerm_network_security_group.nsg_app.id
}

# 7. Create Network Security Group for Functions Subnet
resource "azurerm_network_security_group" "nsg_func" {
  name                = "nsg-functions"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name

  tags = {
    Department = "IT"
  }
}

# 8. Associate NSG with Functions Subnet
resource "azurerm_subnet_network_security_group_association" "asso_func" {
  subnet_id                 = azurerm_subnet.subnet_func.id
  network_security_group_id = azurerm_network_security_group.nsg_func.id
}

# 9. Create Storage Account for Documents
resource "azurerm_storage_account" "storage" {
  name                     = "stdocintel2026v2"
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"

  network_rules {
    default_action             = "Deny"
    bypass                     = ["AzureServices"]
    virtual_network_subnet_ids = [azurerm_subnet.subnet_func.id, azurerm_subnet.subnet_app.id]
    ip_rules                   = ["103.42.196.126"]
  }

  tags = {
    Department = "IT"
  }
}

# 10. Create Container for Raw Uploads
resource "azurerm_storage_container" "raw" {
  name                  = "raw-uploads"
  storage_account_name  = azurerm_storage_account.storage.name
  container_access_type = "private"
}

# 11. Create Container for Processed Documents
resource "azurerm_storage_container" "processed" {
  name                  = "processed-docs"
  storage_account_name  = azurerm_storage_account.storage.name
  container_access_type = "private"
}

# 12. Create Azure Key Vault for Secrets
data "azurerm_client_config" "current" {}

resource "azurerm_key_vault" "vault" {
  name                       = "kv-docintel-2026v2"
  location                   = azurerm_resource_group.rg.location
  resource_group_name        = azurerm_resource_group.rg.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  soft_delete_retention_days = 7

  access_policy {
    tenant_id = data.azurerm_client_config.current.tenant_id
    object_id = data.azurerm_client_config.current.object_id

    secret_permissions = [
      "Get", "List", "Set", "Delete", "Recover", "Backup", "Restore", "Purge"
    ]
  }

  tags = {
    Department = "IT"
  }
}

# 13. Create Azure Cosmos DB Account
resource "azurerm_cosmosdb_account" "db" {
  name                              = "cosmos-docintel-2026v2"
  location                          = azurerm_resource_group.rg.location
  resource_group_name               = azurerm_resource_group.rg.name
  offer_type                        = "Standard"
  kind                              = "GlobalDocumentDB"
  free_tier_enabled                 = false
  public_network_access_enabled     = false
  is_virtual_network_filter_enabled = true

  consistency_policy {
    consistency_level = "Session"
  }

  geo_location {
    location          = azurerm_resource_group.rg.location
    failover_priority = 0
  }

  virtual_network_rule {
    id = azurerm_subnet.subnet_func.id
  }

  tags = {
    Department = "IT"
  }
}

# 14. Create Cosmos DB SQL Database
resource "azurerm_cosmosdb_sql_database" "sqldb" {
  name                = "doc-metadata-db"
  resource_group_name = azurerm_resource_group.rg.name
  account_name        = azurerm_cosmosdb_account.db.name
}

# 15. Create Cosmos DB SQL Container
resource "azurerm_cosmosdb_sql_container" "sqlcontainer" {
  name                = "metadata"
  resource_group_name = azurerm_resource_group.rg.name
  account_name        = azurerm_cosmosdb_account.db.name
  database_name       = azurerm_cosmosdb_sql_database.sqldb.name
  partition_key_path  = "/id"
}

# 16. Storage Account specifically for Function App runtime state
resource "azurerm_storage_account" "fn_storage" {
  name                     = "stfuncapp2026v2"
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"

  tags = {
    Department = "IT"
  }
}

# 17. Basic Service Plan (Supports VNet Integration)
resource "azurerm_service_plan" "fn_plan" {
  name                = "plan-docintel-2026v2"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  os_type             = "Linux"
  sku_name            = "B1"

  tags = {
    Department = "IT"
  }
}

# 18. Linux Function App
resource "azurerm_linux_function_app" "fn" {
  name                       = "func-docintel-2026v2"
  resource_group_name        = azurerm_resource_group.rg.name
  location                   = azurerm_resource_group.rg.location
  storage_account_name       = azurerm_storage_account.fn_storage.name
  storage_account_access_key = azurerm_storage_account.fn_storage.primary_access_key
  service_plan_id            = azurerm_service_plan.fn_plan.id
  virtual_network_subnet_id  = azurerm_subnet.subnet_func.id

  site_config {
    vnet_route_all_enabled = true
    application_stack {
      python_version = "3.12"
    }
  }

  app_settings = {
    "AzureWebJobsStorage"      = azurerm_storage_account.fn_storage.primary_connection_string
    "DocStorageConn"           = azurerm_storage_account.storage.primary_connection_string
    "FUNCTIONS_WORKER_RUNTIME" = "python"
    "CosmosDBConnection"       = "@Microsoft.KeyVault(VaultName=${azurerm_key_vault.vault.name};SecretName=${azurerm_key_vault_secret.cosmos_secret.name})"
  }

  identity {
    type = "SystemAssigned"
  }

  tags = {
    Department = "IT"
  }
}

# 19. Store Cosmos DB connection string safely as a secret in Key Vault
resource "azurerm_key_vault_secret" "cosmos_secret" {
  name         = "CosmosDBConnection"
  value        = azurerm_cosmosdb_account.db.connection_strings[0]
  key_vault_id = azurerm_key_vault.vault.id
}

resource "azurerm_key_vault_access_policy" "function_policy" {
  key_vault_id = azurerm_key_vault.vault.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = azurerm_linux_function_app.fn.identity[0].principal_id

  secret_permissions = [
    "Get", "List"
  ]
}

# 20. Observability: Log Analytics & Application Insights
resource "azurerm_log_analytics_workspace" "law" {
  name                = "law-docintel-2026v2"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "PerGB2018"

  tags = {
    Department = "IT"
  }
}

resource "azurerm_application_insights" "appinsights" {
  name                = "appi-docintel-2026v2"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  workspace_id        = azurerm_log_analytics_workspace.law.id
  application_type    = "web"

  tags = {
    Department = "IT"
  }
}

# 21. Ingress Layer: Azure Container Registry
resource "azurerm_container_registry" "acr" {
  name                = "acrdocintel2026v2"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "Basic"
  admin_enabled       = true

  tags = {
    Department = "IT"
  }
}

# 22. Ingress Layer: Docker Web App (REST API)
resource "azurerm_linux_web_app" "webapp" {
  name                      = "app-docintel-ingress-2026v2"
  resource_group_name       = azurerm_resource_group.rg.name
  location                  = azurerm_resource_group.rg.location
  service_plan_id           = azurerm_service_plan.fn_plan.id
  virtual_network_subnet_id = azurerm_subnet.subnet_app.id

  site_config {
    always_on = true
  }

  tags = {
    Department = "IT"
  }
}

# 23. Cost Management Budget ($1.00 Alert)
resource "azurerm_consumption_budget_resource_group" "budget" {
  name              = "budget-docintel-alert"
  resource_group_id = azurerm_resource_group.rg.id
  amount            = 1.0
  time_grain        = "Annually"

  time_period {
    start_date = "2026-09-01T00:00:00Z"
    end_date   = "2027-09-01T00:00:00Z"
  }

  notification {
    enabled        = true
    threshold      = 100.0
    operator       = "GreaterThan"
    contact_emails = ["admin@example.com"]
  }
}