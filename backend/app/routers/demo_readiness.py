"""Authenticated, non-transactional Paper demo readiness checks.

The hackathon demonstration needs an operator-visible answer to “can I safely
activate an existing options strategy now?”.  This router deliberately stays
outside the order path: its only external broker action is a read-only
``GET /v2/account`` using already-encrypted credentials.  It has no request
fields, no order client and no live-trading configuration path.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shared.risk_governance import get_trading_kill_switch_engaged

from ..alpaca_client import AlpacaAuthError, AlpacaClient, AlpacaError, AlpacaUpstreamError
from ..auth import get_current_user
from ..config import settings
from ..db import get_db
from ..encryption import decrypt_secret
from ..models import Asset, ProviderAsset, TradingProvider, User, UserTradingAccount
from ..redis_client import redis_client
from ..schemas.demo_readiness import PaperDemoReadinessOut

router = APIRouter(prefix="/api/demo-readiness", tags=["demo-readiness"])

_PREFLIGHT_METADATA_KEY = "paper_preflight"
_MCP_HEALTH_PREFIX = "mcp:session:health:"
_MCP_STATUSES = {"STARTING", "HEALTHY", "RECONNECTING", "STOPPED"}
_PREFLIGHT_STATUSES = {"NOT_RUN", "VERIFIED", "AUTH_FAILED", "UNREACHABLE"}


def _paper_url_is_locked() -> bool:
    """Accept only the official HTTPS Paper endpoint, never a live host."""
    parsed = urlparse(settings.alpaca_paper_base_url)
    return parsed.scheme == "https" and parsed.hostname == "paper-api.alpaca.markets"


def _alpaca_account(db: Session, user: User) -> UserTradingAccount | None:
    provider = db.execute(select(TradingProvider).where(TradingProvider.code == "alpaca")).scalar_one_or_none()
    if provider is None:
        return None
    return db.execute(
        select(UserTradingAccount).where(
            UserTradingAccount.user_id == user.id,
            UserTradingAccount.trading_provider_id == provider.id,
        )
    ).scalar_one_or_none()


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _preflight_state(account: UserTradingAccount | None) -> tuple[str, datetime | None]:
    if account is None:
        return "NOT_CONFIGURED", None
    raw = (account.metadata_json or {}).get(_PREFLIGHT_METADATA_KEY)
    if not isinstance(raw, dict):
        return "NOT_RUN", None
    status = raw.get("status")
    return (status if status in _PREFLIGHT_STATUSES else "NOT_RUN"), _parse_timestamp(raw.get("checked_at"))


def _mcp_session_status(account: UserTradingAccount | None) -> str:
    if account is None:
        return "NOT_STARTED"
    try:
        raw = redis_client.get(_MCP_HEALTH_PREFIX + str(account.id))
        if raw is None:
            return "NOT_STARTED"
        if isinstance(raw, bytes):
            raw = raw.decode()
        payload = json.loads(raw)
        status = payload.get("status") if isinstance(payload, dict) else None
        return status if status in _MCP_STATUSES else "UNKNOWN"
    except Exception:  # noqa: BLE001 - readiness must not claim a healthy MCP when Redis is unavailable
        return "UNKNOWN"


def _option_catalog_status(db: Session, account: UserTradingAccount | None) -> tuple[int, datetime | None]:
    if account is None:
        return 0, None
    count = db.scalar(
        select(func.count())
        .select_from(Asset)
        .join(ProviderAsset, ProviderAsset.asset_id == Asset.id)
        .where(
            ProviderAsset.provider_id == account.trading_provider_id,
            Asset.asset_type == "option",
            Asset.status == "active",
            ProviderAsset.status == "active",
            ProviderAsset.tradable.is_(True),
        )
    )
    sync_values = (account.metadata_json or {}).get("options_last_synced")
    timestamps = [_parse_timestamp(value) for value in sync_values.values()] if isinstance(sync_values, dict) else []
    valid_timestamps = [value for value in timestamps if value is not None]
    return int(count or 0), max(valid_timestamps) if valid_timestamps else None


def _kill_switch_status() -> str:
    try:
        return "ENGAGED" if get_trading_kill_switch_engaged(redis_client, default=False) else "DISENGAGED"
    except Exception:  # noqa: BLE001 - unknown must never be shown as trading-ready
        return "UNKNOWN"


def _response(db: Session, user: User) -> PaperDemoReadinessOut:
    account = _alpaca_account(db, user)
    account_configured = bool(account and account.encrypted_api_key and account.encrypted_secret_key)
    account_connected = bool(
        account_configured and account and account.environment == "paper" and account.status == "connected"
    )
    paper_connection_status, checked_at = _preflight_state(account)
    if not account_configured:
        paper_connection_status, checked_at = "NOT_CONFIGURED", None
    option_count, options_last_synced_at = _option_catalog_status(db, account)
    mcp_status = _mcp_session_status(account)
    kill_switch_status = _kill_switch_status()
    paper_url_locked = _paper_url_is_locked()
    ready = bool(
        account_connected
        and paper_url_locked
        and paper_connection_status == "VERIFIED"
        and mcp_status == "HEALTHY"
        and option_count > 0
        and kill_switch_status == "DISENGAGED"
    )
    return PaperDemoReadinessOut(
        account_configured=account_configured,
        account_connected=account_connected,
        paper_url_locked=paper_url_locked,
        paper_connection_status=paper_connection_status,
        paper_connection_checked_at=checked_at,
        mcp_session_status=mcp_status,
        active_option_contract_count=option_count,
        options_last_synced_at=options_last_synced_at,
        trading_kill_switch_status=kill_switch_status,
        ready_for_paper_demo=ready,
    )


def _record_preflight(db: Session, account: UserTradingAccount, *, status: str) -> None:
    metadata = dict(account.metadata_json or {})
    metadata[_PREFLIGHT_METADATA_KEY] = {
        "status": status,
        "checked_at": datetime.now(UTC).isoformat(),
        # Publicly document the probe without retaining the broker response.
        "operation": "GET /v2/account",
    }
    account.metadata_json = metadata
    db.commit()


@router.get("", response_model=PaperDemoReadinessOut)
def get_demo_readiness(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> PaperDemoReadinessOut:
    return _response(db, user)


@router.post("/paper-preflight", response_model=PaperDemoReadinessOut)
def run_paper_preflight(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> PaperDemoReadinessOut:
    """Verify stored Paper credentials with GET /v2/account only.

    This endpoint accepts no key material and imports no order functionality.
    It records a sanitised result for the authenticated readiness panel, then
    returns the same panel state.  No Alpaca response payload is persisted.
    """
    account = _alpaca_account(db, user)
    if (
        account is None
        or account.environment != "paper"
        or account.status != "connected"
        or not account.encrypted_api_key
        or not account.encrypted_secret_key
        or not _paper_url_is_locked()
    ):
        if account is not None:
            _record_preflight(db, account, status="NOT_RUN")
        return _response(db, user)

    try:
        client = AlpacaClient(
            decrypt_secret(account.encrypted_api_key),
            decrypt_secret(account.encrypted_secret_key),
        )
        # The only broker operation in this Phase: a read-only account GET.
        client.get_account()
    except AlpacaAuthError:
        _record_preflight(db, account, status="AUTH_FAILED")
    except (AlpacaUpstreamError, AlpacaError, ValueError):
        _record_preflight(db, account, status="UNREACHABLE")
    except Exception:  # noqa: BLE001 - never disclose decryption/provider internals to the browser
        _record_preflight(db, account, status="UNREACHABLE")
    else:
        _record_preflight(db, account, status="VERIFIED")
    return _response(db, user)
