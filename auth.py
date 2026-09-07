"""
Access control for the AI Governance API.

Every endpoint that reads sensitive data or changes guardrail configuration sits behind
one of the roles below. Without this, the endpoints that govern the guardrails --
/toggle_toxicity, /add_rule, /delete_rule -- are open to anyone who can reach the API,
which means the protection can be switched off and the alarm recording it deleted.

The two admin role names match the ones the frontend already uses (AdminConfig.jsx), so
this promotes the existing browser-side login to a real server-side check rather than
introducing a second, competing model.

Keys come from config.py, which reads config.json with an environment override, so real
keys can be supplied via the API_KEYS environment variable and never enter git.
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
    *caller* is allowed to have.
    """
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
