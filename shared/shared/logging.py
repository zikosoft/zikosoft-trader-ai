"""Format de log JSON commun (B01) + redaction des secrets.

Chaque service configure son logger via `configure_json_logging(service_name)`.
Sortie sur stdout, une ligne JSON par entrée, jamais de secret en clair
(§16.1 de la spec, §32 sécurité).
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# Clés dont la valeur est systématiquement masquée si présente dans un `extra`
# ou dans un payload passé au logger — défense en profondeur en plus de la
# discipline "ne jamais logger un secret" appliquée au niveau applicatif.
_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "secret",
    "secret_key",
    "password",
    "token",
    "bot_token",
    "authorization",
    "access_token",
    "refresh_token",
    "app_encryption_key",
    "anthropic_api_key",
}

REDACTED = "***REDACTED***"


def redact(value: Any) -> Any:
    """Masque récursivement toute clé sensible dans un dict/list arbitraire."""
    if isinstance(value, dict):
        return {
            k: (REDACTED if k.lower() in _SENSITIVE_KEYS else redact(v)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


class JSONFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "service": self.service,
            "event": record.getMessage(),
            "logger": record.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        for key in (
            "execution_context_id",
            "strategy_id",
            "symbol",
            "order_id",
            "correlation_id",
            "user_id",
        ):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(redact(payload), default=str)


def configure_json_logging(service: str, level: int = logging.INFO) -> logging.Logger:
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JSONFormatter(service))
    root.addHandler(handler)
    return logging.getLogger(service)
