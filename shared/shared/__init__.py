"""Package partagé ZikosoftTrader AI.

Contient les contrats stables consommés par `backend`, `agents` et `workers` :
enveloppe d'événement Redis Streams, format d'erreur API, format de log JSON,
journal d'erreurs applicatif (B36) et interface AIProvider (D017/D026).

Ces contrats sont volontairement figés dès le socle (B01–B04) : toute brique
livrée ensuite doit s'appuyer dessus sans les modifier de façon incompatible
(voir §40 de AVANCEMENT.md — principe de livraison "contrats d'abord").
"""

from .ai_governance import get_ai_calls_enabled, set_ai_calls_enabled
from .errors import APIError, ErrorCode
from .events import EventEnvelope, Streams

__all__ = [
    "APIError",
    "ErrorCode",
    "EventEnvelope",
    "Streams",
    "get_ai_calls_enabled",
    "set_ai_calls_enabled",
]
