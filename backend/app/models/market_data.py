"""Données de marché persistées (§B27 "Graphiques marché et analytics").

Écrites par `agents/market_agent/main.py::tick()` (B10) — ce module normalise
déjà les bougies OHLCV et les snapshots de cotation collectés via MCP pour
ses propres besoins (évaluation de stratégie, B13) mais ne les persistait
nulle part avant B27 : `market.analysis.completed` était publié puis jamais
relu, aucune table ne permettait au backend de servir un historique de
bougies au frontend. Même précédent que l'ajout `evidence["bars"]` en B10
lui-même (voir docstring de `agents/market_agent/main.py`) : une brique déjà
livrée (B10, tag v0.4.0) est complétée quand un besoin réel apparaît en aval
(ici, un vrai graphique chandelier), plutôt que de dupliquer la gestion de
session MCP dans une deuxième brique/un deuxième worker.

**Pas de `ExecutionContextMixin`/`UserOwnedMixin` ici** — contrairement à
`portfolio_snapshots` (propriété d'un compte), une bougie AAPL 1Day est une
donnée de MARCHÉ, identique pour tous les comptes qui la consultent (même
principe que `assets`/`provider_assets`, B09/B10, qui ne sont pas non plus
scopées par utilisateur). Aucun risque d'agrégation cross-contexte (§R06) à
gérer ici : rien de spécifique à un `execution_context_id` n'est stocké dans
ces deux tables.

**`MarketQuote` = dernière cotation connue uniquement (pas un historique)**
— upsert par symbole (`symbol` est la clé primaire), volontairement plus
simple qu'une table de séries temporelles : "Prix live" (§B27) n'a besoin
que du dernier prix connu, jamais d'un historique tick-par-tick (que Market
Agent ne collecte de toute façon pas, voir sa docstring "Fonctions agent" —
un seul `get_stock_snapshot` par tick, pas un flux de ticks)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, uuid_pk


class MarketBar(Base, TimestampMixin):
    """Une bougie OHLCV normalisée (`agents/market_agent/main.py::_normalize_bars`),
    persistée telle quelle. `bar_at` = horodatage propre à la bougie (début
    de période), jamais l'heure de collecte — même distinction que
    `PortfolioSnapshot.snapshot_at` vs `created_at`.

    Contrainte unique `(symbol, timeframe, bar_at)` : upsert idempotent — un
    même tick (ou plusieurs comptes partageant le même symbole surveillé)
    peut retraiter la même bougie sans dupliquer de ligne, `ON CONFLICT DO
    UPDATE` (voir `agents/market_agent/main.py::_persist_bars`) écrase avec
    la valeur la plus récemment collectée."""

    __tablename__ = "market_bars"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "bar_at", name="uq_market_bars_symbol_timeframe_bar_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(20), nullable=False)
    bar_at: Mapped[datetime] = mapped_column(nullable=False, index=True)
    open: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    high: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    low: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    close: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    volume: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)


class MarketQuote(Base):
    """Dernière cotation connue par symbole — voir docstring du module pour
    pourquoi ce n'est pas un historique. `symbol` est directement la clé
    primaire (une seule ligne par symbole, upsert en place)."""

    __tablename__ = "market_quotes"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    price: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    # §B10 sécurité "horodatage et fraîcheur" — horodatage RÉEL de la
    # cotation source quand extractible (voir `_extract_quote_price`),
    # `None` si non extractible (jamais fabriqué à partir de l'heure de
    # collecte, même discipline que `_extract_data_timestamps`).
    as_of: Mapped[datetime | None] = mapped_column(nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
