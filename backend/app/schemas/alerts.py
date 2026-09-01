"""Schémas Pydantic — B20 (notifications in-app, Alert Dispatcher)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AlertOut(BaseModel):
    id: UUID
    category: str
    severity: str
    title: str
    message: str
    related_entity_type: str | None
    related_entity_id: UUID | None
    is_read: bool
    created_at: datetime


class AlertListResponse(BaseModel):
    alerts: list[AlertOut]
    total: int


class UnreadCountResponse(BaseModel):
    unread_count: int


class MarkReadResponse(BaseModel):
    updated_count: int
