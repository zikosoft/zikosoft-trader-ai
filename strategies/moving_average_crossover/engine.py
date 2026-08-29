
from __future__ import annotations

from strategies._base.indicators import simple_moving_average


def validate_parameters(params: dict) -> list[str]:
    """Règles cross-champs que le JSON Schema seul n'exprime pas proprement
    (§B12 "Validation short period < long period") — prévu pour être
    appelé par le futur CRUD d'instances de stratégie (B12, pas encore
    construit) avant de créer/modifier une `Strategy`, en plus de la
    validation JSON Schema déjà appliquée par le Strategy Registry (B11)
    sur `parameter_schema`. Retourne une liste d'erreurs (vide = valide)."""
    errors: list[str] = []

    short_period = params.get("short_period")
    long_period = params.get("long_period")
    if isinstance(short_period, int) and isinstance(long_period, int) and short_period >= long_period:
        errors.append("short_period doit être strictement inférieur à long_period")

    stop_loss_pct = params.get("stop_loss_pct")
    if isinstance(stop_loss_pct, int | float) and stop_loss_pct <= 0:
        errors.append("stop_loss_pct doit être strictement positif")

    take_profit_pct = params.get("take_profit_pct")
    if isinstance(take_profit_pct, int | float) and take_profit_pct <= 0:
        errors.append("take_profit_pct doit être strictement positif")

    return errors


def evaluate(bars: list[dict], params: dict) -> dict:
    """Calcul déterministe pur — mêmes entrées -> même sortie, aucun état
    caché, aucun appel réseau/IA. `bars` triés du plus ancien au plus
    récent, `params` déjà validés (voir `validate_parameters`).

    Retourne `{"signal": "BUY"|"SELL"|"HOLD", "reasoning": str,
    "short_ma": float|None, "long_ma": float|None}`."""
    short_period = params["short_period"]
    long_period = params["long_period"]

    closes = [bar["close"] for bar in bars]
    short_series = simple_moving_average(closes, short_period)
    long_series = simple_moving_average(closes, long_period)

    if (
        len(closes) < long_period + 1
        or short_series[-1] is None
        or short_series[-2] is None
        or long_series[-1] is None
        or long_series[-2] is None
    ):
        return {
            "signal": "HOLD",
            "reasoning": "pas assez de bougies pour comparer les deux moyennes mobiles sur deux points consécutifs",
            "short_ma": short_series[-1] if short_series else None,
            "long_ma": long_series[-1] if long_series else None,
        }

    prev_short, prev_long = short_series[-2], long_series[-2]
    curr_short, curr_long = short_series[-1], long_series[-1]

    crossed_up = prev_short <= prev_long and curr_short > curr_long
    crossed_down = prev_short >= prev_long and curr_short < curr_long

    if crossed_up:
        signal = "BUY"
        reasoning = (
            f"la moyenne mobile courte ({short_period}) franchit la moyenne mobile longue "
            f"({long_period}) à la hausse : {prev_short:.4f}->{curr_short:.4f} vs "
            f"{prev_long:.4f}->{curr_long:.4f}"
        )
    elif crossed_down:
        signal = "SELL"
        reasoning = (
            f"la moyenne mobile courte ({short_period}) franchit la moyenne mobile longue "
            f"({long_period}) à la baisse : {prev_short:.4f}->{curr_short:.4f} vs "
            f"{prev_long:.4f}->{curr_long:.4f}"
        )
    else:
        signal = "HOLD"
        reasoning = "pas de croisement des moyennes mobiles sur la dernière bougie"

    return {"signal": signal, "reasoning": reasoning, "short_ma": curr_short, "long_ma": curr_long}
