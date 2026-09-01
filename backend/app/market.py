"""Lecture des données de marché et des marqueurs de graphique (§B27
"Graphiques marché et analytics").

Alimenté par `agents/market_agent/main.py::tick()` (B10, écriture de
`market_bars`/`market_quotes` — voir `_persist_bars`/`_persist_quote` et la
docstring de `backend/app/models/market_data.py` pour pourquoi cette
persistance a été ajoutée maintenant plutôt qu'en B10) : ce module ne lit
QUE ce que le worker/agent a déjà écrit, même principe que
`backend/app/portfolio.py` (B18) vis-à-vis de `portfolio_worker`.

**Marqueurs BUY/SELL, stop-loss/take-profit** : lus directement sur `orders`
(B17) — `stop_loss`/`take_profit` sont déjà des colonnes JSONB posées à la
soumission de l'ordre, le prix d'exécution est reconstruit depuis
`order_events.payload` (voir `_filled_prices`, tolérant à deux formes
plausibles selon que l'événement vient de la soumission REST initiale ou du
listener `trade_updates`, aucune des deux non vérifiable en direct depuis
cette sandbox — même limite documentée partout ailleurs dans ce projet,
voir AVANCEMENT.md §39).

**Marqueurs "Proposition IA"/"Rejet Risk Engine"** : lus sur
`agent_decisions`/`risk_decisions` (B13/B14/B15) — le symbole n'est PAS une
colonne dédiée sur ces deux tables (elles sont génériques, réutilisées par
toute future proposition d'agent), il est extrait de `reasoning->>'symbol'`
(voir `agents/strategy_agent/main.py::_record_decision_and_publish`, qui
l'y place systématiquement) via une expression JSONB côté requête.

**"Performance par stratégie" — limite honnête assumée** (voir
`strategy_activity` ci-dessous) : Alpaca n'expose aucune attribution de P&L
par stratégie (une seule notion de compte), et ce projet ne tient pas non
plus de grand livre interne par stratégie à ce jour (ce serait une brique à
part entière). Le widget affiche donc un PROXY réel — nombre d'ordres et
notional cumulé par stratégie active — jamais un P&L fabriqué à partir de
données qui ne le permettent pas."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    AgentDecision,
    MarketBar,
    MarketQuote,
    Order,
    OrderEvent,
    RiskDecision,
    Strategy,
    StrategyDefinition,
)

MAX_BARS_LIMIT = 500
DEFAULT_BARS_LIMIT = 200

MAX_MARKERS_LIMIT = 200
DEFAULT_MARKERS_LIMIT = 100


def list_symbols(db: Session) -> list[str]:
    """Symboles ayant AU MOINS une bougie réellement persistée — jamais la
    watchlist configurée (`market_agent.DEMO_WATCHLIST`) telle quelle, qui
    prétendrait qu'un graphique est disponible avant qu'aucune donnée n'ait
    été collectée (même discipline anti-fabrication que `ColdStartView`,
    B26)."""
    rows = db.execute(select(MarketBar.symbol).distinct().order_by(MarketBar.symbol)).scalars().all()
    return list(rows)


def list_bars(db: Session, *, symbol: str, timeframe: str, limit: int) -> list[MarketBar]:
    """Les `limit` bougies les plus RÉCENTES, mais renvoyées triées de la
    plus ancienne à la plus récente (convention adaptée au consommateur —
    un graphique chandelier — contrairement aux autres routes "recent" de ce
    projet qui renvoient le plus récent en premier, voir
    `routers/orders.py`)."""
    recent_desc = (
        db.execute(
            select(MarketBar)
            .where(MarketBar.symbol == symbol, MarketBar.timeframe == timeframe)
            .order_by(MarketBar.bar_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return list(reversed(recent_desc))


def latest_quote(db: Session, *, symbol: str) -> MarketQuote | None:
    return db.get(MarketQuote, symbol)


def _extract_filled_price(payload: object) -> float | None:
    """Tolérant par nécessité (voir docstring du module) : `payload` est
    soit le dict brut Alpaca d'un ordre (`filled_avg_price` au premier
    niveau, chemin soumission REST), soit un événement `trade_updates`
    (`{"order": {"filled_avg_price": ...}, ...}`, chemin listener
    temps réel) — jamais aucune valeur fabriquée si ni l'un ni l'autre n'est
    trouvé."""
    if not isinstance(payload, dict):
        return None
    candidates = [payload.get("filled_avg_price")]
    order_data = payload.get("order")
    if isinstance(order_data, dict):
        candidates.append(order_data.get("filled_avg_price"))
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            return float(candidate)
        except (TypeError, ValueError):
            continue
    return None


def _filled_prices(db: Session, order_ids: list[uuid.UUID]) -> dict[uuid.UUID, float]:
    if not order_ids:
        return {}
    rows = db.execute(
        select(OrderEvent.order_id, OrderEvent.payload)
        .where(OrderEvent.order_id.in_(order_ids))
        .order_by(OrderEvent.order_id, OrderEvent.occurred_at.desc())
    ).all()
    result: dict[uuid.UUID, float] = {}
    for order_id, payload in rows:
        if order_id in result:
            continue
        price = _extract_filled_price(payload)
        if price is not None:
            result[order_id] = price
    return result


def list_order_markers(
    db: Session, *, execution_context_id: uuid.UUID, symbol: str, limit: int
) -> list[dict]:
    orders = (
        db.execute(
            select(Order)
            .where(
                Order.execution_context_id == execution_context_id,
                Order.symbol == symbol,
            )
            .order_by(Order.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    filled_prices = _filled_prices(db, [o.id for o in orders])
    return [
        {
            "id": o.id,
            "side": o.side,
            "status": o.status,
            "quantity": float(o.quantity) if o.quantity is not None else None,
            "notional": float(o.notional) if o.notional is not None else None,
            "filled_at": o.filled_at,
            "submitted_at": o.submitted_at,
            "filled_price": filled_prices.get(o.id),
            "stop_loss": o.stop_loss,
            "take_profit": o.take_profit,
        }
        for o in orders
    ]


def list_decision_markers(
    db: Session, *, execution_context_id: uuid.UUID, symbol: str, limit: int
) -> tuple[list[AgentDecision], list[tuple[RiskDecision, AgentDecision]]]:
    """§B27 "Proposition IA"/"Rejet Risk Engine" — voir docstring du module
    pour pourquoi `symbol` est extrait de `reasoning` plutôt qu'une colonne
    dédiée."""
    proposals = (
        db.execute(
            select(AgentDecision)
            .where(
                AgentDecision.execution_context_id == execution_context_id,
                AgentDecision.decision_type == "PROPOSAL",
                AgentDecision.reasoning["symbol"].astext == symbol,
            )
            .order_by(AgentDecision.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )

    risk_rows = (
        db.execute(
            select(RiskDecision, AgentDecision)
            .join(AgentDecision, RiskDecision.agent_decision_id == AgentDecision.id)
            .where(
                RiskDecision.execution_context_id == execution_context_id,
                AgentDecision.reasoning["symbol"].astext == symbol,
            )
            .order_by(RiskDecision.created_at.desc())
            .limit(limit)
        )
        .all()
    )
    return list(proposals), [(r, d) for r, d in risk_rows]


def strategy_activity(db: Session, *, execution_context_id: uuid.UUID) -> list[dict]:
    """§B27 "Performance par stratégie" — voir docstring du module ("limite
    honnête assumée") : proxy d'activité réelle (nombre d'ordres, notional
    cumulé), pas un P&L attribué."""
    strategies = (
        db.execute(
            select(Strategy, StrategyDefinition.type_code)
            .join(StrategyDefinition, Strategy.strategy_definition_id == StrategyDefinition.id)
            .where(Strategy.execution_context_id == execution_context_id)
            .order_by(Strategy.name)
        )
        .all()
    )
    if not strategies:
        return []

    strategy_ids = [s.id for s, _ in strategies]
    order_rows = db.execute(
        select(
            Order.strategy_id,
            Order.side,
            func.count().label("count"),
            func.coalesce(func.sum(Order.notional), 0).label("total_notional"),
        )
        .where(Order.strategy_id.in_(strategy_ids))
        .group_by(Order.strategy_id, Order.side)
    ).all()

    by_strategy: dict[uuid.UUID, dict] = {
        sid: {"order_count": 0, "buy_count": 0, "sell_count": 0, "total_notional": 0.0} for sid in strategy_ids
    }
    for strategy_id, side, count, total_notional in order_rows:
        bucket = by_strategy[strategy_id]
        bucket["order_count"] += count
        bucket["total_notional"] += float(total_notional or 0.0)
        if side == "buy":
            bucket["buy_count"] += count
        elif side == "sell":
            bucket["sell_count"] += count

    return [
        {
            "strategy_id": strategy.id,
            "type_code": type_code,
            "name": strategy.name,
            "status": strategy.status,
            **by_strategy[strategy.id],
        }
        for strategy, type_code in strategies
    ]
