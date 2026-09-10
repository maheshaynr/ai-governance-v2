"""
Bill payment (auto-pay) consent lookup, by user_name.

Kept separate from consent.py -- that module's tables are keyed by
(customer_id, data_category, purpose); this one is a flat user_name -> consent flag
lookup for one specific decision (may a payment be auto-initiated for this user),
checked by api.py's /guardrail_validate before it lets a payment confirmation/
initiation message proceed.
"""

import sqlite3

from database import DB_FILE


def has_card_consent(user_name: str):
    """
    True/False if the user is on record, None if user_name isn't in the table at all.

    The None case matters: an unknown user must be treated as NOT consented (fail
    closed, same philosophy as the Consent Gate's "no purpose declared" default) rather
    than silently allowed through because there's nothing on file to say no.
    """
    if not user_name:
        return None

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        'SELECT card_consent_flag FROM customer_bill_payment_consent WHERE user_name = ?',
        (user_name,),
    )
    row = cursor.fetchone()
    conn.close()

    if row is None:
        return None
    return row[0].strip().lower() == "true"
