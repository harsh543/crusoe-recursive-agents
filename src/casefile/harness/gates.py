"""Code gates that run BEFORE any model call: governance, then required fields. Missing values interrupt; they are never guessed."""
import re
from dataclasses import dataclass

from .state import Alert

ACCOUNT_ID = re.compile(r"acct_[A-Za-z0-9]+")


@dataclass(frozen=True)
class GovernanceConfig:
    supported_alert_types: set
    known_policy_versions: set
    allowed_tenants: set


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""


REQUIRED_AGENTS = ("planner", "investigator", "attributor")


def governance_gate(alert: Alert, cfg: GovernanceConfig, agents=None) -> Decision:
    if alert.alert_type not in cfg.supported_alert_types:
        return Decision(False, f"alert_type {alert.alert_type!r} is not supported")
    if alert.policy_version not in cfg.known_policy_versions:
        return Decision(False, f"policy_version {alert.policy_version!r} does not exist")
    if alert.tenant_id not in cfg.allowed_tenants:
        return Decision(False, f"tenant {alert.tenant_id!r} is not allowed")
    if agents is not None:
        from .agents import NotCertified
        try:
            agents.require_certified(REQUIRED_AGENTS)
        except NotCertified as e:
            return Decision(False, str(e))
    return Decision(True)


def required_fields_check(alert: Alert) -> list[str]:
    bad = []
    if not alert.account_id or not ACCOUNT_ID.fullmatch(alert.account_id):
        bad.append("account_id")
    if not alert.window_start or not alert.window_end or alert.window_end <= alert.window_start:
        bad.append("window")
    return bad
