"""
HTTP client for the DPDP Engine's consent-related routes.

Mirrors llm_watchdog.py's fail-closed idiom: every call catches its own exceptions and
returns a dict with guard_failed=True and a safe default verdict, rather than raising --
so a DPDP outage degrades to "refused", never a silent allow or an unhandled exception at
the call site.
"""

import logging
import uuid
from datetime import datetime, timezone

import requests

import config

_DECISION_UNKNOWN = {
    "decision": "UNKNOWN",
    "guard_failed": True,
    "error": None,
    "decision_id": None,
    "notice_version": None,
    "reason_code": None,
}


def _headers(correlation_id: str) -> dict:
    headers = {
        "Authorization": f"Bearer {config.DPDP_SERVICE_TOKEN}",
        "Content-Type": "application/json",
        "X-Request-Id": str(uuid.uuid4()),
        "X-Correlation-Id": correlation_id,
        "X-Source-Service": "ai-guardrail",
        "X-Schema-Version": "1",
        "Idempotency-Key": str(uuid.uuid4()),
    }
    if config.DPDP_TENANT_ID:
        headers["X-Tenant-Id"] = config.DPDP_TENANT_ID
    return headers


def check_decision(subject_ref, data_categories, purpose, operation,
                    recipient_ref=None, policy_context=None, correlation_id=None) -> dict:
    """
    POST /v1/decisions/check.

    Returns a dict with at least "decision" and "guard_failed". A missing
    DPDP_BASE_URL, a timeout, a non-200 response, or a malformed body all return
    decision="UNKNOWN"/guard_failed=True -- callers already treat "not ALLOW" as a
    refusal, so a guard failure fails closed with no separate branch needed per site.

    recipient_ref/policy_context are omitted from the payload when not given -- a
    self-read operation (the customer reading their own data back) has no third-party
    recipient to name, per the DPDP Engine's own worked examples.
    """
    correlation_id = correlation_id or str(uuid.uuid4())

    if not config.DPDP_BASE_URL:
        return {**_DECISION_UNKNOWN, "error": "DPDP_BASE_URL not configured"}

    payload = {
        "subject_ref": subject_ref,
        "data_categories": data_categories,
        "purpose": purpose,
        "operation": operation,
        "requesting_service": "ai-guardrail",
        "correlation_id": correlation_id,
    }
    if recipient_ref is not None:
        payload["recipient_ref"] = recipient_ref
    if policy_context is not None:
        payload["policy_context"] = policy_context

    try:
        resp = requests.post(
            f"{config.DPDP_BASE_URL}/v1/decisions/check",
            json=payload,
            headers=_headers(correlation_id),
            timeout=config.DPDP_TIMEOUT_SECONDS,
        )
        if resp.status_code != 200:
            return {**_DECISION_UNKNOWN, "error": f"DPDP HTTP {resp.status_code}"}

        body = resp.json()
        return {
            "decision": body.get("decision") or "UNKNOWN",
            "guard_failed": False,
            "error": None,
            "decision_id": body.get("decision_id"),
            "notice_version": body.get("notice_version"),
            "reason_code": body.get("reason_code"),
        }
    except (requests.RequestException, ValueError) as e:
        logging.error(f"DPDP decision check exception: {e}")
        return {**_DECISION_UNKNOWN, "error": str(e)}


def submit_compliance_event(event_type, severity, subject_ref, data_categories,
                             purpose, operation, decision_id, reason_code,
                             occurred_at=None) -> None:
    """
    POST /v1/compliance-events. Fire-and-log only: a failure here must never block or
    unwind a caller's already-decided refusal -- same "an alarm failure must not mask
    the refusal itself" rule tool_broker.py's _alarm/_alarm_consent already follow.
    """
    if not config.DPDP_BASE_URL:
        return

    correlation_id = str(uuid.uuid4())
    payload = {
        "event_type": event_type,
        "event_version": 1,
        "severity": severity,
        "subject_ref": subject_ref,
        "data_categories": data_categories,
        "purpose": purpose,
        "operation": operation,
        "decision_id": decision_id,
        "source_service": "ai-guardrail",
        "reason_code": reason_code,
        "occurred_at": occurred_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    try:
        requests.post(
            f"{config.DPDP_BASE_URL}/v1/compliance-events",
            json=payload,
            headers=_headers(correlation_id),
            timeout=config.DPDP_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        logging.error(f"DPDP compliance event submission failed: {e}")
