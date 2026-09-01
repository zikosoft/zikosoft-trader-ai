"""Regroupe tous les modèles pour qu'Alembic (`target_metadata = Base.metadata`)
"""

from .agents import AgentDecision, AgentMessage
from .alerts import Alert
from .assets import Asset, ProviderAsset
from .base import Base
from .execution import ExecutionContext, ExecutionContextSwitch
from .identity import User, UserSession
from .market_data import MarketBar, MarketQuote
from .notifications import NotificationChannel, NotificationDelivery, NotificationSubscription
from .onboarding import OnboardingStep
from .ops import AuditEvent, ServiceHealthEvent, TechnicalErrorLog
from .orders import Order, OrderEvent
from .portfolio import PortfolioSnapshot, PositionSnapshot
from .preferences import DashboardPreference
from .providers import TradingProvider, UserTradingAccount
from .risk import RiskDecision
from .strategies import Strategy, StrategyDefinition, StrategyRun

__all__ = [
    "Base",
    "User",
    "UserSession",
    "TradingProvider",
    "UserTradingAccount",
    "ExecutionContext",
    "ExecutionContextSwitch",
    "Asset",
    "ProviderAsset",
    "StrategyDefinition",
    "Strategy",
    "StrategyRun",
    "AgentDecision",
    "AgentMessage",
    "RiskDecision",
    "Order",
    "OrderEvent",
    "PositionSnapshot",
    "PortfolioSnapshot",
    "MarketBar",
    "MarketQuote",
    "Alert",
    "NotificationChannel",
    "NotificationSubscription",
    "NotificationDelivery",
    "OnboardingStep",
    "ServiceHealthEvent",
    "AuditEvent",
    "DashboardPreference",
    "TechnicalErrorLog",
]
