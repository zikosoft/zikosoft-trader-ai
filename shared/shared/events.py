"""Enveloppe d'événement commune et noms de streams Redis (brique B04).

Toute publication sur un stream Redis passe par `EventEnvelope`. Le payload
métier (proposition de stratégie, décision de risque, statut d'ordre, ...)
reste un dict libre validé par le service émetteur/récepteur — seule
l'enveloppe est un contrat partagé.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1


class EventEnvelope(BaseModel):
    """Contrat d'enveloppe commun à tous les événements (§5.3 et B04 de la spec)."""

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: str
    schema_version: int = SCHEMA_VERSION
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    correlation_id: uuid.UUID
    causation_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    # `None` réservé aux événements réellement transverses aux contextes —
    # à ce jour uniquement le Watchdog (B22, `system.events` : l'état d'un
    # service backend n'appartient ni à Paper ni à Replay, contrairement à
    # tout le reste du pipeline métier (§4.2/R06) qui DOIT rester scopé à un
    # `execution_context_id`. Assoupli le 26/08 (auparavant obligatoire
    # depuis B04) — tout événement métier existant continue de le fournir
    # explicitement, aucun appelant actuel ne dépend de ce relâchement.
    execution_context_id: uuid.UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    # Pydantic v2 sérialise déjà nativement UUID/datetime en JSON via
    # `model_dump(mode="json")` — pas besoin de `json_encoders` (déprécié).


class Streams:
    """Noms des streams Redis (§5.3 spec, B04 AVANCEMENT).

    Convention dead-letter : `<stream>.dead-letter`.
    """

    MARKET_EVENTS = "market.events"
    MARKET_ANALYSIS_COMPLETED = "market.analysis.completed"
    STRATEGY_PROPOSAL_CREATED = "strategy.proposal.created"
    RISK_CRITIQUE_COMPLETED = "risk.critique.completed"
    RISK_VALIDATION_COMPLETED = "risk.validation.completed"
    ORDER_COMMANDS = "order.commands"
    ORDER_EVENTS = "order.events"
    ALERT_EVENTS = "alert.events"
    SYSTEM_EVENTS = "system.events"

    ALL = (
        MARKET_EVENTS,
        MARKET_ANALYSIS_COMPLETED,
        STRATEGY_PROPOSAL_CREATED,
        RISK_CRITIQUE_COMPLETED,
        RISK_VALIDATION_COMPLETED,
        ORDER_COMMANDS,
        ORDER_EVENTS,
        ALERT_EVENTS,
        SYSTEM_EVENTS,
    )

    @staticmethod
    def dead_letter(stream: str) -> str:
        return f"{stream}.dead-letter"
