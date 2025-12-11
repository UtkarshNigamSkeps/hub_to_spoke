"""
Spoke Controller - Business Logic Layer

Handles business logic for spoke operations, orchestrating between
routes and services.
"""

from typing import Dict, List, Optional, Any

from utils.logger import get_logger, LogContext
from utils.exceptions import (
    DeploymentException
)
from models.spoke_config import SpokeConfiguration
from models.deployment_status import DeploymentStatus
from services.orchestrator import SpokeOrchestrator
from services.storage_service import StorageService
from utils.helpers import (
    calculate_spoke_cidr,
    calculate_subnet_cidrs,
    validate_spoke_id,
    validate_client_name,
    sanitize_name
)


class SpokeController:
    """
    Controller for spoke deployment operations

    Handles:
    - Request validation
    - Configuration building
    - Orchestrator coordination
    - Response formatting
    - Error handling
    """

    def __init__(self):
        """Initialize spoke controller"""
        self.logger = get_logger(__name__)
        self.orchestrator = SpokeOrchestrator()
        self.storage_service = StorageService()

    def create_spoke(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new spoke deployment

        Args:
            request_data: Request payload from API

        Returns:
            Dictionary with deployment status information

        Raises:
            ValueError: If validation fails
            DeploymentException: If deployment fails
        """
        # Extract and validate required fields
        spoke_id = request_data.get('spoke_id')
        client_name = request_data.get('client_name')

        if spoke_id is None:
            raise ValueError("spoke_id is required")

        if not client_name:
            raise ValueError("client_name is required")

        # Validate spoke_id
        if not validate_spoke_id(spoke_id):
            raise ValueError(f"Invalid spoke_id: {spoke_id}. Must be between 1 and 254")

        # Validate client_name
        if not validate_client_name(client_name):
            raise ValueError(
                f"Invalid client_name: {client_name}. "
                "Must be 3-50 characters, alphanumeric with hyphens"
            )

        with LogContext(spoke_id=spoke_id):
            try:
                self.logger.info(f"Creating spoke {spoke_id} for client: {client_name}")

                # Build spoke configuration
                spoke_config = self._build_spoke_config(request_data)

                # Validate configuration
                is_valid, errors = spoke_config.validate()
                if not is_valid:
                    error_msg = f"Configuration validation failed: {', '.join(errors)}"
                    self.logger.error(error_msg)
                    raise ValueError(error_msg)

                # Start deployment (asynchronous in production)
                self.logger.info("Starting deployment workflow")
                deployment_status = self.orchestrator.create_spoke(spoke_config)

                # Format response
                return self._format_deployment_response(deployment_status)

            except ValueError as e:
                self.logger.error(f"Validation error: {e}")
                raise

            except DeploymentException as e:
                self.logger.error(f"Deployment failed: {e}")
                raise ValueError(f"Deployment failed: {str(e)}")

            except Exception as e:
                self.logger.error(f"Unexpected error: {e}", exc_info=True)
                raise

    def get_spoke_status(self, spoke_id: int) -> Dict[str, Any]:
        """
        Get current status of a spoke

        Args:
            spoke_id: Spoke identifier

        Returns:
            Dictionary with spoke status information
        """
        with LogContext(spoke_id=spoke_id):
            try:
                self.logger.debug(f"Retrieving status for spoke {spoke_id}")

                # Get status from orchestrator
                status = self.orchestrator.get_spoke_status(spoke_id)

                return status

            except Exception as e:
                self.logger.error(f"Error getting spoke status: {e}", exc_info=True)
                raise

    def list_spokes(
        self,
        status_filter: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        List all deployed spokes

        Args:
            status_filter: Filter by status (optional)
            limit: Maximum number of results (optional)

        Returns:
            List of spoke information dictionaries
        """
        try:
            self.logger.debug("Listing all spokes")

            # Get all spokes from orchestrator
            spokes = self.orchestrator.list_all_spokes()

            # Apply status filter if provided
            if status_filter:
                spokes = [
                    spoke for spoke in spokes
                    if spoke.get('vm', {}).get('status') == status_filter
                ]

            # Apply limit if provided
            if limit and limit > 0:
                spokes = spokes[:limit]

            self.logger.info(f"Found {len(spokes)} spokes")
            return spokes

        except Exception as e:
            self.logger.error(f"Error listing spokes: {e}", exc_info=True)
            raise

    def delete_spoke(self, spoke_id: int) -> Dict[str, Any]:
        """
        Delete/rollback a spoke deployment

        Args:
            spoke_id: Spoke identifier

        Returns:
            Dictionary with rollback information

        Raises:
            ValueError: If spoke not found
        """
        with LogContext(spoke_id=spoke_id):
            try:
                self.logger.info(f"Deleting spoke {spoke_id}")

                # Check if spoke exists
                status = self.orchestrator.get_spoke_status(spoke_id)
                if not status.get('exists', False):
                    raise ValueError(f"Spoke {spoke_id} not found")

                # Retrieve deployment record to get actual configuration
                deployment = self.storage_service.get_deployment(spoke_id)

                # Get actual VM name from Azure or deployment record
                vm_name = status.get('vm', {}).get('name', f"spoke-vm-{spoke_id}")
                vnet_name = status.get('vnet', {}).get('name', f"spoke-vnet-{spoke_id}")

                # Get backend pool and routing rule names from deployment record (if available)
                backend_pool_name = None
                routing_rule_name = None
                if deployment:
                    backend_pool_name = deployment.get('backend_pool_name')
                    routing_rule_name = deployment.get('routing_rule_name')

                # Get client name for fallback naming
                client_name = status.get('vnet', {}).get('tags', {}).get('client_name', 'unknown')

                # Fallback to default naming if not in deployment record
                # Use client_name for AGW resources, not spoke_id
                if not backend_pool_name:
                    sanitized_client_name = sanitize_name(client_name)
                    backend_pool_name = f"{sanitized_client_name}-pool"
                if not routing_rule_name:
                    sanitized_client_name = sanitize_name(client_name)
                    routing_rule_name = f"{sanitized_client_name}-route"

                # Build config for rollback with actual resource names
                spoke_config = SpokeConfiguration(
                    spoke_id=spoke_id,
                    client_name=client_name,
                    address_prefix=calculate_spoke_cidr(spoke_id),
                    vm_subnet_prefix=f"10.11.{spoke_id}.0/26",
                    db_subnet_prefix=f"10.11.{spoke_id}.64/26",
                    kv_subnet_prefix=f"10.11.{spoke_id}.128/26",
                    workspace_subnet_prefix=f"10.11.{spoke_id}.192/26",
                    vm_name=vm_name,
                    vnet_name=vnet_name,
                    backend_pool_name=backend_pool_name,
                    routing_rule_name=routing_rule_name
                )

                # Create deployment status for tracking
                deployment_status = DeploymentStatus(
                    spoke_id=spoke_id,
                    client_name=spoke_config.client_name
                )

                # Mark existing resources as completed so rollback knows what to remove
                deployment_status.update_step("create_vnet", "completed")
                deployment_status.update_step("create_nic", "completed")
                deployment_status.update_step("deploy_vm", "completed")
                deployment_status.update_step("update_agw", "completed")

                # Perform rollback
                success = self.orchestrator.rollback_spoke(spoke_config, deployment_status)

                # If rollback successful, delete deployment record from storage
                if success:
                    self.storage_service.delete_deployment(spoke_id)
                    self.logger.info(f"Deleted deployment record for spoke {spoke_id}")

                return {
                    'spoke_id': spoke_id,
                    'rollback_status': 'completed' if success else 'failed',
                    'removed_resources': [
                        'vnet',
                        'subnets',
                        'network_interface',
                        'virtual_machine',
                        'application_gateway_backend_pool'
                    ]
                }

            except ValueError as e:
                self.logger.error(f"Validation error: {e}")
                raise

            except Exception as e:
                self.logger.error(f"Error deleting spoke: {e}", exc_info=True)
                raise

    def _build_spoke_config(self, request_data: Dict[str, Any]) -> SpokeConfiguration:
        """
        Build SpokeConfiguration from request data

        Args:
            request_data: Request payload

        Returns:
            Validated SpokeConfiguration object
        """
        spoke_id = request_data['spoke_id']
        client_name = request_data['client_name']

        # Calculate network configuration
        address_prefix = calculate_spoke_cidr(spoke_id)

        # Get subnet CIDRs from request or calculate defaults
        if 'subnets' in request_data:
            # Use subnets from request payload
            subnets = request_data['subnets']
            vm_subnet = subnets.get('vm_subnet_prefix')
            db_subnet = subnets.get('db_subnet_prefix')
            kv_subnet = subnets.get('kv_subnet_prefix')
            workspace_subnet = subnets.get('workspace_subnet_prefix')
        else:
            # Calculate default subnets
            subnet_cidrs = calculate_subnet_cidrs(address_prefix)
            vm_subnet = subnet_cidrs['vm_subnet_prefix']
            db_subnet = subnet_cidrs['db_subnet_prefix']
            kv_subnet = subnet_cidrs['kv_subnet_prefix']
            workspace_subnet = subnet_cidrs['workspace_subnet_prefix']

        # Get AGW configuration from request or use defaults
        agw_config = request_data.get('application_gateway', {})
        # Use client_name for AGW resources, not spoke_id
        sanitized_client_name = sanitize_name(client_name)
        backend_pool = agw_config.get('backend_pool_name', f"{sanitized_client_name}-pool")
        routing_rule = agw_config.get('routing_rule_name', f"{sanitized_client_name}-route")

        # Build configuration
        config = SpokeConfiguration(
            spoke_id=spoke_id,
            client_name=client_name,
            address_prefix=address_prefix,
            vm_subnet_prefix=vm_subnet,
            db_subnet_prefix=db_subnet,
            kv_subnet_prefix=kv_subnet,
            workspace_subnet_prefix=workspace_subnet,
            vm_name=f"spoke-vm-{spoke_id}",
            vm_size=request_data.get('vm_size', 'Standard_B2s'),
            admin_username=request_data.get('admin_username', 'azureuser'),
            ssh_public_key=request_data.get('ssh_public_key', ''),
            backend_pool_name=backend_pool,
            routing_rule_name=routing_rule
        )

        self.logger.debug(f"Built configuration: {config}")
        return config

    def _format_deployment_response(self, deployment_status: DeploymentStatus) -> Dict[str, Any]:
        """
        Format deployment status for API response

        Args:
            deployment_status: DeploymentStatus object

        Returns:
            Dictionary formatted for JSON response
        """
        return {
            'spoke_id': deployment_status.spoke_id,
            'client_name': deployment_status.client_name,
            'status': deployment_status.status,
            'progress': deployment_status.get_progress_percentage(),
            'vnet_name': deployment_status.vnet_name,
            'vnet_id': deployment_status.vnet_id,
            'vm_name': deployment_status.vm_name,
            'vm_id': deployment_status.vm_id,
            'vm_private_ip': deployment_status.vm_private_ip,
            'deployment_steps': [
                {
                    'step_name': step.step_name,
                    'status': step.status,
                    'started_at': step.started_at,
                    'completed_at': step.completed_at,
                    'error_message': step.error_message
                }
                for step in deployment_status.deployment_steps
            ],
            'created_at': deployment_status.created_at,
            'updated_at': deployment_status.updated_at,
            'completed_at': deployment_status.completed_at,
            'error_message': deployment_status.error_message,
            'failed_step': deployment_status.failed_step
        }
