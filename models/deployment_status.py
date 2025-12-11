"""
Deployment Status Tracking Model

Tracks the progress and status of spoke deployments.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum
from utils.helpers import get_timestamp


class DeploymentStatusEnum(str, Enum):
    """Deployment status values"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    ROLLBACK_FAILED = "rollback_failed"


class DeploymentStepEnum(str, Enum):
    """Deployment step names"""
    VNET_CREATION = "vnet_creation"
    SUBNET_CREATION = "subnet_creation"
    VM_DEPLOYMENT = "vm_deployment"
    VNET_PEERING = "vnet_peering"
    AGW_UPDATE = "agw_update"


@dataclass
class DeploymentStep:
    """
    Individual step in the deployment process

    Attributes:
        step_name: Name of the step (vnet, subnets, vm, peering, agw)
        status: Current status (pending, in_progress, completed, failed)
        started_at: When the step started
        completed_at: When the step completed
        error_message: Error message if failed
    """
    step_name: str
    status: str = DeploymentStatusEnum.PENDING
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None

    def start(self):
        """Mark step as started"""
        self.status = DeploymentStatusEnum.IN_PROGRESS
        self.started_at = get_timestamp()

    def complete(self):
        """Mark step as completed"""
        self.status = DeploymentStatusEnum.COMPLETED
        self.completed_at = get_timestamp()

    def fail(self, error_message: str):
        """Mark step as failed"""
        self.status = DeploymentStatusEnum.FAILED
        self.completed_at = get_timestamp()
        self.error_message = error_message

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            "step_name": self.step_name,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error_message": self.error_message
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'DeploymentStep':
        """Create from dictionary"""
        return cls(
            step_name=data['step_name'],
            status=data.get('status', DeploymentStatusEnum.PENDING),
            started_at=data.get('started_at'),
            completed_at=data.get('completed_at'),
            error_message=data.get('error_message')
        )


@dataclass
class DeploymentStatus:
    """
    Tracks the overall deployment status for a spoke

    Attributes:
        spoke_id: Spoke identifier
        client_name: Client/project name
        status: Overall deployment status
        vnet_name: Name of created VNet
        vnet_id: Azure resource ID of VNet
        vm_name: Name of created VM
        vm_id: Azure resource ID of VM
        vm_private_ip: Private IP address of VM
        deployment_steps: List of deployment steps
        created_at: When deployment was initiated
        updated_at: Last update timestamp
        completed_at: When deployment completed (if completed)
        error_message: Overall error message (if failed)
        failed_step: Which step failed (if failed)
    """

    # Identity
    spoke_id: int
    client_name: str

    # Status
    status: str = DeploymentStatusEnum.PENDING

    # Resources Created
    vnet_name: Optional[str] = None
    vnet_id: Optional[str] = None
    vm_name: Optional[str] = None
    vm_id: Optional[str] = None
    vm_private_ip: Optional[str] = None
    backend_pool_name: Optional[str] = None
    routing_rule_name: Optional[str] = None

    # Deployment Steps
    deployment_steps: List[DeploymentStep] = field(default_factory=list)

    # Timestamps
    created_at: str = field(default_factory=get_timestamp)
    updated_at: str = field(default_factory=get_timestamp)
    completed_at: Optional[str] = None

    # Error Information
    error_message: Optional[str] = None
    failed_step: Optional[str] = None

    def __post_init__(self):
        """Initialize deployment steps if not provided"""
        # Steps will be created dynamically as the deployment progresses
        # via the update_step() method
        if not self.deployment_steps:
            self.deployment_steps = []

    def get_step(self, step_name: str) -> Optional[DeploymentStep]:
        """
        Get a specific deployment step

        Args:
            step_name: Name of the step

        Returns:
            DeploymentStep or None if not found
        """
        for step in self.deployment_steps:
            if step.step_name == step_name:
                return step
        return None

    def update_step(self, step_name: str, status: str, error: Optional[str] = None):
        """
        Update status of a specific step

        Args:
            step_name: Name of the step to update
            status: New status (pending, in_progress, completed, failed)
            error: Error message if failed
        """
        step = self.get_step(step_name)
        if not step:
            # Create step if it doesn't exist
            step = DeploymentStep(step_name=step_name)
            self.deployment_steps.append(step)

        if status == DeploymentStatusEnum.IN_PROGRESS:
            step.start()
            if self.status == DeploymentStatusEnum.PENDING:
                self.status = DeploymentStatusEnum.IN_PROGRESS
        elif status == DeploymentStatusEnum.COMPLETED:
            step.complete()
        elif status == DeploymentStatusEnum.FAILED:
            step.fail(error or "Unknown error")
            self.mark_failed(step_name, error)

        self.updated_at = get_timestamp()

    def mark_completed(self):
        """Mark entire deployment as completed"""
        self.status = DeploymentStatusEnum.COMPLETED
        self.completed_at = get_timestamp()
        self.updated_at = get_timestamp()

    def mark_failed(self, step: str, error: str):
        """
        Mark deployment as failed at a specific step

        Args:
            step: Step name where failure occurred
            error: Error message
        """
        self.status = DeploymentStatusEnum.FAILED
        self.failed_step = step
        self.error_message = error
        self.completed_at = get_timestamp()
        self.updated_at = get_timestamp()

    def get_progress_percentage(self) -> int:
        """
        Calculate deployment progress as percentage

        Returns:
            Progress percentage (0-100)
        """
        if not self.deployment_steps:
            return 0

        completed_steps = sum(
            1 for step in self.deployment_steps
            if step.status == DeploymentStatusEnum.COMPLETED
        )
        total_steps = len(self.deployment_steps)

        return int((completed_steps / total_steps) * 100) if total_steps > 0 else 0

    def get_current_step(self) -> Optional[DeploymentStep]:
        """
        Get the current step being executed

        Returns:
            Current step or None
        """
        for step in self.deployment_steps:
            if step.status == DeploymentStatusEnum.IN_PROGRESS:
                return step
        return None

    def is_completed(self) -> bool:
        """Check if deployment is completed"""
        return self.status == DeploymentStatusEnum.COMPLETED

    def is_failed(self) -> bool:
        """Check if deployment has failed"""
        return self.status == DeploymentStatusEnum.FAILED

    def is_in_progress(self) -> bool:
        """Check if deployment is in progress"""
        return self.status == DeploymentStatusEnum.IN_PROGRESS

    def to_dict(self) -> Dict:
        """
        Convert to dictionary for API response/storage

        Returns:
            Dictionary representation
        """
        return {
            "spoke_id": self.spoke_id,
            "client_name": self.client_name,
            "status": self.status,
            "vnet_name": self.vnet_name,
            "vnet_id": self.vnet_id,
            "vm_name": self.vm_name,
            "vm_id": self.vm_id,
            "vm_private_ip": self.vm_private_ip,
            "backend_pool_name": self.backend_pool_name,
            "routing_rule_name": self.routing_rule_name,
            "deployment_steps": [step.to_dict() for step in self.deployment_steps],
            "progress_percentage": self.get_progress_percentage(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "error_message": self.error_message,
            "failed_step": self.failed_step
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'DeploymentStatus':
        """
        Create from dictionary (load from storage)

        Args:
            data: Dictionary with deployment status data

        Returns:
            DeploymentStatus instance
        """
        steps = [
            DeploymentStep.from_dict(step_data)
            for step_data in data.get('deployment_steps', [])
        ]

        return cls(
            spoke_id=data['spoke_id'],
            client_name=data['client_name'],
            status=data.get('status', DeploymentStatusEnum.PENDING),
            vnet_name=data.get('vnet_name'),
            vnet_id=data.get('vnet_id'),
            vm_name=data.get('vm_name'),
            vm_id=data.get('vm_id'),
            vm_private_ip=data.get('vm_private_ip'),
            backend_pool_name=data.get('backend_pool_name'),
            routing_rule_name=data.get('routing_rule_name'),
            deployment_steps=steps,
            created_at=data.get('created_at', get_timestamp()),
            updated_at=data.get('updated_at', get_timestamp()),
            completed_at=data.get('completed_at'),
            error_message=data.get('error_message'),
            failed_step=data.get('failed_step')
        )

    def get_summary(self) -> Dict:
        """
        Get a brief summary (for list view)

        Returns:
            Summary dictionary
        """
        return {
            "spoke_id": self.spoke_id,
            "client_name": self.client_name,
            "status": self.status,
            "progress_percentage": self.get_progress_percentage(),
            "vnet_name": self.vnet_name,
            "vm_name": self.vm_name,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }

    def __repr__(self) -> str:
        return (
            f"<DeploymentStatus(spoke_id={self.spoke_id}, "
            f"client_name='{self.client_name}', "
            f"status='{self.status}', "
            f"progress={self.get_progress_percentage()}%)>"
        )
