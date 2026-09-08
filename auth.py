"""
Access control for the AI Governance API.

NOT CURRENTLY ENFORCED: api.py's endpoints no longer call require_role() below -- every
request runs as ANONYMOUS_PRINCIPAL (unrestricted, super_admin-equivalent), by explicit
request. That means the protections this module used to provide are off: any caller can
read any customer record, change guardrail configuration, and see whatever a super_admin
key could. require_role() and the key-lookup machinery are left in place, unused, so
authentication can be re-enabled by wiring Depends(require_role(...)) back onto the
endpoints in api.py without rebuilding this module from scratch.

Keys still come from config.py (config.json with an environment override), for when this
is turned back on.
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


# A fixed stand-in principal used everywhere the app previously required a caller to
# authenticate. Endpoints no longer check X-API-Key at all -- see the removal of
# require_role from every route in api.py -- but tool_broker, the audit log, and
# may_see_raw_output still expect a Principal object internally, so this keeps that
# plumbing intact without requiring a real identity behind it.
ANONYMOUS_PRINCIPAL = Principal(name="anonymous", role=ROLE_SUPER_ADMIN)


def entitled_records(principal: Principal) -> list:
    """
    The record IDs this principal may read via a tool call. ["*"] means unrestricted.

    Used by tool_broker to decide whether a database read the model asked for is one the
    *caller* is allowed to have. super_admin always bypasses the configured map entirely,
    since with no authentication there is no real caller identity to look up -- every
    request now runs as ANONYMOUS_PRINCIPAL, which is unrestricted by design.
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
