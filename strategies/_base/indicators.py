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
