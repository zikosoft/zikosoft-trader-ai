"""Orchestrateur de l'onboarding Alpaca (B07) — pipeline à 8 étapes
persistantes, reprenable, idempotent (`OnboardingStep`, schéma depuis B03).

Chaque étape est un enregistrement en base (`PENDING -> RUNNING ->
COMPLETED` ou `FAILED`) — pas un état en mémoire. Rejouer `run_pipeline`
saute toute étape déjà `COMPLETED` et s'arrête net à la première étape qui
échoue : les étapes suivantes ne sont jamais tentées tant que leur
dépendance n'est pas `COMPLETED` (§B07 "Empêcher l'exécution des étapes
dépendantes"). C'est ce mécanisme unique qui sert à la fois le premier
"Connect & Verify", le bouton "Retry this step" (rejouer sans refournir les
clés — déjà chiffrées en base) et, après `reset_pipeline`, "Restart complete
setup".

Étapes réelles (1-4) vs. étapes stub (5-8, dépendent de briques qui
n'existent pas encore — B09, B10) : voir `_STUBBED_STEPS`. Même principe que
B02 déclarant les 15 services Docker dès le jour 1 avant d'avoir de la
logique métier — le pipeline complet existe et est démontrable, sans
prétendre que les systèmes correspondants tournent déjà."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import assets as assets_service
from .alpaca_client import AlpacaAuthError, AlpacaClient, AlpacaError, AlpacaUpstreamError
from .config import settings
from .context import ensure_user_contexts
from .encryption import CURRENT_KEY_VERSION, decrypt_secret, encrypt_secret
from .models import OnboardingStep, PortfolioSnapshot, TradingProvider, User, UserTradingAccount

STEP_CODES: tuple[str, ...] = (
    "credentials_validated",
    "paper_environment_confirmed",
    "account_synchronized",
    "portfolio_loaded",
    "assets_synchronized",
    "market_stream_established",
    "mcp_session_initialized",
    "ai_agents_ready",
)

# Étapes dont la vraie logique arrive avec une brique future — voir
# docstring du module. Marquées COMPLETED avec une note explicite dans
# `error_details` (réutilisé comme canal de note, pas une erreur) plutôt que
# de simuler un vrai travail.
_STUBBED_STEPS: dict[str, str] = {
    "market_stream_established": "stub — B10 (Market Agent/MCP) pas encore implémenté",
    "mcp_session_initialized": "stub — B10 (session MCP) pas encore implémenté",
    "ai_agents_ready": "stub — B10 (agents IA) pas encore implémentés",
}


class OnboardingStepFailed(Exception):
    def __init__(self, step_code: str, message: str, *, retriable: bool = True) -> None:
        self.step_code = step_code
        self.message = message
        self.retriable = retriable
        super().__init__(message)


def _get_or_create_account(db: Session, user: User) -> UserTradingAccount:
    provider = db.execute(
        select(TradingProvider).where(TradingProvider.code == "alpaca")
    ).scalar_one()
    account = db.execute(
        select(UserTradingAccount).where(
            UserTradingAccount.user_id == user.id,
            UserTradingAccount.trading_provider_id == provider.id,
        )
    ).scalar_one_or_none()
    if account is None:
        account = UserTradingAccount(
            user_id=user.id,
            trading_provider_id=provider.id,
            environment="paper",
            status="pending",
        )
        db.add(account)
        db.flush()
    return account


def _ensure_steps(db: Session, account: UserTradingAccount) -> dict[str, OnboardingStep]:
    rows = (
        db.execute(
            select(OnboardingStep).where(
                OnboardingStep.user_trading_account_id == account.id
            )
        )
        .scalars()
        .all()
    )
    by_code = {row.step_code: row for row in rows}
    for code in STEP_CODES:
        if code not in by_code:
            row = OnboardingStep(
                user_id=account.user_id,
                user_trading_account_id=account.id,
                step_code=code,
                status="PENDING",
            )
            db.add(row)
            db.flush()
            by_code[code] = row
    return by_code


def _mark_running(step: OnboardingStep) -> None:
    step.status = "RUNNING"
    step.started_at = datetime.now(UTC)
    step.error_details = None


def _mark_completed(step: OnboardingStep, *, note: str | None = None) -> None:
    step.status = "COMPLETED"
    step.completed_at = datetime.now(UTC)
    step.error_details = {"note": note} if note else None


def _mark_failed(step: OnboardingStep, message: str, *, retriable: bool) -> None:
    step.status = "FAILED"
    step.error_details = {"message": message, "retriable": retriable}


def run_pipeline(
    db: Session,
    user: User,
    *,
    api_key: str | None = None,
    secret_key: str | None = None,
    alpaca_client_factory: type[AlpacaClient] = AlpacaClient,
) -> UserTradingAccount:
    """Exécute (ou reprend) le pipeline pour `user`. `api_key`/`secret_key`
    ne sont nécessaires que si l'étape `credentials_validated` n'est pas
    encore `COMPLETED` — une reprise normale n'a pas besoin de les
    refournir, ils restent chiffrés en base après le premier succès."""
    account = _get_or_create_account(db, user)
    steps = _ensure_steps(db, account)

    for code in STEP_CODES:
        step = steps[code]
        if step.status == "COMPLETED":
            continue

        _mark_running(step)
        db.flush()

        try:
            if code in _STUBBED_STEPS:
                _mark_completed(step, note=_STUBBED_STEPS[code])
            else:
                _run_real_step(
                    db,
                    user,
                    account,
                    code,
                    api_key=api_key,
                    secret_key=secret_key,
                    client_factory=alpaca_client_factory,
                )
                _mark_completed(step)
        except OnboardingStepFailed as exc:
            _mark_failed(step, exc.message, retriable=exc.retriable)
            db.flush()
            account.status = "failed"
            return account

        db.flush()

    account.status = "connected"
    return account


def _run_real_step(
    db: Session,
    user: User,
    account: UserTradingAccount,
    code: str,
    *,
    api_key: str | None,
    secret_key: str | None,
    client_factory: type[AlpacaClient],
) -> None:
    if code == "credentials_validated":
        if not api_key or not secret_key:
            raise OnboardingStepFailed(
                code, "Clé API et clé secrète requises.", retriable=False
            )
        client = client_factory(api_key, secret_key)
        try:
            client.get_account()
        except AlpacaAuthError as exc:
            raise OnboardingStepFailed(code, "Identifiants Alpaca invalides.") from exc
        except AlpacaUpstreamError as exc:
            raise OnboardingStepFailed(code, f"Alpaca injoignable : {exc}") from exc
        # Persisté (chiffré) seulement après validation réussie — jamais une
        # clé prouvée invalide, même chiffrée (§B07 "clé valide enregistrée
        # chiffrée").
        account.encrypted_api_key = encrypt_secret(api_key)
        account.encrypted_secret_key = encrypt_secret(secret_key)
        account.encryption_key_version = CURRENT_KEY_VERSION

    elif code == "paper_environment_confirmed":
        # V1 : Paper verrouillé au niveau du client (base_url figée, pas de
        # variable pour basculer vers l'API live — voir alpaca_client.py).
        # Vérification réelle, pas un simple pass : détecte toute
        # mauvaise configuration qui pointerait vers l'API live.
        if "paper-api" not in settings.alpaca_paper_base_url:
            raise OnboardingStepFailed(
                code,
                "Configuration invalide : l'URL Alpaca configurée ne pointe pas vers Paper.",
                retriable=False,
            )

    elif code == "account_synchronized":
        client = _decrypted_client(account, client_factory)
        try:
            alpaca_account = client.get_account()
        except AlpacaError as exc:
            raise OnboardingStepFailed(code, f"synchronisation du compte échouée : {exc}") from exc
        account.external_account_id = alpaca_account.id
        account.metadata_json = {
            **account.metadata_json,
            "alpaca_status": alpaca_account.status,
            "alpaca_currency": alpaca_account.currency,
        }
        account.last_synced_at = datetime.now(UTC)

    elif code == "portfolio_loaded":
        client = _decrypted_client(account, client_factory)
        try:
            alpaca_account = client.get_account()
        except AlpacaError as exc:
            raise OnboardingStepFailed(code, f"chargement du portefeuille échoué : {exc}") from exc
        contexts = ensure_user_contexts(db, user)
        paper_context_id = contexts["PAPER"].id
        # Append-only par design (`PortfolioSnapshot` = photo périodique,
        # voir son docstring) : une nouvelle ligne à chaque succès de cette
        # étape est le comportement attendu, pas une violation
        # d'idempotence — l'idempotence exigée par B07 porte sur l'absence
        # d'effet de bord destructeur/dupliqué (ex. pas de double compte
        # créé), pas sur "zéro nouvelle ligne".
        db.add(
            PortfolioSnapshot(
                user_id=user.id,
                execution_context_id=paper_context_id,
                cash=float(alpaca_account.cash),
                buying_power=float(alpaca_account.buying_power),
                portfolio_value=float(alpaca_account.portfolio_value),
                raw_provider_payload={
                    "id": alpaca_account.id,
                    "account_number": alpaca_account.account_number,
                    "status": alpaca_account.status,
                    "currency": alpaca_account.currency,
                },
                snapshot_at=datetime.now(UTC),
            )
        )

    elif code == "assets_synchronized":
        # §B09 — même client que les étapes précédentes (clés déjà
        # persistées à `credentials_validated`), aucune ré-authentification
        # nécessaire. `AssetSyncError` enveloppe déjà toute `AlpacaError`
        # (voir assets.py) — reconverti ici en `OnboardingStepFailed`, même
        # principe que `account_synchronized`/`portfolio_loaded` ci-dessus.
        try:
            assets_service.sync_assets(db, account, client_factory=client_factory)
        except assets_service.AssetSyncError as exc:
            raise OnboardingStepFailed(code, f"synchronisation du catalogue échouée : {exc}") from exc

    else:  # pragma: no cover — defensive, tous les codes réels sont listés ci-dessus
        raise AssertionError(f"étape réelle non gérée : {code!r}")


def _decrypted_client(
    account: UserTradingAccount, client_factory: type[AlpacaClient]
) -> AlpacaClient:
    return client_factory(
        decrypt_secret(account.encrypted_api_key), decrypt_secret(account.encrypted_secret_key)
    )


def get_status(db: Session, user: User) -> tuple[UserTradingAccount | None, list[OnboardingStep]]:
    provider = db.execute(
        select(TradingProvider).where(TradingProvider.code == "alpaca")
    ).scalar_one()
    account = db.execute(
        select(UserTradingAccount).where(
            UserTradingAccount.user_id == user.id,
            UserTradingAccount.trading_provider_id == provider.id,
        )
    ).scalar_one_or_none()
    if account is None:
        return None, []
    steps = (
        db.execute(
            select(OnboardingStep)
            .where(OnboardingStep.user_trading_account_id == account.id)
            .order_by(OnboardingStep.created_at)
        )
        .scalars()
        .all()
    )
    # Ordre stable = ordre du pipeline (STEP_CODES), pas l'ordre de création
    # en base (les deux coïncident normalement, mais on ne veut pas dépendre
    # d'un détail d'implémentation pour l'affichage).
    steps_by_code = {s.step_code: s for s in steps}
    ordered = [steps_by_code[code] for code in STEP_CODES if code in steps_by_code]
    return account, ordered


def reset_pipeline(db: Session, user: User) -> None:
    """§B07 "Restart complete setup" — remet toutes les étapes à zéro et
    efface les identifiants stockés (l'utilisateur doit resaisir ses clés,
    potentiellement différentes). Ne supprime pas les `PortfolioSnapshot`
    déjà écrits (historique, pas un artefact d'onboarding à effacer)."""
    account, steps = get_status(db, user)
    if account is None:
        return
    for step in steps:
        step.status = "PENDING"
        step.started_at = None
        step.completed_at = None
        step.error_details = None
    account.status = "pending"
    account.encrypted_api_key = None
    account.encrypted_secret_key = None
    account.external_account_id = None
    account.last_synced_at = None
    db.flush()
