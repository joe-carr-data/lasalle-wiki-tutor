import json
import logging
import os
import sys

IS_LOCAL: bool = os.getenv('ENV', 'PROD').upper() == 'LOCAL'
JSON_INDENT: int = 2

# Create a sample LogRecord to inspect its default attributes
log_record = logging.LogRecord(name="my_logger", level=logging.INFO, pathname=__file__, lineno=10, msg="Test", args=(),
                               exc_info=None)

# Get the default attributes
default_attributes = log_record.__dict__.keys()


class DevEnvironmentExtraParameterFormatter(logging.Formatter):
    COLORS = {
        'INFO': '\033[32m',     # Green
        'ERROR': '\033[31m',    # Red
        'WARNING': '\033[33m',  # Yellow
        'RESET': '\033[0m'
    }

    def __init__(self):
        super().__init__("%(asctime)s - %(levelname)s - %(message)s")

    def format(self, record):
        extra = {
            key: getattr(record, key)
            for key in record.__dict__.keys()
            if key not in default_attributes
        }
        color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        reset = self.COLORS['RESET']

        try:
            base_msg = record.getMessage()
        except TypeError:
            # If formatting fails, fallback to the raw msg
            base_msg = str(record.msg)

        if not extra:
            record.msg = f"{color}{base_msg}{reset}"
            record.args = ()
            return super().format(record)

        try:
            extra_str = json.dumps(extra, indent=JSON_INDENT)
        except TypeError:
            extra_str = str(extra)

        record.msg = f"{color}{base_msg}\n{extra_str}{reset}"
        record.args = ()
        return super().format(record)




class JSONFormatter(logging.Formatter):
    """
    JSON formatter for Datadog integration.

    Flattens extra fields to top-level for Datadog indexing and full-text search.
    Uses dot notation for nested fields (e.g., context.company_id).
    """

    MAX_DEPTH = 10  # Prevent infinite recursion
    MAX_ITEMS = 100  # Prevent memory exhaustion

    def _flatten_dict(self, d, parent_key='', sep='.', _depth=0, _total_count=None):
        """Flatten nested dict using dot notation for Datadog attribute indexing."""
        if _total_count is None:
            _total_count = [0]  # Use list to allow mutation in recursion

        if _depth >= self.MAX_DEPTH:
            return {parent_key: '<max_depth_exceeded>'} if parent_key else {}

        items = []
        for k, v in d.items():
            if _total_count[0] >= self.MAX_ITEMS:
                items.append(('_truncated', True))
                break
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                nested_items = self._flatten_dict(v, new_key, sep=sep, _depth=_depth + 1, _total_count=_total_count)
                items.extend(nested_items.items())
            else:
                items.append((new_key, v))
                _total_count[0] += 1
        return dict(items)

    def _safe_serialize(self, obj):
        """Safely serialize objects for JSON, handling non-serializable types."""
        if obj is None:
            return None
        if isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, (list, tuple)):
            return [self._safe_serialize(item) for item in obj[:self.MAX_ITEMS]]
        if isinstance(obj, dict):
            # Apply MAX_ITEMS limit to dictionaries too
            items = list(obj.items())[:self.MAX_ITEMS]
            return {k: self._safe_serialize(v) for k, v in items}
        # Safe fallback: type name only to avoid exposing sensitive data
        return f"<{type(obj).__name__}>"

    def format(self, record):
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)

        log_entry = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": message,
        }

        try:
            extra = {
                key: getattr(record, key)
                for key in record.__dict__.keys()
                if key not in default_attributes
            }
            if extra:
                # Flatten extra fields to top-level for Datadog indexing
                flattened = self._flatten_dict(self._safe_serialize(extra))
                # Avoid collision with reserved keys
                for key in list(flattened.keys()):
                    if key in log_entry:
                        flattened[f"extra.{key}"] = flattened.pop(key)
                log_entry.update(flattened)
        except Exception as e:
            log_entry["_extra_error"] = str(e)

        return json.dumps(log_entry, default=str)



class LevelBasedStreamHandler(logging.Handler):
    """
    Custom handler that routes logs to stdout or stderr based on level.

    This prevents Datadog from marking all logs as ERROR, since Datadog
    treats stderr output as errors by default.

    - ERROR and CRITICAL → stderr
    - DEBUG, INFO, WARNING → stdout
    """

    def __init__(self):
        super().__init__()
        self._stdout_handler = logging.StreamHandler(sys.stdout)
        self._stderr_handler = logging.StreamHandler(sys.stderr)

    def setFormatter(self, fmt):
        super().setFormatter(fmt)
        self._stdout_handler.setFormatter(fmt)
        self._stderr_handler.setFormatter(fmt)

    def emit(self, record):
        if record.levelno >= logging.ERROR:
            self._stderr_handler.emit(record)
        else:
            self._stdout_handler.emit(record)


def setup_logger():
    """Configure and return a fully initialized root logger."""
    root_logger = logging.getLogger()

    # Add a LevelBasedStreamHandler if none exist
    if not root_logger.handlers:
        stream_handler = LevelBasedStreamHandler()
        root_logger.addHandler(stream_handler)

    # Set the formatter based on the environment
    if IS_LOCAL:
        formatter = DevEnvironmentExtraParameterFormatter()
    else:
        formatter = JSONFormatter()

    for handler in root_logger.handlers:
        handler.setFormatter(formatter)

    root_logger.setLevel(logging.INFO)
    return root_logger


# Initialize the logger immediately upon import
logger = setup_logger()

