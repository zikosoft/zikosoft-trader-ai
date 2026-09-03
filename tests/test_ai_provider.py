from __future__ import annotations

import httpx
import pytest
import respx

pytest.importorskip("anthropic", reason="suite agents — lancer avec `make test-agents` (.venv-agents)")

from shared.ai_provider import (  # noqa: E402 — après importorskip, volontaire
    AIProviderConfig,
    AIProviderError,
    ModelTier,
    build_ai_provider,
    estimate_maximum_call_cost_usd,
    get_ai_provider,
    reset_ai_provider_cache,
)

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"

SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}, "confidence": {"type": "number"}},
    "required": ["summary", "confidence"],
}


def _tool_use_response(*, tool_name: str = "emit_structured_output", input_payload: dict) -> dict:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-4-5",
        "content": [
            {"type": "tool_use", "id": "toolu_test", "name": tool_name, "input": input_payload}
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


class TestClaudeAIProviderStructuredComplete:
    def test_returns_tool_input_on_success(self):
        with respx.mock(assert_all_called=True) as mock:
            mock.post(ANTHROPIC_MESSAGES_URL).mock(
                return_value=httpx.Response(
                    200, json=_tool_use_response(input_payload={"summary": "marché stable", "confidence": 0.8})
                )
            )
            provider = build_ai_provider(api_key="fake-key")
            result = provider.structured_complete(prompt="Analyse le marché.", schema=SCHEMA)
        assert result == {"summary": "marché stable", "confidence": 0.8}

    def test_uses_high_stakes_model_by_default(self):
        with respx.mock(assert_all_called=True) as mock:
            mock.post(ANTHROPIC_MESSAGES_URL).mock(
                return_value=httpx.Response(200, json=_tool_use_response(input_payload={"summary": "x", "confidence": 0.1}))
            )
            provider = build_ai_provider(
                api_key="fake-key", config=AIProviderConfig(high_stakes_model="model-high", low_stakes_model="model-low")
            )
            provider.structured_complete(prompt="p", schema=SCHEMA)
            sent_body = mock.calls.last.request.content
        assert b'"model-high"' in sent_body

    def test_low_stakes_tier_uses_cheaper_model(self):
        with respx.mock(assert_all_called=True) as mock:
            mock.post(ANTHROPIC_MESSAGES_URL).mock(
                return_value=httpx.Response(200, json=_tool_use_response(input_payload={"summary": "x", "confidence": 0.1}))
            )
            provider = build_ai_provider(
                api_key="fake-key", config=AIProviderConfig(high_stakes_model="model-high", low_stakes_model="model-low")
            )
            provider.structured_complete(prompt="p", schema=SCHEMA, tier=ModelTier.LOW_STAKES)
            sent_body = mock.calls.last.request.content
        assert b'"model-low"' in sent_body

    def test_forces_tool_choice_never_free_text(self):
        """§D022 — sortie structurée via tool-use natif, jamais de parsing
        JSON libre en post-traitement : vérifie que l'appel force bien
        `tool_choice`."""
        with respx.mock(assert_all_called=True) as mock:
            mock.post(ANTHROPIC_MESSAGES_URL).mock(
                return_value=httpx.Response(200, json=_tool_use_response(input_payload={"summary": "x", "confidence": 0.1}))
            )
            provider = build_ai_provider(api_key="fake-key")
            provider.structured_complete(prompt="p", schema=SCHEMA)
            sent_body = mock.calls.last.request.content
        assert b'"tool_choice"' in sent_body
        assert b'"type":"tool"' in sent_body or b'"type": "tool"' in sent_body

    def test_disabled_raises_without_any_http_call(self):
        with respx.mock(assert_all_called=False) as mock:
            route = mock.post(ANTHROPIC_MESSAGES_URL)
            provider = build_ai_provider(api_key="fake-key", config=AIProviderConfig(enabled=False))
            with pytest.raises(AIProviderError, match="disabled"):
                provider.structured_complete(prompt="p", schema=SCHEMA)
            assert route.call_count == 0

    def test_rate_limit_exceeded_raises_without_extra_http_call(self):
        with respx.mock(assert_all_called=False) as mock:
            route = mock.post(ANTHROPIC_MESSAGES_URL).mock(
                return_value=httpx.Response(200, json=_tool_use_response(input_payload={"summary": "x", "confidence": 0.1}))
            )
            provider = build_ai_provider(api_key="fake-key", config=AIProviderConfig(max_calls_per_minute=2))
            provider.structured_complete(prompt="p", schema=SCHEMA)
            provider.structured_complete(prompt="p", schema=SCHEMA)
            with pytest.raises(AIProviderError, match="rate limit"):
                provider.structured_complete(prompt="p", schema=SCHEMA)
            assert route.call_count == 2

    def test_daily_usd_budget_blocks_second_request_before_http_call(self, redis_client):
        """The cost cap is reserved before network I/O, not reconciled later."""
        from datetime import UTC, datetime

        from shared.ai_runtime_settings import AI_DAILY_CALL_KEY_PREFIX, AI_DAILY_COST_KEY_PREFIX

        day = datetime.now(UTC).date().isoformat()
        redis_client.delete(AI_DAILY_CALL_KEY_PREFIX + day, AI_DAILY_COST_KEY_PREFIX + day)
        config = AIProviderConfig(daily_quota_client=redis_client, max_calls_per_day=10)
        one_call_budget = estimate_maximum_call_cost_usd(
            prompt="p", model=config.high_stakes_model, config=config
        )
        # Leave one micro-dollar margin so Decimal floor/ceiling conversion is
        # tested as a real allowed call, not as an accidental float boundary.
        config.daily_budget_usd = one_call_budget + 0.001
        try:
            with respx.mock(assert_all_called=False) as mock:
                route = mock.post(ANTHROPIC_MESSAGES_URL).mock(
                    return_value=httpx.Response(200, json=_tool_use_response(input_payload={"summary": "x", "confidence": 0.1}))
                )
                provider = build_ai_provider(api_key="fake-key", config=config)
                provider.structured_complete(prompt="p", schema=SCHEMA)
                with pytest.raises(AIProviderError, match="daily USD budget"):
                    provider.structured_complete(prompt="p", schema=SCHEMA)
                assert route.call_count == 1
        finally:
            redis_client.delete(AI_DAILY_CALL_KEY_PREFIX + day, AI_DAILY_COST_KEY_PREFIX + day)

    def test_upstream_error_normalized_to_ai_provider_error(self):
        """Toute panne réseau/HTTP doit remonter en `AIProviderError`, jamais
        une exception brute du SDK `anthropic` — même principe que
        `McpSessionError` (un seul type d'erreur à gérer côté agent)."""
        with respx.mock(assert_all_called=True) as mock:
            mock.post(ANTHROPIC_MESSAGES_URL).mock(return_value=httpx.Response(500, json={"error": "boom"}))
            provider = build_ai_provider(api_key="fake-key")
            with pytest.raises(AIProviderError):
                provider.structured_complete(prompt="p", schema=SCHEMA)

    def test_missing_tool_use_block_raises_ai_provider_error(self):
        """Le modèle répond mais sans passer par l'outil forcé (ex. refus,
        réponse texte) — doit être traité comme un échec exploitable, pas
        un crash ni un `None` silencieux."""
        with respx.mock(assert_all_called=True) as mock:
            mock.post(ANTHROPIC_MESSAGES_URL).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "id": "msg_test",
                        "type": "message",
                        "role": "assistant",
                        "model": "claude-haiku-4-5",
                        "content": [{"type": "text", "text": "je ne peux pas répondre à ça"}],
                        "stop_reason": "end_turn",
                        "usage": {"input_tokens": 5, "output_tokens": 5},
                    },
                )
            )
            provider = build_ai_provider(api_key="fake-key")
            with pytest.raises(AIProviderError, match="tool_use"):
                provider.structured_complete(prompt="p", schema=SCHEMA)

    def test_api_key_never_appears_in_request_body(self):
        """§B10 sécurité "aucun secret dans le prompt" — vérifie que la clé
        API elle-même (transmise en en-tête HTTP par le SDK, pas par nous)
        n'apparaît jamais dans le corps de la requête envoyée."""
        marker_key = "sk-ant-MARKER-NEVER-IN-BODY"
        with respx.mock(assert_all_called=True) as mock:
            mock.post(ANTHROPIC_MESSAGES_URL).mock(
                return_value=httpx.Response(200, json=_tool_use_response(input_payload={"summary": "x", "confidence": 0.1}))
            )
            provider = build_ai_provider(api_key=marker_key)
            provider.structured_complete(prompt="Analyse ceci.", schema=SCHEMA)
            sent_body = mock.calls.last.request.content
            # La clé part bien en en-tête (comportement normal du SDK), jamais
            # dans le corps JSON de la requête.
            sent_header = mock.calls.last.request.headers.get("x-api-key", "")
        assert marker_key.encode() not in sent_body
        assert marker_key in sent_header


class TestRateLimiterWindow:
    """La fenêtre glissante de 60s (D026 — quota indépendant du nombre de
    visiteurs) doit vraiment libérer des créneaux avec le temps, pas
    seulement compter jusqu'à la limite et bloquer indéfiniment."""

    def test_old_calls_expire_out_of_the_window(self):
        with respx.mock(assert_all_called=False) as mock:
            mock.post(ANTHROPIC_MESSAGES_URL).mock(
                return_value=httpx.Response(200, json=_tool_use_response(input_payload={"summary": "x", "confidence": 0.1}))
            )
            provider = build_ai_provider(api_key="fake-key", config=AIProviderConfig(max_calls_per_minute=1))
            provider.structured_complete(prompt="p", schema=SCHEMA)
            with pytest.raises(AIProviderError, match="rate limit"):
                provider.structured_complete(prompt="p", schema=SCHEMA)
            # Simule l'écoulement du temps en manipulant directement l'état
            # interne du limiteur plutôt qu'un vrai `time.sleep(61)` (lent,
            # inutile pour vérifier la logique d'expiration elle-même).
            provider._limiter._calls[0] -= 61
            provider.structured_complete(prompt="p", schema=SCHEMA)  # ne lève plus


class TestAIProviderConfigDefaults:
    def test_config_matches_documented_tiering_defaults(self):
        """Corrèle avec AVANCEMENT.md D026 : deux tiers de modèle
        (Haiku/Sonnet), un plafond d'appels raisonnable par défaut."""
        config = AIProviderConfig()
        assert config.high_stakes_model != config.low_stakes_model
        assert config.max_calls_per_minute > 0
        assert config.enabled is True
        assert config.timeout_seconds > 0

    def test_max_tokens_configurable_and_used_in_request(self):
        """§B10 checklist "budget de tokens configurable" — trouvé inerte le
        28/08 (`max_tokens` figé en dur à 1024 dans `_call_structured`,
        jamais lu depuis `self.config`), corrigé. Vérifie que la valeur
        configurée est bien celle envoyée à l'API, pas une valeur en dur."""
        assert AIProviderConfig().max_tokens == 1024
        with respx.mock(assert_all_called=True) as mock:
            mock.post(ANTHROPIC_MESSAGES_URL).mock(
                return_value=httpx.Response(200, json=_tool_use_response(input_payload={"summary": "x", "confidence": 0.1}))
            )
            provider = build_ai_provider(api_key="fake-key", config=AIProviderConfig(max_tokens=256))
            provider.structured_complete(prompt="p", schema=SCHEMA)
            sent_body = mock.calls.last.request.content
        assert b'"max_tokens":256' in sent_body or b'"max_tokens": 256' in sent_body


class TestGetAIProviderCache:
    """§Correctif du 28/08 (audit B10) : `build_ai_provider` appelé à chaque
    tick recréait un `_RateLimiter` vierge, rendant le quota d'appels
    inopérant en pratique malgré `TestRateLimiterWindow` ci-dessus prouvant
    que le mécanisme lui-même est correct isolément. `get_ai_provider` est
    le point d'entrée que les 4 agents consommateurs d'IA utilisent
    désormais (market_agent, strategy_agent, risk_critic_agent,
    execution_explanation_agent) — ces tests prouvent le cache lui-même,
    pas leur intégration (déjà couverte par les suites de chaque agent)."""

    def setup_method(self):
        reset_ai_provider_cache()

    def teardown_method(self):
        reset_ai_provider_cache()

    def test_same_api_key_returns_same_instance(self):
        first = get_ai_provider(api_key="cache-key", config=AIProviderConfig())
        second = get_ai_provider(api_key="cache-key", config=AIProviderConfig())
        assert first is second

    def test_different_api_key_returns_different_instance(self):
        first = get_ai_provider(api_key="cache-key-a", config=AIProviderConfig())
        second = get_ai_provider(api_key="cache-key-b", config=AIProviderConfig())
        assert first is not second

    def test_rate_limiter_state_survives_across_calls_unlike_build_ai_provider(self):
        """La preuve directe du bug corrigé : avec `build_ai_provider`, deux
        appels successifs avec `max_calls_per_minute=1` ne lèvent JAMAIS
        (chaque instance repart d'un quota vierge) ; avec `get_ai_provider`,
        le deuxième appel épuise bien le quota accumulé par le premier."""
        config = AIProviderConfig(max_calls_per_minute=1)
        with respx.mock(assert_all_called=False) as mock:
            mock.post(ANTHROPIC_MESSAGES_URL).mock(
                return_value=httpx.Response(200, json=_tool_use_response(input_payload={"summary": "x", "confidence": 0.1}))
            )
            build_ai_provider(api_key="cache-key", config=config).structured_complete(prompt="p", schema=SCHEMA)
            # Bug reproduit : une NOUVELLE instance via `build_ai_provider`
            # ne voit jamais le quota déjà consommé ci-dessus.
            build_ai_provider(api_key="cache-key", config=config).structured_complete(prompt="p", schema=SCHEMA)

            reset_ai_provider_cache()
            get_ai_provider(api_key="cache-key", config=config).structured_complete(prompt="p", schema=SCHEMA)
            with pytest.raises(AIProviderError, match="rate limit"):
                get_ai_provider(api_key="cache-key", config=config).structured_complete(prompt="p", schema=SCHEMA)

    def test_enabled_flag_refreshed_on_cached_instance(self):
        """L'interrupteur Settings (D026) doit agir immédiatement même sur
        une instance mise en cache — sinon couper l'IA depuis Settings
        n'aurait plus d'effet tant que le process de l'agent tourne."""
        provider = get_ai_provider(api_key="cache-key", config=AIProviderConfig(enabled=True))
        assert provider.config.enabled is True
        same_provider = get_ai_provider(api_key="cache-key", config=AIProviderConfig(enabled=False))
        assert same_provider is provider
        assert same_provider.config.enabled is False
        with pytest.raises(AIProviderError, match="disabled"):
            same_provider.structured_complete(prompt="p", schema=SCHEMA)
