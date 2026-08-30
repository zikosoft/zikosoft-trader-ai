"""B36 — journal d'erreurs applicatif : redaction et écriture non bloquante."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from shared.error_log import ErrorModule, log_error
from shared.logging import redact


def test_redact_masks_sensitive_keys():
    payload = {"symbol": "AAPL", "api_key": "sk-secret", "nested": {"password": "hunter2", "ok": "keep"}}
    redacted = redact(payload)
    assert redacted["api_key"] == "***REDACTED***"
    assert redacted["nested"]["password"] == "***REDACTED***"
    assert redacted["nested"]["ok"] == "keep"
    assert redacted["symbol"] == "AAPL"


def test_log_error_never_raises_on_engine_failure():
    """Un souci d'écriture du log ne doit jamais faire échouer l'appelant
    (critère d'acceptation B36) — même si le moteur DB est cassé."""
    broken_engine = MagicMock()
    broken_engine.begin.side_effect = RuntimeError("db is down")

    log_error(  # ne doit pas lever, même si le moteur explose
        broken_engine,
        module=ErrorModule.ORDER_WORKER,
        feature="place_order",
        response_or_error={"secret": "should-be-redacted-if-it-ever-logs"},
    )


def test_log_error_writes_row_end_to_end(db_session):
    from app.db import engine
    from sqlalchemy import text

    corr_id = uuid.uuid4()
    log_error(
        engine,
        module=ErrorModule.RISK_ENGINE,
        feature="validate_proposal",
        severity="WARNING",
        correlation_id=corr_id,
        request_payload={"notional": 1500, "api_key": "must-not-leak"},
        response_or_error="stale market data",
        http_status=422,
        error_code="STALE_DATA",
        latency_ms=12,
    )
    row = db_session.execute(
        text("SELECT module, severity, request_payload, occurred_at FROM technical_error_logs "
             "WHERE correlation_id = :cid"),
        {"cid": str(corr_id)},
    ).mappings().first()

    assert row is not None
    assert row["module"] == ErrorModule.RISK_ENGINE
    assert row["severity"] == "WARNING"
    assert row["request_payload"]["api_key"] == "***REDACTED***"
    assert row["occurred_at"] is not None
