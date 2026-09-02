"""B12 — CRUD d'instances de stratégie (§8.3 : une `Strategy` créée par un
utilisateur à partir d'une `StrategyDefinition` du registre B11). Schéma DB
déjà posé en B03 — cette brique construit le comportement dessus, même
principe que B06 pour les contextes d'exécution.

Limites produit (§8.4 de la spec, citées dans AVANCEMENT.md B12) :
**5 stratégies enregistrées (fixe), stratégies actives et symboles cumulés
profil-dépendants depuis B30** (`app/profile_limits.py::PROFILE_LIMITS`,
1/2/3 actives et 2/5/10 symboles selon novice/intermediate/expert). Le
plafond d'enregistrement (5) reste volontairement fixe et hors grille de
profil — la checklist B30 ne le mentionne pas, seule "limite de stratégies
ACTIVES selon profil" est demandée ; en faire une limite par profil aurait
été une extension de périmètre non demandée.

Toutes les limites sont appliquées **par contexte d'exécution** (Paper et
Replay ont chacun leur propre budget), cohérent avec le principe
d'isolation totale entre contextes déjà établi en B06 (`Strategy` hérite de
`ExecutionContextMixin`) — la spec ne précisait pas explicitement ce point,
lecture la plus prudente retenue plutôt qu'un pool global ambigu."""

from __future__ import annotations

import importlib
import uuid
from typing import Any

import jsonschema
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Strategy, StrategyDefinition, User
from .profile_limits import limits_for

MAX_SAVED_STRATEGIES = 5

# §B30 — anciennes constantes fixes CONSERVÉES (plutôt que supprimées) :
# elles restent le point de référence documenté dans AVANCEMENT.md/les
# tests existants pour la borne haute ("expert"), et
# `workers/risk_engine/main.py` les duplique explicitement à ces mêmes
# valeurs comme garde-fou non profil-aware (voir docstring de
# `profile_limits.py`) — les faire disparaître aurait cassé cette référence
# partagée pour un gain nul, la vraie limite appliquée passe désormais par
# `_active_limit_for`/`_symbol_limit_for` ci-dessous.
MAX_ACTIVE_STRATEGIES = 3
MAX_CUMULATIVE_SYMBOLS = 10


def _active_limit_for(user: User) -> int:
    return limits_for(user.experience_profile)["max_active_strategies"]


def _symbol_limit_for(user: User) -> int:
    return limits_for(user.experience_profile)["max_symbols"]

# §8.3 "Lifecycle : DRAFT → READY → ACTIVE → PAUSED → STOPPED (↘ ERROR)".
# V1 simplifie : `create_instance` exige des paramètres déjà complets et
# valides (JSON Schema + validation croisée propre à la stratégie), donc va
# directement en READY — pas de flux "brouillon incrémental" (aucun
# formulaire dynamique construit dans cette brique, voir limites honnêtes
# du journal AVANCEMENT.md). DRAFT reste dans le modèle pour un futur
# formulaire multi-étapes (B25+), pas produit par ce module aujourd'hui.
STATUS_DRAFT = "DRAFT"
STATUS_READY = "READY"
STATUS_ACTIVE = "ACTIVE"
STATUS_PAUSED = "PAUSED"
STATUS_STOPPED = "STOPPED"
STATUS_ERROR = "ERROR"

# STOPPED is a deliberate terminal state for the current run, not for the
# strategy definition: a user must be able to restart the same configured
# strategy after pressing Stop.
_ACTIVATABLE_FROM = {STATUS_READY, STATUS_PAUSED, STATUS_STOPPED}
_EDITABLE_FROM = {STATUS_DRAFT, STATUS_READY, STATUS_PAUSED, STATUS_STOPPED}


class StrategyInstanceError(Exception):
    """Base — jamais levée directement, voir les sous-classes ci-dessous."""


class StrategyDefinitionNotFound(StrategyInstanceError):
    def __init__(self, type_code: str) -> None:
        self.type_code = type_code
        super().__init__(f"définition de stratégie inconnue ou inactive : {type_code!r}")


class StrategyInstanceNotFound(StrategyInstanceError):
    def __init__(self, instance_id: uuid.UUID) -> None:
        self.instance_id = instance_id
        super().__init__(f"instance de stratégie introuvable : {instance_id}")


class StrategyParametersInvalid(StrategyInstanceError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors) or "paramètres invalides")


class StrategyLimitExceeded(StrategyInstanceError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class StrategyInvalidTransition(StrategyInstanceError):
    def __init__(self, current_status: str, action: str) -> None:
        self.current_status = current_status
        self.action = action
        super().__init__(f"transition {action!r} impossible depuis le statut {current_status!r}")


class StrategyDeletionBlocked(StrategyInstanceError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)


def _normalize_symbols(symbols: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for raw in symbols or []:
        symbol = (raw or "").strip().upper()
        if symbol:
            seen[symbol] = None  # dict = dédoublonnage en préservant l'ordre
    return list(seen)


def _cross_field_validation_errors(type_code: str, parameters: dict[str, Any]) -> list[str]:
    """Appelle `strategies.<type_code>.engine.validate_parameters()` si le
    module de stratégie en expose une (§B12 "Validation short period <
    long period" pour Moving Average Crossover, par ex.) — hook optionnel :
    une stratégie sans cette fonction n'est pas bloquée, seule la
    validation JSON Schema du Strategy Registry (B11) s'applique alors."""
    try:
        module = importlib.import_module(f"strategies.{type_code}.engine")
    except ImportError:
        return []
    validate_fn = getattr(module, "validate_parameters", None)
    if validate_fn is None:
        return []
    try:
        return list(validate_fn(parameters))
    except Exception as exc:  # noqa: BLE001 — ne doit jamais faire planter la requête
        return [f"validate_parameters() de {type_code!r} a levé une exception inattendue : {exc}"]


def _validate_parameters_or_raise(definition: StrategyDefinition, parameters: dict[str, Any]) -> None:
    try:
        jsonschema.validate(instance=parameters, schema=definition.parameter_schema)
    except jsonschema.exceptions.ValidationError as exc:
        raise StrategyParametersInvalid([f"paramètres non conformes au schéma : {exc.message}"]) from exc

    cross_field_errors = _cross_field_validation_errors(definition.type_code, parameters)
    if cross_field_errors:
        raise StrategyParametersInvalid(cross_field_errors)


def _get_active_definition(db: Session, type_code: str) -> StrategyDefinition:
    definition = db.execute(
        select(StrategyDefinition).where(
            StrategyDefinition.type_code == type_code, StrategyDefinition.is_active.is_(True)
        )
    ).scalar_one_or_none()
    if definition is None:
        raise StrategyDefinitionNotFound(type_code)
    return definition


def _get_owned_instance(db: Session, user: User, execution_context_id: uuid.UUID, instance_id: uuid.UUID) -> Strategy:
    instance = db.execute(
        select(Strategy).where(
            Strategy.id == instance_id,
            Strategy.user_id == user.id,
            Strategy.execution_context_id == execution_context_id,
        )
    ).scalar_one_or_none()
    if instance is None:
        raise StrategyInstanceNotFound(instance_id)
    return instance


def _enforce_saved_limit(db: Session, user: User, execution_context_id: uuid.UUID) -> None:
    count = db.execute(
        select(Strategy).where(
            Strategy.user_id == user.id, Strategy.execution_context_id == execution_context_id
        )
    ).scalars().all()
    if len(count) >= MAX_SAVED_STRATEGIES:
        raise StrategyLimitExceeded(
            f"limite de {MAX_SAVED_STRATEGIES} stratégies enregistrées atteinte pour ce contexte"
        )


def _enforce_symbol_limit(
    db: Session, user: User, execution_context_id: uuid.UUID, new_symbols: list[str], *, exclude_instance_id=None
) -> None:
    existing = db.execute(
        select(Strategy).where(
            Strategy.user_id == user.id, Strategy.execution_context_id == execution_context_id
        )
    ).scalars().all()
    cumulative: set[str] = set()
    for row in existing:
        if exclude_instance_id is not None and row.id == exclude_instance_id:
            continue
        cumulative.update(row.symbols or [])
    cumulative.update(new_symbols)
    # §B30 — plafond dépendant du profil de l'utilisateur (voir
    # `_symbol_limit_for` ci-dessus) plutôt que la constante fixe
    # `MAX_CUMULATIVE_SYMBOLS` (conservée pour `workers/risk_engine`,
    # jamais utilisée directement ici depuis B30).
    limit = _symbol_limit_for(user)
    if len(cumulative) > limit:
        raise StrategyLimitExceeded(
            f"limite de {limit} symboles cumulés dépassée pour ce contexte (profil {user.experience_profile!r}) "
            f"({len(cumulative)} avec cette stratégie)"
        )


def _enforce_active_limit(db: Session, user: User, execution_context_id: uuid.UUID) -> None:
    active = db.execute(
        select(Strategy).where(
            Strategy.user_id == user.id,
            Strategy.execution_context_id == execution_context_id,
            Strategy.status == STATUS_ACTIVE,
        )
    ).scalars().all()
    limit = _active_limit_for(user)
    if len(active) >= limit:
        raise StrategyLimitExceeded(
            f"limite de {limit} stratégie(s) active(s) atteinte pour ce contexte (profil {user.experience_profile!r})"
        )


def create_instance(
    db: Session,
    user: User,
    execution_context_id: uuid.UUID,
    *,
    type_code: str,
    name: str,
    symbols: list[str],
    parameters: dict[str, Any],
    risk_configuration: dict[str, Any] | None = None,
) -> Strategy:
    definition = _get_active_definition(db, type_code)
    normalized_symbols = _normalize_symbols(symbols)
    if not normalized_symbols:
        raise StrategyParametersInvalid(["au moins un symbole est requis"])
    _validate_parameters_or_raise(definition, parameters)

    _enforce_saved_limit(db, user, execution_context_id)
    _enforce_symbol_limit(db, user, execution_context_id, normalized_symbols)

    instance = Strategy(
        user_id=user.id,
        execution_context_id=execution_context_id,
        strategy_definition_id=definition.id,
        name=name,
        definition_version=definition.version,
        parameters=parameters,
        symbols=normalized_symbols,
        risk_configuration=risk_configuration or {},
        status=STATUS_READY,
    )
    db.add(instance)
    db.commit()
    db.refresh(instance)
    return instance


def list_instances(db: Session, user: User, execution_context_id: uuid.UUID) -> list[Strategy]:
    return list(
        db.execute(
            select(Strategy)
            .where(Strategy.user_id == user.id, Strategy.execution_context_id == execution_context_id)
            .order_by(Strategy.created_at.desc())
        )
        .scalars()
        .all()
    )


def get_instance(db: Session, user: User, execution_context_id: uuid.UUID, instance_id: uuid.UUID) -> Strategy:
    return _get_owned_instance(db, user, execution_context_id, instance_id)


def update_instance(
    db: Session,
    user: User,
    execution_context_id: uuid.UUID,
    instance_id: uuid.UUID,
    *,
    name: str | None = None,
    symbols: list[str] | None = None,
    parameters: dict[str, Any] | None = None,
    risk_configuration: dict[str, Any] | None = None,
) -> Strategy:
    instance = _get_owned_instance(db, user, execution_context_id, instance_id)
    if instance.status not in _EDITABLE_FROM:
        raise StrategyInvalidTransition(instance.status, "update")

    definition = db.get(StrategyDefinition, instance.strategy_definition_id)
    effective_parameters = parameters if parameters is not None else instance.parameters
    effective_symbols = _normalize_symbols(symbols) if symbols is not None else instance.symbols
    if not effective_symbols:
        raise StrategyParametersInvalid(["au moins un symbole est requis"])
    _validate_parameters_or_raise(definition, effective_parameters)
    if symbols is not None:
        _enforce_symbol_limit(
            db, user, execution_context_id, effective_symbols, exclude_instance_id=instance.id
        )

    if name is not None:
        instance.name = name
    instance.symbols = effective_symbols
    instance.parameters = effective_parameters
    if risk_configuration is not None:
        instance.risk_configuration = risk_configuration

    db.commit()
    db.refresh(instance)
    return instance


def clone_instance(
    db: Session, user: User, execution_context_id: uuid.UUID, instance_id: uuid.UUID, *, new_name: str | None = None
) -> Strategy:
    original = _get_owned_instance(db, user, execution_context_id, instance_id)

    _enforce_saved_limit(db, user, execution_context_id)
    _enforce_symbol_limit(db, user, execution_context_id, original.symbols)

    clone = Strategy(
        user_id=user.id,
        execution_context_id=execution_context_id,
        strategy_definition_id=original.strategy_definition_id,
        name=new_name or f"{original.name} (copie)",
        definition_version=original.definition_version,
        parameters=dict(original.parameters),
        symbols=list(original.symbols),
        risk_configuration=dict(original.risk_configuration),
        status=STATUS_READY,  # §B12 "Cloner avec nouvel UUID" — la copie démarre toujours inactive
        cloned_from_id=original.id,
    )
    db.add(clone)
    db.commit()
    db.refresh(clone)
    return clone


def activate_instance(db: Session, user: User, execution_context_id: uuid.UUID, instance_id: uuid.UUID) -> Strategy:
    instance = _get_owned_instance(db, user, execution_context_id, instance_id)
    if instance.status not in _ACTIVATABLE_FROM:
        raise StrategyInvalidTransition(instance.status, "activate")

    _enforce_active_limit(db, user, execution_context_id)

    instance.status = STATUS_ACTIVE
    db.commit()
    db.refresh(instance)
    return instance


def pause_instance(db: Session, user: User, execution_context_id: uuid.UUID, instance_id: uuid.UUID) -> Strategy:
    instance = _get_owned_instance(db, user, execution_context_id, instance_id)
    if instance.status != STATUS_ACTIVE:
        raise StrategyInvalidTransition(instance.status, "pause")

    instance.status = STATUS_PAUSED
    db.commit()
    db.refresh(instance)
    return instance


def stop_instance(db: Session, user: User, execution_context_id: uuid.UUID, instance_id: uuid.UUID) -> Strategy:
    instance = _get_owned_instance(db, user, execution_context_id, instance_id)
    if instance.status not in {STATUS_ACTIVE, STATUS_PAUSED, STATUS_READY, STATUS_DRAFT}:
        raise StrategyInvalidTransition(instance.status, "stop")

    instance.status = STATUS_STOPPED
    db.commit()
    db.refresh(instance)
    return instance


def delete_instance(db: Session, user: User, execution_context_id: uuid.UUID, instance_id: uuid.UUID) -> None:
    """§B12 "Supprimer si inactive" — refuse explicitement si `ACTIVE`.
    Une stratégie déjà liée à un historique réel (`StrategyRun`, clones,
    ordres) est protégée par les contraintes FK elles-mêmes (aucun
    `ondelete=CASCADE` déclaré en B03) : la suppression échoue alors avec
    une erreur d'intégrité, remontée ici comme un conflit clair plutôt que
    de perdre silencieusement de l'historique."""
    instance = _get_owned_instance(db, user, execution_context_id, instance_id)
    if instance.status == STATUS_ACTIVE:
        raise StrategyInvalidTransition(instance.status, "delete")

    from sqlalchemy.exc import IntegrityError

    db.delete(instance)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise StrategyDeletionBlocked(
            "impossible de supprimer : liée à des exécutions ou des ordres existants"
        ) from exc
