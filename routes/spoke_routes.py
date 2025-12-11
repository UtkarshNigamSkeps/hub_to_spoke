"""
Spoke Routes - REST API Endpoints

Defines all HTTP endpoints for spoke management operations.
"""

from flask import Blueprint, request, jsonify
from utils.logger import get_logger

# Create Blueprint
spoke_bp = Blueprint('spokes', __name__, url_prefix='/api/spokes')
logger = get_logger(__name__)


@spoke_bp.route('', methods=['POST'])
def create_spoke():
    """
    Create a new spoke deployment

    Request Body:
    {
        "spoke_id": 1,
        "client_name": "acme-corp",
        "vm_size": "Standard_B2s",  // Optional
        "admin_username": "azureuser",  // Optional
        "ssh_public_key": "ssh-rsa AAAA..."  // Optional
    }

    Response:
    {
        "status": "success",
        "data": {
            "spoke_id": 1,
            "client_name": "acme-corp",
            "status": "in_progress",
            "deployment_steps": [...],
            "progress": 0
        }
    }
    """
    from controllers.spoke_controller import SpokeController

    try:
        # Get JSON payload
        data = request.get_json()

        if not data:
            return jsonify({
                'status': 'error',
                'message': 'Request body is required'
            }), 400

        # Create spoke via controller
        controller = SpokeController()
        result = controller.create_spoke(data)

        return jsonify({
            'status': 'success',
            'data': result
        }), 201

    except ValueError as e:
        error_msg = str(e)
        logger.warning(f"Validation/Deployment error: {error_msg}")

        # Check if this is a deployment failure (not validation)
        if 'Deployment failed' in error_msg:
            # Extract spoke_id from request data for rollback status info
            spoke_id = data.get('spoke_id') if data else None

            return jsonify({
                'status': 'error',
                'message': error_msg,
                'rollback_status': 'queued',
                'note': f'Automatic rollback is running in background. Check status: GET /api/spokes/{spoke_id}' if spoke_id else 'Automatic rollback queued in background.'
            }), 500
        else:
            # Regular validation error
            return jsonify({
                'status': 'error',
                'message': error_msg
            }), 400

    except Exception as e:
        logger.error(f"Error creating spoke: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Internal server error',
            'details': str(e)
        }), 500


@spoke_bp.route('/<int:spoke_id>', methods=['GET'])
def get_spoke(spoke_id: int):
    """
    Get spoke deployment status

    Path Parameters:
        spoke_id: Spoke identifier (1-254)

    Response:
    {
        "status": "success",
        "data": {
            "spoke_id": 1,
            "exists": true,
            "vnet": {...},
            "vm": {...},
            "agw": {...}
        }
    }
    """
    from controllers.spoke_controller import SpokeController

    try:
        # Validate spoke_id
        if spoke_id < 1 or spoke_id > 254:
            return jsonify({
                'status': 'error',
                'message': 'spoke_id must be between 1 and 254'
            }), 400

        # Get spoke status via controller
        controller = SpokeController()
        result = controller.get_spoke_status(spoke_id)

        if not result.get('exists', False):
            return jsonify({
                'status': 'error',
                'message': f'Spoke {spoke_id} not found'
            }), 404

        return jsonify({
            'status': 'success',
            'data': result
        }), 200

    except Exception as e:
        logger.error(f"Error getting spoke {spoke_id}: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Internal server error',
            'details': str(e)
        }), 500


@spoke_bp.route('', methods=['GET'])
def list_spokes():
    """
    List all deployed spokes

    Query Parameters:
        status: Filter by deployment status (optional)
                Valid values: 'completed', 'failed', 'in_progress', 'pending', 'rolling_back'
        limit: Maximum number of results (optional)

    Examples:
        GET /api/spokes
        GET /api/spokes?status=failed
        GET /api/spokes?status=completed&limit=10

    Response:
    {
        "status": "success",
        "data": [
            {
                "spoke_id": 1,
                "exists": true,
                "deployment_status": "completed",
                "vnet": {...},
                "vm": {...}
            },
            ...
        ],
        "count": 2
    }
    """
    from controllers.spoke_controller import SpokeController

    try:
        # Get query parameters
        status_filter = request.args.get('status')
        limit = request.args.get('limit', type=int)

        # List spokes via controller
        controller = SpokeController()
        spokes = controller.list_spokes(status_filter=status_filter, limit=limit)

        return jsonify({
            'status': 'success',
            'data': spokes,
            'count': len(spokes)
        }), 200

    except Exception as e:
        logger.error(f"Error listing spokes: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Internal server error',
            'details': str(e)
        }), 500


@spoke_bp.route('/<int:spoke_id>', methods=['DELETE'])
def delete_spoke(spoke_id: int):
    """
    Delete/rollback a spoke deployment

    Path Parameters:
        spoke_id: Spoke identifier (1-254)

    Response:
    {
        "status": "success",
        "message": "Spoke 1 deleted successfully",
        "data": {
            "spoke_id": 1,
            "rollback_status": "completed",
            "removed_resources": [...]
        }
    }
    """
    from controllers.spoke_controller import SpokeController

    try:
        # Validate spoke_id
        if spoke_id < 1 or spoke_id > 254:
            return jsonify({
                'status': 'error',
                'message': 'spoke_id must be between 1 and 254'
            }), 400

        # Delete spoke via controller
        controller = SpokeController()
        result = controller.delete_spoke(spoke_id)

        return jsonify({
            'status': 'success',
            'message': f'Spoke {spoke_id} deleted successfully',
            'data': result
        }), 200

    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 404

    except Exception as e:
        logger.error(f"Error deleting spoke {spoke_id}: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Internal server error',
            'details': str(e)
        }), 500


@spoke_bp.errorhandler(404)
def spoke_not_found(e):
    """Handle 404 errors for spoke routes"""
    return jsonify({
        'status': 'error',
        'message': 'Resource not found'
    }), 404


@spoke_bp.errorhandler(500)
def spoke_internal_error(e):
    """Handle 500 errors for spoke routes"""
    logger.error(f"Internal error: {e}", exc_info=True)
    return jsonify({
        'status': 'error',
        'message': 'Internal server error'
    }), 500
