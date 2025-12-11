"""
Hub-and-Spoke Azure Deployment Automation
Flask Application Entry Point
"""

from flask import Flask
from flask_cors import CORS
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def create_app():
    """
    Application factory pattern
    Creates and configures the Flask application
    """
    app = Flask(__name__)

    # Configuration
    app.config['JSON_SORT_KEYS'] = False
    app.config['DEBUG'] = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'

    # Enable CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Setup logging
    from utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("Initializing Hub-and-Spoke Automation API")

    # Register blueprints (routes)
    from routes.spoke_routes import spoke_bp

    app.register_blueprint(spoke_bp)

    logger.info("Blueprints registered successfully")

    # Error handlers
    @app.errorhandler(404)
    def not_found(_error):
        return {'error': 'Not found', 'message': 'The requested resource was not found'}, 404

    @app.errorhandler(500)
    def internal_error(_error):
        return {'error': 'Internal server error', 'message': 'An unexpected error occurred'}, 500

    @app.errorhandler(400)
    def bad_request(_error):
        return {'error': 'Bad request', 'message': 'The request was invalid'}, 400

    # Root endpoint
    @app.route('/', methods=['GET'])
    def index():
        return {
            'message': 'Hub-and-Spoke Azure Deployment Automation API',
            'version': '1.0.0',
            'endpoints': {
                'spokes': '/api/spokes',
                'docs': 'See README.md for API documentation'
            }
        }, 200

    return app


if __name__ == '__main__':
    app = create_app()

    # Get configuration from environment
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    use_reloader = os.getenv('FLASK_NO_RELOAD', 'False').lower() != 'true'  # Disable if FLASK_NO_RELOAD=true

    print(f"Starting Hub-and-Spoke Automation API...")
    print(f"Server running on http://{host}:{port}")
    print(f"Debug mode: {debug}")
    print(f"Auto-reload: {use_reloader}")
    if not use_reloader:
        print("⚠️  Auto-reload DISABLED - Background rollback threads will complete successfully")

    app.run(host=host, port=port, debug=debug, use_reloader=use_reloader)
