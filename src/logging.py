import logging
import sys
import json
from typing import Dict, Any
from datetime import datetime, timezone


# Custom JSON formatter for structured logging
class JsonFormatter(logging.Formatter):
    """
    A custom logging formatter that outputs log records as JSON strings.

    This formatter includes standard log record attributes like timestamp,
    level, logger name, message, pathname, and line number. If exception
    information is present, it's also included in the JSON output.
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        Formats a log record into a JSON string.

        Args:
            record (logging.LogRecord): The log record to format.

        Returns:
            str: A JSON string representing the log record.
        """
        log_record: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
            "pathname": record.pathname,
            "lineno": record.lineno,
        }
        # Include exception info if present
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record)


# Configure the root logger
def setup_logging() -> logging.Logger:
    """
    Configures the root logger for the CacheWarp application.

    This function sets the logging level to DEBUG (you might want to change
    this to INFO in a production environment). It also creates a console
    handler that outputs logs to standard output (stdout) and applies the
    custom JsonFormatter to format the logs as JSON. It also ensures that
    any existing handlers are cleared to prevent duplicate logging.

    Returns:
        logging.Logger: The configured logger instance for the application.
    """
    logger = logging.getLogger("cachewarp")
    logger.setLevel(logging.DEBUG)  # In production, consider setting to INFO

    # Clear any existing handlers to avoid duplicate logs
    logger.handlers.clear()

    # Create a console handler that outputs logs to stdout with JSON formatting
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(JsonFormatter())
    logger.addHandler(console_handler)

    return logger


# Initialize the logger
logger = setup_logging()
