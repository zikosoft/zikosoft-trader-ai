"""Read-only Paper demo readiness contracts.

The status is intentionally separate from the trading/order contracts: it is
only a checklist and a non-transactional broker connectivity probe.  It never
accepts credentials and it cannot create, modify, or cancel an order.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


PaperConnectionStatus = Literal[
    "NOT_CONFIGURED",
    "NOT_RUN",
    "VERIFIED",
    "AUTH_FAILED",
    "UNREACHABLE",
]
McpReadinessStatus = Literal["NOT_STARTED", "STARTING", "HEALTHY", "RECONNECTING", "STOPPED", "UNKNOWN"]
KillSwitchReadinessStatus = Literal["DISENGAGED", "ENGAGED", "UNKNOWN"]


class PaperDemoReadinessOut(BaseModel):
    """Sanitised, authenticated readiness for the Paper options demo."""

    account_configured: bool
    account_connected: bool
    paper_url_locked: bool
    paper_connection_status: PaperConnectionStatus
    paper_connection_checked_at: datetime | None
    mcp_session_status: McpReadinessStatus
    active_option_contract_count: int
    options_last_synced_at: datetime | None
    trading_kill_switch_status: KillSwitchReadinessStatus
    ready_for_paper_demo: bool
    non_transactional: bool = True
