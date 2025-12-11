"""
Azure Network Service

Handles VNet, Subnet, and VNet Peering operations using Azure SDK.
"""

from typing import List, Optional, Dict
from azure.identity import ClientSecretCredential
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.network.models import (
    VirtualNetwork,
    Subnet,
    AddressSpace,
    VirtualNetworkPeering,
    SubResource
)
from azure.core.exceptions import ResourceNotFoundError, HttpResponseError

from config.settings import settings
from utils.logger import get_logger, LogContext
from utils.exceptions import (
    VNetCreationError,
    SubnetCreationError,
    PeeringCreationError,
    ResourceNotFoundError as HubSpokeResourceNotFoundError
)
from utils.helpers import (
    generate_vnet_name,
    generate_subnet_name,
    generate_peering_name
)
from models.spoke_config import SpokeConfiguration


class AzureNetworkService:
    """
    Service for managing Azure network resources

    Handles:
    - VNet creation
    - Subnet creation
    - VNet peering
    - Resource validation
    """

    def __init__(self, credential: Optional[ClientSecretCredential] = None):
        """
        Initialize Azure Network Service

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

        self.logger.info("Azure Network Service initialized")

    def get_next_available_spoke_id(self) -> int:
        """
        Calculate next available spoke ID by checking existing VNets

        Returns:
            Next available spoke ID
        """
        try:
            self.logger.debug("Calculating next available spoke ID")

            vnets = self.network_client.virtual_networks.list(
                resource_group_name=self.settings.RESOURCE_GROUP_NAME
            )

            # Find all spoke VNet IDs
            spoke_ids = []
            for vnet in vnets:
                if vnet.name and vnet.name.startswith('spoke-vnet-'):
                    try:
                        # Extract ID from name: spoke-vnet-1 -> 1
                        spoke_id = int(vnet.name.split('-')[-1])
                        spoke_ids.append(spoke_id)
                    except (ValueError, IndexError):
                        continue

            # Return next ID
            next_id = max(spoke_ids) + 1 if spoke_ids else 1
            self.logger.info(f"Next available spoke ID: {next_id}")
            return next_id

        except Exception as e:
            self.logger.warning(f"Error calculating next spoke ID: {e}, defaulting to 1")
            return 1

    def create_spoke_vnet(
        self,
        spoke_config: SpokeConfiguration,
        spoke_id: Optional[int] = None
    ) -> VirtualNetwork:
        """
        Create a spoke VNet

        Args:
            spoke_config: Spoke configuration
            spoke_id: Optional spoke ID override

        Returns:
            Created VirtualNetwork object

        Raises:
            VNetCreationError: If VNet creation fails
        """
        vnet_name = generate_vnet_name(spoke_id or spoke_config.spoke_id)

        with LogContext(spoke_id=spoke_config.spoke_id):
            try:
                self.logger.info(f"Creating VNet: {vnet_name} with CIDR: {spoke_config.address_prefix}")

                # Check if VNet already exists
                if self._vnet_exists(vnet_name):
                    self.logger.warning(f"VNet {vnet_name} already exists, retrieving existing")
                    return self.network_client.virtual_networks.get(
                        resource_group_name=self.settings.RESOURCE_GROUP_NAME,
                        virtual_network_name=vnet_name
                    )

                # Create VNet parameters
                vnet_params = VirtualNetwork(
                    location=self.settings.AZURE_LOCATION,
                    address_space=AddressSpace(
                        address_prefixes=[spoke_config.address_prefix]
                    ),
                    tags={
                        'spoke_id': str(spoke_config.spoke_id),
                        'client_name': spoke_config.client_name,
                        'managed_by': 'hub-spoke-automation'
                    }
                )

                # Create VNet (async operation)
                self.logger.debug(f"Starting VNet creation operation for {vnet_name}")
                poller = self.network_client.virtual_networks.begin_create_or_update(
                    resource_group_name=self.settings.RESOURCE_GROUP_NAME,
                    virtual_network_name=vnet_name,
                    parameters=vnet_params
                )

                # Wait for completion
                vnet = poller.result()
                self.logger.info(f"✓ VNet created successfully: {vnet_name} (ID: {vnet.id})")

                return vnet

            except HttpResponseError as e:
                error_msg = f"Azure API error creating VNet: {str(e)}"
                self.logger.error(error_msg, exc_info=True)
                raise VNetCreationError(vnet_name, error_msg, e)

            except Exception as e:
                error_msg = f"Unexpected error creating VNet: {str(e)}"
                self.logger.error(error_msg, exc_info=True)
                raise VNetCreationError(vnet_name, error_msg, e)

    def create_subnets(
        self,
        spoke_config: SpokeConfiguration,
        vnet_name: Optional[str] = None
    ) -> List[Subnet]:
        """
        Create all four subnets in a spoke VNet

        Args:
            spoke_config: Spoke configuration with subnet CIDRs
            vnet_name: Optional VNet name override

        Returns:
            List of created Subnet objects

        Raises:
            SubnetCreationError: If subnet creation fails
        """
        vnet_name = vnet_name or generate_vnet_name(spoke_config.spoke_id)

        with LogContext(spoke_id=spoke_config.spoke_id):
            self.logger.info(f"Creating subnets in VNet: {vnet_name}")

            # Define subnets to create
            subnet_configs = [
                ('vm', spoke_config.vm_subnet_prefix),
                ('db', spoke_config.db_subnet_prefix),
                ('kv', spoke_config.kv_subnet_prefix),
                ('workspace', spoke_config.workspace_subnet_prefix)
            ]

            created_subnets = []

            for subnet_type, subnet_cidr in subnet_configs:
                subnet_name = generate_subnet_name(spoke_config.spoke_id, subnet_type)

                try:
                    self.logger.debug(f"Creating subnet: {subnet_name} with CIDR: {subnet_cidr}")

                    # Check if subnet already exists
                    if self._subnet_exists(vnet_name, subnet_name):
                        self.logger.warning(f"Subnet {subnet_name} already exists, retrieving")
                        subnet = self.network_client.subnets.get(
                            resource_group_name=self.settings.RESOURCE_GROUP_NAME,
                            virtual_network_name=vnet_name,
                            subnet_name=subnet_name
                        )
                        created_subnets.append(subnet)
                        continue

                    # Create subnet parameters
                    subnet_params = Subnet(
                        address_prefix=subnet_cidr,
                        name=subnet_name
                    )

                    # Create subnet (async operation)
                    poller = self.network_client.subnets.begin_create_or_update(
                        resource_group_name=self.settings.RESOURCE_GROUP_NAME,
                        virtual_network_name=vnet_name,
                        subnet_name=subnet_name,
                        subnet_parameters=subnet_params
                    )

                    # Wait for completion
                    subnet = poller.result()
                    created_subnets.append(subnet)
                    self.logger.info(f"✓ Subnet created: {subnet_name}")

                except HttpResponseError as e:
                    error_msg = f"Azure API error creating subnet {subnet_name}: {str(e)}"
                    self.logger.error(error_msg, exc_info=True)
                    raise SubnetCreationError(subnet_name, error_msg, e)

                except Exception as e:
                    error_msg = f"Unexpected error creating subnet {subnet_name}: {str(e)}"
                    self.logger.error(error_msg, exc_info=True)
                    raise SubnetCreationError(subnet_name, error_msg, e)

            self.logger.info(f"✓ All {len(created_subnets)} subnets created successfully")
            return created_subnets

    def create_vnet_peering(
        self,
        spoke_vnet_name: str,
        spoke_vnet_id: str
    ) -> tuple[VirtualNetworkPeering, VirtualNetworkPeering]:
        """
        Create bidirectional VNet peering between Hub and Spoke

        Args:
            spoke_vnet_name: Name of the spoke VNet
            spoke_vnet_id: Resource ID of the spoke VNet

        Returns:
            Tuple of (hub_to_spoke_peering, spoke_to_hub_peering)

        Raises:
            PeeringCreationError: If peering creation fails
        """
        hub_vnet_name = self.settings.HUB_VNET_NAME

        try:
            self.logger.info(f"Creating VNet peering between {hub_vnet_name} and {spoke_vnet_name}")

            # Get Hub VNet
            hub_vnet = self.network_client.virtual_networks.get(
                resource_group_name=self.settings.HUB_VNET_RESOURCE_GROUP,
                virtual_network_name=hub_vnet_name
            )
            hub_vnet_id = hub_vnet.id

            # Create peering names
            hub_to_spoke_peering_name = generate_peering_name(hub_vnet_name, spoke_vnet_name)
            spoke_to_hub_peering_name = generate_peering_name(spoke_vnet_name, hub_vnet_name)

            # Create Hub -> Spoke peering
            self.logger.debug(f"Creating peering: {hub_to_spoke_peering_name}")
            hub_to_spoke_params = VirtualNetworkPeering(
                allow_virtual_network_access=True,
                allow_forwarded_traffic=True,
                allow_gateway_transit=False,
                use_remote_gateways=False,
                remote_virtual_network=SubResource(id=spoke_vnet_id)
            )

            hub_to_spoke_poller = self.network_client.virtual_network_peerings.begin_create_or_update(
                resource_group_name=self.settings.HUB_VNET_RESOURCE_GROUP,
                virtual_network_name=hub_vnet_name,
                virtual_network_peering_name=hub_to_spoke_peering_name,
                virtual_network_peering_parameters=hub_to_spoke_params
            )

            # Create Spoke -> Hub peering
            self.logger.debug(f"Creating peering: {spoke_to_hub_peering_name}")
            spoke_to_hub_params = VirtualNetworkPeering(
                allow_virtual_network_access=True,
                allow_forwarded_traffic=True,
                allow_gateway_transit=False,
                use_remote_gateways=False,
                remote_virtual_network=SubResource(id=hub_vnet_id)
            )

            spoke_to_hub_poller = self.network_client.virtual_network_peerings.begin_create_or_update(
                resource_group_name=self.settings.RESOURCE_GROUP_NAME,
                virtual_network_name=spoke_vnet_name,
                virtual_network_peering_name=spoke_to_hub_peering_name,
                virtual_network_peering_parameters=spoke_to_hub_params
            )

            # Wait for both peerings to complete
            hub_to_spoke_peering = hub_to_spoke_poller.result()
            spoke_to_hub_peering = spoke_to_hub_poller.result()

            self.logger.info(f"✓ VNet peering created successfully")
            self.logger.info(f"  - {hub_to_spoke_peering_name}: {hub_to_spoke_peering.peering_state}")
            self.logger.info(f"  - {spoke_to_hub_peering_name}: {spoke_to_hub_peering.peering_state}")

            return hub_to_spoke_peering, spoke_to_hub_peering

        except ResourceNotFoundError:
            error_msg = f"Hub VNet '{hub_vnet_name}' not found"
            self.logger.error(error_msg, exc_info=True)
            raise HubSpokeResourceNotFoundError("VNet", hub_vnet_name)

        except HttpResponseError as e:
            error_msg = f"Azure API error creating peering: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise PeeringCreationError(f"{hub_vnet_name}-{spoke_vnet_name}", error_msg, e)

        except Exception as e:
            error_msg = f"Unexpected error creating peering: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise PeeringCreationError(f"{hub_vnet_name}-{spoke_vnet_name}", error_msg, e)

    def verify_vnet_connectivity(self, spoke_vnet_name: str) -> bool:
        """
        Verify that peering is established and connected

        Args:
            spoke_vnet_name: Name of the spoke VNet

        Returns:
            True if peering is connected, False otherwise
        """
        try:
            self.logger.debug(f"Verifying connectivity for {spoke_vnet_name}")

            hub_vnet_name = self.settings.HUB_VNET_NAME
            peering_name = generate_peering_name(hub_vnet_name, spoke_vnet_name)

            # Get peering status
            peering = self.network_client.virtual_network_peerings.get(
                resource_group_name=self.settings.HUB_VNET_RESOURCE_GROUP,
                virtual_network_name=hub_vnet_name,
                virtual_network_peering_name=peering_name
            )

            is_connected = peering.peering_state == "Connected"
            self.logger.info(f"Peering status: {peering.peering_state}, Connected: {is_connected}")

            return is_connected

        except Exception as e:
            self.logger.warning(f"Error verifying connectivity: {e}")
            return False

    def get_subnet_by_name(self, vnet_name: str, subnet_name: str) -> Optional[Subnet]:
        """
        Get subnet by name

        Args:
            vnet_name: VNet name
            subnet_name: Subnet name

        Returns:
            Subnet object or None if not found
        """
        try:
            subnet = self.network_client.subnets.get(
                resource_group_name=self.settings.RESOURCE_GROUP_NAME,
                virtual_network_name=vnet_name,
                subnet_name=subnet_name
            )
            return subnet
        except ResourceNotFoundError:
            return None
        except Exception as e:
            self.logger.error(f"Error getting subnet {subnet_name}: {e}")
            return None

    def delete_spoke_vnet(self, vnet_name: str) -> bool:
        """
        Delete a spoke VNet (for rollback)

        Args:
            vnet_name: Name of VNet to delete

        Returns:
            True if deleted successfully
        """
        try:
            self.logger.warning(f"Deleting VNet: {vnet_name}")

            poller = self.network_client.virtual_networks.begin_delete(
                resource_group_name=self.settings.RESOURCE_GROUP_NAME,
                virtual_network_name=vnet_name
            )

            poller.result()
            self.logger.info(f"✓ VNet deleted: {vnet_name}")
            return True

        except Exception as e:
            self.logger.error(f"Error deleting VNet {vnet_name}: {e}")
            return False

    # Private helper methods

    def _vnet_exists(self, vnet_name: str) -> bool:
        """Check if VNet exists"""
        try:
            self.network_client.virtual_networks.get(
                resource_group_name=self.settings.RESOURCE_GROUP_NAME,
                virtual_network_name=vnet_name
            )
            return True
        except ResourceNotFoundError:
            return False
        except Exception:
            return False

    def _subnet_exists(self, vnet_name: str, subnet_name: str) -> bool:
        """Check if subnet exists"""
        try:
            self.network_client.subnets.get(
                resource_group_name=self.settings.RESOURCE_GROUP_NAME,
                virtual_network_name=vnet_name,
                subnet_name=subnet_name
            )
            return True
        except ResourceNotFoundError:
            return False
        except Exception:
            return False

    def list_spoke_vnets(self) -> List[Dict]:
        """
        List all spoke VNets in the resource group

        Returns:
            List of spoke VNet information dictionaries
        """
        try:
            vnets = self.network_client.virtual_networks.list(
                resource_group_name=self.settings.RESOURCE_GROUP_NAME
            )

            spoke_vnets = []
            for vnet in vnets:
                if vnet.name and vnet.name.startswith('spoke-vnet-'):
                    spoke_info = {
                        'name': vnet.name,
                        'id': vnet.id,
                        'location': vnet.location,
                        'address_space': vnet.address_space.address_prefixes if vnet.address_space else [],
                        'tags': vnet.tags or {}
                    }
                    spoke_vnets.append(spoke_info)

            return spoke_vnets

        except Exception as e:
            self.logger.error(f"Error listing spoke VNets: {e}")
            return []

    def __repr__(self) -> str:
        return f"<AzureNetworkService(subscription={self.settings.AZURE_SUBSCRIPTION_ID[:8]}...)>"
