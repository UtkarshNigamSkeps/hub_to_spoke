"""
Application Gateway Update Service

Handles Azure Application Gateway backend pool and routing rule updates.
"""

from typing import Optional, List
from azure.identity import ClientSecretCredential
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.network.models import (
    ApplicationGateway,
    ApplicationGatewayBackendAddressPool,
    ApplicationGatewayBackendAddress
)
from azure.core.exceptions import ResourceNotFoundError, HttpResponseError

from config.settings import settings
from utils.logger import get_logger, LogContext
from utils.exceptions import AGWUpdateError, ResourceNotFoundError as HubSpokeResourceNotFoundError
from utils.helpers import wait_with_timeout
from models.spoke_config import SpokeConfiguration


class ApplicationGatewayService:
    """
    Service for managing Azure Application Gateway

    Handles:
    - Backend pool addition
    - Routing rule creation
    - AGW configuration updates
    - Backend health monitoring
    """

    def __init__(self, credential: Optional[ClientSecretCredential] = None):
        """
        Initialize Application Gateway Service

        Args:
            credential: Azure credential (if None, creates from settings)
        """
        self.logger = get_logger(__name__)
        self.settings = settings

        # Initialize credential
        if credential is None:
            self.credential = ClientSecretCredential(
                tenant_id=self.settings.AZURE_TENANT_ID,
                client_id=self.settings.AZURE_CLIENT_ID,
                client_secret=self.settings.AZURE_CLIENT_SECRET
            )
        else:
            self.credential = credential

        # Initialize network client
        self.network_client = NetworkManagementClient(
            credential=self.credential,
            subscription_id=self.settings.AZURE_SUBSCRIPTION_ID
        )

        self.logger.info("Application Gateway Service initialized")

    def get_application_gateway(self) -> ApplicationGateway:
        """
        Retrieve current Application Gateway configuration

        Returns:
            ApplicationGateway object

        Raises:
            ResourceNotFoundError: If AGW not found
        """
        try:
            self.logger.debug(f"Retrieving Application Gateway: {self.settings.APPLICATION_GATEWAY_NAME}")

            agw = self.network_client.application_gateways.get(
                resource_group_name=self.settings.HUB_VNET_RESOURCE_GROUP,
                application_gateway_name=self.settings.APPLICATION_GATEWAY_NAME
            )

            self.logger.info(f"✓ Retrieved AGW: {agw.name} (State: {agw.provisioning_state})")
            return agw

        except ResourceNotFoundError:
            error_msg = f"Application Gateway '{self.settings.APPLICATION_GATEWAY_NAME}' not found"
            self.logger.error(error_msg)
            raise HubSpokeResourceNotFoundError("ApplicationGateway", self.settings.APPLICATION_GATEWAY_NAME)

        except Exception as e:
            error_msg = f"Error retrieving Application Gateway: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise AGWUpdateError(self.settings.APPLICATION_GATEWAY_NAME, error_msg, e)

    def add_backend_pool(
        self,
        spoke_config: SpokeConfiguration,
        vm_private_ip: str
    ) -> ApplicationGateway:
        """
        Add backend pool for spoke VM to Application Gateway

        Args:
            spoke_config: Spoke configuration
            vm_private_ip: Private IP address of the VM

        Returns:
            Updated ApplicationGateway object

        Raises:
            AGWUpdateError: If update fails
        """
        agw_name = self.settings.APPLICATION_GATEWAY_NAME
        pool_name = spoke_config.backend_pool_name

        with LogContext(spoke_id=spoke_config.spoke_id):
            try:
                self.logger.info(f"Adding backend pool '{pool_name}' to AGW with IP: {vm_private_ip}")

                # Get current AGW configuration
                agw = self.get_application_gateway()

                # Check if backend pool already exists
                existing_pools = agw.backend_address_pools or []
                for pool in existing_pools:
                    if pool.name == pool_name:
                        self.logger.warning(f"Backend pool '{pool_name}' already exists, updating")
                        # Remove existing pool to update it
                        existing_pools.remove(pool)
                        break

                # Create new backend pool
                new_pool = ApplicationGatewayBackendAddressPool(
                    name=pool_name,
                    backend_addresses=[
                        ApplicationGatewayBackendAddress(
                            ip_address=vm_private_ip
                        )
                    ]
                )

                # Add new pool to list
                existing_pools.append(new_pool)
                agw.backend_address_pools = existing_pools

                # Update AGW (this is a long operation - 5-10 minutes)
                self.logger.info("Updating Application Gateway (this may take 5-10 minutes)...")
                self.logger.info("⏳ Please be patient...")

                poller = self.network_client.application_gateways.begin_create_or_update(
                    resource_group_name=self.settings.HUB_VNET_RESOURCE_GROUP,
                    application_gateway_name=agw_name,
                    parameters=agw
                )

                # Wait for completion
                updated_agw = poller.result()

                self.logger.info(f"✓ Backend pool '{pool_name}' added successfully")
                self.logger.info(f"  - AGW State: {updated_agw.provisioning_state}")

                return updated_agw

            except HttpResponseError as e:
                error_msg = f"Azure API error adding backend pool: {str(e)}"
                self.logger.error(error_msg, exc_info=True)
                raise AGWUpdateError(agw_name, error_msg, e)

            except Exception as e:
                error_msg = f"Unexpected error adding backend pool: {str(e)}"
                self.logger.error(error_msg, exc_info=True)
                raise AGWUpdateError(agw_name, error_msg, e)

    def create_routing_rule(
        self,
        spoke_config: SpokeConfiguration
    ) -> ApplicationGateway:
        """
        Create routing rule for spoke

        Args:
            spoke_config: Spoke configuration

        Returns:
            Updated ApplicationGateway object

        Raises:
            AGWUpdateError: If update fails

        Note:
            This is a simplified implementation. In production, you would:
            - Create HTTP settings
            - Create listeners
            - Create path-based or URL-based rules
            For now, we just log that the pool is ready for manual rule configuration.
        """
        rule_name = spoke_config.routing_rule_name
        pool_name = spoke_config.backend_pool_name

        with LogContext(spoke_id=spoke_config.spoke_id):
            try:
                self.logger.info(f"Backend pool '{pool_name}' is ready for routing configuration")
                self.logger.info(f"⚠ Manual step: Configure routing rule '{rule_name}' in Azure Portal")
                self.logger.info(f"  - Navigate to: Application Gateway > Routing rules")
                self.logger.info(f"  - Create rule pointing to backend pool: {pool_name}")

                # Get current AGW for return
                agw = self.get_application_gateway()

                # In a full implementation, you would:
                # 1. Create HTTP settings
                # 2. Create listener (if needed)
                # 3. Create request routing rule
                # 4. Update AGW configuration

                # For now, return current AGW
                return agw

            except Exception as e:
                error_msg = f"Error in routing rule preparation: {str(e)}"
                self.logger.error(error_msg, exc_info=True)
                raise AGWUpdateError(self.settings.APPLICATION_GATEWAY_NAME, error_msg, e)

    def verify_backend_health(self, pool_name: str, timeout_seconds: int = 300) -> bool:
        """
        Verify backend pool health status

        Args:
            pool_name: Name of backend pool to check
            timeout_seconds: Maximum time to wait (default: 5 minutes)

        Returns:
            True if backend is healthy

        Note:
            Backend health check may take several minutes after AGW update
        """
        try:
            self.logger.info(f"Checking backend health for pool: {pool_name}")

            def check_health():
                try:
                    # Get backend health
                    health = self.network_client.application_gateways.backend_health(
                        resource_group_name=self.settings.HUB_VNET_RESOURCE_GROUP,
                        application_gateway_name=self.settings.APPLICATION_GATEWAY_NAME
                    ).result()

                    # Check if pool exists in health report
                    if health and health.backend_address_pools:
                        for pool_health in health.backend_address_pools:
                            if pool_health.backend_address_pool and \
                               pool_health.backend_address_pool.id and \
                               pool_name in pool_health.backend_address_pool.id:
                                # Found our pool
                                if pool_health.backend_http_settings_collection:
                                    # Check if any backend is healthy
                                    for settings in pool_health.backend_http_settings_collection:
                                        if settings.servers:
                                            for server in settings.servers:
                                                if server.health and server.health.lower() == 'healthy':
                                                    return True
                    return False

                except Exception as e:
                    self.logger.debug(f"Health check in progress: {e}")
                    return False

            try:
                wait_with_timeout(
                    condition_func=check_health,
                    timeout_seconds=timeout_seconds,
                    interval_seconds=30,
                    error_message=f"Backend pool '{pool_name}' did not become healthy"
                )

                self.logger.info(f"✓ Backend pool '{pool_name}' is healthy")
                return True

            except TimeoutError:
                self.logger.warning(f"⚠ Backend health check timed out for '{pool_name}'")
                self.logger.warning("  This is common and doesn't necessarily indicate a problem")
                self.logger.warning("  Backend health can be verified manually in Azure Portal")
                # Don't raise error - health check timeout is not critical
                return False

        except Exception as e:
            self.logger.warning(f"Error verifying backend health: {e}")
            return False

    def list_backend_pools(self) -> List[str]:
        """
        List all backend pool names in the Application Gateway

        Returns:
            List of backend pool names
        """
        try:
            agw = self.get_application_gateway()

            if agw.backend_address_pools:
                pool_names = [pool.name for pool in agw.backend_address_pools if pool.name]
                self.logger.debug(f"Found {len(pool_names)} backend pools")
                return pool_names

            return []

        except Exception as e:
            self.logger.error(f"Error listing backend pools: {e}")
            return []

    def remove_backend_pool(self, pool_name: str) -> bool:
        """
        Remove backend pool from Application Gateway (for rollback)

        Args:
            pool_name: Name of backend pool to remove

        Returns:
            True if removed successfully
        """
        try:
            self.logger.warning(f"Removing backend pool: {pool_name}")

            # Get current AGW configuration
            agw = self.get_application_gateway()

            # Find and remove the pool
            if agw.backend_address_pools:
                original_count = len(agw.backend_address_pools)
                agw.backend_address_pools = [
                    pool for pool in agw.backend_address_pools
                    if pool.name != pool_name
                ]

                if len(agw.backend_address_pools) < original_count:
                    # Pool was removed, update AGW
                    self.logger.info("Updating Application Gateway...")

                    poller = self.network_client.application_gateways.begin_create_or_update(
                        resource_group_name=self.settings.HUB_VNET_RESOURCE_GROUP,
                        application_gateway_name=self.settings.APPLICATION_GATEWAY_NAME,
                        parameters=agw
                    )

                    poller.result()
                    self.logger.info(f"✓ Backend pool '{pool_name}' removed")
                    return True
                else:
                    self.logger.warning(f"Backend pool '{pool_name}' not found")
                    return False

            self.logger.warning("No backend pools configured in AGW")
            return False

        except Exception as e:
            self.logger.error(f"Error removing backend pool {pool_name}: {e}")
            return False

    def get_agw_status(self) -> dict:
        """
        Get Application Gateway status summary

        Returns:
            Dictionary with AGW status information
        """
        try:
            agw = self.get_application_gateway()

            status = {
                'name': agw.name,
                'provisioning_state': agw.provisioning_state,
                'operational_state': agw.operational_state,
                'backend_pools_count': len(agw.backend_address_pools) if agw.backend_address_pools else 0,
                'location': agw.location
            }

            return status

        except Exception as e:
            self.logger.error(f"Error getting AGW status: {e}")
            return {}

    def __repr__(self) -> str:
        return f"<ApplicationGatewayService(agw={self.settings.APPLICATION_GATEWAY_NAME})>"
