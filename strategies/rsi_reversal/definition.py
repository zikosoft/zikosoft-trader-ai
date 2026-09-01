"""B12 — définition (au sens B11 : `StrategyDefinition` en mémoire) de la
stratégie RSI Reversal, deuxième stratégie prédéfinie livrée pour le
registre B11, à côté de `moving_average_crossover`."""

from __future__ import annotations

from shared.strategy_registry import StrategyDefinition

# Même convention que `moving_average_crossover/definition.py` : pas de
# champ "symbole" ici, porté par `Strategy.symbols` (colonne dédiée, B03).
PARAMETER_SCHEMA = {
    "type": "object",
    "properties": {
        "timeframe": {"type": "string", "enum": ["1Min", "5Min", "15Min", "1Hour", "1Day"]},
        "rsi_period": {"type": "integer", "minimum": 2, "maximum": 100},
        # §B12 "Validation seuil achat < seuil vente" — bornés en [0, 100],
        # convention RSI standard (l'indicateur lui-même est borné).
        "oversold_threshold": {"type": "number", "minimum": 0, "maximum": 100},
        "overbought_threshold": {"type": "number", "minimum": 0, "maximum": 100},
        "stop_loss_pct": {"type": "number", "exclusiveMinimum": 0, "maximum": 50},
        "take_profit_pct": {"type": "number", "exclusiveMinimum": 0, "maximum": 100},
    },
    "required": [
        "timeframe",
        "rsi_period",
        "oversold_threshold",
        "overbought_threshold",
        "stop_loss_pct",
        "take_profit_pct",
    ],
    # Comparaison croisée (oversold < overbought) appliquée en Python pur
    # dans engine.validate_parameters() — même raison que documentée dans
    # moving_average_crossover/definition.py pour short_period < long_period.
}

UI_SCHEMA = {
    "timeframe": {"widget": "select", "label": "Intervalle", "order": 1},
    "rsi_period": {"widget": "number", "label": "Période RSI", "order": 2},
    "oversold_threshold": {"widget": "number", "label": "Seuil de survente (achat)", "order": 3},
    "overbought_threshold": {"widget": "number", "label": "Seuil de surachat (vente)", "order": 4},
    "stop_loss_pct": {"widget": "number", "label": "Stop-loss (%)", "order": 5},
    "take_profit_pct": {"widget": "number", "label": "Take-profit (%)", "order": 6},
}

DEFAULTS_BY_PROFILE = {
    # Seuils 30/70 = convention manuel la plus répandue pour un RSI(14) —
    # profil beginner volontairement le plus documenté/standard des deux.
    "beginner": {
        "timeframe": "1Day",
        "rsi_period": 14,
        "oversold_threshold": 30,
        "overbought_threshold": 70,
        "stop_loss_pct": 2.0,
        "take_profit_pct": 4.0,
    },
    # Période plus courte + seuils resserrés = plus de signaux, cohérent
    # avec un profil "advanced" qui accepte plus de bruit pour plus de
    # réactivité (même logique que moving_average_crossover/advanced).
    "advanced": {
        "timeframe": "15Min",
        "rsi_period": 9,
        "oversold_threshold": 25,
        "overbought_threshold": 75,
        "stop_loss_pct": 1.0,
        "take_profit_pct": 2.0,
    },
}

REQUIRED_MARKET_DATA = {
    "bars": {"timeframes": ["1Min", "5Min", "15Min", "1Hour", "1Day"], "lookback": 500},
}

DEFINITION = StrategyDefinition(
    type_code="rsi_reversal",
    version="1.0.0",
    name="RSI Reversal",
    description=(
        "Indice de force relative (RSI) sur un symbole — signal BUY quand le RSI tombe à ou sous "
        "le seuil de survente (retournement haussier attendu), SELL quand il monte à ou au-dessus "
        "du seuil de surachat, sinon HOLD. Calcul 100% déterministe, aucun appel IA."
    ),
    parameter_schema=PARAMETER_SCHEMA,
    ui_schema=UI_SCHEMA,
    defaults_by_profile=DEFAULTS_BY_PROFILE,
    required_market_data=REQUIRED_MARKET_DATA,
    required_capabilities=[],
)
