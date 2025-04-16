import logging
import sys
import json
from typing import Dict, Any
from datetime import datetime

# Custom JSON formatter for structured logging
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_record: Dict[str, Any] = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat(),
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
def setup_logging():
    logger = logging.getLogger("cachewarp")
    logger.setLevel(logging.DEBUG)  # in prod, change into to INFO

    # Clear any existing handlers to avoid duplicates
    logger.handlers.clear()

    # Create a console handler with JSON formatting
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(JsonFormatter())
    logger.addHandler(console_handler)

    return logger

# Initialize the logger
logger = setup_logging()