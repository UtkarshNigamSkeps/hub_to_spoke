"""
Configuration Management for Hub-Spoke Automation

Loads and validates all configuration from environment variables.
Provides a singleton Settings instance for the entire application.
"""

import os
from typing import Optional
from dotenv import load_dotenv
from utils.exceptions import ConfigurationError

# Load environment variables from .env file
load_dotenv()


class Settings:
    """
    Centralized configuration management
    Loads all settings from environment variables with validation
    """

    # Singleton instance
    _instance: Optional['Settings'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Settings, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize settings from environment variables"""
        if self._initialized:
            return

        # Azure Authentication (Required)
        self.AZURE_SUBSCRIPTION_ID = self._get_required("AZURE_SUBSCRIPTION_ID")
        self.AZURE_TENANT_ID = self._get_required("AZURE_TENANT_ID")
        self.AZURE_CLIENT_ID = self._get_required("AZURE_CLIENT_ID")
        self.AZURE_CLIENT_SECRET = self._get_required("AZURE_CLIENT_SECRET")

        # Azure Resource Configuration (Required)
        self.RESOURCE_GROUP_NAME = self._get_required("RESOURCE_GROUP_NAME")
        self.AZURE_RESOURCE_GROUP = self.RESOURCE_GROUP_NAME  # Alias for consistency
        self.HUB_VNET_NAME = self._get_required("HUB_VNET_NAME")
        self.HUB_VNET_RESOURCE_GROUP = self._get_optional(
            "HUB_VNET_RESOURCE_GROUP",
            self.RESOURCE_GROUP_NAME  # Default to same resource group
        )
        self.APPLICATION_GATEWAY_NAME = self._get_required("APPLICATION_GATEWAY_NAME")
        self.AZURE_LOCATION = self._get_optional("AZURE_LOCATION", "eastus")

        # Hub Network Configuration
        self.HUB_VNET_CIDR = self._get_optional("HUB_VNET_CIDR", "10.0.0.0/16")
        self.HUB_AGW_SUBNET_NAME = self._get_optional("HUB_AGW_SUBNET_NAME", "agw-subnet")

        # Spoke Network Configuration
        self.SPOKE_BASE_CIDR = self._get_optional("SPOKE_BASE_CIDR", "10.11.0.0/16")
        self.SPOKE_CIDR_PREFIX = self._get_optional("SPOKE_CIDR_PREFIX", "10.11")
        self.SPOKE_CIDR_SUFFIX = self._get_optional("SPOKE_CIDR_SUFFIX", "/24")

        # Flask Configuration
        self.FLASK_ENV = self._get_optional("FLASK_ENV", "production")
        self.FLASK_DEBUG = self._get_bool("FLASK_DEBUG", False)
        self.FLASK_HOST = self._get_optional("FLASK_HOST", "0.0.0.0")
        self.FLASK_PORT = self._get_int("FLASK_PORT", 5000)

        # Application Configuration
        self.ENVIRONMENT = self._get_optional("ENVIRONMENT", "development")

        # Logging Configuration
        self.LOG_LEVEL = self._get_optional("LOG_LEVEL", "INFO")
        self.LOG_FILE = self._get_optional("LOG_FILE", "logs/hub_spoke_deployment.log")
        self.ERROR_LOG_FILE = self._get_optional("ERROR_LOG_FILE", "logs/errors.log")

        # Deployment Configuration
        self.ENABLE_ROLLBACK = self._get_bool("ENABLE_ROLLBACK", True)
        self.DEPLOYMENT_TIMEOUT_MINUTES = self._get_int("DEPLOYMENT_TIMEOUT_MINUTES", 30)
        self.MAX_CONCURRENT_DEPLOYMENTS = self._get_int("MAX_CONCURRENT_DEPLOYMENTS", 3)

        # State Storage
        self.DEPLOYMENTS_DB_FILE = self._get_optional(
            "DEPLOYMENTS_DB_FILE",
            "storage/deployments.json"
        )

        self._initialized = True

    def _get_required(self, key: str) -> str:
        """
        Get required environment variable
        Raises ConfigurationError if not found
        """
        value = os.getenv(key)
        if not value:
            raise ConfigurationError(
                key,
                f"Required environment variable '{key}' is not set. "
                f"Please check your .env file."
            )
        return value

    def _get_optional(self, key: str, default: str) -> str:
        """Get optional environment variable with default value"""
        return os.getenv(key, default)

    def _get_int(self, key: str, default: int) -> int:
        """Get integer environment variable with default value"""
        value = os.getenv(key)
        if value is None:
            return default
        try:
            return int(value)
        except ValueError:
            raise ConfigurationError(
                key,
                f"Value '{value}' is not a valid integer"
            )

    def _get_bool(self, key: str, default: bool) -> bool:
        """Get boolean environment variable with default value"""
        value = os.getenv(key)
        if value is None:
            return default
        return value.lower() in ('true', '1', 'yes', 'on')

    def validate(self) -> tuple[bool, list[str]]:
        """
        Validate configuration settings
        Returns: (is_valid, list_of_errors)
        """
        errors = []

        # Validate Azure credentials format
        if not self.AZURE_SUBSCRIPTION_ID or len(self.AZURE_SUBSCRIPTION_ID) < 32:
            errors.append("AZURE_SUBSCRIPTION_ID appears invalid")

        if not self.AZURE_TENANT_ID or len(self.AZURE_TENANT_ID) < 32:
            errors.append("AZURE_TENANT_ID appears invalid")

        # Validate resource names (Azure naming rules)
        if not self._is_valid_azure_name(self.RESOURCE_GROUP_NAME):
            errors.append("RESOURCE_GROUP_NAME contains invalid characters")

        if not self._is_valid_azure_name(self.HUB_VNET_NAME):
            errors.append("HUB_VNET_NAME contains invalid characters")

        # Validate CIDR notation
        if not self._is_valid_cidr(self.HUB_VNET_CIDR):
            errors.append(f"HUB_VNET_CIDR '{self.HUB_VNET_CIDR}' is not valid CIDR notation")

        # Validate log level
        valid_log_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if self.LOG_LEVEL.upper() not in valid_log_levels:
            errors.append(f"LOG_LEVEL must be one of: {', '.join(valid_log_levels)}")

        # Validate numeric ranges
        if self.FLASK_PORT < 1 or self.FLASK_PORT > 65535:
            errors.append("FLASK_PORT must be between 1 and 65535")

        if self.DEPLOYMENT_TIMEOUT_MINUTES < 1:
            errors.append("DEPLOYMENT_TIMEOUT_MINUTES must be positive")

        if self.MAX_CONCURRENT_DEPLOYMENTS < 1:
            errors.append("MAX_CONCURRENT_DEPLOYMENTS must be positive")

        return len(errors) == 0, errors

    @staticmethod
    def _is_valid_azure_name(name: str) -> bool:
        """
        Validate Azure resource name
        Rules: alphanumeric, hyphens, underscores (varies by resource)
        """
        if not name:
            return False
        # Basic validation - can be enhanced
        import re
        return bool(re.match(r'^[a-zA-Z0-9_-]+$', name))

    @staticmethod
    def _is_valid_cidr(cidr: str) -> bool:
        """Validate CIDR notation (basic check)"""
        if not cidr:
            return False
        try:
            parts = cidr.split('/')
            if len(parts) != 2:
                return False

            # Validate IP address
            ip_parts = parts[0].split('.')
            if len(ip_parts) != 4:
                return False
            for part in ip_parts:
                num = int(part)
                if num < 0 or num > 255:
                    return False

            # Validate prefix length
            prefix = int(parts[1])
            if prefix < 0 or prefix > 32:
                return False

            return True
        except (ValueError, AttributeError):
            return False

    def to_dict(self) -> dict:
        """Convert settings to dictionary (for debugging/logging)"""
        return {
            "AZURE_SUBSCRIPTION_ID": self._mask_secret(self.AZURE_SUBSCRIPTION_ID),
            "AZURE_TENANT_ID": self._mask_secret(self.AZURE_TENANT_ID),
            "AZURE_CLIENT_ID": self._mask_secret(self.AZURE_CLIENT_ID),
            "AZURE_CLIENT_SECRET": "***MASKED***",
            "RESOURCE_GROUP_NAME": self.RESOURCE_GROUP_NAME,
            "HUB_VNET_NAME": self.HUB_VNET_NAME,
            "HUB_VNET_RESOURCE_GROUP": self.HUB_VNET_RESOURCE_GROUP,
            "APPLICATION_GATEWAY_NAME": self.APPLICATION_GATEWAY_NAME,
            "AZURE_LOCATION": self.AZURE_LOCATION,
            "FLASK_ENV": self.FLASK_ENV,
            "FLASK_DEBUG": self.FLASK_DEBUG,
            "LOG_LEVEL": self.LOG_LEVEL,
        }

    @staticmethod
    def _mask_secret(value: str, show_chars: int = 4) -> str:
        """Mask secret value for logging"""
        if not value or len(value) <= show_chars:
            return "***"
        return f"{value[:show_chars]}...{value[-show_chars:]}"

    def __repr__(self) -> str:
        return f"<Settings(env={self.FLASK_ENV}, location={self.AZURE_LOCATION})>"


# Global settings instance
settings = Settings()
