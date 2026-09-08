"""
Notice Registry and Consent Ledger.

Every guardrail elsewhere in this codebase answers "can this text be shown" -- masking,
toxicity, injection. None of them answer "was this customer's data ever consented to
being used this way," which is the actual center of DPDP's consent requirement. This
module is that record: what a customer was told (notices) and what they agreed to
(consents), checked by tool_broker.py before a card read is allowed to proceed.

Scoped to CREDIT_CARD for the first pass -- both tables are category-agnostic, so
extending to AADHAAR/PAN later is a seed-data change, not new code.
"""

import sqlite3
from datetime import datetime

from database import DB_FILE

PURPOSES = ("BILLING_SUPPORT", "FRAUD_INVESTIGATION", "MARKETING")

STATUS_GRANTED = "GRANTED"
STATUS_WITHDRAWN = "WITHDRAWN"


def _connect():
    return sqlite3.connect(DB_FILE)


def has_consent(customer_id, data_category: str, purpose: str) -> bool:
    """
    Whether this customer has a live GRANTED consent for this category and purpose.

    No declared purpose is handled by the caller (tool_broker), not here -- this
    function only answers the question when both are known. An absent row and a
    withdrawn row both return False; there is no default-allow path.
    """
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT 1 FROM consents WHERE customer_id = ? AND data_category = ? '
        'AND purpose = ? AND status = ? LIMIT 1',
        (str(customer_id), data_category, purpose, STATUS_GRANTED),
    )
    row = cursor.fetchone()
    conn.close()
    return row is not None


def grant_consent(customer_id, data_category: str, purpose: str, notice_id: str):
    conn = _connect()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat() + "Z"
    cursor.execute(
        'INSERT INTO consents (customer_id, data_category, purpose, notice_id, status, granted_at, withdrawn_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        (str(customer_id), data_category, purpose, notice_id, STATUS_GRANTED, now, None),
    )
    conn.commit()
    conn.close()


def withdraw_consent(customer_id, data_category: str, purpose: str) -> bool:
    """
    Marks the most recent GRANTED row for this (customer, category, purpose) as
    WITHDRAWN. Returns False if there was nothing granted to withdraw.

    DPDP requires withdrawal to actually stop processing -- has_consent reads live
    status, not a cached grant, so this takes effect on the very next request, not on
    some later reconciliation pass.
    """
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT id FROM consents WHERE customer_id = ? AND data_category = ? '
        'AND purpose = ? AND status = ? ORDER BY id DESC LIMIT 1',
        (str(customer_id), data_category, purpose, STATUS_GRANTED),
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False

    now = datetime.utcnow().isoformat() + "Z"
    cursor.execute(
        'UPDATE consents SET status = ?, withdrawn_at = ? WHERE id = ?',
        (STATUS_WITHDRAWN, now, row[0]),
    )
    conn.commit()
    conn.close()
    return True


def get_notice(data_category: str, purpose: str):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT notice_id, data_category, purpose, notice_text, version FROM notices '
        'WHERE data_category = ? AND purpose = ? ORDER BY version DESC LIMIT 1',
        (data_category, purpose),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "notice_id": row[0],
        "data_category": row[1],
        "purpose": row[2],
        "notice_text": row[3],
        "version": row[4],
    }


def list_consents() -> list:
    """Every consent record, newest first -- backs the admin Consents ledger tab."""
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT id, customer_id, data_category, purpose, notice_id, status, granted_at, withdrawn_at '
        'FROM consents ORDER BY id DESC'
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "customer_id": r[1],
            "data_category": r[2],
            "purpose": r[3],
            "notice_id": r[4],
            "status": r[5],
            "granted_at": r[6],
            "withdrawn_at": r[7],
        }
        for r in rows
    ]
