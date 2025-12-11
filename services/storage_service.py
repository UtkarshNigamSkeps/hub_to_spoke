"""
Storage Service - JSON File Persistence

Handles saving and loading deployment data to/from JSON file.
"""

import json
import os
from typing import List, Optional, Dict, Any
from threading import Lock

from config.settings import settings
from models.deployment_status import DeploymentStatus
from utils.logger import get_logger
from utils.exceptions import StorageException


class StorageService:
    """
    Manages deployment data persistence using JSON file

    Features:
    - Thread-safe read/write operations
    - Automatic file creation
    - Query deployments by spoke_id or status
    - Deployment history tracking
    """

    def __init__(self, storage_file: Optional[str] = None):
        """
        Initialize storage service

        Args:
            storage_file: Path to JSON storage file (defaults to settings)
        """
        self.logger = get_logger(__name__)
        self.storage_file = storage_file or settings.DEPLOYMENTS_DB_FILE
        self._lock = Lock()  # Thread-safe operations

        # Ensure storage directory exists
        self._ensure_storage_directory()

        # Initialize file if it doesn't exist
        self._initialize_storage_file()

    def _ensure_storage_directory(self):
        """Create storage directory if it doesn't exist"""
        storage_dir = os.path.dirname(self.storage_file)
        if storage_dir and not os.path.exists(storage_dir):
            os.makedirs(storage_dir, exist_ok=True)
            self.logger.info(f"Created storage directory: {storage_dir}")

    def _initialize_storage_file(self):
        """Create empty storage file if it doesn't exist"""
        if not os.path.exists(self.storage_file):
            with self._lock:
                self._write_data({"deployments": []})
                self.logger.info(f"Initialized storage file: {self.storage_file}")

    def _read_data(self) -> Dict[str, Any]:
        """
        Read data from JSON file

        Returns:
            Dictionary with deployments data
        """
        try:
            with open(self.storage_file, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON decode error: {e}")
            return {"deployments": []}
        except Exception as e:
            self.logger.error(f"Error reading storage file: {e}")
            return {"deployments": []}

    def _write_data(self, data: Dict[str, Any]):
        """
        Write data to JSON file

        Args:
            data: Dictionary to write
        """
        try:
            with open(self.storage_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            self.logger.error(f"Error writing storage file: {e}")
            raise StorageException("storage_write", f"Failed to write storage: {str(e)}")

    def save_deployment(self, deployment_status: DeploymentStatus) -> bool:
        """
        Save or update a deployment record

        Args:
            deployment_status: DeploymentStatus object to save

        Returns:
            True if saved successfully
        """
        with self._lock:
            try:
                data = self._read_data()
                deployments = data.get("deployments", [])

                # Convert DeploymentStatus to dict
                deployment_dict = self._status_to_dict(deployment_status)

                # Check if deployment already exists (update)
                existing_index = None
                for i, dep in enumerate(deployments):
                    if dep.get("spoke_id") == deployment_status.spoke_id:
                        existing_index = i
                        break

                if existing_index is not None:
                    # Update existing
                    deployments[existing_index] = deployment_dict
                    self.logger.debug(f"Updated deployment for spoke {deployment_status.spoke_id}")
                else:
                    # Add new
                    deployments.append(deployment_dict)
                    self.logger.debug(f"Saved new deployment for spoke {deployment_status.spoke_id}")

                data["deployments"] = deployments
                self._write_data(data)

                return True

            except Exception as e:
                self.logger.error(f"Error saving deployment: {e}")
                return False

    def get_deployment(self, spoke_id: int) -> Optional[Dict[str, Any]]:
        """
        Get deployment by spoke_id

        Args:
            spoke_id: Spoke identifier

        Returns:
            Deployment dictionary or None
        """
        with self._lock:
            try:
                data = self._read_data()
                deployments = data.get("deployments", [])

                for deployment in deployments:
                    if deployment.get("spoke_id") == spoke_id:
                        return deployment

                return None

            except Exception as e:
                self.logger.error(f"Error getting deployment: {e}")
                return None

    def list_deployments(
        self,
        status_filter: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        List all deployments with optional filtering

        Args:
            status_filter: Filter by status (e.g., 'completed', 'failed')
            limit: Maximum number of results

        Returns:
            List of deployment dictionaries
        """
        with self._lock:
            try:
                data = self._read_data()
                deployments = data.get("deployments", [])

                # Apply status filter
                if status_filter:
                    deployments = [
                        d for d in deployments
                        if d.get("status") == status_filter
                    ]

                # Sort by created_at (most recent first)
                deployments.sort(
                    key=lambda x: x.get("created_at", ""),
                    reverse=True
                )

                # Apply limit
                if limit and limit > 0:
                    deployments = deployments[:limit]

                return deployments

            except Exception as e:
                self.logger.error(f"Error listing deployments: {e}")
                return []

    def delete_deployment(self, spoke_id: int) -> bool:
        """
        Delete a deployment record

        Args:
            spoke_id: Spoke identifier

        Returns:
            True if deleted successfully
        """
        with self._lock:
            try:
                data = self._read_data()
                deployments = data.get("deployments", [])

                # Filter out the deployment to delete
                original_count = len(deployments)
                deployments = [
                    d for d in deployments
                    if d.get("spoke_id") != spoke_id
                ]

                if len(deployments) < original_count:
                    data["deployments"] = deployments
                    self._write_data(data)
                    self.logger.info(f"Deleted deployment for spoke {spoke_id}")
                    return True
                else:
                    self.logger.warning(f"No deployment found for spoke {spoke_id}")
                    return False

            except Exception as e:
                self.logger.error(f"Error deleting deployment: {e}")
                return False

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get deployment statistics

        Returns:
            Dictionary with statistics
        """
        with self._lock:
            try:
                data = self._read_data()
                deployments = data.get("deployments", [])

                stats = {
                    "total_deployments": len(deployments),
                    "completed": 0,
                    "in_progress": 0,
                    "failed": 0,
                    "rolled_back": 0,
                    "latest_deployment": None
                }

                for deployment in deployments:
                    status = deployment.get("status", "")
                    if "completed" in status.lower():
                        stats["completed"] += 1
                    elif "progress" in status.lower():
                        stats["in_progress"] += 1
                    elif "failed" in status.lower():
                        stats["failed"] += 1
                    elif "rolled" in status.lower():
                        stats["rolled_back"] += 1

                # Get latest deployment
                if deployments:
                    latest = max(
                        deployments,
                        key=lambda x: x.get("created_at", ""),
                        default=None
                    )
                    stats["latest_deployment"] = latest

                return stats

            except Exception as e:
                self.logger.error(f"Error getting statistics: {e}")
                return {"error": str(e)}

    def _status_to_dict(self, status: DeploymentStatus) -> Dict[str, Any]:
        """
        Convert DeploymentStatus to dictionary

        Args:
            status: DeploymentStatus object

        Returns:
            Dictionary representation
        """
        return {
            "spoke_id": status.spoke_id,
            "client_name": status.client_name,
            "status": status.status,
            "vnet_name": status.vnet_name,
            "vnet_id": status.vnet_id,
            "vm_name": status.vm_name,
            "vm_id": status.vm_id,
            "vm_private_ip": status.vm_private_ip,
            "backend_pool_name": status.backend_pool_name,
            "routing_rule_name": status.routing_rule_name,
            "deployment_steps": [
                {
                    "step_name": step.step_name,
                    "status": step.status,
                    "started_at": step.started_at,
                    "completed_at": step.completed_at,
                    "error_message": step.error_message
                }
                for step in status.deployment_steps
            ],
            "created_at": status.created_at,
            "updated_at": status.updated_at,
            "completed_at": status.completed_at,
            "error_message": status.error_message,
            "failed_step": status.failed_step
        }

    def clear_all(self) -> bool:
        """
        Clear all deployment data (use with caution!)

        Returns:
            True if cleared successfully
        """
        with self._lock:
            try:
                self._write_data({"deployments": []})
                self.logger.warning("Cleared all deployment data")
                return True
            except Exception as e:
                self.logger.error(f"Error clearing data: {e}")
                return False
