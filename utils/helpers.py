"""
Helper Utilities for Hub-Spoke Automation

Common utility functions used across the application:
- CIDR calculation
- Resource name generation
- Validation functions
- Time utilities
"""

import re
import ipaddress
from typing import Dict, List, Tuple
from datetime import datetime, timezone
import time


# ============================================================================
# CIDR Calculation Functions
# ============================================================================

def calculate_spoke_cidr(spoke_id: int, base_prefix: str = "10.11") -> str:
    """
    Calculate spoke CIDR from spoke ID

    Args:
        spoke_id: Spoke identifier (1, 2, 3, ...)
        base_prefix: Base network prefix (default: "10.11")

    Returns:
        CIDR notation: "10.11.X.0/24"

    Example:
        calculate_spoke_cidr(1) -> "10.11.1.0/24"
        calculate_spoke_cidr(5) -> "10.11.5.0/24"
    """
    if spoke_id < 1 or spoke_id > 255:
        raise ValueError(f"spoke_id must be between 1 and 255, got {spoke_id}")

    return f"{base_prefix}.{spoke_id}.0/24"


def calculate_subnet_cidrs(spoke_cidr: str) -> Dict[str, str]:
    """
    Calculate 4 subnet CIDRs from spoke CIDR

    Each spoke (10.11.X.0/24) is divided into 4 /26 subnets:
    - VM Subnet: 10.11.X.0/26 (64 IPs)
    - DB Subnet: 10.11.X.64/26 (64 IPs)
    - Key Vault Subnet: 10.11.X.128/26 (64 IPs)
    - Workspace Subnet: 10.11.X.192/26 (64 IPs)

    Args:
        spoke_cidr: Spoke CIDR in format "10.11.X.0/24"

    Returns:
        Dictionary with subnet CIDRs

    Example:
        calculate_subnet_cidrs("10.11.1.0/24") -> {
            "vm_subnet": "10.11.1.0/26",
            "db_subnet": "10.11.1.64/26",
            "kv_subnet": "10.11.1.128/26",
            "workspace_subnet": "10.11.1.192/26"
        }
    """
    try:
        network = ipaddress.IPv4Network(spoke_cidr, strict=False)
        base_ip = str(network.network_address)
        parts = base_ip.split('.')

        return {
            "vm_subnet_prefix": f"{parts[0]}.{parts[1]}.{parts[2]}.0/26",
            "db_subnet_prefix": f"{parts[0]}.{parts[1]}.{parts[2]}.64/26",
            "kv_subnet_prefix": f"{parts[0]}.{parts[1]}.{parts[2]}.128/26",
            "workspace_subnet_prefix": f"{parts[0]}.{parts[1]}.{parts[2]}.192/26"
        }
    except Exception as e:
        raise ValueError(f"Invalid CIDR notation '{spoke_cidr}': {str(e)}")


def validate_cidr(cidr: str) -> bool:
    """
    Validate CIDR notation

    Args:
        cidr: CIDR string (e.g., "10.11.1.0/24")

    Returns:
        True if valid, False otherwise
    """
    try:
        ipaddress.IPv4Network(cidr, strict=False)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def cidr_overlaps(cidr1: str, cidr2: str) -> bool:
    """
    Check if two CIDR ranges overlap

    Args:
        cidr1: First CIDR
        cidr2: Second CIDR

    Returns:
        True if they overlap, False otherwise
    """
    try:
        network1 = ipaddress.IPv4Network(cidr1, strict=False)
        network2 = ipaddress.IPv4Network(cidr2, strict=False)
        return network1.overlaps(network2)
    except Exception:
        return False


def cidr_contains_ip(cidr: str, ip: str) -> bool:
    """
    Check if an IP address is within a CIDR range

    Args:
        cidr: CIDR notation
        ip: IP address

    Returns:
        True if IP is in CIDR range
    """
    try:
        network = ipaddress.IPv4Network(cidr, strict=False)
        ip_addr = ipaddress.IPv4Address(ip)
        return ip_addr in network
    except Exception:
        return False


# ============================================================================
# Resource Name Generation Functions
# ============================================================================

def generate_vnet_name(spoke_id: int, prefix: str = "spoke-vnet") -> str:
    """
    Generate VNet name from spoke ID

    Args:
        spoke_id: Spoke identifier
        prefix: Name prefix

    Returns:
        VNet name: "spoke-vnet-1"
    """
    return f"{prefix}-{spoke_id}"


def generate_subnet_name(spoke_id: int, subnet_type: str) -> str:
    """
    Generate subnet name

    Args:
        spoke_id: Spoke identifier
        subnet_type: Type of subnet (vm, db, kv, workspace)

    Returns:
        Subnet name: "spoke-1-vm-subnet"
    """
    subnet_type = subnet_type.lower().replace('_', '-')
    return f"spoke-{spoke_id}-{subnet_type}-subnet"


def generate_vm_name(client_name: str, spoke_id: int, suffix: str = "vm") -> str:
    """
    Generate VM name from client name and spoke ID

    Args:
        client_name: Client/project name
        spoke_id: Spoke identifier
        suffix: VM suffix

    Returns:
        VM name: "acmefinance-spoke1-vm"
    """
    sanitized_name = sanitize_name(client_name)
    return f"{sanitized_name}-spoke{spoke_id}-{suffix}"


def generate_nic_name(vm_name: str) -> str:
    """Generate network interface name from VM name"""
    return f"{vm_name}-nic"


def generate_peering_name(source_vnet: str, target_vnet: str) -> str:
    """
    Generate VNet peering name

    Args:
        source_vnet: Source VNet name
        target_vnet: Target VNet name

    Returns:
        Peering name: "hub-vnet-to-spoke-vnet-1"
    """
    return f"{source_vnet}-to-{target_vnet}"


def sanitize_name(name: str, max_length: int = 64) -> str:
    """
    Sanitize resource name according to Azure naming rules

    Azure rules:
    - Alphanumeric and hyphens only
    - Must start with letter or number
    - Must end with letter or number
    - Lowercase recommended

    Args:
        name: Original name
        max_length: Maximum length

    Returns:
        Sanitized name
    """
    # Convert to lowercase
    name = name.lower()

    # Replace invalid characters with hyphens
    name = re.sub(r'[^a-z0-9-]', '-', name)

    # Remove consecutive hyphens
    name = re.sub(r'-+', '-', name)

    # Remove leading/trailing hyphens
    name = name.strip('-')

    # Ensure it starts with alphanumeric
    if name and not name[0].isalnum():
        name = 'a' + name

    # Truncate to max length
    if len(name) > max_length:
        name = name[:max_length].rstrip('-')

    return name or 'default'


# ============================================================================
# Validation Functions
# ============================================================================

def validate_spoke_id(spoke_id: int) -> bool:
    """
    Validate spoke ID

    Args:
        spoke_id: Spoke identifier

    Returns:
        True if valid (1-254), False otherwise
    """
    return isinstance(spoke_id, int) and 1 <= spoke_id <= 254


def validate_client_name(client_name: str) -> bool:
    """
    Validate client name

    Rules:
    - 3-50 characters
    - Alphanumeric with hyphens
    - Cannot start or end with hyphen
    - Cannot have consecutive hyphens

    Args:
        client_name: Client name string

    Returns:
        True if valid, False otherwise
    """
    if not client_name or not isinstance(client_name, str):
        return False

    # Length check
    if len(client_name) < 3 or len(client_name) > 50:
        return False

    # Pattern: alphanumeric with hyphens, not starting/ending with hyphen
    pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?$'
    if not re.match(pattern, client_name):
        return False

    # No consecutive hyphens
    if '--' in client_name:
        return False

    return True


# ============================================================================
# Validation Functions
# ============================================================================

def validate_ssh_public_key(key: str) -> bool:
    """
    Validate SSH public key format

    Args:
        key: SSH public key string

    Returns:
        True if valid format
    """
    if not key:
        return False

    key = key.strip()

    # Check for common SSH key types
    valid_prefixes = ['ssh-rsa', 'ssh-ed25519', 'ssh-dss', 'ecdsa-sha2-nistp256']

    return any(key.startswith(prefix) for prefix in valid_prefixes)


def validate_azure_vm_size(size: str) -> bool:
    """
    Validate Azure VM size

    Args:
        size: VM size (e.g., "Standard_B2s")

    Returns:
        True if valid format
    """
    if not size:
        return False

    # Basic format validation
    # Full list would be too long, so we check format
    pattern = r'^(Basic_|Standard_|Standard_[A-Z]+\d+)[A-Za-z0-9_]*$'
    return bool(re.match(pattern, size))


def validate_resource_name(name: str, min_length: int = 1, max_length: int = 64) -> Tuple[bool, str]:
    """
    Validate Azure resource name

    Args:
        name: Resource name
        min_length: Minimum length
        max_length: Maximum length

    Returns:
        (is_valid, error_message)
    """
    if not name:
        return False, "Name cannot be empty"

    if len(name) < min_length:
        return False, f"Name must be at least {min_length} characters"

    if len(name) > max_length:
        return False, f"Name must be at most {max_length} characters"

    # Check valid characters
    if not re.match(r'^[a-zA-Z0-9-_]+$', name):
        return False, "Name can only contain alphanumeric characters, hyphens, and underscores"

    # Check starts and ends with alphanumeric
    if not name[0].isalnum() or not name[-1].isalnum():
        return False, "Name must start and end with alphanumeric character"

    return True, ""


def validate_spoke_id(spoke_id: int) -> Tuple[bool, str]:
    """
    Validate spoke ID

    Args:
        spoke_id: Spoke identifier

    Returns:
        (is_valid, error_message)
    """
    if not isinstance(spoke_id, int):
        return False, "Spoke ID must be an integer"

    if spoke_id < 1:
        return False, "Spoke ID must be positive"

    if spoke_id > 255:
        return False, "Spoke ID must be 255 or less (CIDR limitation)"

    return True, ""


# ============================================================================
# Time Utilities
# ============================================================================

def get_timestamp() -> str:
    """
    Get current timestamp in ISO 8601 format

    Returns:
        ISO 8601 timestamp string
    """
    return datetime.now(timezone.utc).isoformat()


def parse_timestamp(timestamp_str: str) -> datetime:
    """
    Parse ISO 8601 timestamp string

    Args:
        timestamp_str: ISO 8601 string

    Returns:
        datetime object
    """
    return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))


def format_duration(seconds: float) -> str:
    """
    Format duration in human-readable format

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted string (e.g., "2m 30s", "1h 15m")
    """
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


def wait_with_timeout(
    condition_func,
    timeout_seconds: int,
    interval_seconds: int = 5,
    error_message: str = "Operation timed out"
):
    """
    Wait for a condition to be true with timeout

    Args:
        condition_func: Function that returns True when condition is met
        timeout_seconds: Maximum time to wait
        interval_seconds: Time between checks
        error_message: Error message if timeout

    Raises:
        TimeoutError: If condition not met within timeout

    Example:
        wait_with_timeout(
            lambda: vm_status() == "Succeeded",
            timeout_seconds=600,
            interval_seconds=10
        )
    """
    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        if condition_func():
            return

        time.sleep(interval_seconds)

    elapsed = time.time() - start_time
    raise TimeoutError(f"{error_message} (waited {format_duration(elapsed)})")


# ============================================================================
# Miscellaneous Utilities
# ============================================================================

def extract_spoke_id_from_vnet_name(vnet_name: str) -> int:
    """
    Extract spoke ID from VNet name

    Args:
        vnet_name: VNet name (e.g., "spoke-vnet-1")

    Returns:
        Spoke ID

    Raises:
        ValueError: If spoke ID cannot be extracted
    """
    match = re.search(r'-(\d+)$', vnet_name)
    if match:
        return int(match.group(1))
    raise ValueError(f"Cannot extract spoke ID from '{vnet_name}'")


def chunks(lst: List, chunk_size: int):
    """
    Split list into chunks

    Args:
        lst: List to split
        chunk_size: Size of each chunk

    Yields:
        Chunks of the list
    """
    for i in range(0, len(lst), chunk_size):
        yield lst[i:i + chunk_size]


def deep_merge(dict1: dict, dict2: dict) -> dict:
    """
    Deep merge two dictionaries

    Args:
        dict1: First dictionary
        dict2: Second dictionary (takes precedence)

    Returns:
        Merged dictionary
    """
    result = dict1.copy()
    for key, value in dict2.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result
