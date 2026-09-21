"""
Agent identity issuance and verification -- separate from governance_db.py's storage, the same
way auth.py is kept separate from database.py.

register_agent() issues a fresh, agent-specific secret (never a shared token -- see the design
doc's §3: a shared secret "can't tell agents apart"). verify_agent() is the inline check every
identity-bearing /v1/agent/* route runs first; it never raises, it returns None on any failure, so
callers have one uniform "not verified" branch rather than needing to catch exceptions.
"""

import hashlib
import hmac
import secrets
import uuid

import governance_db


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def register_agent(agent_name, business_unit, owner_name, location_of_deployment,
                    in_house_or_external, device_id=None):
    agent_id = str(uuid.uuid4())
    plaintext_secret = secrets.token_urlsafe(32)
    timestamp = governance_db.create_agent(
        agent_id=agent_id,
        agent_name=agent_name,
        agent_secret_hash=_hash_secret(plaintext_secret),
        business_unit=business_unit,
        owner_name=owner_name,
        location_of_deployment=location_of_deployment,
        in_house_or_external=in_house_or_external,
        device_id=device_id,
    )
    return agent_id, plaintext_secret, timestamp


def verify_agent(agent_id, secret):
    """
    Returns the agent record (dict, without agent_secret_hash) on success, None on any failure --
    unknown agent_id, wrong secret, or a revoked agent. Constant-time secret comparison so a
    mismatch doesn't leak timing information about how much of the secret was correct.
    """
    if not agent_id or not secret:
        return None

    agent = governance_db.get_agent(agent_id)
    if not agent or agent["status"] != "active":
        return None

    if not hmac.compare_digest(_hash_secret(secret), agent["agent_secret_hash"]):
        return None

    agent.pop("agent_secret_hash", None)
    return agent
