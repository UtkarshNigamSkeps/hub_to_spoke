"""
Spoke Configuration Data Model

Represents configuration for a single spoke deployment with validation.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple
from utils.helpers import (
    calculate_spoke_cidr,
    calculate_subnet_cidrs,
    validate_cidr,
    validate_ssh_public_key,
    validate_azure_vm_size,
    validate_resource_name,
    validate_spoke_id,
    sanitize_name,
    get_timestamp
)
from utils.exceptions import ValidationError


@dataclass
class SpokeConfiguration:
    """
    Configuration for a single spoke deployment

    Attributes:
        spoke_id: Unique spoke identifier (1, 2, 3, ...)
        client_name: Client/project name
        address_prefix: Spoke VNet CIDR (10.11.X.0/24)
        vm_subnet_prefix: VM subnet CIDR
        db_subnet_prefix: Database subnet CIDR
        kv_subnet_prefix: Key Vault subnet CIDR
        workspace_subnet_prefix: External workspace subnet CIDR
        vm_name: Virtual machine name
        vm_size: Azure VM size (e.g., Standard_B2s)
        admin_username: VM admin username
        ssh_public_key: SSH public key for VM access
        vnet_name: Virtual network name (optional, generated if not provided)
        backend_pool_name: Application Gateway backend pool name
        routing_rule_name: Application Gateway routing rule name
        created_at: Timestamp when configuration was created
        updated_at: Timestamp when configuration was last updated
    """

    # Identity
    spoke_id: int
    client_name: str

    # Network Configuration
    address_prefix: str
    vm_subnet_prefix: str
    db_subnet_prefix: str
    kv_subnet_prefix: str
    workspace_subnet_prefix: str

    # VM Configuration
    vm_name: str
    vm_size: str = "Standard_B2s"
    admin_username: str = "azureuser"
    ssh_public_key: str = ""

    # VNet Configuration (optional, generated if not provided)
    vnet_name: str = ""

    # Application Gateway Configuration
    backend_pool_name: str = ""
    routing_rule_name: str = ""

    # Metadata
    created_at: str = field(default_factory=get_timestamp)
    updated_at: str = field(default_factory=get_timestamp)

    @classmethod
    def from_dict(cls, data: Dict) -> 'SpokeConfiguration':
        """
        Create SpokeConfiguration from dictionary (API JSON payload)

        Args:
            data: Dictionary with configuration data

        Returns:
            SpokeConfiguration instance

        Raises:
            ValidationError: If required fields are missing

        Example:
            config = SpokeConfiguration.from_dict({
                "spoke_id": 1,
                "client_name": "AcmeFinance",
                "address_prefix": "10.11.1.0/24",
                "vm": {
                    "name": "acme-vm-01",
                    "size": "Standard_B2s",
                    "admin_username": "azureuser",
                    "ssh_public_key": "ssh-rsa ..."
                },
                "subnets": {
                    "vm_subnet_prefix": "10.11.1.0/26",
                    "db_subnet_prefix": "10.11.1.64/26",
                    "kv_subnet_prefix": "10.11.1.128/26",
                    "workspace_subnet_prefix": "10.11.1.192/26"
                },
                "application_gateway": {
                    "backend_pool_name": "acme-finance-pool",
                    "routing_rule_name": "acme-route"
                }
            })
        """
        # Extract nested structures
        vm_config = data.get('vm', {})
        subnet_config = data.get('subnets', {})
        agw_config = data.get('application_gateway', {})

        # Required fields check
        if 'spoke_id' not in data:
            raise ValidationError('spoke_id', None, 'spoke_id is required')

        if 'client_name' not in data:
            raise ValidationError('client_name', None, 'client_name is required')

        # Auto-calculate subnets if not provided
        spoke_id = data['spoke_id']
        address_prefix = data.get('address_prefix') or calculate_spoke_cidr(spoke_id)

        # Use provided subnets or calculate from address_prefix
        if not subnet_config:
            subnet_config = calculate_subnet_cidrs(address_prefix)

        return cls(
            spoke_id=spoke_id,
            client_name=data['client_name'],
            address_prefix=address_prefix,
            vm_subnet_prefix=subnet_config.get('vm_subnet_prefix', ''),
            db_subnet_prefix=subnet_config.get('db_subnet_prefix', ''),
            kv_subnet_prefix=subnet_config.get('kv_subnet_prefix', ''),
            workspace_subnet_prefix=subnet_config.get('workspace_subnet_prefix', ''),
            vm_name=vm_config.get('name', f"{sanitize_name(data['client_name'])}-vm-{spoke_id}"),
            vm_size=vm_config.get('size', 'Standard_B2s'),
            admin_username=vm_config.get('admin_username', 'azureuser'),
            ssh_public_key=vm_config.get('ssh_public_key', ''),
            backend_pool_name=agw_config.get('backend_pool_name', f"{sanitize_name(data['client_name'])}-pool"),
            routing_rule_name=agw_config.get('routing_rule_name', f"{sanitize_name(data['client_name'])}-route"),
        )

    def to_dict(self) -> Dict:
        """
        Convert configuration to dictionary for storage/API response

        Returns:
            Dictionary representation
        """
        return {
            "spoke_id": self.spoke_id,
            "client_name": self.client_name,
            "address_prefix": self.address_prefix,
            "subnets": {
                "vm_subnet_prefix": self.vm_subnet_prefix,
                "db_subnet_prefix": self.db_subnet_prefix,
                "kv_subnet_prefix": self.kv_subnet_prefix,
                "workspace_subnet_prefix": self.workspace_subnet_prefix
            },
            "vm": {
                "name": self.vm_name,
                "size": self.vm_size,
                "admin_username": self.admin_username,
                "ssh_public_key": self.ssh_public_key[:50] + "..." if len(self.ssh_public_key) > 50 else self.ssh_public_key
            },
            "application_gateway": {
                "backend_pool_name": self.backend_pool_name,
                "routing_rule_name": self.routing_rule_name
            },
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }

    def validate(self) -> Tuple[bool, List[str]]:
        """
        Validate all configuration fields

        Returns:
            (is_valid, list_of_error_messages)
        """
        errors = []

        # Validate spoke_id
        is_valid, error = validate_spoke_id(self.spoke_id)
        if not is_valid:
            errors.append(f"spoke_id: {error}")

        # Validate client_name
        is_valid, error = validate_resource_name(self.client_name)
        if not is_valid:
            errors.append(f"client_name: {error}")

        # Validate address_prefix
        if not validate_cidr(self.address_prefix):
            errors.append(f"address_prefix: Invalid CIDR notation '{self.address_prefix}'")
        else:
            # Check if it matches expected pattern
            expected_cidr = calculate_spoke_cidr(self.spoke_id)
            if self.address_prefix != expected_cidr:
                errors.append(
                    f"address_prefix: Expected '{expected_cidr}' for spoke_id {self.spoke_id}, "
                    f"got '{self.address_prefix}'"
                )

        # Validate subnet prefixes
        subnet_fields = [
            ('vm_subnet_prefix', self.vm_subnet_prefix),
            ('db_subnet_prefix', self.db_subnet_prefix),
            ('kv_subnet_prefix', self.kv_subnet_prefix),
            ('workspace_subnet_prefix', self.workspace_subnet_prefix)
        ]

        for field_name, subnet_cidr in subnet_fields:
            if not validate_cidr(subnet_cidr):
                errors.append(f"{field_name}: Invalid CIDR notation '{subnet_cidr}'")

        # Validate VM name
        is_valid, error = validate_resource_name(self.vm_name, max_length=64)
        if not is_valid:
            errors.append(f"vm_name: {error}")

        # Validate VM size
        if not validate_azure_vm_size(self.vm_size):
            errors.append(f"vm_size: Invalid Azure VM size '{self.vm_size}'")

        # Validate admin_username
        if not self.admin_username or len(self.admin_username) < 1:
            errors.append("admin_username: Cannot be empty")
        if len(self.admin_username) > 32:
            errors.append("admin_username: Must be 32 characters or less")

        # Validate SSH public key
        if self.ssh_public_key and not validate_ssh_public_key(self.ssh_public_key):
            errors.append(
                "ssh_public_key: Invalid format. Must start with 'ssh-rsa', 'ssh-ed25519', etc."
            )

        # Validate AGW names
        is_valid, error = validate_resource_name(self.backend_pool_name, max_length=80)
        if not is_valid:
            errors.append(f"backend_pool_name: {error}")

        is_valid, error = validate_resource_name(self.routing_rule_name, max_length=80)
        if not is_valid:
            errors.append(f"routing_rule_name: {error}")

        return len(errors) == 0, errors

    def validate_strict(self) -> None:
        """
        Validate configuration and raise exception if invalid

        Raises:
            ValidationError: If configuration is invalid
        """
        is_valid, errors = self.validate()
        if not is_valid:
            raise ValidationError(
                'configuration',
                self.to_dict(),
                f"Configuration validation failed: {'; '.join(errors)}"
            )

    def update_timestamp(self):
        """Update the updated_at timestamp"""
        self.updated_at = get_timestamp()

    def __repr__(self) -> str:
        return (
            f"<SpokeConfiguration(spoke_id={self.spoke_id}, "
            f"client_name='{self.client_name}', "
            f"address_prefix='{self.address_prefix}')>"
        )


def create_spoke_config_from_spoke_id(
    spoke_id: int,
    client_name: str,
    vm_size: str = "Standard_B2s",
    admin_username: str = "azureuser",
    ssh_public_key: str = ""
) -> SpokeConfiguration:
    """
    Quick helper to create spoke configuration with auto-calculated values

    Args:
        spoke_id: Spoke identifier
        client_name: Client/project name
        vm_size: Azure VM size
        admin_username: VM admin username
        ssh_public_key: SSH public key

    Returns:
        SpokeConfiguration instance with auto-calculated CIDRs

    Example:
        config = create_spoke_config_from_spoke_id(
            spoke_id=1,
            client_name="AcmeFinance",
            ssh_public_key="ssh-rsa ..."
        )
    """
    address_prefix = calculate_spoke_cidr(spoke_id)
    subnets = calculate_subnet_cidrs(address_prefix)

    return SpokeConfiguration(
        spoke_id=spoke_id,
        client_name=client_name,
        address_prefix=address_prefix,
        vm_subnet_prefix=subnets['vm_subnet_prefix'],
        db_subnet_prefix=subnets['db_subnet_prefix'],
        kv_subnet_prefix=subnets['kv_subnet_prefix'],
        workspace_subnet_prefix=subnets['workspace_subnet_prefix'],
        vm_name=f"{sanitize_name(client_name)}-vm-{spoke_id}",
        vm_size=vm_size,
        admin_username=admin_username,
        ssh_public_key=ssh_public_key,
        backend_pool_name=f"{sanitize_name(client_name)}-pool",
        routing_rule_name=f"{sanitize_name(client_name)}-route"
    )
