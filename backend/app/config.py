"""Configuration centralisée (lue depuis les variables d'environnement, voir
.env.example à la racine). Un seul objet `settings` importé partout — pas de
`os.environ.get()` dispersé dans le code (facilite l'audit des secrets, B32)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    app_name: str = "zikosofttrader-ai"

    demo_user_email: str = "demo@zikosofttrader.local"
    demo_user_password: str = "demo"
    # Affiche les identifiants démo via GET /api/auth/demo-credentials (B05) —
    # pratique pour un jury de hackathon, à désactiver si l'environnement
    # déployé doit être davantage durci (B38/B32).
    demo_credentials_visible: bool = True

    database_url: str = "postgresql+psycopg://zikosofttrader:zikosofttrader@localhost:5432/zikosofttrader"

    redis_url: str = "redis://localhost:6379/0"

    # Vide par défaut : une clé absente doit faire échouer explicitement tout
    # chiffrement/déchiffrement (§B08 "Tester clé de chiffrement absente"),
    # jamais stocker un secret en clair par accident. Chaque environnement
    # doit générer sa propre clé Fernet dans son `.env` ; aucune clé générée
    # ne doit être versionnée dans `.env.example`.
    app_encryption_key: str = ""

    # --- Alpaca (B07) ---
    # V1 : Paper uniquement, verrouillé (§B07 "Mode Paper verrouillé") — pas
    # de variable pour basculer vers l'API live, intentionnellement.
    alpaca_paper_base_url: str = "https://paper-api.alpaca.markets"
    # Alpaca market-data host used for option-chain snapshots. Trading and
    # account calls remain locked to the Paper Trading API above.
    alpaca_data_base_url: str = "https://data.alpaca.markets"
    alpaca_request_timeout_seconds: float = 10.0

    ai_provider: str = "claude"
    anthropic_api_key: str = ""
    ai_model_high_stakes: str = "claude-sonnet-4-5"
    ai_model_low_stakes: str = "claude-haiku-4-5"
    ai_max_calls_per_minute: int = 30
    ai_max_calls_per_day: int = 50
    ai_temperature: float = 0.2
    ai_max_tokens: int = 1024
    ai_timeout_seconds: float = 20.0
    ai_daily_budget_usd: float = Field(default=2.0, ge=0.0, le=10_000.0)
    # Plafond de déploiement : il ne transite jamais dans une requête de mise
    # à jour et ne peut donc pas être augmenté depuis Settings. L'opérateur
    # le modifie exclusivement dans `.env`, puis redémarre les services.
    ai_daily_budget_hard_cap_usd: float = Field(default=10.0, gt=0.0, le=10_000.0)
    ai_calls_enabled: bool = True

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    gtm_container_id: str = ""
    ga_measurement_id: str = ""

    heartbeat_interval_seconds: int = 5
    heartbeat_ttl_seconds: int = 15

    # --- Authentification locale (B05) ---
    session_ttl_hours: int = 12
    session_cookie_name: str = "zikosoft_session"
    login_rate_limit_max_attempts: int = 5
    login_rate_limit_window_seconds: int = 60

    # --- Portefeuille (B18) ---
    # Cache Redis court sur les lectures les plus fréquentes (résumé,
    # positions) — voir routers/portfolio.py. `<= 0` désactive le cache
    # (utile pour les tests, qui veulent voir chaque écriture immédiatement
    # sans attendre l'expiration d'une clé posée par un test précédent).
    portfolio_cache_ttl_seconds: float = 5.0

    # --- Replay Engine (B19, Étape A) ---
    # Chemin du dataset fixe (voir scripts/fetch_replay_dataset.py et
    # shared/shared/replay_market_data.py::DEFAULT_REPLAY_DATASET_PATH pour
    # le défaut réel si laissé vide ici).
    replay_dataset_path: str = ""


settings = Settings()
