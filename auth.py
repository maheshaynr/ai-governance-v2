"""
Role-based behavior for the AI Guardrail API.

There is no login, no secret, and no per-user identity here -- a caller simply declares
which role they're acting as via the X-Role header, and require_role() enforces what
that role may do (e.g. admin_pii can view governance data but not change guardrail
config; only super_admin can). This is a workflow/UI distinction between roles, not a
security boundary: nothing stops a caller from declaring a different role than they'd
normally be issued. If a real security boundary is ever needed again, this is the place
to reintroduce one (e.g. a verified X-API-Key lookup, which is what previously lived
here and was removed by explicit request).

Entitlements still come from config.py, now keyed by role directly rather than by an
individual name, since there's no individual identity behind a declared role.
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
_KNOWN_ROLES = set(ANY_ROLE)


@dataclass(frozen=True)
class Principal:
    """The caller behind a request, per their own self-declared role."""

    name: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role in ADMIN_ROLES


def require_role(*allowed_roles: str):
    """
    Build a FastAPI dependency that reads the caller's self-declared role and checks it
    against what this endpoint permits.

    Usage:
        @app.post("/add_rule")
        def add_rule(request: RuleRequest,
                     principal: Principal = Depends(require_role(ROLE_SUPER_ADMIN))):

    No header, or a value that isn't one of the three known roles, defaults to the
    least-privileged role (caller) rather than erroring -- since nothing is being
    authenticated, failing toward the lowest privilege is the only meaningful default
    for "nothing (or garbage) was declared". Returns 403 when a role was declared but
    isn't permitted to perform this action; there's no 401 case any more, since there's
    no credential to be missing or wrong.
    """
    if not allowed_roles:
        raise ValueError("require_role needs at least one role")

    def dependency(x_role: Optional[str] = Header(default=None, alias="X-Role")) -> Principal:
        role = x_role if x_role in _KNOWN_ROLES else ROLE_CALLER
        principal = Principal(name=role, role=role)

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
    -- that role is unrestricted by design.
    """
    if principal.role == ROLE_SUPER_ADMIN:
        return ["*"]

    allowed = config.ENTITLEMENTS.get(principal.role, [])
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
