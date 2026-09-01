"""Package de la stratégie RSI Reversal — deuxième stratégie prédéfinie
livrée pour le registre B11, à côté de `moving_average_crossover` (§B12)."""

from __future__ import annotations

from .definition import DEFINITION
from .engine import evaluate, validate_parameters

__all__ = ["DEFINITION", "evaluate", "validate_parameters"]
