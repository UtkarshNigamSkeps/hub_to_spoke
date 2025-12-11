"""
Request Validators

Provides validation functions for API request payloads.
"""

from typing import Dict, List, Tuple, Any
import re

from utils.helpers import validate_spoke_id, validate_client_name


def validate_create_spoke_request(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate create spoke request payload

    Args:
        data: Request JSON data

    Returns:
        Tuple of (is_valid: bool, errors: List[str])
    """
    errors = []

    # Required fields
    if 'spoke_id' not in data:
        errors.append("spoke_id is required")
    else:
        spoke_id = data['spoke_id']
        if not isinstance(spoke_id, int):
            errors.append("spoke_id must be an integer")
        elif not validate_spoke_id(spoke_id):
            errors.append("spoke_id must be between 1 and 254")

    if 'client_name' not in data:
        errors.append("client_name is required")
    else:
        client_name = data['client_name']
        if not isinstance(client_name, str):
            errors.append("client_name must be a string")
        elif not validate_client_name(client_name):
            errors.append(
                "client_name must be 3-50 characters, "
                "alphanumeric with hyphens, and cannot start/end with hyphen"
            )

    # Optional fields validation
    if 'vm_size' in data:
        vm_size = data['vm_size']
        if not isinstance(vm_size, str):
            errors.append("vm_size must be a string")
        elif not validate_vm_size(vm_size):
            errors.append(
                "vm_size must be a valid Azure VM size (e.g., Standard_B2s, Standard_D2s_v3)"
            )

    if 'admin_username' in data:
        admin_username = data['admin_username']
        if not isinstance(admin_username, str):
            errors.append("admin_username must be a string")
        elif not validate_username(admin_username):
            errors.append(
                "admin_username must be 1-64 characters, "
                "alphanumeric with underscores, and cannot start with numbers"
            )

    if 'ssh_public_key' in data:
        ssh_key = data['ssh_public_key']
        if not isinstance(ssh_key, str):
            errors.append("ssh_public_key must be a string")
        elif ssh_key and not validate_ssh_public_key(ssh_key):
            errors.append(
                "ssh_public_key must be a valid SSH public key "
                "(starts with ssh-rsa, ssh-ed25519, or ecdsa-sha2-nistp256)"
            )

    return len(errors) == 0, errors


def validate_vm_size(vm_size: str) -> bool:
    """
    Validate Azure VM size format

    Args:
        vm_size: VM size string (e.g., "Standard_B2s")

    Returns:
        True if valid, False otherwise
    """
    if not vm_size:
        return False

    # Azure VM size pattern: Standard_<series><version>_<size>
    # Examples: Standard_B2s, Standard_D2s_v3, Standard_F4s_v2
    pattern = r'^(Basic|Standard)_[A-Z]+[0-9]+[a-z]*(_v[0-9]+)?$'
    return bool(re.match(pattern, vm_size))


def validate_username(username: str) -> bool:
    """
    Validate admin username

    Args:
        username: Username string

    Returns:
        True if valid, False otherwise
    """
    if not username or len(username) < 1 or len(username) > 64:
        return False

    # Cannot start with numbers, only alphanumeric and underscores
    pattern = r'^[a-zA-Z_][a-zA-Z0-9_]*$'
    return bool(re.match(pattern, username))


def validate_ssh_public_key(ssh_key: str) -> bool:
    """
    Validate SSH public key format

    Args:
        ssh_key: SSH public key string

    Returns:
        True if valid, False otherwise
    """
    if not ssh_key:
        return False

    # Check if starts with valid key type
    valid_types = ['ssh-rsa', 'ssh-ed25519', 'ecdsa-sha2-nistp256', 'ecdsa-sha2-nistp384', 'ecdsa-sha2-nistp521']

    for key_type in valid_types:
        if ssh_key.startswith(key_type):
            # Basic validation: should have at least 3 parts (type, key, optional comment)
            parts = ssh_key.split()
            return len(parts) >= 2

    return False


def validate_query_parameters(
    status: str = None,
    limit: int = None
) -> Tuple[bool, List[str]]:
    """
    Validate query parameters for list operations

    Args:
        status: Status filter value
        limit: Limit value

    Returns:
        Tuple of (is_valid: bool, errors: List[str])
    """
    errors = []

    # Validate status if provided
    if status is not None:
        valid_statuses = ['pending', 'in_progress', 'completed', 'failed', 'running', 'stopped']
        if status not in valid_statuses:
            errors.append(f"status must be one of: {', '.join(valid_statuses)}")

    # Validate limit if provided
    if limit is not None:
        if not isinstance(limit, int):
            errors.append("limit must be an integer")
        elif limit < 1 or limit > 100:
            errors.append("limit must be between 1 and 100")

    return len(errors) == 0, errors


def sanitize_input(value: str, max_length: int = 255) -> str:
    """
    Sanitize string input to prevent injection attacks

    Args:
        value: Input string
        max_length: Maximum allowed length

    Returns:
        Sanitized string
    """
    if not isinstance(value, str):
        return str(value)

    # Remove any control characters
    sanitized = ''.join(char for char in value if char.isprintable())

    # Truncate to max length
    sanitized = sanitized[:max_length]

    # Strip whitespace
    sanitized = sanitized.strip()

    return sanitized


def validate_spoke_id_parameter(spoke_id: Any) -> Tuple[bool, str]:
    """
    Validate spoke_id parameter

    Args:
        spoke_id: Spoke ID value

    Returns:
        Tuple of (is_valid: bool, error_message: str)
    """
    if spoke_id is None:
        return False, "spoke_id is required"

    if not isinstance(spoke_id, int):
        return False, "spoke_id must be an integer"

    if not validate_spoke_id(spoke_id):
        return False, "spoke_id must be between 1 and 254"

    return True, ""
