"""
Spoke Deployment Orchestrator

Coordinates the complete spoke deployment workflow by orchestrating
all Azure services (Network, Compute, Application Gateway).
"""

from typing import Optional, Dict, Any
from datetime import datetime
from azure.identity import ClientSecretCredential

from config.settings import settings
from utils.logger import get_logger, LogContext
from utils.exceptions import (
    DeploymentException,
    RollbackError,
    ConfigurationError
)
from utils.helpers import generate_vnet_name, generate_nic_name
from models.spoke_config import SpokeConfiguration
from models.deployment_status import DeploymentStatus, DeploymentStatusEnum
from services.azure_network import AzureNetworkService
from services.azure_compute import AzureComputeService
from services.agw_updater import ApplicationGatewayService
from services.storage_service import StorageService


class SpokeOrchestrator:
    """
    Main orchestrator for spoke deployment workflow

    Coordinates:
    1. Configuration validation
    2. VNet and subnet creation
    3. VM deployment
    4. VNet peering
    5. Application Gateway updates
    6. Status tracking
    7. Rollback on failure (if enabled)
    """

    def __init__(self, credential: Optional[ClientSecretCredential] = None):
        """
        Initialize Spoke Orchestrator

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

        # Initialize service clients
        self.network_service = AzureNetworkService(credential=self.credential)
        self.compute_service = AzureComputeService(credential=self.credential)
        self.agw_service = ApplicationGatewayService(credential=self.credential)
        self.storage_service = StorageService()

        self.logger.info("Spoke Orchestrator initialized")

    def create_spoke(
        self,
        spoke_config: SpokeConfiguration
    ) -> DeploymentStatus:
        """
        Main orchestration method for spoke deployment

        Args:
            spoke_config: Validated spoke configuration

        Returns:
            DeploymentStatus with complete deployment information

        Raises:
            DeploymentException: If deployment fails
        """
        spoke_id = spoke_config.spoke_id
        deployment_status = DeploymentStatus(
            spoke_id=spoke_id,
            client_name=spoke_config.client_name,
            status=DeploymentStatusEnum.IN_PROGRESS
        )

        with LogContext(spoke_id=spoke_id):
            try:
                self.logger.info("=" * 80)
                self.logger.info(f"🚀 Starting spoke {spoke_id} deployment for client: {spoke_config.client_name}")
                self.logger.info("=" * 80)

                # Step 1: Validate configuration
                self._execute_step(
                    deployment_status,
                    "validate_config",
                    "Validating configuration",
                    self._validate_configuration,
                    spoke_config
                )

                # Step 2: Create VNet
                vnet = self._execute_step(
                    deployment_status,
                    "create_vnet",
                    "Creating VNet",
                    self.network_service.create_spoke_vnet,
                    spoke_config
                )

                # Step 3: Create Subnets
                subnets = self._execute_step(
                    deployment_status,
                    "create_subnets",
                    "Creating subnets",
                    self.network_service.create_subnets,
                    spoke_config
                )

                # Step 4: Create Network Interface
                vm_subnet = subnets[0]  # First subnet is VM subnet
                nic_name = generate_nic_name(spoke_config.vm_name)
                nic = self._execute_step(
                    deployment_status,
                    "create_nic",
                    "Creating network interface",
                    self.compute_service.create_network_interface,
                    nic_name,
                    vm_subnet.id,
                    spoke_id
                )

                # Step 5: Deploy Virtual Machine
                vm = self._execute_step(
                    deployment_status,
                    "deploy_vm",
                    "Deploying virtual machine",
                    self.compute_service.create_virtual_machine,
                    spoke_config,
                    nic.id
                )

                # Step 6: Wait for VM to be ready
                self._execute_step(
                    deployment_status,
                    "wait_vm_ready",
                    "Waiting for VM to be ready",
                    self.compute_service.wait_for_vm_ready,
                    spoke_config.vm_name
                )

                # Step 7: Get VM Private IP
                vm_private_ip = self._execute_step(
                    deployment_status,
                    "get_vm_ip",
                    "Retrieving VM private IP",
                    self.compute_service.get_vm_private_ip,
                    spoke_config.vm_name
                )

                if not vm_private_ip:
                    raise DeploymentException(
                        spoke_id,
                        "get_vm_ip",
                        "Failed to retrieve VM private IP address"
                    )

                self.logger.info(f"✓ VM Private IP: {vm_private_ip}")

                # Step 8: Create VNet Peering
                self._execute_step(
                    deployment_status,
                    "create_peering",
                    "Creating VNet peering",
                    self.network_service.create_vnet_peering,
                    vnet.name,
                    vnet.id
                )

                # Step 9: Verify Connectivity
                self._execute_step(
                    deployment_status,
                    "verify_connectivity",
                    "Verifying VNet connectivity",
                    self.network_service.verify_vnet_connectivity,
                    vnet.name
                )

                # Step 10: Update Application Gateway
                self._execute_step(
                    deployment_status,
                    "update_agw",
                    "Updating Application Gateway",
                    self.agw_service.add_backend_pool,
                    spoke_config,
                    vm_private_ip
                )

                # Step 11: Create Routing Rule (placeholder)
                self._execute_step(
                    deployment_status,
                    "create_routing_rule",
                    "Preparing routing rule",
                    self.agw_service.create_routing_rule,
                    spoke_config
                )

                # Mark deployment as successful
                deployment_status.status = DeploymentStatusEnum.COMPLETED
                deployment_status.vm_private_ip = vm_private_ip
                deployment_status.vnet_id = vnet.id
                deployment_status.backend_pool_name = spoke_config.backend_pool_name
                deployment_status.routing_rule_name = spoke_config.routing_rule_name
                deployment_status.completed_at = datetime.now()

                # Save to persistent storage
                self.storage_service.save_deployment(deployment_status)

                self.logger.info("=" * 80)
                self.logger.info(f"✅ Spoke {spoke_id} deployment completed successfully!")
                self.logger.info(f"   VNet: {vnet.name}")
                self.logger.info(f"   VM: {spoke_config.vm_name}")
                self.logger.info(f"   Private IP: {vm_private_ip}")
                self.logger.info(f"   Progress: {deployment_status.get_progress_percentage()}%")
                self.logger.info("=" * 80)

                return deployment_status

            except Exception as e:
                # Mark deployment as failed
                deployment_status.status = DeploymentStatusEnum.FAILED
                deployment_status.error_message = str(e)
                deployment_status.failed_at = datetime.now()

                # Save failed deployment to storage
                self.storage_service.save_deployment(deployment_status)

                self.logger.error(f"❌ Spoke {spoke_id} deployment failed: {str(e)}")

                # Attempt rollback if enabled
                if self.settings.ENABLE_ROLLBACK:
                    self.logger.warning("🔄 Attempting rollback...")
                    try:
                        self.rollback_spoke(spoke_config, deployment_status)
                    except Exception as rollback_error:
                        self.logger.error(f"Rollback failed: {rollback_error}")
                        deployment_status.error_message += f" | Rollback error: {str(rollback_error)}"

                raise DeploymentException(spoke_id, "deployment", str(e))

    def _execute_step(
        self,
        deployment_status: DeploymentStatus,
        step_name: str,
        step_description: str,
        func,
        *args,
        **kwargs
    ) -> Any:
        """
        Execute a deployment step with progress tracking

        Args:
            deployment_status: Current deployment status
            step_name: Unique step identifier
            step_description: Human-readable step description
            func: Function to execute
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function

        Returns:
            Result from function execution

        Raises:
            Exception: Re-raises any exception from function
        """
        self.logger.info(f"▶️  {step_description}...")
        deployment_status.update_step(step_name, "in_progress")

        try:
            result = func(*args, **kwargs)
            deployment_status.update_step(step_name, "completed")
            self.logger.info(f"✓ {step_description} completed")
            return result

        except Exception as e:
            deployment_status.update_step(
                step_name,
                "failed",
                error=str(e)
            )
            self.logger.error(f"✗ {step_description} failed: {str(e)}")
            raise

    def _validate_configuration(self, spoke_config: SpokeConfiguration) -> bool:
        """
        Validate spoke configuration

        Args:
            spoke_config: Configuration to validate

        Returns:
            True if valid

        Raises:
            ConfigurationError: If validation fails
        """
        is_valid, errors = spoke_config.validate()

        if not is_valid:
            error_msg = f"Configuration validation failed: {', '.join(errors)}"
            self.logger.error(error_msg)
            raise ConfigurationError("spoke_config", error_msg)

        self.logger.debug("Configuration validated successfully")
        return True

    def rollback_spoke(
        self,
        spoke_config: SpokeConfiguration,
        deployment_status: DeploymentStatus
    ) -> bool:
        """
        Rollback spoke deployment by removing created resources

        Args:
            spoke_config: Spoke configuration
            deployment_status: Current deployment status

        Returns:
            True if rollback successful

        Raises:
            RollbackError: If rollback fails
        """
        spoke_id = spoke_config.spoke_id

        with LogContext(spoke_id=spoke_id):
            try:
                self.logger.warning(f"Starting rollback for spoke {spoke_id}")
                deployment_status.status = DeploymentStatusEnum.ROLLING_BACK

                rollback_errors = []

                # Determine which resources to remove based on completed steps
                completed_steps = [
                    step.step_name for step in deployment_status.deployment_steps
                    if step.status == "completed"
                ]

                # Rollback Application Gateway backend pool
                if "update_agw" in completed_steps:
                    self.logger.info("Rolling back Application Gateway backend pool")
                    try:
                        self.agw_service.remove_backend_pool(spoke_config.backend_pool_name)
                    except Exception as e:
                        rollback_errors.append(f"AGW rollback: {str(e)}")

                # Rollback VM
                if "deploy_vm" in completed_steps:
                    self.logger.info("Rolling back virtual machine")
                    try:
                        self.compute_service.delete_vm(spoke_config.vm_name)
                    except Exception as e:
                        rollback_errors.append(f"VM rollback: {str(e)}")

                    # Delete OS disk (VM deletion doesn't auto-delete managed disks)
                    try:
                        disk_name = f"{spoke_config.vm_name}-osdisk"
                        self.logger.info(f"Rolling back OS disk: {disk_name}")
                        self.compute_service.delete_disk(disk_name)
                    except Exception as e:
                        rollback_errors.append(f"Disk rollback: {str(e)}")

                # Rollback NIC
                nic_deleted = False
                if "create_nic" in completed_steps:
                    self.logger.info("Rolling back network interface")
                    try:
                        nic_name = generate_nic_name(spoke_config.vm_name)
                        nic_deleted = self.compute_service.delete_nic(nic_name)
                        if not nic_deleted:
                            self.logger.error(f"NIC {nic_name} deletion returned False")
                            rollback_errors.append(f"NIC rollback: Failed to delete {nic_name}")
                    except Exception as e:
                        rollback_errors.append(f"NIC rollback: {str(e)}")

                # Rollback VNet (this also removes subnets and peering)
                # Only attempt if NIC was deleted successfully or didn't need to be deleted
                if "create_vnet" in completed_steps:
                    if "create_nic" in completed_steps and not nic_deleted:
                        self.logger.warning("Skipping VNet deletion because NIC deletion failed")
                        rollback_errors.append("VNet rollback: Skipped due to NIC deletion failure")
                    else:
                        self.logger.info("Rolling back VNet")
                        try:
                            # Use actual VNet name from config
                            vnet_name = spoke_config.vnet_name if spoke_config.vnet_name else generate_vnet_name(spoke_id)
                            self.network_service.delete_spoke_vnet(vnet_name)
                        except Exception as e:
                            rollback_errors.append(f"VNet rollback: {str(e)}")

                if rollback_errors:
                    error_msg = f"Rollback completed with errors: {'; '.join(rollback_errors)}"
                    self.logger.error(error_msg)
                    deployment_status.status = DeploymentStatusEnum.ROLLBACK_FAILED
                    raise RollbackError(spoke_id, "rollback", error_msg)

                self.logger.info(f"✓ Rollback completed successfully for spoke {spoke_id}")
                deployment_status.status = DeploymentStatusEnum.ROLLED_BACK
                return True

            except Exception as e:
                error_msg = f"Rollback failed: {str(e)}"
                self.logger.error(error_msg)
                deployment_status.status = DeploymentStatusEnum.ROLLBACK_FAILED
                raise RollbackError(spoke_id, "rollback", error_msg)

    def get_spoke_status(self, spoke_id: int) -> Dict[str, Any]:
        """
        Get current status of a spoke deployment

        Args:
            spoke_id: Spoke identifier

        Returns:
            Dictionary with spoke status information
        """
        try:
            vnet_name = generate_vnet_name(spoke_id)

            # Check if VNet exists
            vnets = self.network_service.list_spoke_vnets()
            spoke_vnet = next((v for v in vnets if v['name'] == vnet_name), None)

            if not spoke_vnet:
                return {
                    'spoke_id': spoke_id,
                    'exists': False,
                    'status': 'not_found'
                }

            # Get VM status
            vm_name = f"spoke-vm-{spoke_id}"
            vm_status = self.compute_service.get_vm_status(vm_name)
            vm_ip = self.compute_service.get_vm_private_ip(vm_name)

            # Get backend pool name from storage (if available)
            deployment = self.storage_service.get_deployment(spoke_id)
            backend_pool_name = None
            routing_rule_name = None
            agw_configured = False

            if deployment:
                backend_pool_name = deployment.get('backend_pool_name')
                routing_rule_name = deployment.get('routing_rule_name')

                # Verify if backend pool actually exists in AGW
                if backend_pool_name:
                    backend_pools = self.agw_service.list_backend_pools()
                    agw_configured = backend_pool_name in backend_pools

            return {
                'spoke_id': spoke_id,
                'exists': True,
                'vnet': spoke_vnet,
                'vm': {
                    'name': vm_name,
                    'status': vm_status,
                    'private_ip': vm_ip
                },
                'agw': {
                    'backend_pool_configured': agw_configured,
                    'backend_pool_name': backend_pool_name,
                    'routing_rule_name': routing_rule_name
                }
            }

        except Exception as e:
            self.logger.error(f"Error getting spoke status: {e}")
            return {
                'spoke_id': spoke_id,
                'exists': False,
                'error': str(e)
            }

    def list_all_spokes(self) -> list[Dict[str, Any]]:
        """
        List all deployed spokes

        Returns:
            List of spoke information dictionaries
        """
        try:
            vnets = self.network_service.list_spoke_vnets()

            spokes = []
            for vnet in vnets:
                # Extract spoke ID from VNet name
                try:
                    spoke_id = int(vnet['name'].split('-')[-1])
                    spoke_info = self.get_spoke_status(spoke_id)
                    spokes.append(spoke_info)
                except (ValueError, IndexError):
                    continue

            return spokes

        except Exception as e:
            self.logger.error(f"Error listing spokes: {e}")
            return []

    def __repr__(self) -> str:
        return f"<SpokeOrchestrator(location={self.settings.AZURE_LOCATION})>"
