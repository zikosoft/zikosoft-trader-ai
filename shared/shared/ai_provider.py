"""Interface AIProvider — décision D017/D026 (voir AVANCEMENT.md B10).

Abstraction commune utilisée par Market Agent, Strategy Agent, Risk Critic
Agent, Execution & Explanation Agent et Ask Ziko AI (B29), pour que le
fournisseur de modèle reste swappable (cohérent avec la roadmap V2 privée,
non exposée publiquement) sans toucher à la logique métier de chaque agent.

Fournisseur V1 retenu : Claude (Anthropic). Gouvernance des coûts intégrée
dès le socle : tiering de modèle, quota d'appels, interrupteur global — pour
répondre au risque R15 (coût token non maîtrisé sur une instance publique).
"""

from __future__ import annotations

import abc
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("ai_provider")


class AIProviderError(Exception):
    """Levée en cas d'échec (timeout, erreur upstream, quota dépassé).

    Les agents appelants doivent toujours prévoir un fallback sûr (HOLD /
    REQUIRES_APPROVAL) en cas d'exception ici — jamais de crash silencieux
    (voir B13 critères d'acceptation)."""


class ModelTier:
    """Deux tiers de modèle pour maîtriser le coût (D026)."""

    LOW_STAKES = "low_stakes"   # ex. normalisation Market Agent, résumés
    HIGH_STAKES = "high_stakes"  # ex. Strategy Agent, Risk Critic, Explanation


@dataclass
class AIProviderConfig:
    enabled: bool = True
    max_calls_per_minute: int = 30
    max_calls_per_day: int = 500
    # Set by agent containers when the shared Redis daily cap is enabled.
    daily_quota_client: Any = None
    high_stakes_model: str = "claude-sonnet-4-5"
    low_stakes_model: str = "claude-haiku-4-5"
    timeout_seconds: float = 20.0
    temperature: float = 0.2
    # §B10 checklist "budget de tokens configurable" — trouvé en écart le
    # 28/08 (audit B10) : `max_tokens` était figé en dur (1024) dans
    # `ClaudeAIProvider._call_structured`, jamais exposé sur la config
    # malgré le checklist item. Corrigé ici plutôt que de laisser un champ
    # de configuration prévu mais inerte.
    max_tokens: int = 1024


class _RateLimiter:
    """Quota d'appels glissant sur 60s, indépendant du nombre de visiteurs
    sur l'instance déployée (D026 — gouvernance des coûts)."""

    def __init__(self, max_calls_per_minute: int) -> None:
        self.max_calls_per_minute = max_calls_per_minute
        self._calls: deque[float] = deque()

    def allow(self) -> bool:
        now = time.monotonic()
        while self._calls and now - self._calls[0] > 60:
            self._calls.popleft()
        if len(self._calls) >= self.max_calls_per_minute:
            return False
        self._calls.append(now)
        return True


class AIProvider(abc.ABC):
    """Interface abstraite. Une seule implémentation concrète en V1
    (`ClaudeAIProvider`), mais tout appelant doit passer par cette interface —
    jamais un import direct du SDK du fournisseur dans un agent métier."""

    def __init__(self, config: AIProviderConfig | None = None) -> None:
        self.config = config or AIProviderConfig()
        self._limiter = _RateLimiter(self.config.max_calls_per_minute)

    def structured_complete(
        self,
        *,
        prompt: str,
        schema: dict[str, Any],
        tier: str = ModelTier.HIGH_STAKES,
        context_label: str = "",
    ) -> dict[str, Any]:
        """Retourne une sortie conforme à `schema` (JSON Schema), en s'appuyant
        sur le tool-use/function-calling natif du fournisseur (D022) — jamais
        un parsing JSON libre en post-traitement. Lève `AIProviderError` si
        désactivé, si le quota est dépassé, ou en cas d'échec après retry."""
        if not self.config.enabled:
            raise AIProviderError("AI calls disabled via Settings (interrupteur global, D026)")
        if self.config.daily_quota_client is not None:
            from shared.ai_runtime_settings import consume_daily_call

            try:
                allowed_today = consume_daily_call(
                    self.config.daily_quota_client, limit=self.config.max_calls_per_day
                )
            except Exception as exc:  # noqa: BLE001 - safe fallback when Redis is unavailable
                raise AIProviderError("AI daily quota is unavailable") from exc
            if not allowed_today:
                raise AIProviderError(f"AI daily call limit exceeded ({context_label or 'unknown'})")
        if not self._limiter.allow():
            raise AIProviderError(f"AI call rate limit exceeded ({context_label or 'unknown'})")
        model = self.config.high_stakes_model if tier == ModelTier.HIGH_STAKES else self.config.low_stakes_model
        return self._call_structured(prompt=prompt, schema=schema, model=model)

    @abc.abstractmethod
    def _call_structured(self, *, prompt: str, schema: dict[str, Any], model: str) -> dict[str, Any]:
        """Implémentation spécifique au fournisseur. Doit lever `AIProviderError`
        (pas une exception brute du SDK) en cas d'échec, pour que l'appelant
        n'ait qu'un seul type d'erreur à gérer."""
        raise NotImplementedError


class ClaudeAIProvider(AIProvider):
    """Implémentation Claude (Anthropic API) — tool-use natif pour contraindre
    la sortie au schéma dès la génération. Le SDK réel (`anthropic`) est
    importé paresseusement pour que `shared` reste installable sans dépendance
    lourde dans les contextes qui n'en ont pas besoin (ex. tests unitaires
    d'autres modules)."""

    def __init__(self, api_key: str, config: AIProviderConfig | None = None) -> None:
        super().__init__(config)
        self._api_key = api_key

    def _call_structured(self, *, prompt: str, schema: dict[str, Any], model: str) -> dict[str, Any]:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - dépendance ajoutée en B10/B13
            raise AIProviderError("anthropic SDK not installed") from exc

        client = anthropic.Anthropic(api_key=self._api_key, timeout=self.config.timeout_seconds)
        tool_name = "emit_structured_output"
        try:
            response = client.messages.create(
                model=model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                tools=[{"name": tool_name, "description": "Emit the structured result.", "input_schema": schema}],
                tool_choice={"type": "tool", "name": tool_name},
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:  # noqa: BLE001 — normalisé en AIProviderError pour les agents
            raise AIProviderError(f"Claude API call failed: {exc}") from exc

        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
                return block.input
        raise AIProviderError("Claude response did not include the expected tool_use block")


def build_ai_provider(*, api_key: str, config: AIProviderConfig | None = None) -> AIProvider:
    """Point d'entrée unique pour instancier le provider configuré (D017).

    Construit toujours une INSTANCE NEUVE (et donc un `_RateLimiter` vierge)
    — utile pour les tests et pour tout appelant qui veut délibérément
    repartir de zéro. Un service qui boucle indéfiniment (`run_service()`,
    tous les agents consommateurs d'IA) doit utiliser `get_ai_provider()`
    ci-dessous, pas cette fonction directement — voir son docstring."""
    return ClaudeAIProvider(api_key=api_key, config=config)


# §B10 checklist "quota d'appels global par minute/heure" — bug trouvé le
# 28/08 (audit B10) : les 4 agents consommateurs d'IA (market_agent,
# strategy_agent, risk_critic_agent, execution_explanation_agent)
# appelaient tous `build_ai_provider(...)` À CHAQUE TICK, ce qui recréait
# un `_RateLimiter` vierge à chaque appel — le quota glissant sur 60s
# n'accumulait donc jamais aucun état d'un tick à l'autre, le rendant
# inopérant en pratique malgré le mécanisme lui-même étant correct et
# testé isolément (voir `TestRateLimiterWindow`). Un cache par clé API,
# vivant pour toute la durée du process (cohérent avec `run_service()` qui
# tourne en boucle infinie dans le même process jusqu'à SIGTERM), corrige
# ça sans toucher à la logique métier de chaque agent — un seul point de
# changement (`get_ai_provider` remplace `build_ai_provider` dans les 4
# call sites), même discipline anti-duplication que D028/D069.
_provider_cache: dict[str, AIProvider] = {}


def get_ai_provider(*, api_key: str, config: AIProviderConfig) -> AIProvider:
    """Retourne un `AIProvider` mis en cache par clé API pour la durée du
    process, pour que le quota d'appels (`_RateLimiter`) s'accumule
    réellement au fil des ticks plutôt que d'être réinitialisé à chaque
    appel (voir note ci-dessus).

    Les champs de `config` qui peuvent légitimement changer d'un tick à
    l'autre (`enabled` — lu depuis Redis à chaque tick pour que
    l'interrupteur Settings agisse "en un clic sans redéployer", D026 —
    ainsi que les autres champs, lus depuis l'environnement) sont
    réappliqués sur l'instance mise en cache plutôt que de reconstruire un
    nouvel objet, précisément pour que le `_RateLimiter` sous-jacent
    survive à ces changements de configuration."""
    provider = _provider_cache.get(api_key)
    if provider is None:
        provider = build_ai_provider(api_key=api_key, config=config)
        _provider_cache[api_key] = provider
        return provider
    provider.config.enabled = config.enabled
    provider.config.high_stakes_model = config.high_stakes_model
    provider.config.low_stakes_model = config.low_stakes_model
    provider.config.timeout_seconds = config.timeout_seconds
    provider.config.temperature = config.temperature
    provider.config.max_calls_per_day = config.max_calls_per_day
    provider.config.daily_quota_client = config.daily_quota_client
    provider.config.max_tokens = config.max_tokens
    if provider.config.max_calls_per_minute != config.max_calls_per_minute:
        provider.config.max_calls_per_minute = config.max_calls_per_minute
        provider._limiter.max_calls_per_minute = config.max_calls_per_minute
    return provider


def reset_ai_provider_cache() -> None:
    """Vide le cache process de `get_ai_provider` — jamais utile en
    production (un process d'agent ne veut justement PAS repartir de zéro,
    c'est tout le sens du cache), réservé aux tests pour qu'aucune suite ne
    dépende silencieusement de l'ordre d'exécution (deux agents différents
    peuvent utiliser la même clé API factice dans leurs tests respectifs —
    voir la fixture `_reset_ai_provider_cache` de `tests/conftest.py`)."""
    _provider_cache.clear()
