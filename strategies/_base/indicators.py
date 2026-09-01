"""Indicateurs techniques déterministes partagés entre modules de
stratégie — sans dépendance externe (pas de numpy/pandas), cohérent avec le
reste du projet qui évite les dépendances lourdes superflues.

Convention commune à tous les indicateurs de ce fichier : `values` est une
liste de flottants triée du plus ancien au plus récent (même ordre que les
`bars` renvoyés par les outils MCP Alpaca, voir agents/common/mcp_session.py,
B10) ; chaque fonction renvoie une liste de MÊME LONGUEUR que `values`, avec
`None` pour les points où l'historique est insuffisant — même convention
que `pandas.Series.rolling(period).mean()`, pour rester familier sans en
dépendre."""

from __future__ import annotations


def simple_moving_average(values: list[float], period: int) -> list[float | None]:
    """Moyenne mobile simple sur une fenêtre glissante de `period` points."""
    if period < 1:
        raise ValueError("period doit être >= 1")

    result: list[float | None] = [None] * len(values)
    running_sum = 0.0
    for i, value in enumerate(values):
        running_sum += value
        if i >= period:
            running_sum -= values[i - period]
        if i >= period - 1:
            result[i] = running_sum / period
    return result


def relative_strength_index(values: list[float], period: int) -> list[float | None]:
    """RSI (§B12 "RSI Reversal") — moyenne SIMPLE des gains/pertes sur la
    fenêtre glissante (technique de somme courante identique à
    `simple_moving_average` ci-dessus), pas le lissage exponentiel de Wilder
    utilisé par la convention "RSI classique" : choix délibéré pour rester
    cohérent avec le seul autre indicateur du fichier (aucune dépendance
    numpy/pandas) et pour qu'un résultat reste vérifiable à la main dans les
    tests, au prix d'une légère différence numérique avec un RSI Wilder
    "manuel" — documenté ici plutôt que passé sous silence.

    Convention de padding différente de `simple_moving_average` : un RSI a
    besoin de `period` VARIATIONS (donc `period + 1` clôtures) avant son
    premier point exploitable — `result[period]` est le premier point non
    `None`, pas `result[period - 1]`."""
    if period < 1:
        raise ValueError("period doit être >= 1")

    result: list[float | None] = [None] * len(values)
    if len(values) < period + 1:
        return result

    gains = [0.0] * len(values)
    losses = [0.0] * len(values)
    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains[i] = max(change, 0.0)
        losses[i] = max(-change, 0.0)

    running_gain = sum(gains[1 : period + 1])
    running_loss = sum(losses[1 : period + 1])
    result[period] = _rsi_from_averages(running_gain / period, running_loss / period)

    for i in range(period + 1, len(values)):
        running_gain += gains[i] - gains[i - period]
        running_loss += losses[i] - losses[i - period]
        result[i] = _rsi_from_averages(running_gain / period, running_loss / period)

    return result


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    """Cas limites : aucune perte du tout sur la fenêtre -> 100 (survente
    inversée, tendance haussière pure) si des gains existent, sinon 50 (prix
    parfaitement plat — ni sur-achat ni survente, valeur neutre)."""
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))
