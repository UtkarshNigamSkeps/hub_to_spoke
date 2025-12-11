# Azure Configuration Setup Guide

This guide explains what Azure credentials you need and **where to find them** to configure this Hub-and-Spoke automation application.

## Required Azure Credentials

You need to create a **Service Principal** in Azure with appropriate permissions. This Service Principal will be used by the application to create and manage Azure resources.

---

## Step 1: Get Your Azure Subscription ID and Tenant ID

### Azure Subscription ID
1. Go to [Azure Portal](https://portal.azure.com)
2. Search for **"Subscriptions"** in the top search bar
3. Click on your subscription name
4. Copy the **Subscription ID** (format: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`)

**Where to put it:** `.env` file → `AZURE_SUBSCRIPTION_ID`

### Azure Tenant ID
1. In Azure Portal, search for **"Azure Active Directory"** or **"Microsoft Entra ID"**
2. Click on **Overview** in the left menu
3. Copy the **Tenant ID** (format: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`)

**Where to put it:** `.env` file → `AZURE_TENANT_ID`

---

## Step 2: Create a Service Principal (App Registration)

A Service Principal is an identity that allows this application to authenticate and access Azure resources programmatically.

### Option A: Using Azure Portal (Easiest)

1. **Register an Application:**
   - Go to [Azure Portal](https://portal.azure.com)
   - Search for **"Azure Active Directory"** or **"Microsoft Entra ID"**
   - Click **"App registrations"** in the left menu
   - Click **"+ New registration"**
   - Enter a name (e.g., `hub-spoke-automation`)
   - Leave other settings as default
   - Click **"Register"**

2. **Get Application (Client) ID:**
   - After registration, you'll see the **Overview** page
   - Copy the **Application (client) ID** (format: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`)
   - **Where to put it:** `.env` file → `AZURE_CLIENT_ID`

3. **Create Client Secret:**
   - In the same App Registration, click **"Certificates & secrets"** in the left menu
   - Click **"+ New client secret"**
   - Add a description (e.g., `hub-spoke-secret`)
   - Choose an expiration period (e.g., 24 months)
   - Click **"Add"**
   - **IMPORTANT:** Copy the **Value** immediately (it will only show once!)
   - **Where to put it:** `.env` file → `AZURE_CLIENT_SECRET`

### Option B: Using Azure CLI (Faster)

```bash
# Login to Azure
az login

# Create Service Principal
az ad sp create-for-rbac --name "hub-spoke-automation" \
  --role "Contributor" \
  --scopes /subscriptions/{your-subscription-id}
```

This command will output:
```json
{
  "appId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",        ← AZURE_CLIENT_ID
  "displayName": "hub-spoke-automation",
  "password": "xxxxxxxxxxxxxxxxxxxxxxxxxxxx",              ← AZURE_CLIENT_SECRET
  "tenant": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"        ← AZURE_TENANT_ID
}
```

**IMPORTANT:** Save the `password` value immediately - you cannot retrieve it later!

---

## Step 3: Assign Permissions to Service Principal

The Service Principal needs permissions to create and manage Azure resources.

### Required Permissions:
- **Contributor** role on your Resource Group (or Subscription)
- **Network Contributor** role (for VNet operations)

### Assign Permissions via Azure Portal:

1. Go to your **Subscription** or **Resource Group**
2. Click **"Access control (IAM)"** in the left menu
3. Click **"+ Add"** → **"Add role assignment"**
4. Select **"Contributor"** role
5. Click **"Next"**
6. Click **"+ Select members"**
7. Search for your app name (`hub-spoke-automation`)
8. Select it and click **"Select"**
9. Click **"Review + assign"**

### Assign Permissions via Azure CLI:

```bash
# Get your Service Principal Object ID
SP_ID=$(az ad sp list --display-name "hub-spoke-automation" --query "[0].id" -o tsv)

# Assign Contributor role at subscription level
az role assignment create \
  --assignee $SP_ID \
  --role "Contributor" \
  --scope /subscriptions/{your-subscription-id}

# Or assign to specific resource group
az role assignment create \
  --assignee $SP_ID \
  --role "Contributor" \
  --scope /subscriptions/{your-subscription-id}/resourceGroups/{your-resource-group}
```

---

## Step 4: Create Required Azure Resources

Before running the application, you need to create these resources manually:

### 4.1 Create Resource Group

**Azure Portal:**
1. Search for **"Resource groups"**
2. Click **"+ Create"**
3. Enter name (e.g., `rg-hub-spoke-prod`)
4. Select region (e.g., `East US`)
5. Click **"Review + create"** → **"Create"**

**Azure CLI:**
```bash
az group create --name rg-hub-spoke-prod --location eastus
```

**Where to put it:** `.env` file → `RESOURCE_GROUP_NAME`

### 4.2 Create Hub Virtual Network

**Azure Portal:**
1. Search for **"Virtual networks"**
2. Click **"+ Create"**
3. Select your resource group
4. Name: `hub-vnet`
5. Region: Same as resource group
6. Address space: `10.0.0.0/16`
7. Add subnet:
   - Name: `agw-subnet`
   - Address range: `10.0.1.0/24`
8. Click **"Review + create"** → **"Create"**

**Azure CLI:**
```bash
# Create VNet
az network vnet create \
  --name hub-vnet \
  --resource-group rg-hub-spoke-prod \
  --location eastus \
  --address-prefix 10.0.0.0/16

# Create Application Gateway subnet
az network vnet subnet create \
  --name agw-subnet \
  --resource-group rg-hub-spoke-prod \
  --vnet-name hub-vnet \
  --address-prefix 10.0.1.0/24
```

**Where to put it:**
- `.env` file → `HUB_VNET_NAME=hub-vnet`
- `.env` file → `HUB_VNET_CIDR=10.0.0.0/16`
- `.env` file → `HUB_AGW_SUBNET_NAME=agw-subnet`

### 4.3 Create Application Gateway

**Azure Portal:**
1. Search for **"Application gateways"**
2. Click **"+ Create"**
3. Basics:
   - Name: `hub-agw`
   - Region: Same as VNet
   - Tier: Standard_v2 (or WAF_v2)
   - Virtual network: `hub-vnet`
   - Subnet: `agw-subnet`
4. Frontends:
   - Frontend IP: Public
   - Create new public IP
5. Backends: Skip for now (will be added by automation)
6. Configuration: Add default routing rule
7. Click **"Review + create"** → **"Create"**

**Azure CLI:**
```bash
# Create public IP
az network public-ip create \
  --name hub-agw-pip \
  --resource-group rg-hub-spoke-prod \
  --location eastus \
  --sku Standard

# Create Application Gateway
az network application-gateway create \
  --name hub-agw \
  --resource-group rg-hub-spoke-prod \
  --location eastus \
  --vnet-name hub-vnet \
  --subnet agw-subnet \
  --public-ip-address hub-agw-pip \
  --sku Standard_v2 \
  --capacity 2
```

**Where to put it:** `.env` file → `APPLICATION_GATEWAY_NAME=hub-agw`

---

## Step 5: Configure Your .env File

Now that you have all the values, update your `.env` file:

```bash
# ============================================
# REQUIRED: Azure Authentication
# ============================================
AZURE_SUBSCRIPTION_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx  # From Step 1
AZURE_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx        # From Step 1
AZURE_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx        # From Step 2
AZURE_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxx            # From Step 2 (keep secret!)

# ============================================
# REQUIRED: Azure Resource Configuration
# ============================================
RESOURCE_GROUP_NAME=rg-hub-spoke-prod                       # From Step 4.1
HUB_VNET_NAME=hub-vnet                                      # From Step 4.2
HUB_VNET_RESOURCE_GROUP=rg-hub-spoke-prod                   # Same as RESOURCE_GROUP_NAME
APPLICATION_GATEWAY_NAME=hub-agw                            # From Step 4.3
AZURE_LOCATION=eastus                                       # Your Azure region

# ============================================
# Hub Network Configuration
# ============================================
HUB_VNET_CIDR=10.0.0.0/16                                   # Your hub VNet CIDR
HUB_AGW_SUBNET_NAME=agw-subnet                              # Your AGW subnet name

# ============================================
# Spoke Network Configuration (Defaults OK)
# ============================================
SPOKE_BASE_CIDR=10.11.0.0/16                                # Base CIDR for all spokes
SPOKE_CIDR_PREFIX=10.11                                     # Spoke VNets will be 10.11.X.0/24
SPOKE_CIDR_SUFFIX=/24                                       # Each spoke gets /24 subnet

# ============================================
# Application Configuration (Defaults OK)
# ============================================
FLASK_ENV=production
FLASK_DEBUG=False
FLASK_HOST=0.0.0.0
FLASK_PORT=5001

LOG_LEVEL=INFO
LOG_FILE=logs/hub_spoke_deployment.log
ERROR_LOG_FILE=logs/errors.log

ENABLE_ROLLBACK=True
DEPLOYMENT_TIMEOUT_MINUTES=30
MAX_CONCURRENT_DEPLOYMENTS=3

DEPLOYMENTS_DB_FILE=storage/deployments.json
```

---

## Configuration Variables Explained

### Azure Authentication (ALL REQUIRED)

| Variable | Description | Where to Find |
|----------|-------------|---------------|
| `AZURE_SUBSCRIPTION_ID` | Your Azure subscription ID | Portal → Subscriptions |
| `AZURE_TENANT_ID` | Your Azure AD tenant ID | Portal → Azure Active Directory → Overview |
| `AZURE_CLIENT_ID` | Service Principal application ID | Portal → App registrations → Your app → Overview |
| `AZURE_CLIENT_SECRET` | Service Principal secret/password | Portal → App registrations → Your app → Certificates & secrets |

### Azure Resources (ALL REQUIRED)

| Variable | Description | Default | Notes |
|----------|-------------|---------|-------|
| `RESOURCE_GROUP_NAME` | Resource group name | - | Must exist before running |
| `HUB_VNET_NAME` | Hub virtual network name | - | Must exist before running |
| `HUB_VNET_RESOURCE_GROUP` | Hub VNet resource group | Same as RESOURCE_GROUP_NAME | Can be different if hub is in another RG |
| `APPLICATION_GATEWAY_NAME` | Application Gateway name | - | Must exist before running |
| `AZURE_LOCATION` | Azure region | `eastus` | e.g., eastus, westus2, westeurope |

### Network Configuration (Optional - Defaults Provided)

| Variable | Description | Default | Notes |
|----------|-------------|---------|-------|
| `HUB_VNET_CIDR` | Hub VNet CIDR block | `10.0.0.0/16` | Must match your actual hub VNet |
| `HUB_AGW_SUBNET_NAME` | AGW subnet name | `agw-subnet` | Must exist in hub VNet |
| `SPOKE_BASE_CIDR` | Base CIDR for all spokes | `10.11.0.0/16` | Plan for max 254 spokes |
| `SPOKE_CIDR_PREFIX` | First 2 octets for spokes | `10.11` | Each spoke gets 10.11.X.0/24 |
| `SPOKE_CIDR_SUFFIX` | Subnet mask for spokes | `/24` | Each spoke gets 256 IPs |

### Application Configuration (Optional - Defaults Provided)

| Variable | Description | Default |
|----------|-------------|---------|
| `FLASK_ENV` | Flask environment | `production` |
| `FLASK_DEBUG` | Enable Flask debug mode | `False` |
| `FLASK_HOST` | Flask bind address | `0.0.0.0` |
| `FLASK_PORT` | Flask port | `5001` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `ENABLE_ROLLBACK` | Auto-rollback on failure | `True` |
| `DEPLOYMENT_TIMEOUT_MINUTES` | Deployment timeout | `30` |
| `MAX_CONCURRENT_DEPLOYMENTS` | Max parallel deployments | `3` |

---

## Verification

After configuring your `.env` file, test the connection:

```bash
# Using Docker
docker-compose up -d
docker-compose logs -f

# Or locally
source venv/bin/activate
python app.py
```

Check the health endpoint:
```bash
curl http://localhost:5001/health/azure
```

You should see:
```json
{
  "status": "healthy",
  "azure_connectivity": "connected",
  "subscription_id": "xxxx...xxxx",
  "resource_group": "rg-hub-spoke-prod"
}
```

---

## Security Best Practices

1. **Never commit `.env` file** to version control (already in `.gitignore`)
2. **Rotate client secrets** regularly (every 6-12 months)
3. **Use least privilege** - only grant necessary permissions
4. **Store secrets securely** - consider Azure Key Vault for production
5. **Use separate Service Principals** for dev/staging/production environments

---

## Troubleshooting

### "Required environment variable 'X' is not set"
- Check your `.env` file exists in the project root
- Verify the variable name is spelled correctly
- Ensure no extra spaces around `=` sign

### "Authentication failed"
- Verify `AZURE_CLIENT_SECRET` is correct (copy-paste carefully)
- Check Service Principal has not expired
- Ensure Service Principal has Contributor role

### "Resource not found"
- Verify resource names match exactly (case-sensitive)
- Check resources exist in the specified region
- Confirm Service Principal has access to the resource group

### "Network already exists" or CIDR conflicts
- Check SPOKE_CIDR_PREFIX doesn't overlap with HUB_VNET_CIDR
- Ensure spoke IDs don't conflict with existing VNets
- Verify Application Gateway subnet is large enough (/24 or larger)

---

## Next Steps

Once your `.env` file is configured:

1. **Start the application:** `docker-compose up -d`
2. **Check health:** `curl http://localhost:5001/health`
3. **Create your first spoke:** See README.md for API examples
4. **Monitor logs:** `docker-compose logs -f` or check `logs/` directory

For detailed API usage and examples, see the main [README.md](README.md) file.
