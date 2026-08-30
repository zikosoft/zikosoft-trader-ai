"""portfolio-worker — B18, snapshots périodiques du portefeuille (cash,
buying power, valeur, P&L) et des positions ouvertes, pour chaque compte
Alpaca Paper connecté. Alimente `routers/portfolio.py` (lecture backend) —
ce worker ne fait qu'ÉCRIRE, aucune route API ici (voir `backend/app/portfolio.py`).

Comme `market_agent`/`risk_engine`/`order_worker` (B10/B15/B17), ce module
n'a pas accès aux modèles ORM de `backend` (image Docker séparée, §B01) —
tout passe par du SQL brut via `text()`.

**Fréquence — gate basé sur la base de données, pas sur un état en
mémoire** : un dict `{execution_context_id: last_snapshot_at}` tenu en
mémoire du process ne survivrait pas à un redémarrage du worker (`docker
compose restart portfolio-worker`, déploiement, panne) — au redémarrage, le
premier tick écrirait un nouveau snapshot immédiatement même si le
précédent datait de quelques secondes, ce qui peut arriver en pratique
(voir B23, redémarrages de service testés). À la place, chaque tick
interroge `MAX(portfolio_snapshots.snapshot_at)` pour le contexte concerné
et saute l'écriture si elle est plus récente que
`PORTFOLIO_SNAPSHOT_INTERVAL_SECONDS` — même principe que le cooldown de
`risk_engine` (`COOLDOWN_SECONDS`/`_seconds_since_last_risk_decision`), mais
volontairement basé en base plutôt qu'en mémoire ici (l'état DOIT survivre
un redémarrage — un cooldown de risque, lui, n'a pas cette exigence).

**`daily_pl`** = `equity − last_equity` (champs `GET /v2/account`, voir
https://docs.alpaca.markets/us/reference/getaccount-1.md) — c'est
l'approche documentée par Alpaca elle-même pour le P&L quotidien.
`None` si l'un des deux champs manque (jamais fabriqué).

**`total_pl` — limite honnête assumée et documentée (voir AVANCEMENT.md
§39)** : Alpaca n'expose AUCUN champ de P&L cumulé depuis l'ouverture du
compte. `total_pl` est donc calculé comme `portfolio_value actuel −
portfolio_value du premier PortfolioSnapshot jamais enregistré pour ce
contexte` — c'est-à-dire "P&L depuis que ZikosoftTrader AI a commencé à
suivre ce compte", PAS "P&L depuis le financement du compte" (qui a pu
avoir lieu avant la connexion à ZikosoftTrader AI). Le tout premier
snapshot d'un contexte a donc `total_pl = 0.0` par construction (il EST sa
propre référence) — valeur honnête, pas un cas limite masqué.

**Aucun événement publié** (contrairement à B04/B06 qui publient des
contrats en avance de leurs consommateurs) : `risk_engine` (B15/D042) lit
`portfolio_snapshots`/`positions_snapshots` directement en SQL, pas via un
événement — aucun consommateur événementiel identifié à ce jour qui
justifierait un nouveau contrat `shared.events.Streams`."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

import redis
from common.bootstrap import run_service
from common.encryption import decrypt_secret
from sqlalchemy import text
from sqlalchemy.engine import Engine

from portfolio_worker.alpaca_portfolio_client import (
    AlpacaAccountSnapshot,
    AlpacaPortfolioClient,
    AlpacaPortfolioError,
    AlpacaPositionSnapshot,
)

logger = logging.getLogger("portfolio-worker")

# §B18 — voir docstring du module ("gate basé sur la base de données").
SNAPSHOT_INTERVAL_SECONDS = int(os.environ.get("PORTFOLIO_SNAPSHOT_INTERVAL_SECONDS", "300"))

_CONNECTED_ACCOUNTS_SQL = text(
    """
    SELECT uta.id AS account_id, uta.user_id, uta.encrypted_api_key, uta.encrypted_secret_key
    FROM user_trading_accounts uta
    JOIN trading_providers tp ON tp.id = uta.trading_provider_id
    WHERE tp.code = 'alpaca' AND uta.environment = 'paper' AND uta.status = 'connected'
          AND uta.encrypted_api_key IS NOT NULL AND uta.encrypted_secret_key IS NOT NULL
    """
)

_PAPER_CONTEXT_SQL = text("SELECT id FROM execution_contexts WHERE user_id = :user_id AND kind = 'PAPER'")

_LAST_SNAPSHOT_AT_SQL = text(
    "SELECT MAX(snapshot_at) FROM portfolio_snapshots WHERE execution_context_id = :execution_context_id"
)

_EARLIEST_PORTFOLIO_VALUE_SQL = text(
    """
    SELECT portfolio_value FROM portfolio_snapshots
    WHERE execution_context_id = :execution_context_id
    ORDER BY snapshot_at ASC
    LIMIT 1
    """
)

_INSERT_PORTFOLIO_SNAPSHOT_SQL = text(
    """
    INSERT INTO portfolio_snapshots
        (id, user_id, execution_context_id, cash, buying_power, portfolio_value,
         daily_pl, total_pl, raw_provider_payload, snapshot_at)
    VALUES
        (:id, :user_id, :execution_context_id, :cash, :buying_power, :portfolio_value,
         :daily_pl, :total_pl, CAST(:raw_provider_payload AS jsonb), :snapshot_at)
    """
)

_INSERT_POSITION_SNAPSHOT_SQL = text(
    """
    INSERT INTO positions_snapshots
        (id, user_id, execution_context_id, symbol, quantity, average_entry_price,
         market_value, unrealized_pl, snapshot_at)
    VALUES
        (:id, :user_id, :execution_context_id, :symbol, :quantity, :average_entry_price,
         :market_value, :unrealized_pl, :snapshot_at)
    """
)


def _connected_accounts(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(_CONNECTED_ACCOUNTS_SQL).mappings().all()
    return [dict(row) for row in rows]


def _paper_execution_context_id(engine: Engine, user_id: uuid.UUID) -> uuid.UUID | None:
    with engine.connect() as conn:
        row = conn.execute(_PAPER_CONTEXT_SQL, {"user_id": user_id}).first()
    return row[0] if row else None


def _seconds_since_last_snapshot(engine: Engine, *, execution_context_id: uuid.UUID) -> float | None:
    with engine.connect() as conn:
        row = conn.execute(_LAST_SNAPSHOT_AT_SQL, {"execution_context_id": execution_context_id}).first()
    last_at = row[0] if row else None
    if last_at is None:
        return None
    if last_at.tzinfo is None:
        last_at = last_at.replace(tzinfo=UTC)
    return (datetime.now(UTC) - last_at).total_seconds()


def _earliest_portfolio_value(engine: Engine, *, execution_context_id: uuid.UUID) -> float | None:
    with engine.connect() as conn:
        row = conn.execute(_EARLIEST_PORTFOLIO_VALUE_SQL, {"execution_context_id": execution_context_id}).first()
    return float(row[0]) if row is not None else None


def _compute_daily_pl(account: AlpacaAccountSnapshot) -> float | None:
    if account.equity is None or account.last_equity is None:
        return None
    try:
        return float(account.equity) - float(account.last_equity)
    except (TypeError, ValueError):
        return None


def _compute_total_pl(engine: Engine, *, execution_context_id: uuid.UUID, current_value: float) -> float:
    """Voir docstring du module ("total_pl — limite honnête assumée") : le
    premier snapshot d'un contexte est sa propre référence (`total_pl =
    0.0`), pas une valeur manquante — la métrique "P&L depuis que ce
    contexte est suivi" vaut honnêtement zéro au moment où le suivi
    commence."""
    earliest = _earliest_portfolio_value(engine, execution_context_id=execution_context_id)
    reference = earliest if earliest is not None else current_value
    return current_value - reference


def _write_snapshot(
    engine: Engine,
    *,
    user_id: uuid.UUID,
    execution_context_id: uuid.UUID,
    account: AlpacaAccountSnapshot,
    positions: list[AlpacaPositionSnapshot],
) -> None:
    # Un seul horodatage pour TOUT ce tick (portfolio_snapshot + toutes les
    # positions_snapshots) — voir `backend/app/portfolio.py::latest_positions`,
    # qui s'ancre sur ce même `snapshot_at` partagé pour distinguer "jamais
    # tourné" de "tourné mais compte flat" (0 position ouverte).
    snapshot_at = datetime.now(UTC)
    portfolio_value = float(account.portfolio_value)
    daily_pl = _compute_daily_pl(account)
    total_pl = _compute_total_pl(engine, execution_context_id=execution_context_id, current_value=portfolio_value)

    raw_payload: dict[str, Any] = {
        "cash": account.cash,
        "buying_power": account.buying_power,
        "portfolio_value": account.portfolio_value,
        "equity": account.equity,
        "last_equity": account.last_equity,
    }

    with engine.begin() as conn:
        conn.execute(
            _INSERT_PORTFOLIO_SNAPSHOT_SQL,
            {
                "id": uuid.uuid4(),
                "user_id": user_id,
                "execution_context_id": execution_context_id,
                "cash": float(account.cash),
                "buying_power": float(account.buying_power),
                "portfolio_value": portfolio_value,
                "daily_pl": daily_pl,
                "total_pl": total_pl,
                "raw_provider_payload": json.dumps(raw_payload),
                "snapshot_at": snapshot_at,
            },
        )
        for position in positions:
            conn.execute(
                _INSERT_POSITION_SNAPSHOT_SQL,
                {
                    "id": uuid.uuid4(),
                    "user_id": user_id,
                    "execution_context_id": execution_context_id,
                    "symbol": position.symbol,
                    "quantity": float(position.qty),
                    "average_entry_price": float(position.avg_entry_price),
                    "market_value": float(position.market_value),
                    "unrealized_pl": float(position.unrealized_pl),
                    "snapshot_at": snapshot_at,
                },
            )


def tick(engine: Engine, redis_client: redis.Redis) -> None:
    for account in _connected_accounts(engine):
        account_id = account["account_id"]
        user_id = account["user_id"]

        context_id = _paper_execution_context_id(engine, user_id)
        if context_id is None:
            logger.warning("account %s: aucun contexte PAPER trouvé, tick sauté", account_id)
            continue

        elapsed = _seconds_since_last_snapshot(engine, execution_context_id=context_id)
        if elapsed is not None and elapsed < SNAPSHOT_INTERVAL_SECONDS:
            continue

        try:
            api_key = decrypt_secret(account["encrypted_api_key"])
            secret_key = decrypt_secret(account["encrypted_secret_key"])
        except Exception:  # noqa: BLE001 — jamais logué en détail (pourrait fuiter des infos sur la clé)
            logger.exception("account %s: échec de déchiffrement des identifiants", account_id)
            continue

        try:
            client = AlpacaPortfolioClient(api_key, secret_key)
            alpaca_account = client.get_account()
            positions = client.get_positions()
        except AlpacaPortfolioError as exc:
            logger.warning("account %s: échec de synchronisation du portefeuille : %s", account_id, exc)
            continue

        try:
            _write_snapshot(
                engine, user_id=user_id, execution_context_id=context_id, account=alpaca_account, positions=positions
            )
        except Exception:  # noqa: BLE001 — un échec d'écriture ne doit pas tuer le tick entier (autres comptes)
            logger.exception("account %s: échec d'écriture du snapshot portefeuille", account_id)
            continue

        logger.info(
            "portfolio snapshot écrit (%d position(s))",
            len(positions),
            extra={"execution_context_id": str(context_id)},
        )


if __name__ == "__main__":
    run_service("portfolio-worker", tick)
