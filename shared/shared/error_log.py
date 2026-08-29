"""Journal d'erreurs applicatif — brique B36.

Écriture dans `technical_error_logs`, dénormalisée par design (aucune jointure
nécessaire pour lire une ligne), non bloquante : un échec d'écriture du log
ne doit jamais faire échouer la fonctionnalité elle-même (voir B36 dans
AVANCEMENT.md). Le schéma exact des colonnes est défini une fois ici et repris
tel quel par la migration Alembic (`backend/alembic/versions/0001_initial.py`,
table `technical_error_logs`) — les deux doivent rester synchronisés.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .logging import redact

_fallback_logger = logging.getLogger("error_log_fallback")

_INSERT_SQL = text(
    """
    INSERT INTO technical_error_logs (
        id, occurred_at, user_id, execution_context_id, module, feature,
        severity, correlation_id, request_payload, response_or_error,
        http_status, error_code, latency_ms, resolved
    ) VALUES (
        :id, :occurred_at, :user_id, :execution_context_id, :module, :feature,
        :severity, :correlation_id, :request_payload, :response_or_error,
        :http_status, :error_code, :latency_ms, false
    )
    """
)


class ErrorModule:
    """Catégories par brique — une valeur par service (voir B36)."""

    AUTH = "AUTH"
    CONTEXT = "CONTEXT"
    ONBOARDING = "ONBOARDING"
    MARKET_AGENT = "MARKET_AGENT"
    MCP_SESSION = "MCP_SESSION"
    STRATEGY_AGENT = "STRATEGY_AGENT"
    RISK_CRITIC_AGENT = "RISK_CRITIC_AGENT"
    RISK_ENGINE = "RISK_ENGINE"
    EXECUTION_EXPLANATION_AGENT = "EXECUTION_EXPLANATION_AGENT"
    ORDER_WORKER = "ORDER_WORKER"
    ALERT_WORKER = "ALERT_WORKER"
    TELEGRAM = "TELEGRAM"
    WATCHDOG = "WATCHDOG"
    EVENT_BUS = "EVENT_BUS"
    AI_PROVIDER = "AI_PROVIDER"
    BACKEND_API = "BACKEND_API"


def log_error(
    engine: Engine,
    *,
    module: str,
    feature: str,
    severity: str = "ERROR",
    user_id: uuid.UUID | None = None,
    execution_context_id: uuid.UUID | None = None,
    correlation_id: uuid.UUID | None = None,
    request_payload: dict[str, Any] | None = None,
    response_or_error: dict[str, Any] | str | None = None,
    http_status: int | None = None,
    error_code: str | None = None,
    latency_ms: int | None = None,
) -> None:
    """Insère une ligne dans `technical_error_logs`. Ne lève jamais d'exception :
    un souci d'écriture du log est lui-même journalisé en fallback (stdout) et
    avalé, pour ne jamais faire échouer la fonctionnalité appelante.
    """
    try:
        params = {
            "id": str(uuid.uuid4()),
            "occurred_at": datetime.now(UTC),
            "user_id": str(user_id) if user_id else None,
            "execution_context_id": str(execution_context_id) if execution_context_id else None,
            "module": module,
            "feature": feature,
            "severity": severity,
            "correlation_id": str(correlation_id) if correlation_id else None,
            "request_payload": _to_json(redact(request_payload)) if request_payload else None,
            "response_or_error": _to_json(
                redact(response_or_error) if isinstance(response_or_error, dict) else response_or_error
            )
            if response_or_error is not None
            else None,
            "http_status": http_status,
            "error_code": error_code,
            "latency_ms": latency_ms,
        }
        with engine.begin() as conn:
            conn.execute(_INSERT_SQL, params)
    except Exception:  # noqa: BLE001 — volontaire : le logging ne doit jamais casser l'appelant
        _fallback_logger.exception(
            "failed to write technical_error_logs row (module=%s feature=%s)", module, feature
        )


def _to_json(value: Any) -> str:
    import json

    return json.dumps(value, default=str)
