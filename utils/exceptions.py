"""
Custom Exception Hierarchy for Hub-Spoke Automation

Provides specific exceptions for different failure scenarios with context.
"""


class HubSpokeException(Exception):
    """Base exception for all hub-spoke automation errors"""

    def __init__(self, message: str, details: dict = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigurationError(HubSpokeException):
    """Raised when configuration is missing or invalid"""

    def __init__(self, config_key: str, reason: str):
        self.config_key = config_key
        self.reason = reason
        super().__init__(
            f"Configuration error for '{config_key}': {reason}",
            {"config_key": config_key, "reason": reason}
        )


class ValidationError(HubSpokeException):
    """Raised when input validation fails"""

    def __init__(self, field: str, value: any, reason: str):
        self.field = field
        self.value = value
        self.reason = reason
        super().__init__(
            f"Validation error for field '{field}': {reason}",
            {"field": field, "value": str(value), "reason": reason}
        )


class AzureResourceException(HubSpokeException):
    """Base exception for Azure resource operations"""

    def __init__(self, resource_type: str, resource_name: str, reason: str, azure_error: Exception = None):
        self.resource_type = resource_type
        self.resource_name = resource_name
        self.reason = reason
        self.azure_error = azure_error

        super().__init__(
            f"Azure {resource_type} error for '{resource_name}': {reason}",
            {
                "resource_type": resource_type,
                "resource_name": resource_name,
                "reason": reason,
                "azure_error": str(azure_error) if azure_error else None
            }
        )


class VNetCreationError(AzureResourceException):
    """Raised when VNet creation fails"""

    def __init__(self, vnet_name: str, reason: str, azure_error: Exception = None):
        super().__init__("VNet", vnet_name, reason, azure_error)


class SubnetCreationError(AzureResourceException):
    """Raised when subnet creation fails"""

    def __init__(self, subnet_name: str, reason: str, azure_error: Exception = None):
        super().__init__("Subnet", subnet_name, reason, azure_error)


class PeeringCreationError(AzureResourceException):
    """Raised when VNet peering creation fails"""

    def __init__(self, peering_name: str, reason: str, azure_error: Exception = None):
        super().__init__("VNet Peering", peering_name, reason, azure_error)


class VMDeploymentError(AzureResourceException):
    """Raised when VM deployment fails"""

    def __init__(self, vm_name: str, reason: str, azure_error: Exception = None):
        super().__init__("Virtual Machine", vm_name, reason, azure_error)


class AGWUpdateError(AzureResourceException):
    """Raised when Application Gateway update fails"""

    def __init__(self, agw_name: str, reason: str, azure_error: Exception = None):
        super().__init__("Application Gateway", agw_name, reason, azure_error)


class ResourceNotFoundError(AzureResourceException):
    """Raised when an Azure resource is not found"""

    def __init__(self, resource_type: str, resource_name: str):
        super().__init__(
            resource_type,
            resource_name,
            "Resource not found",
            None
        )


class QuotaExceededException(HubSpokeException):
    """Raised when Azure quota/limit is exceeded"""

    def __init__(self, resource_type: str, quota_name: str, current: int, limit: int):
        self.resource_type = resource_type
        self.quota_name = quota_name
        self.current = current
        self.limit = limit

        super().__init__(
            f"Quota exceeded for {resource_type} ({quota_name}): {current}/{limit}",
            {
                "resource_type": resource_type,
                "quota_name": quota_name,
                "current": current,
                "limit": limit
            }
        )


class DeploymentException(HubSpokeException):
    """Base exception for deployment-related errors"""

    def __init__(self, spoke_id: int, step: str, reason: str):
        self.spoke_id = spoke_id
        self.step = step
        self.reason = reason

        super().__init__(
            f"Deployment failed for spoke {spoke_id} at step '{step}': {reason}",
            {
                "spoke_id": spoke_id,
                "step": step,
                "reason": reason
            }
        )


class DeploymentTimeoutError(DeploymentException):
    """Raised when deployment exceeds timeout"""

    def __init__(self, spoke_id: int, step: str, timeout_minutes: int):
        self.timeout_minutes = timeout_minutes
        super().__init__(
            spoke_id,
            step,
            f"Deployment timed out after {timeout_minutes} minutes"
        )


class RollbackError(DeploymentException):
    """Raised when rollback operation fails"""

    def __init__(self, spoke_id: int, step: str, reason: str):
        super().__init__(spoke_id, step, f"Rollback failed: {reason}")


class StorageException(HubSpokeException):
    """Raised when storage operations fail"""

    def __init__(self, operation: str, message: str, details: dict = None):
        self.operation = operation
        super().__init__(f"Storage error during {operation}: {message}", details)
