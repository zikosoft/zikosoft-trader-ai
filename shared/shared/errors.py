"""Format d'erreur API commun (B01 — "définir un format d'erreur API commun")."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    CONFLICT = "CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class APIError(BaseModel):
    """Corps JSON standard pour toute erreur renvoyée par l'API.

    Exemple :
        {
          "error": {
            "code": "VALIDATION_ERROR",
            "message": "notional must be positive",
            "request_id": "5b6f...",
            "occurred_at": "2026-08-31T10:00:00.123Z",
            "details": {"field": "notional"}
          }
        }
    """

    code: ErrorCode
    message: str
    request_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    details: dict | None = None

    def to_response(self) -> dict:
        return {"error": self.model_dump(mode="json")}
