"""B12 — définition (au sens B11 : `StrategyDefinition` en mémoire) de la
stratégie Moving Average Crossover, la première stratégie prédéfinie
livrée pour le registre B11."""

from __future__ import annotations

from shared.strategy_registry import StrategyDefinition

# Pas de champ "symbole" ici : c'est `Strategy.symbols` (liste, colonne
# dédiée du modèle DB depuis B03) qui porte les symboles surveillés par une
# INSTANCE de cette stratégie (voir backend/app/strategy_instances.py, B12
# CRUD) — ces paramètres s'appliquent identiquement à chacun d'eux. Le futur
# Strategy Agent (B13) appellera `evaluate()` une fois par symbole de
# `instance.symbols`, avec les mêmes `params` à chaque fois.
PARAMETER_SCHEMA = {
    "type": "object",
    "properties": {
        # §B12 "Timeframes autorisés" — valeurs alignées sur la convention
        # documentée par Alpaca pour `TimeFrame` (non vérifiable en direct
        # depuis cette sandbox — aucun accès réseau réel, même limite que
        # documentée en B10).
        "timeframe": {"type": "string", "enum": ["1Min", "5Min", "15Min", "1Hour", "1Day"]},
        "short_period": {"type": "integer", "minimum": 2, "maximum": 200},
        "long_period": {"type": "integer", "minimum": 2, "maximum": 500},
        "stop_loss_pct": {"type": "number", "exclusiveMinimum": 0, "maximum": 50},
        "take_profit_pct": {"type": "number", "exclusiveMinimum": 0, "maximum": 100},
    },
    "required": ["timeframe", "short_period", "long_period", "stop_loss_pct", "take_profit_pct"],
    # §B12 "Validation short period < long period" : JSON Schema seul
    # n'exprime pas proprement une comparaison entre deux propriétés
    # (nécessiterait un mot-clé personnalisé) — appliqué en Python pur,
    # voir engine.validate_parameters(), plus lisible et plus facilement
    # testable qu'un schéma "if/then" alambiqué.
}

UI_SCHEMA = {
    "timeframe": {"widget": "select", "label": "Intervalle", "order": 1},
    "short_period": {"widget": "number", "label": "Période courte", "order": 2},
    "long_period": {"widget": "number", "label": "Période longue", "order": 3},
    "stop_loss_pct": {"widget": "number", "label": "Stop-loss (%)", "order": 4},
    "take_profit_pct": {"widget": "number", "label": "Take-profit (%)", "order": 5},
}

DEFAULTS_BY_PROFILE = {
    "beginner": {
        "timeframe": "1Day",
        "short_period": 10,
        "long_period": 30,
        "stop_loss_pct": 2.0,
        "take_profit_pct": 4.0,
    },
    "advanced": {
        "timeframe": "15Min",
        "short_period": 9,
        "long_period": 21,
        "stop_loss_pct": 1.0,
        "take_profit_pct": 2.0,
    },
}

REQUIRED_MARKET_DATA = {
    "bars": {"timeframes": ["1Min", "5Min", "15Min", "1Hour", "1Day"], "lookback": 500},
}

DEFINITION = StrategyDefinition(
    type_code="moving_average_crossover",
    version="1.0.0",
    name="Moving Average Crossover",
    description=(
        "Croisement de deux moyennes mobiles simples (courte/longue) sur un symbole — "
        "signal BUY quand la moyenne courte franchit la longue à la hausse, SELL à la "
        "baisse, sinon HOLD. Calcul 100% déterministe, aucun appel IA."
    ),
    parameter_schema=PARAMETER_SCHEMA,
    ui_schema=UI_SCHEMA,
    defaults_by_profile=DEFAULTS_BY_PROFILE,
    required_market_data=REQUIRED_MARKET_DATA,
    required_capabilities=[],
)
