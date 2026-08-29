"""Package de la stratégie AI Market Agent Strategy — première stratégie IA
réelle du registre B11 (§B12, `required_capabilities=["ai"]`)."""

from __future__ import annotations

from .definition import DEFINITION
from .engine import evaluate, validate_parameters

__all__ = ["DEFINITION", "evaluate", "validate_parameters"]
