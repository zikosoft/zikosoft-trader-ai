
from __future__ import annotations

from strategies._base.indicators import relative_strength_index


def validate_parameters(params: dict) -> list[str]:
    """§B12 "Validation seuil achat < seuil vente" — même principe que
    `moving_average_crossover.validate_parameters` : règle cross-champs que
    le JSON Schema seul n'exprime pas proprement. Retourne une liste
    d'erreurs (vide = valide)."""
    errors: list[str] = []

    oversold = params.get("oversold_threshold")
    overbought = params.get("overbought_threshold")
    if isinstance(oversold, int | float) and isinstance(overbought, int | float) and oversold >= overbought:
        errors.append("oversold_threshold doit être strictement inférieur à overbought_threshold")

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
    "rsi": float|None}`."""
    period = params["rsi_period"]
    oversold = params["oversold_threshold"]
    overbought = params["overbought_threshold"]

    closes = [bar["close"] for bar in bars]
    rsi_series = relative_strength_index(closes, period)
    current_rsi = rsi_series[-1] if rsi_series else None

    if current_rsi is None:
        return {
            "signal": "HOLD",
            "reasoning": f"pas assez de bougies pour calculer le RSI({period}) (besoin de {period + 1} clôtures minimum)",
            "rsi": None,
        }

    if current_rsi <= oversold:
        signal = "BUY"
        reasoning = (
            f"RSI({period}) = {current_rsi:.2f} <= seuil de survente {oversold} : "
            "retournement haussier attendu"
        )
    elif current_rsi >= overbought:
        signal = "SELL"
        reasoning = (
            f"RSI({period}) = {current_rsi:.2f} >= seuil de surachat {overbought} : "
            "retournement baissier attendu"
        )
    else:
        signal = "HOLD"
        reasoning = f"RSI({period}) = {current_rsi:.2f} entre les seuils {oversold}/{overbought} : pas de signal"

    return {"signal": signal, "reasoning": reasoning, "rsi": current_rsi}
