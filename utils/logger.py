"""
Logging Framework for Hub-Spoke Automation

Provides structured logging with:
- Console output (colored, formatted)
- File output (rotating logs)
- Error-only file
- Context injection (spoke_id tracking)
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional


# Color codes for terminal output
class Colors:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    GRAY = '\033[90m'


class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors for console output"""

    COLORS = {
        'DEBUG': Colors.GRAY,
        'INFO': Colors.GREEN,
        'WARNING': Colors.YELLOW,
        'ERROR': Colors.RED,
        'CRITICAL': Colors.RED + Colors.BOLD,
    }

    def format(self, record):
        # Add color to level name
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{levelname}{Colors.RESET}"

        # Format the message
        formatted = super().format(record)

        # Reset color at the end
        return formatted


class ContextFilter(logging.Filter):
    """Add context information to log records"""

    def filter(self, record):
        # Add context fields if not present
        if not hasattr(record, 'spoke_id'):
            record.spoke_id = 'N/A'
        if not hasattr(record, 'correlation_id'):
            record.correlation_id = 'N/A'
        return True


def setup_logging(
    log_level: str = "INFO",
    log_file: str = "logs/hub_spoke_deployment.log",
    error_log_file: str = "logs/errors.log",
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    enable_console: bool = True,
    enable_colors: bool = True
) -> None:
    """
    Setup application logging

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to main log file
        error_log_file: Path to error-only log file
        max_bytes: Max size of log file before rotation
        backup_count: Number of backup log files to keep
        enable_console: Enable console output
        enable_colors: Enable colored console output
    """

    # Ensure log directory exists
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    error_log_dir = os.path.dirname(error_log_file)
    if error_log_dir and not os.path.exists(error_log_dir):
        os.makedirs(error_log_dir, exist_ok=True)

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Remove existing handlers
    root_logger.handlers.clear()

    # Create context filter
    context_filter = ContextFilter()

    # Format for log messages
    detailed_format = (
        '%(asctime)s - %(levelname)s - %(name)s - '
        '[spoke_id:%(spoke_id)s] - %(message)s'
    )

    # Console Handler (with colors)
    if enable_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(getattr(logging, log_level.upper()))

        if enable_colors:
            console_formatter = ColoredFormatter(
                fmt=detailed_format,
                datefmt='%Y-%m-%d %H:%M:%S'
            )
        else:
            console_formatter = logging.Formatter(
                fmt=detailed_format,
                datefmt='%Y-%m-%d %H:%M:%S'
            )

        console_handler.setFormatter(console_formatter)
        console_handler.addFilter(context_filter)
        root_logger.addHandler(console_handler)

    # File Handler (all logs with rotation)
    if log_file:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)  # Capture everything in file

        file_formatter = logging.Formatter(
            fmt=detailed_format,
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        file_handler.addFilter(context_filter)
        root_logger.addHandler(file_handler)

    # Error File Handler (errors only)
    if error_log_file:
        error_handler = RotatingFileHandler(
            error_log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)

        error_formatter = logging.Formatter(
            fmt=detailed_format,
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        error_handler.setFormatter(error_formatter)
        error_handler.addFilter(context_filter)
        root_logger.addHandler(error_handler)

    # Suppress noisy third-party loggers
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('azure').setLevel(logging.WARNING)
    logging.getLogger('werkzeug').setLevel(logging.WARNING)

    # Log initialization
    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized - Level: {log_level}")
    logger.info(f"Log file: {log_file}")
    logger.info(f"Error log file: {error_log_file}")


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a module

    Args:
        name: Usually __name__ of the calling module

    Returns:
        Logger instance

    Usage:
        logger = get_logger(__name__)
        logger.info("Message")
    """
    return logging.getLogger(name)


class LogContext:
    """
    Context manager for adding context to log messages

    Usage:
        with LogContext(spoke_id=1):
            logger.info("Creating VNet")
            # Output: ... [spoke_id:1] - Creating VNet
    """

    def __init__(self, spoke_id: Optional[int] = None, correlation_id: Optional[str] = None):
        self.spoke_id = spoke_id
        self.correlation_id = correlation_id or self._generate_correlation_id()
        self.old_factory = None

    def __enter__(self):
        # Save old factory
        self.old_factory = logging.getLogRecordFactory()

        # Create new factory with context
        spoke_id = self.spoke_id
        correlation_id = self.correlation_id

        def record_factory(*args, **kwargs):
            record = self.old_factory(*args, **kwargs)
            record.spoke_id = spoke_id if spoke_id is not None else 'N/A'
            record.correlation_id = correlation_id
            return record

        logging.setLogRecordFactory(record_factory)
        return self

    def __exit__(self, _exc_type, _exc_val, _exc_tb):
        # Restore old factory
        if self.old_factory:
            logging.setLogRecordFactory(self.old_factory)

    @staticmethod
    def _generate_correlation_id() -> str:
        """Generate a unique correlation ID"""
        import uuid
        return str(uuid.uuid4())[:8]


def log_function_call(func):
    """
    Decorator to log function calls with timing

    Usage:
        @log_function_call
        def create_vnet(name):
            pass
    """
    import functools
    import time

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger = get_logger(func.__module__)
        func_name = func.__name__

        logger.debug(f"Calling {func_name}() with args={args}, kwargs={kwargs}")

        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            elapsed = time.time() - start_time
            logger.debug(f"{func_name}() completed in {elapsed:.2f}s")
            return result
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"{func_name}() failed after {elapsed:.2f}s: {str(e)}")
            raise

    return wrapper


# Initialize logging on module import (with defaults)
# Can be reconfigured later with setup_logging()
try:
    from config.settings import settings
    setup_logging(
        log_level=settings.LOG_LEVEL,
        log_file=settings.LOG_FILE,
        error_log_file=settings.ERROR_LOG_FILE
    )
except Exception:
    # Fallback if settings not available
    setup_logging()
