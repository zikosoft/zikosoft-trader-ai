"""Lecture du portefeuille (B18) — cash/buying power/valeur, positions
ouvertes, historique paginé, cartes de performance 1D-7D.

Alimenté par `workers/portfolio_worker/main.py` (écriture périodique de
`portfolio_snapshots`/`positions_snapshots`, voir son docstring) — ce module
ne lit QUE ce que le worker a déjà écrit, aucun appel Alpaca direct ici.
Cohérent avec D037 ("une seule frontière Alpaca par préoccupation" posé en
B17 pour les ordres) : le worker périodique possède la frontière Alpaca
pour le portefeuille, ce module ne fait que des lectures PostgreSQL, comme
`routers/strategy_instances.py` ne parle jamais à Alpaca directement non
plus.

Isolation totale par `execution_context_id` partout ici (§R06 — jamais
d'agrégation cross-contexte Replay/Paper)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import PortfolioSnapshot, PositionSnapshot

# §B18 checklist "Historique limité à 90 jours dans l'UI" — appliqué ici,
# côté backend, pas seulement suggéré côté frontend (pas encore construit,
# voir B26) : un appelant ne peut structurellement pas obtenir plus que
# cette fenêtre, quel que soit le `days` demandé (borné côté routeur).
DEFAULT_HISTORY_DAYS = 90

# §B18 "Cartes 1D à 7D" — fenêtres exactes listées dans la spec (§18).
PERFORMANCE_WINDOW_DAYS: tuple[int, ...] = (1, 3, 7)

_NOT_ENOUGH_HISTORY = "Not enough account history yet"


def latest_snapshot(db: Session, *, execution_context_id: uuid.UUID) -> PortfolioSnapshot | None:
    return db.execute(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.execution_context_id == execution_context_id)
        .order_by(PortfolioSnapshot.snapshot_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def latest_positions(
    db: Session, *, execution_context_id: uuid.UUID
) -> tuple[list[PositionSnapshot], datetime | None]:
    """Dernier "tour" de positions écrit par le worker.

    Ancré sur le `snapshot_at` du dernier `PortfolioSnapshot`, PAS sur le
    `MAX(snapshot_at)` de `positions_snapshots` lui-même : le worker écrit
    TOUJOURS un `PortfolioSnapshot` par tick réussi, mais seulement UNE
    ligne `PositionSnapshot` PAR POSITION OUVERTE — un compte "flat" (0
    position ouverte) produit 0 ligne `positions_snapshots` ce tick-là. Se
    baser sur `MAX(positions_snapshots.snapshot_at)` rendrait donc "aucun
    tour n'a jamais eu lieu" et "le worker tourne mais le compte est flat
    depuis toujours" indiscernables (les deux renvoient 0 ligne). En ancrant
    sur `PortfolioSnapshot` (qui, lui, existe toujours dès qu'un tour a eu
    lieu) et en exigeant que le worker écrive les deux avec le MÊME
    `snapshot_at` (un seul `datetime.now(UTC)` par tick, voir
    `workers/portfolio_worker/main.py::_run_tick`), les deux cas sont
    distingués correctement : `(None)` = jamais tourné, `([], <horodatage>)`
    = tourné mais flat, `([...], <horodatage>)` = positions ouvertes."""
    latest_portfolio = latest_snapshot(db, execution_context_id=execution_context_id)
    if latest_portfolio is None:
        return [], None
    rows = (
        db.execute(
            select(PositionSnapshot)
            .where(
                PositionSnapshot.execution_context_id == execution_context_id,
                PositionSnapshot.snapshot_at == latest_portfolio.snapshot_at,
            )
            .order_by(PositionSnapshot.symbol)
        )
        .scalars()
        .all()
    )
    return list(rows), latest_portfolio.snapshot_at


def history(
    db: Session,
    *,
    execution_context_id: uuid.UUID,
    days: int,
    limit: int,
    offset: int,
) -> tuple[list[PortfolioSnapshot], int]:
    """Historique paginé, borné à `days` — voir `DEFAULT_HISTORY_DAYS`."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    base = select(PortfolioSnapshot).where(
        PortfolioSnapshot.execution_context_id == execution_context_id,
        PortfolioSnapshot.snapshot_at >= cutoff,
    )
    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    rows = (
        db.execute(base.order_by(PortfolioSnapshot.snapshot_at.desc()).limit(limit).offset(offset))
        .scalars()
        .all()
    )
    return list(rows), total


def performance_cards(db: Session, *, execution_context_id: uuid.UUID) -> list[dict]:
    """§B18 "Cartes 1D à 7D, valeur en dollars et pourcentage" /
    "Not enough account history yet" — pour chaque fenêtre, cherche le
    snapshot le plus proche (mais pas postérieur) à `<dernier snapshot> -
    fenêtre` et compare au dernier snapshot connu. Si aucun snapshot
    n'existe avant ce seuil (compte trop récent / pas assez d'historique
    accumulé), la carte est honnêtement marquée `available=False` avec la
    raison "Not enough account history yet" plutôt que de fabriquer une
    variation à partir d'une référence hors-fenêtre ou d'extrapoler."""
    latest = latest_snapshot(db, execution_context_id=execution_context_id)
    if latest is None:
        return [_card(window, available=False) for window in PERFORMANCE_WINDOW_DAYS]

    cards: list[dict] = []
    for window in PERFORMANCE_WINDOW_DAYS:
        cutoff = latest.snapshot_at - timedelta(days=window)
        reference = db.execute(
            select(PortfolioSnapshot)
            .where(
                PortfolioSnapshot.execution_context_id == execution_context_id,
                PortfolioSnapshot.snapshot_at <= cutoff,
            )
            .order_by(PortfolioSnapshot.snapshot_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if reference is None:
            cards.append(_card(window, available=False))
            continue

        ref_value = float(reference.portfolio_value)
        value_change = float(latest.portfolio_value) - ref_value
        percent_change = (value_change / ref_value) * 100.0 if ref_value != 0 else None
        cards.append(_card(window, available=True, value_change=value_change, percent_change=percent_change))
    return cards


def _card(
    window_days: int,
    *,
    available: bool,
    value_change: float | None = None,
    percent_change: float | None = None,
) -> dict:
    return {
        "window": f"{window_days}D",
        "available": available,
        "reason": None if available else _NOT_ENOUGH_HISTORY,
        "value_change": value_change,
        "percent_change": percent_change,
    }
