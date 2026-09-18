import json
import logging
from datetime import datetime, timezone


STANDARD_LOG_FIELDS = set(logging.makeLogRecord({}).__dict__)


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str = "queue-api"):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        message = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": self.service,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in STANDARD_LOG_FIELDS and key not in {"message", "asctime"}:
                message[key] = value
        if record.exc_info:
            message["exception"] = self.formatException(record.exc_info)
        return json.dumps(message, ensure_ascii=False, default=str)


def configure_logging(level: str, service: str = "queue-api") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(service))
    normalized_level = level.upper()
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(normalized_level)

    # Uvicorn installs dedicated handlers before FastAPI's lifespan starts.
    # Replace them as well so application, error and access logs share one format.
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers = [handler]
        logger.setLevel(normalized_level)
        logger.propagate = False
