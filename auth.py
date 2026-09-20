"""
Access control for the AI Governance API.

Enforced again as of the RBAC restoration: api.py's endpoints call require_role() below,
gating every route into one of three bands (super_admin-only config mutations, either
admin role for governance-data reads and record-level triage actions, or any
authenticated caller for the Chat Bot surface). A handful of routes are deliberately
left ungated -- /system_status (health check), /guardrail_validate (an external
validation API for other systems), and the external-agent-facing /v1/agent/register,
/v1/agent/decisions/check, /v1/agent/activity, which carry their own separate
X-Agent-Id/secret identity check (see agent_auth.py) instead of a human X-API-Key.

ANONYMOUS_PRINCIPAL is kept only as a fallback default for internal helpers that accept a
Principal (e.g. tool_broker paths not wired to a request), not as a live app-wide bypass.

Keys come from config.py (config.json with an environment override).
"""

from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException

import config

ROLE_SUPER_ADMIN = "super_admin"
ROLE_ADMIN_PII = "admin_pii"
ROLE_CALLER = "caller"

# Either admin role may read governance data (alarms, analytics, rules). Only
# super_admin may change it.
ADMIN_ROLES = (ROLE_SUPER_ADMIN, ROLE_ADMIN_PII)
ANY_ROLE = (ROLE_SUPER_ADMIN, ROLE_ADMIN_PII, ROLE_CALLER)


@dataclass(frozen=True)
class Principal:
    """The authenticated caller behind a request."""

    name: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role in ADMIN_ROLES


def _lookup(api_key: str) -> Optional[Principal]:
    entry = config.API_KEYS.get(api_key)
    if not isinstance(entry, dict):
        return None

    name = entry.get("name")
    role = entry.get("role")
    if not name or role not in ANY_ROLE:
        return None

    return Principal(name=name, role=role)


def require_role(*allowed_roles: str):
    """
    Build a FastAPI dependency that authenticates the caller and checks their role.

    Usage:
        @app.post("/add_rule")
        def add_rule(request: RuleRequest,
                     principal: Principal = Depends(require_role(ROLE_SUPER_ADMIN))):

    Returns 401 when the key is missing or unknown, 403 when the key is valid but the
    role is not permitted -- distinguishing "who are you" from "you may not do this",
    which the audit trail needs to tell apart.
    """
    if not allowed_roles:
        raise ValueError("require_role needs at least one role")

    def dependency(x_api_key: Optional[str] = Header(default=None)) -> Principal:
        if not x_api_key:
            raise HTTPException(
                status_code=401,
                detail="Missing X-API-Key header.",
                headers={"WWW-Authenticate": "X-API-Key"},
            )

        principal = _lookup(x_api_key)
        if principal is None:
            raise HTTPException(status_code=401, detail="Unknown API key.")

        if principal.role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{principal.role}' is not permitted to perform this action.",
            )

        return principal

    return dependency


def entitled_records(principal: Principal) -> list:
    """
    The record IDs this principal may read via a tool call. ["*"] means unrestricted.

    Used by tool_broker to decide whether a database read the model asked for is one the
    *caller* is allowed to have. super_admin always bypasses the configured map entirely
    -- that role is unrestricted by design, regardless of which key carries it.
    """
    if principal.role == ROLE_SUPER_ADMIN:
        return ["*"]

    allowed = config.ENTITLEMENTS.get(principal.name, [])
    if isinstance(allowed, str):
        return [allowed]
    return [str(record_id) for record_id in allowed]


def may_read_record(principal: Principal, record_id) -> bool:
    allowed = entitled_records(principal)
    return "*" in allowed or str(record_id) in allowed


def may_read_all_records(principal: Principal) -> bool:
    """
    Whether this principal may perform a bulk read of every record.

    Some /demo_chat keyword paths return the whole customer and spender tables at once.
    A caller entitled to one record must not reach those by phrasing, so bulk reads
    require unrestricted entitlement rather than any single-record grant.
    """
    return "*" in entitled_records(principal)


def using_default_keys() -> bool:
    """
    True when the shipped development keys are still in play, so startup can warn. A
    governance product running on published placeholder credentials is worth shouting
    about.
    """
    return "dev-super-admin-key" in config.API_KEYS
