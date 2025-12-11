"""
Azure Compute Service

Handles Virtual Machine deployment and management using Azure SDK.
"""

from typing import Optional
from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.compute.models import (
    VirtualMachine,
    HardwareProfile,
    StorageProfile,
    OSDisk,
    OSProfile,
    LinuxConfiguration,
    SshConfiguration,
    SshPublicKey,
    NetworkProfile,
    NetworkInterfaceReference,
    ImageReference,
    DiskCreateOptionTypes,
    CachingTypes
)
from azure.mgmt.network.models import NetworkInterface, NetworkInterfaceIPConfiguration
from azure.core.exceptions import ResourceNotFoundError, HttpResponseError

from config.settings import settings
from utils.logger import get_logger, LogContext
from utils.exceptions import VMDeploymentError
from utils.helpers import wait_with_timeout
from models.spoke_config import SpokeConfiguration


class AzureComputeService:
    """
    Service for managing Azure compute resources

    Handles:
    - VM deployment
    - Network interface creation
    - VM status monitoring
    """

    def __init__(self, credential: Optional[ClientSecretCredential] = None):
        """
        Initialize Azure Compute Service

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

        # Initialize compute and network clients
        self.compute_client = ComputeManagementClient(
            credential=self.credential,
            subscription_id=self.settings.AZURE_SUBSCRIPTION_ID
        )

        self.network_client = NetworkManagementClient(
            credential=self.credential,
            subscription_id=self.settings.AZURE_SUBSCRIPTION_ID
        )

        self.logger.info("Azure Compute Service initialized")

    def create_network_interface(
        self,
        nic_name: str,
        subnet_id: str,
        spoke_id: int,
        private_ip: Optional[str] = None
    ) -> NetworkInterface:
        """
        Create network interface for VM

        Args:
            nic_name: Name for the NIC
            subnet_id: Resource ID of the subnet
            spoke_id: Spoke identifier
            private_ip: Optional static private IP

        Returns:
            Created NetworkInterface object

        Raises:
            VMDeploymentError: If NIC creation fails
        """
        with LogContext(spoke_id=spoke_id):
            try:
                self.logger.info(f"Creating network interface: {nic_name}")

                # Check if NIC already exists
                if self._nic_exists(nic_name):
                    self.logger.warning(f"NIC {nic_name} already exists, retrieving")
                    return self.network_client.network_interfaces.get(
                        resource_group_name=self.settings.RESOURCE_GROUP_NAME,
                        network_interface_name=nic_name
                    )

                # Create NIC parameters
                ip_config = NetworkInterfaceIPConfiguration(
                    name=f"{nic_name}-ipconfig",
                    subnet={'id': subnet_id},
                    private_ip_allocation_method='Dynamic' if not private_ip else 'Static'
                )

                if private_ip:
                    ip_config.private_ip_address = private_ip

                nic_params = NetworkInterface(
                    location=self.settings.AZURE_LOCATION,
                    ip_configurations=[ip_config],
                    tags={
                        'spoke_id': str(spoke_id),
                        'managed_by': 'hub-spoke-automation'
                    }
                )

                # Create NIC (async operation)
                self.logger.debug(f"Starting NIC creation operation for {nic_name}")
                poller = self.network_client.network_interfaces.begin_create_or_update(
                    resource_group_name=self.settings.RESOURCE_GROUP_NAME,
                    network_interface_name=nic_name,
                    parameters=nic_params
                )

                # Wait for completion
                nic = poller.result()
                private_ip_assigned = nic.ip_configurations[0].private_ip_address
                self.logger.info(f"✓ NIC created: {nic_name} with IP: {private_ip_assigned}")

                return nic

            except HttpResponseError as e:
                error_msg = f"Azure API error creating NIC: {str(e)}"
                self.logger.error(error_msg, exc_info=True)
                raise VMDeploymentError(nic_name, error_msg, e)

            except Exception as e:
                error_msg = f"Unexpected error creating NIC: {str(e)}"
                self.logger.error(error_msg, exc_info=True)
                raise VMDeploymentError(nic_name, error_msg, e)

    def create_virtual_machine(
        self,
        spoke_config: SpokeConfiguration,
        nic_id: str
    ) -> VirtualMachine:
        """
        Deploy Linux virtual machine

        Args:
            spoke_config: Spoke configuration with VM details
            nic_id: Resource ID of the network interface

        Returns:
            Created VirtualMachine object

        Raises:
            VMDeploymentError: If VM deployment fails
        """
        vm_name = spoke_config.vm_name

        with LogContext(spoke_id=spoke_config.spoke_id):
            try:
                self.logger.info(f"Deploying VM: {vm_name} (size: {spoke_config.vm_size})")

                # Check if VM already exists
                if self._vm_exists(vm_name):
                    self.logger.warning(f"VM {vm_name} already exists, retrieving")
                    return self.compute_client.virtual_machines.get(
                        resource_group_name=self.settings.RESOURCE_GROUP_NAME,
                        vm_name=vm_name
                    )

                # Prepare SSH configuration
                ssh_public_keys = []
                if spoke_config.ssh_public_key:
                    ssh_public_keys.append(
                        SshPublicKey(
                            path=f'/home/{spoke_config.admin_username}/.ssh/authorized_keys',
                            key_data=spoke_config.ssh_public_key
                        )
                    )

                # Create VM parameters
                vm_params = VirtualMachine(
                    location=self.settings.AZURE_LOCATION,
                    hardware_profile=HardwareProfile(
                        vm_size=spoke_config.vm_size
                    ),
                    storage_profile=StorageProfile(
                        image_reference=ImageReference(
                            publisher='Canonical',
                            offer='0001-com-ubuntu-server-jammy',
                            sku='22_04-lts-gen2',
                            version='latest'
                        ),
                        os_disk=OSDisk(
                            name=f"{vm_name}-osdisk",
                            create_option=DiskCreateOptionTypes.FROM_IMAGE,
                            caching=CachingTypes.READ_WRITE,
                            managed_disk={'storage_account_type': 'Standard_LRS'}
                        )
                    ),
                    os_profile=OSProfile(
                        computer_name=vm_name,
                        admin_username=spoke_config.admin_username,
                        linux_configuration=LinuxConfiguration(
                            disable_password_authentication=True,
                            ssh=SshConfiguration(
                                public_keys=ssh_public_keys
                            )
                        )
                    ),
                    network_profile=NetworkProfile(
                        network_interfaces=[
                            NetworkInterfaceReference(
                                id=nic_id,
                                primary=True
                            )
                        ]
                    ),
                    tags={
                        'spoke_id': str(spoke_config.spoke_id),
                        'client_name': spoke_config.client_name,
                        'managed_by': 'hub-spoke-automation'
                    }
                )

                # Create VM (async operation)
                self.logger.debug(f"Starting VM creation operation for {vm_name}")
                self.logger.info("This may take 5-10 minutes...")

                poller = self.compute_client.virtual_machines.begin_create_or_update(
                    resource_group_name=self.settings.RESOURCE_GROUP_NAME,
                    vm_name=vm_name,
                    parameters=vm_params
                )

                # Wait for completion
                vm = poller.result()
                self.logger.info(f"✓ VM deployed successfully: {vm_name}")
                self.logger.info(f"  - VM ID: {vm.id}")
                self.logger.info(f"  - Provisioning State: {vm.provisioning_state}")

                return vm

            except HttpResponseError as e:
                error_msg = f"Azure API error creating VM: {str(e)}"
                self.logger.error(error_msg, exc_info=True)
                raise VMDeploymentError(vm_name, error_msg, e)

            except Exception as e:
                error_msg = f"Unexpected error creating VM: {str(e)}"
                self.logger.error(error_msg, exc_info=True)
                raise VMDeploymentError(vm_name, error_msg, e)

    def wait_for_vm_ready(self, vm_name: str, timeout_seconds: int = 600) -> bool:
        """
        Wait for VM to reach 'Succeeded' provisioning state

        Args:
            vm_name: Name of the VM
            timeout_seconds: Maximum time to wait (default: 10 minutes)

        Returns:
            True if VM is ready

        Raises:
            TimeoutError: If VM doesn't become ready within timeout
        """
        self.logger.info(f"Waiting for VM {vm_name} to be ready...")

        def check_vm_ready():
            try:
                vm = self.compute_client.virtual_machines.get(
                    resource_group_name=self.settings.RESOURCE_GROUP_NAME,
                    vm_name=vm_name
                )
                return vm.provisioning_state == 'Succeeded'
            except Exception:
                return False

        try:
            wait_with_timeout(
                condition_func=check_vm_ready,
                timeout_seconds=timeout_seconds,
                interval_seconds=10,
                error_message=f"VM {vm_name} did not become ready"
            )

            self.logger.info(f"✓ VM {vm_name} is ready")
            return True

        except TimeoutError as e:
            self.logger.error(str(e))
            raise

    def get_vm_private_ip(self, vm_name: str) -> Optional[str]:
        """
        Get private IP address of VM

        Args:
            vm_name: Name of the VM

        Returns:
            Private IP address or None if not found
        """
        try:
            vm = self.compute_client.virtual_machines.get(
                resource_group_name=self.settings.RESOURCE_GROUP_NAME,
                vm_name=vm_name
            )

            # Get NIC ID from VM
            if not vm.network_profile or not vm.network_profile.network_interfaces:
                return None

            nic_id = vm.network_profile.network_interfaces[0].id
            nic_name = nic_id.split('/')[-1]

            # Get NIC details
            nic = self.network_client.network_interfaces.get(
                resource_group_name=self.settings.RESOURCE_GROUP_NAME,
                network_interface_name=nic_name
            )

            # Get private IP
            if nic.ip_configurations:
                private_ip = nic.ip_configurations[0].private_ip_address
                self.logger.debug(f"VM {vm_name} private IP: {private_ip}")
                return private_ip

            return None

        except Exception as e:
            self.logger.error(f"Error getting VM private IP: {e}")
            return None

    def get_vm_status(self, vm_name: str) -> Optional[str]:
        """
        Get VM power state

        Args:
            vm_name: Name of the VM

        Returns:
            Power state string or None
        """
        try:
            instance_view = self.compute_client.virtual_machines.instance_view(
                resource_group_name=self.settings.RESOURCE_GROUP_NAME,
                vm_name=vm_name
            )

            if instance_view.statuses:
                for status in instance_view.statuses:
                    if status.code.startswith('PowerState/'):
                        power_state = status.code.split('/')[-1]
                        self.logger.debug(f"VM {vm_name} power state: {power_state}")
                        return power_state

            return None

        except Exception as e:
            self.logger.error(f"Error getting VM status: {e}")
            return None

    def delete_vm(self, vm_name: str) -> bool:
        """
        Delete VM (for rollback)

        Args:
            vm_name: Name of VM to delete

        Returns:
            True if deleted successfully
        """
        try:
            self.logger.warning(f"Deleting VM: {vm_name}")

            poller = self.compute_client.virtual_machines.begin_delete(
                resource_group_name=self.settings.RESOURCE_GROUP_NAME,
                vm_name=vm_name
            )

            poller.result()
            self.logger.info(f"✓ VM deleted: {vm_name}")
            return True

        except Exception as e:
            self.logger.error(f"Error deleting VM {vm_name}: {e}")
            return False

    def delete_nic(self, nic_name: str) -> bool:
        """
        Delete network interface (for rollback)

        Args:
            nic_name: Name of NIC to delete

        Returns:
            True if deleted successfully
        """
        try:
            self.logger.warning(f"Deleting NIC: {nic_name}")

            poller = self.network_client.network_interfaces.begin_delete(
                resource_group_name=self.settings.RESOURCE_GROUP_NAME,
                network_interface_name=nic_name
            )

            poller.result()
            self.logger.info(f"✓ NIC deleted: {nic_name}")
            return True

        except Exception as e:
            self.logger.error(f"Error deleting NIC {nic_name}: {e}")
            return False

    def delete_disk(self, disk_name: str) -> bool:
        """
        Delete managed disk (for rollback)

        Args:
            disk_name: Name of disk to delete

        Returns:
            True if deleted successfully
        """
        try:
            self.logger.warning(f"Deleting disk: {disk_name}")

            poller = self.compute_client.disks.begin_delete(
                resource_group_name=self.settings.RESOURCE_GROUP_NAME,
                disk_name=disk_name
            )

            poller.result()
            self.logger.info(f"✓ Disk deleted: {disk_name}")
            return True

        except Exception as e:
            self.logger.error(f"Error deleting disk {disk_name}: {e}")
            return False

    # Private helper methods

    def _nic_exists(self, nic_name: str) -> bool:
        """Check if network interface exists"""
        try:
            self.network_client.network_interfaces.get(
                resource_group_name=self.settings.RESOURCE_GROUP_NAME,
                network_interface_name=nic_name
            )
            return True
        except ResourceNotFoundError:
            return False
        except Exception:
            return False

    def _vm_exists(self, vm_name: str) -> bool:
        """Check if VM exists"""
        try:
            self.compute_client.virtual_machines.get(
                resource_group_name=self.settings.RESOURCE_GROUP_NAME,
                vm_name=vm_name
            )
            return True
        except ResourceNotFoundError:
            return False
        except Exception:
            return False

    def __repr__(self) -> str:
        return f"<AzureComputeService(subscription={self.settings.AZURE_SUBSCRIPTION_ID[:8]}...)>"
