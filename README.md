# Hub-and-Spoke Azure Deployment Automation

Automated REST API for deploying Azure Hub-and-Spoke network architectures with VMs and Application Gateway configuration.

## Table of Contents

- [Overview](#overview)
- [Architecture Design](#architecture-design)
- [Project Structure](#project-structure)
- [Major Classes and Components](#major-classes-and-components)
- [API Endpoints](#api-endpoints)
- [Quick Start](#quick-start)
- [Docker Deployment](#docker-deployment)
- [Technologies](#technologies)
- [Key Features](#key-features)
- [Storage](#storage)
- [Rollback & Error Handling](#rollback--error-handling)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Overview

This Flask-based automation service dynamically creates spoke VNets in a hub-and-spoke architecture. Each spoke includes:
- Dedicated VNet (`10.11.X.0/24`) with auto-calculated CIDR blocks
- 4 subnets (VM, Database, KeyVault, Workspace) - each `/26` subnet
- Linux VM (Ubuntu 22.04 LTS) with SSH key authentication
- Automatic bidirectional VNet peering with Hub
- Application Gateway backend pool configuration
- Persistent deployment tracking with JSON storage
- **Intelligent rollback** with proper resource dependency handling

---

## Architecture Design

### 1. Network Architecture

```
┌─────────────────────────────────────────────────────────────┐
│   HUB VNET (10.0.0.0/16)                                    │
│   ┌─────────────────────────────────────────┐               │
│   │   Application Gateway                   │               │
│   │   - Backend Pools (per client)          │               │
│   │   - Routing Rules                       │               │
│   └─────────────────────────────────────────┘               │
└──────────┬──────────────────────────────────────────────────┘
           │
           │ VNet Peering (Bidirectional)
           │
    ┌──────┴──────────┬──────────────┬──────────────┐
    │                 │              │              │
    ▼                 ▼              ▼              ▼
┌─────────┐      ┌─────────┐   ┌─────────┐   ┌─────────┐
│ SPOKE 1 │      │ SPOKE 2 │   │ SPOKE 3 │   │ SPOKE N │
│10.11.1.0│      │10.11.2.0│   │10.11.3.0│   │10.11.N.0│
│   /24   │      │   /24   │   │   /24   │   │   /24   │
└─────────┘      └─────────┘   └─────────┘   └─────────┘
    │
    ├─ VM Subnet:        10.11.1.0/26   (0-63)
    ├─ DB Subnet:        10.11.1.64/26  (64-127)
    ├─ KeyVault Subnet:  10.11.1.128/26 (128-191)
    └─ Workspace Subnet: 10.11.1.192/26 (192-255)
```

### 2. Application Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         CLIENT                              │
└────────────────┬────────────────────────────────────────────┘
                 │ HTTP/HTTPS
                 ▼
┌─────────────────────────────────────────────────────────────┐
│                    FLASK APPLICATION                        │
│                       (Docker)                              │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              ROUTES (REST API Layer)                │   │
│  │  - spoke_routes.py: /api/spokes/*                   │   │
│  └──────────────┬──────────────────────────────────────┘   │
│                 │                                           │
│  ┌──────────────▼──────────────────────────────────────┐   │
│  │           CONTROLLERS (Business Logic)              │   │
│  │  - SpokeController: Validation, orchestration       │   │
│  └──────────────┬──────────────────────────────────────┘   │
│                 │                                           │
│  ┌──────────────▼──────────────────────────────────────┐   │
│  │       ORCHESTRATOR (Workflow Coordination)          │   │
│  │  - SpokeOrchestrator: 11-step deployment flow      │   │
│  └──┬─────────┬─────────┬─────────────┬────────────────┘   │
│     │         │         │             │                    │
│  ┌──▼─────┐ ┌▼──────┐ ┌▼──────────┐ ┌▼────────────────┐   │
│  │ Azure  │ │ Azure │ │ App GW    │ │ Storage Service │   │
│  │Network │ │Compute│ │ Service   │ │ (JSON File)     │   │
│  │Service │ │Service│ │           │ │                 │   │
│  └────┬───┘ └───┬───┘ └─────┬─────┘ └────────┬────────┘   │
│       │         │           │                 │            │
└───────┼─────────┼───────────┼─────────────────┼────────────┘
        │         │           │                 │
        ▼         ▼           ▼                 ▼
┌─────────────────────────────────────────────────────────────┐
│                    AZURE CLOUD                              │
│  - Virtual Networks      - Virtual Machines                 │
│  - Subnets              - Application Gateway               │
│  - VNet Peering         - Network Interfaces                │
└─────────────────────────────────────────────────────────────┘
```

### 3. Deployment Workflow (11 Steps)

```
┌──────────────────────────────────────────────────────────────┐
│                   DEPLOYMENT WORKFLOW                        │
└──────────────────────────────────────────────────────────────┘

1.  Validate Configuration
    └─ Validate spoke_id, client_name, CIDR blocks, VM size

2.  Create VNet
    └─ Create spoke VNet with calculated CIDR (10.11.X.0/24)

3.  Create Subnets
    └─ Create 4 subnets (VM, DB, KeyVault, Workspace)

4.  Create Network Interface
    └─ Create NIC in VM subnet

5.  Deploy Virtual Machine
    └─ Deploy Ubuntu 22.04 LTS VM with SSH key

6.  Wait for VM Ready
    └─ Poll VM status until running

7.  Get VM Private IP
    └─ Retrieve assigned private IP address

8.  Create VNet Peering
    └─ Establish bidirectional peering with Hub

9.  Verify Connectivity
    └─ Check peering status is "Connected"

10. Update Application Gateway
    └─ Add VM to backend pool with routing rule

11. Save to Storage
    └─ Persist deployment status to JSON file

    ┌────────────────────────────────────────────────────────┐
    │    On Failure: Asynchronous Rollback                  │
    │    (if ENABLE_ROLLBACK=true)                           │
    │                                                        │
    │    1. API returns error immediately (~30-60s)         │
    │    2. Background thread starts rollback               │
    │    3. Status: failed → rolling_back → rolled_back     │
    │                                                        │
    │    Rollback Order (respects dependencies):            │
    │    1. Application Gateway backend pool                │
    │    2. Virtual Machine (waits for completion)          │
    │    3. OS Disk (only if VM deleted)                    │
    │    4. Network Interface (5 retries, 60s waits)        │
    │    5. VNet (attempts even if NIC fails)               │
    └────────────────────────────────────────────────────────┘
```

**Deployment Status Values:**
- `pending` - Not yet started
- `in_progress` - Currently deploying
- `completed` - Deployment successful
- `failed` - Deployment failed (before rollback starts)
- `rolling_back` - Automatic rollback in progress (background)
- `rolled_back` - Rollback completed successfully
- `rollback_failed` - Rollback encountered errors (manual cleanup may be needed)
```

### 4. Data Flow

```
API Request → Route Handler → Controller → Orchestrator
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    │                         │                         │
                    ▼                         ▼                         ▼
            Azure Network Service     Azure Compute Service    AGW Service
                    │                         │                         │
                    └─────────────────────────┼─────────────────────────┘
                                              │
                                              ▼
                                    DeploymentStatus Model
                                              │
                                              ▼
                                    Storage Service (JSON)
                                              │
                                              ▼
                                    API Response (JSON)
```

---

## Project Structure

```
hub_to_spoke/
├── app.py                          # Flask application entry point
├── requirements.txt                # Python dependencies
├── Dockerfile                      # Container definition
├── docker-compose.yml              # Docker orchestration
├── .env                            # Environment variables (create from template)
│
├── config/
│   └── settings.py                # Singleton settings manager
│                                  # Loads Azure credentials from env vars
│
├── models/
│   ├── spoke_config.py            # SpokeConfiguration dataclass
│   │                              # Input configuration with validation
│   └── deployment_status.py       # DeploymentStatus dataclass
│                                  # Progress tracking with 11 steps
│
├── services/
│   ├── azure_network.py           # AzureNetworkService class
│   │                              # VNet, Subnet, Peering operations
│   ├── azure_compute.py           # AzureComputeService class
│   │                              # VM deployment and management
│   ├── agw_updater.py             # ApplicationGatewayService class
│   │                              # Backend pool and routing rule updates
│   ├── orchestrator.py            # SpokeOrchestrator class
│   │                              # Main workflow coordinator (11 steps)
│   └── storage_service.py         # StorageService class
│                                  # Thread-safe JSON file persistence
│
├── controllers/
│   └── spoke_controller.py        # SpokeController class
│                                  # Business logic, validation, formatting
│
├── routes/
│   └── spoke_routes.py            # Blueprint: /api/spokes
│                                  # REST API endpoint definitions
│
├── utils/
│   ├── logger.py                  # Structured logging with context
│   ├── exceptions.py              # Custom exception hierarchy
│   └── helpers.py                 # CIDR calculations, validators
│
├── api/
│   └── validators.py              # Request validation functions
│
└── storage/
    └── deployments.json           # Persistent deployment data
```

---

## Major Classes and Components

### 1. Models

#### `SpokeConfiguration` ([models/spoke_config.py](models/spoke_config.py))
**Purpose:** Data model representing a spoke deployment configuration

**Key Attributes:**
- `spoke_id` (int): Unique spoke identifier (1-254)
- `client_name` (str): Client/project name
- `address_prefix` (str): Spoke VNet CIDR (10.11.X.0/24)
- `vm_subnet_prefix`, `db_subnet_prefix`, `kv_subnet_prefix`, `workspace_subnet_prefix`: Subnet CIDRs
- `vm_name`, `vm_size`, `admin_username`, `ssh_public_key`: VM configuration
- `backend_pool_name`, `routing_rule_name`: Application Gateway resources

**Key Methods:**
- `from_dict(data)`: Create instance from API JSON payload
- `to_dict()`: Serialize to dictionary for API response
- `validate()`: Validate all fields (CIDR, VM size, SSH key, etc.)
- `validate_strict()`: Validate and raise exception if invalid

**Usage:**
```python
config = SpokeConfiguration(
    spoke_id=1,
    client_name="acme-corp",
    address_prefix="10.11.1.0/24",
    vm_subnet_prefix="10.11.1.0/26",
    # ... other fields
)
is_valid, errors = config.validate()
```

#### `DeploymentStatus` ([models/deployment_status.py](models/deployment_status.py))
**Purpose:** Track deployment progress and status through all 11 steps

**Key Attributes:**
- `spoke_id`, `client_name`: Identity
- `status`: Overall status (pending, in_progress, completed, failed, rolling_back)
- `vnet_name`, `vnet_id`, `vm_name`, `vm_id`, `vm_private_ip`: Created resources
- `deployment_steps`: List of DeploymentStep objects (11 steps)
- `progress_percentage`: Calculated from completed steps
- `error_message`, `failed_step`: Error tracking

**Key Methods:**
- `update_step(step_name, status)`: Update individual step status
- `mark_completed()`: Mark entire deployment as successful
- `mark_failed(step, error)`: Mark deployment as failed
- `get_progress_percentage()`: Calculate 0-100% progress
- `to_dict()`: Serialize for API response/storage

**Usage:**
```python
status = DeploymentStatus(spoke_id=1, client_name="acme-corp")
status.update_step("create_vnet", "in_progress")
status.update_step("create_vnet", "completed")
progress = status.get_progress_percentage()  # Returns 0-100
```

### 2. Services

#### `SpokeOrchestrator` ([services/orchestrator.py](services/orchestrator.py))
**Purpose:** Main coordinator for the complete spoke deployment workflow

**Key Responsibilities:**
- Execute 11-step deployment workflow in sequence
- Coordinate Azure Network, Compute, and AGW services
- Track progress at each step using DeploymentStatus
- Handle errors and trigger automatic rollback
- Save deployment state to persistent storage

**Key Methods:**
- `create_spoke(spoke_config)`: Main deployment method (11 steps)
- `rollback_spoke(spoke_config, deployment_status)`: Intelligent resource removal with dependency handling
- `get_spoke_status(spoke_id)`: Get current status from Azure
- `list_all_spokes()`: List all deployed spokes
- `_execute_step(status, step_name, func, *args)`: Execute step with tracking

**Usage:**
```python
orchestrator = SpokeOrchestrator()
deployment_status = orchestrator.create_spoke(spoke_config)
# Returns DeploymentStatus with all created resources
```

#### `AzureNetworkService` ([services/azure_network.py](services/azure_network.py))
**Purpose:** Manage Azure networking resources (VNets, Subnets, Peering)

**Key Methods:**
- `create_spoke_vnet(spoke_config)`: Create VNet with specified CIDR
- `create_subnets(spoke_config)`: Create 4 subnets within VNet
- `create_vnet_peering(vnet_name, vnet_id)`: Establish bidirectional peering with Hub
- `verify_vnet_connectivity(vnet_name)`: Check peering status
- `delete_spoke_vnet(vnet_name)`: Delete VNet (for rollback)
- `list_spoke_vnets()`: List all spoke VNets

**Dependencies:** Azure NetworkManagementClient

#### `AzureComputeService` ([services/azure_compute.py](services/azure_compute.py))
**Purpose:** Manage Azure compute resources (VMs, NICs, Disks)

**Key Methods:**
- `create_network_interface(nic_name, subnet_id, spoke_id)`: Create NIC in subnet
- `create_virtual_machine(spoke_config, nic_id)`: Deploy Ubuntu 22.04 LTS VM
- `wait_for_vm_ready(vm_name)`: Poll until VM is running
- `get_vm_private_ip(vm_name)`: Retrieve VM's private IP
- `get_vm_status(vm_name)`: Get current VM power state
- `delete_vm(vm_name, wait_timeout)`: Delete VM with timeout and verification
- `delete_nic(nic_name, wait_timeout)`: Delete NIC with timeout and verification
- `delete_disk(disk_name, wait_timeout)`: Delete managed disk with timeout

**Improvements:**
- All deletion methods now wait for completion before returning
- Existence checks before attempting deletion
- Verification after deletion to ensure resource is removed
- Proper handling of ResourceNotFoundError

**Dependencies:** Azure ComputeManagementClient

#### `ApplicationGatewayService` ([services/agw_updater.py](services/agw_updater.py))
**Purpose:** Manage Application Gateway backend pools and routing rules

**Key Methods:**
- `add_backend_pool(spoke_config, vm_private_ip)`: Add VM to AGW backend pool
- `remove_backend_pool(pool_name)`: Remove backend pool (for rollback)
- `create_routing_rule(spoke_config)`: Create routing rule for spoke
- `list_backend_pools()`: List all configured backend pools

**Dependencies:** Azure NetworkManagementClient

#### `StorageService` ([services/storage_service.py](services/storage_service.py))
**Purpose:** Thread-safe JSON file storage for deployment persistence

**Key Methods:**
- `save_deployment(deployment_status)`: Save deployment to JSON file
- `get_deployment(spoke_id)`: Retrieve deployment by spoke_id
- `list_deployments(status_filter)`: List all deployments with optional filter
- `delete_deployment(spoke_id)`: Remove deployment record

**Storage Location:** `storage/deployments.json`

**Thread Safety:** Uses file locking for concurrent access

### 3. Controllers

#### `SpokeController` ([controllers/spoke_controller.py](controllers/spoke_controller.py))
**Purpose:** Business logic layer between routes and services

**Key Responsibilities:**
- Validate API request payloads
- Build SpokeConfiguration from request data
- Coordinate with SpokeOrchestrator
- Format responses for API
- Handle errors and exceptions

**Key Methods:**
- `create_spoke(request_data)`: Process spoke creation request
- `get_spoke_status(spoke_id)`: Get spoke status
- `list_spokes(status_filter, limit)`: List all spokes with filtering
- `delete_spoke(spoke_id)`: Delete spoke and rollback resources
- `_build_spoke_config(request_data)`: Build configuration from API payload
- `_format_deployment_response(status)`: Format DeploymentStatus for API

**Usage:**
```python
controller = SpokeController()
result = controller.create_spoke({
    "spoke_id": 1,
    "client_name": "acme-corp",
    "ssh_public_key": "ssh-rsa ..."
})
```

### 4. Routes

#### `spoke_routes.py` ([routes/spoke_routes.py](routes/spoke_routes.py))
**Purpose:** REST API endpoint definitions using Flask Blueprint

**Endpoints:**
- `POST /api/spokes`: Create new spoke
- `GET /api/spokes/<id>`: Get spoke status
- `GET /api/spokes`: List all spokes
- `DELETE /api/spokes/<id>`: Delete/rollback spoke

**Features:**
- Request parsing and validation
- Error handling (404, 400, 500)
- JSON response formatting
- Blueprint pattern for modularity

### 5. Configuration

#### `Settings` ([config/settings.py](config/settings.py))
**Purpose:** Singleton configuration manager

**Environment Variables:**
- `AZURE_SUBSCRIPTION_ID`, `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`
- `RESOURCE_GROUP_NAME`, `HUB_VNET_NAME`, `APPLICATION_GATEWAY_NAME`
- `AZURE_LOCATION`, `ENABLE_ROLLBACK`

**Pattern:** Singleton ensures one configuration instance across the app

### 6. Utilities

#### Logging ([utils/logger.py](utils/logger.py))
- Structured logging with JSON format
- LogContext for spoke_id tracking across logs
- Different log levels (DEBUG, INFO, WARNING, ERROR)

#### Exceptions ([utils/exceptions.py](utils/exceptions.py))
- Custom exception hierarchy
- `DeploymentException`, `VNetCreationError`, `RollbackError`, etc.
- Consistent error handling across the application

#### Helpers ([utils/helpers.py](utils/helpers.py))
- `calculate_spoke_cidr(spoke_id)`: Calculate VNet CIDR (10.11.X.0/24)
- `calculate_subnet_cidrs(vnet_cidr)`: Calculate 4 subnet CIDRs
- `validate_cidr(cidr)`: Validate CIDR notation
- `validate_ssh_public_key(key)`: Validate SSH key format
- `validate_azure_vm_size(size)`: Validate Azure VM SKU

---

## API Endpoints

### Spoke Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/spokes` | Create new spoke |
| GET | `/api/spokes/<id>` | Get spoke status |
| GET | `/api/spokes` | List all spokes |
| DELETE | `/api/spokes/<id>` | Delete/rollback spoke |

### Root Endpoint

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | API information and version |

---

## API Examples with curl

### 1. Get API Information

```bash
curl -X GET http://localhost:5000/
```

**Response:**
```json
{
  "message": "Hub-and-Spoke Azure Deployment Automation API",
  "version": "1.0.0",
  "endpoints": {
    "spokes": "/api/spokes",
    "docs": "See README.md for API documentation"
  }
}
```

---

### 2. Create a New Spoke (Minimal)

**Request:**
```bash
curl -X POST http://localhost:5000/api/spokes \
  -H "Content-Type: application/json" \
  -d '{
    "spoke_id": 1,
    "client_name": "acme-corp",
    "ssh_public_key": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC... your-email@example.com"
  }'
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "spoke_id": 1,
    "client_name": "acme-corp",
    "status": "completed",
    "progress": 100,
    "vnet_name": "spoke-vnet-1",
    "vnet_id": "/subscriptions/.../spoke-vnet-1",
    "vm_name": "spoke-vm-1",
    "vm_id": "/subscriptions/.../spoke-vm-1",
    "vm_private_ip": "10.11.1.4",
    "deployment_steps": [
      {
        "step_name": "validate_config",
        "status": "completed",
        "started_at": "2025-12-11T10:00:00Z",
        "completed_at": "2025-12-11T10:00:01Z",
        "error_message": null
      },
      {
        "step_name": "create_vnet",
        "status": "completed",
        "started_at": "2025-12-11T10:00:01Z",
        "completed_at": "2025-12-11T10:00:15Z",
        "error_message": null
      }
      // ... 9 more steps
    ],
    "created_at": "2025-12-11T10:00:00Z",
    "updated_at": "2025-12-11T10:05:30Z",
    "completed_at": "2025-12-11T10:05:30Z",
    "error_message": null,
    "failed_step": null
  }
}
```

---

### 3. Create a Spoke (Full Configuration)

**Request:**
```bash
curl -X POST http://localhost:5000/api/spokes \
  -H "Content-Type: application/json" \
  -d '{
    "spoke_id": 2,
    "client_name": "contoso-finance",
    "vm_size": "Standard_D2s_v3",
    "admin_username": "azureadmin",
    "ssh_public_key": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC... admin@contoso.com",
    "subnets": {
      "vm_subnet_prefix": "10.11.2.0/26",
      "db_subnet_prefix": "10.11.2.64/26",
      "kv_subnet_prefix": "10.11.2.128/26",
      "workspace_subnet_prefix": "10.11.2.192/26"
    },
    "application_gateway": {
      "backend_pool_name": "contoso-finance-pool",
      "routing_rule_name": "contoso-finance-route"
    }
  }'
```

---

### 4. Get Spoke Status by ID

**Request:**
```bash
curl -X GET http://localhost:5000/api/spokes/1
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "spoke_id": 1,
    "exists": true,
    "vnet": {
      "name": "spoke-vnet-1",
      "id": "/subscriptions/.../spoke-vnet-1",
      "location": "eastus",
      "address_space": ["10.11.1.0/24"],
      "provisioning_state": "Succeeded",
      "tags": {
        "spoke_id": "1",
        "client_name": "acme-corp"
      }
    },
    "vm": {
      "name": "spoke-vm-1",
      "status": "running",
      "private_ip": "10.11.1.4"
    },
    "agw": {
      "backend_pool_configured": true,
      "backend_pool_name": "acme-corp-pool",
      "routing_rule_name": "acme-corp-route"
    }
  }
}
```

---

### 5. List All Spokes

**Request:**
```bash
curl -X GET http://localhost:5000/api/spokes
```

**Response:**
```json
{
  "status": "success",
  "data": [
    {
      "spoke_id": 1,
      "exists": true,
      "vnet": {
        "name": "spoke-vnet-1",
        "address_space": ["10.11.1.0/24"]
      },
      "vm": {
        "name": "spoke-vm-1",
        "status": "running",
        "private_ip": "10.11.1.4"
      }
    },
    {
      "spoke_id": 2,
      "exists": true,
      "vnet": {
        "name": "spoke-vnet-2",
        "address_space": ["10.11.2.0/24"]
      },
      "vm": {
        "name": "spoke-vm-2",
        "status": "running",
        "private_ip": "10.11.2.4"
      }
    }
  ],
  "count": 2
}
```

---

### 6. List Spokes with Filters

**Filter by Deployment Status:**
```bash
# Get all failed deployments
curl -X GET "http://localhost:5000/api/spokes?status=failed"

# Get all completed deployments
curl -X GET "http://localhost:5000/api/spokes?status=completed"

# Get in-progress deployments
curl -X GET "http://localhost:5000/api/spokes?status=in_progress"

# Get pending deployments
curl -X GET "http://localhost:5000/api/spokes?status=pending"

# Get deployments that are rolling back
curl -X GET "http://localhost:5000/api/spokes?status=rolling_back"
```

**Valid status values:** `completed`, `failed`, `in_progress`, `pending`, `rolling_back`

**Limit Results:**
```bash
curl -X GET "http://localhost:5000/api/spokes?limit=5"
```

**Combine Filters:**
```bash
curl -X GET "http://localhost:5000/api/spokes?status=failed&limit=10"
```

---

### 7. Delete a Spoke (Rollback)

**Request:**
```bash
curl -X DELETE http://localhost:5000/api/spokes/1
```

**Response:**
```json
{
  "status": "success",
  "message": "Spoke 1 deleted successfully",
  "data": {
    "spoke_id": 1,
    "rollback_status": "completed",
    "removed_resources": [
      "vnet",
      "subnets",
      "network_interface",
      "virtual_machine",
      "application_gateway_backend_pool"
    ]
  }
}
```

---

### 8. Error Responses

**Spoke Not Found (404):**
```bash
curl -X GET http://localhost:5000/api/spokes/999
```

```json
{
  "status": "error",
  "message": "Spoke 999 not found"
}
```

**Invalid spoke_id (400):**
```bash
curl -X POST http://localhost:5000/api/spokes \
  -H "Content-Type: application/json" \
  -d '{"spoke_id": 300, "client_name": "test"}'
```

```json
{
  "status": "error",
  "message": "Invalid spoke_id: 300. Must be between 1 and 254"
}
```

**Missing Required Fields (400):**
```bash
curl -X POST http://localhost:5000/api/spokes \
  -H "Content-Type: application/json" \
  -d '{"spoke_id": 1}'
```

```json
{
  "status": "error",
  "message": "client_name is required"
}
```

**Internal Server Error (500):**
```json
{
  "status": "error",
  "message": "Internal server error",
  "details": "Error message details"
}
```

---

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Azure subscription with Hub VNet and Application Gateway pre-deployed
- Azure Service Principal with Network & VM Contributor roles

### 1. Clone Repository

```bash
git clone <repository-url>
cd hub_to_spoke
```

### 2. Configure Environment

```bash
# Create environment file
cp .env.example .env

# Edit with your Azure credentials
nano .env
```

Required variables:
```bash
# Azure Authentication
AZURE_SUBSCRIPTION_ID=your-subscription-id
AZURE_TENANT_ID=your-tenant-id
AZURE_CLIENT_ID=your-client-id
AZURE_CLIENT_SECRET=your-client-secret

# Azure Resources
RESOURCE_GROUP_NAME=rg-hub-spoke
HUB_VNET_NAME=hub-vnet
APPLICATION_GATEWAY_NAME=hub-agw
AZURE_LOCATION=eastus

# Application Settings
ENABLE_ROLLBACK=true
FLASK_PORT=5000
FLASK_DEBUG=false
```

### 3. Deploy with Docker

```bash
# Build and start
docker-compose up -d --build

# Check status
docker-compose ps

# View logs
docker-compose logs -f

# Check health
curl http://localhost:5000/
```

API is now running at `http://localhost:5000`

---

## Docker Deployment

### Docker Commands

```bash
# Start services
docker-compose up -d

# Stop services
docker-compose down

# View logs
docker-compose logs -f

# Restart services
docker-compose restart

# Rebuild and start
docker-compose up -d --build

# Check status
docker-compose ps

# Execute commands in container
docker-compose exec app bash

# View resource usage
docker stats
```

### Docker Configuration

**Dockerfile Highlights:**
- Base image: Python 3.11-slim
- Non-root user for security
- Health check endpoint
- Volume mount for persistent storage

**docker-compose.yml:**
- Port mapping: 5000:5000
- Volume for storage persistence
- Environment variable injection
- Restart policy: unless-stopped

---

## Technologies

- **Python 3.11** - Application runtime
- **Flask 3.0** - REST API framework
- **Azure SDK for Python** - Azure service integration
  - `azure-identity` - Authentication
  - `azure-mgmt-network` - VNet, Subnet, Peering
  - `azure-mgmt-compute` - Virtual Machines
- **Docker** - Containerization
- **JSON** - Data persistence
- **python-dotenv** - Environment variable management

---

## Key Features

✅ **Automated Deployment** - Single API call creates complete infrastructure (11 steps)
✅ **Progress Tracking** - Real-time status with 11-step workflow
✅ **Persistent Storage** - JSON file storage survives restarts
✅ **Intelligent Rollback** - Removes resources with proper dependency handling
✅ **Structured Logging** - Context-aware logs with spoke_id
✅ **Input Validation** - Comprehensive validation (spoke_id, CIDR, SSH keys, VM size)
✅ **Security** - Non-root container, SSH keys, no hardcoded secrets
✅ **Thread-Safe Storage** - Concurrent deployment support
✅ **RESTful API** - Standard HTTP methods and JSON responses
✅ **Error Handling** - Detailed error messages and status codes
✅ **Docker Support** - One-command deployment
✅ **Ubuntu 22.04 LTS** - Latest long-term support Ubuntu release
✅ **Retry Logic** - Exponential backoff for NIC deletion with 3 attempts

---

## Storage

Deployments are persisted to `storage/deployments.json`:

```json
{
  "deployments": [
    {
      "spoke_id": 1,
      "client_name": "acme-corp",
      "status": "completed",
      "vnet_name": "spoke-vnet-1",
      "vnet_id": "/subscriptions/.../spoke-vnet-1",
      "vm_name": "spoke-vm-1",
      "vm_id": "/subscriptions/.../spoke-vm-1",
      "vm_private_ip": "10.11.1.4",
      "backend_pool_name": "acme-corp-pool",
      "routing_rule_name": "acme-corp-route",
      "progress_percentage": 100,
      "created_at": "2025-12-11T10:00:00Z",
      "updated_at": "2025-12-11T10:05:30Z",
      "completed_at": "2025-12-11T10:05:30Z",
      "deployment_steps": [
        {
          "step_name": "validate_config",
          "status": "completed",
          "started_at": "2025-12-11T10:00:00Z",
          "completed_at": "2025-12-11T10:00:01Z",
          "error_message": null
        }
        // ... 10 more steps
      ],
      "error_message": null,
      "failed_step": null
    }
  ]
}
```

---

## Rollback & Error Handling

### Intelligent Rollback System

The system features an **asynchronous** rollback mechanism that runs in the background when deployments fail. This ensures fast API responses while properly cleaning up resources.

#### Asynchronous Behavior

**When deployment fails:**
1. API returns error response immediately (~30-60 seconds after failure)
2. Rollback starts automatically in background thread
3. Client polls `GET /api/spokes/{id}` to check rollback progress
4. Status transitions: `failed` → `rolling_back` → `rolled_back` or `rollback_failed`

**API Response on Failure:**
```json
{
  "status": "error",
  "message": "Deployment failed: ...",
  "rollback_status": "queued",
  "note": "Automatic rollback is running in background. Check status: GET /api/spokes/2"
}
```

#### Rollback Process

**Rollback Order:**
1. **Application Gateway** - Remove backend pool first (no dependencies)
2. **Virtual Machine** - Delete and wait for completion (10 min timeout)
3. **OS Disk** - Only if VM deletion succeeded
4. **Network Interface** - Always check if NIC exists (even if not in completed steps)
   - Wait 15s after VM deletion if VM existed
   - Retry up to 5 times with 60s waits (handles Azure's 180s NIC reservation)
   - Detect and clean up orphan NICs from partial deployments
5. **VNet & Subnets** - Attempt deletion even if NIC has issues (will fail gracefully with detailed error)

**Key Features:**
- ✅ **Asynchronous Execution**: Runs in background, doesn't block API response
- ✅ **Dependency Tracking**: Tracks success of each deletion before proceeding
- ✅ **Timeout Handling**: Each resource has appropriate deletion timeout
- ✅ **Verification**: Verifies resources are actually deleted, not just assumed
- ✅ **Orphan Resource Detection**: Checks for resources that exist but weren't marked as "completed" (partial deployments)
- ✅ **Azure NIC Reservation Handling**: Waits out Azure's 180-second NIC reservation after failed VM creation
- ✅ **Graceful Failures**: Attempts VNet deletion even if NIC fails, with clear error messages
- ✅ **Error Collection**: Collects all errors and saves to deployment status for visibility
- ✅ **Thread Safety**: Uses daemon threads that don't block application shutdown

**Example Rollback Flow (Partial Deployment - Async):**
```
Client: POST /api/spokes {"spoke_id": 2, ...}
├─ Server: VNet created ✓
├─ Server: Subnets created ✓
├─ Server: NIC created ✓
├─ Server: VM creation fails (quota exceeded) ✗
├─ Server: Queues async rollback in background thread
└─ Response (after ~30 seconds): {
    "status": "error",
    "message": "Deployment failed: quota exceeded",
    "rollback_status": "queued",
    "note": "Check status: GET /api/spokes/2"
  }

Background Rollback Thread (runs for ~3-5 minutes):
├─ Check NIC (not in completed steps but exists - orphan)
├─ Delete NIC Attempt 1 → Fails (NicReservedForAnotherVm - Azure 180s hold)
├─ Wait 60 seconds...
├─ Delete NIC Attempt 2 → Fails (still reserved)
├─ Wait 60 seconds...
├─ Delete NIC Attempt 3 → Fails (still reserved)
├─ Wait 60 seconds...
├─ Delete NIC Attempt 4 (180s elapsed) → Success ✓
└─ Delete VNet → Success ✓

Client: GET /api/spokes/2 (poll for status)
└─ Response: {"deployment_status": "rolled_back", ...}
```

**Client Usage Pattern:**
```bash
# 1. Try deployment
curl -X POST http://localhost:5001/api/spokes -d '{"spoke_id": 2, ...}'
# Response: "rollback_status": "queued"

# 2. Wait a bit, then check status
sleep 10
curl http://localhost:5001/api/spokes/2
# Response: "deployment_status": "rolling_back"

# 3. Wait for rollback to complete (3-5 min for NIC reservation)
sleep 180
curl http://localhost:5001/api/spokes/2
# Response: "deployment_status": "rolled_back" (success!)
```

### Error Handling Features

- **Graceful Degradation**: Rollback continues even if some resources fail
- **Detailed Error Messages**: Each failure includes resource name and error details
- **Storage Persistence**: Failed deployments and rollback errors are saved to storage for visibility
- **Retry Logic**: Automatic retries for transient Azure API failures
- **Partial Deployment Cleanup**: Detects and cleans up orphan resources from partial deployments
- **Rollback Status Tracking**: Deployment status shows whether rollback succeeded, failed, or completed with warnings

---

## Troubleshooting

### Common Issues

#### 1. Rollback Fails - NIC Deletion
**Problem**: "NIC rollback: Failed to delete spoke-vm-X-nic"

**Root Cause**: When a VM deployment fails (e.g., quota exceeded), Azure reserves the NIC for **180 seconds** to prevent race conditions. This is an Azure platform behavior.

**Solution**: The system now includes:
- 15-second wait after VM deletion
- Up to 5 retry attempts with exponential backoff (60s wait between retries)
- Specific detection of "NicReservedForAnotherVm" error
- Specific detection of "NIC in use" errors
- Automatic orphan NIC detection for partial deployments

**Timeline**:
- Attempt 1: Immediate (fails with NicReservedForAnotherVm)
- Attempt 2: After 60 seconds
- Attempt 3: After 60 seconds (total 120s elapsed)
- Attempt 4: After 60 seconds (total 180s elapsed - should succeed)
- Attempt 5: After 60 seconds (fallback)

If rollback still fails, the deployment status will show detailed error messages. You can:
1. Check deployment status: `GET /api/spokes/<id>`
2. Wait 3-5 minutes for Azure's NIC reservation to expire
3. Retry deletion: `DELETE /api/spokes/<id>`

#### 1b. Partial Deployment with Orphan Resources
**Problem**: Deployment fails (e.g., quota exceeded) and leaves VNet/NIC resources

**How Fixed**: The rollback logic now checks for orphan resources even if they weren't marked as "completed" steps. For example:
- VNet creation completed ✅
- NIC creation started but not marked complete ⚠️
- VM creation failed due to quota ❌
- Rollback will detect and delete the orphan NIC + VNet

**Visibility**: Failed deployments are saved with full error details including rollback status.

#### 2. Cannot SSH to VM
**Problem**: "No line of sight to private IP address"

**Solution**: VMs are deployed with private IPs only. To connect:
- Use Azure Bastion (recommended)
- Set up VPN Gateway
- Deploy a jump box with public IP
- Use Azure Cloud Shell

#### 3. VM Deployment Timeout
**Problem**: VM creation takes too long

**Solution**: VM deployment can take 5-10 minutes. The system waits up to 10 minutes. Check Azure Portal for VM status.

---

## License

MIT
