"""
Agent Governance Layer storage -- agent registry, activity log, and agent-scoped compliance
events. See Implementation_Plan/Agent_Governance_Layer_Design.md for the full rationale.

Deliberately a separate SQLite file (governance.db) from cohort.db: this is a distinct bounded
concern from customer/consent data, the same way the DPDP Engine keeps its own dpdp.db separate
from anything Guardrail-specific. Plain sqlite3, no ORM, matching consent.py/database.py's idiom.
"""

import sqlite3
from datetime import datetime, timezone

DB_FILE = "governance.db"


def _connect():
    return sqlite3.connect(DB_FILE)


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def init_db():
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS agents (
            agent_id TEXT PRIMARY KEY,
            agent_name TEXT,
            agent_secret_hash TEXT,
            business_unit TEXT,
            owner_name TEXT,
            location_of_deployment TEXT,
            in_house_or_external TEXT,
            identity_assignment_timestamp TEXT,
            status TEXT,
            device_id TEXT
        )
    ''')

    # device_id was added after the initial release -- an existing governance.db from before this
    # change won't have the column yet, so add it in place rather than requiring a fresh DB.
    existing_columns = {row[1] for row in cursor.execute("PRAGMA table_info(agents)").fetchall()}
    if "device_id" not in existing_columns:
        cursor.execute("ALTER TABLE agents ADD COLUMN device_id TEXT")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            agent_id TEXT,
            invoking_user_id TEXT,
            action TEXT,
            outcome TEXT,
            latency_ms INTEGER,
            correlation_id TEXT,
            reason_code TEXT,
            device_id TEXT
        )
    ''')

    # reason_code was added after the initial release, so a blocked row can answer "why"
    # on its own instead of requiring a separate Compliance Events lookup. device_id was
    # added after that, so a decision-check row and its paired activity row (same
    # correlation_id) can be cross-checked against each other -- confirmed useful once
    # VOXA verified device_id is one persisted value shared across every skill on an
    # install, not something that could legitimately differ row to row.
    activity_columns = {row[1] for row in cursor.execute("PRAGMA table_info(activity_log)").fetchall()}
    if "reason_code" not in activity_columns:
        cursor.execute("ALTER TABLE activity_log ADD COLUMN reason_code TEXT")
    if "device_id" not in activity_columns:
        cursor.execute("ALTER TABLE activity_log ADD COLUMN device_id TEXT")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS governance_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT,
            severity TEXT,
            agent_id TEXT,
            reason_code TEXT,
            correlation_id TEXT,
            occurred_at TEXT
        )
    ''')

    # Mocked IAM -- deliberately its own table, never duplicated onto `agents`. Identity
    # (who this agent is) and authorization (what it's entitled to do) stay separate for the
    # same reason activity_log/governance_events are already separate from agents: a static
    # identity record and a live, independently-changing state must not be conflated, or one
    # ends up caching a stale copy of the other. device_id NULL here means "not yet
    # restricted by device" (wildcard) -- VOXA doesn't send device_id on every call yet, so
    # entitlements can't all be device-scoped from day one.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS iam_entitlements (
            principal_ref TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            device_id TEXT,
            allowed_app TEXT NOT NULL,
            granted_at TEXT
        )
    ''')

    # Reserved for genuine scope/authorization violations only (§ the design doc's incident
    # vs. compliance-event distinction) -- never raised for an ordinary consent denial or a
    # masked-content block, which stay as Activity Log + Compliance Events, nothing higher.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS incidents (
            incident_id TEXT PRIMARY KEY,
            event_type TEXT,
            severity TEXT,
            agent_id TEXT,
            principal_ref TEXT,
            reason_code TEXT,
            correlation_id TEXT,
            created_at TEXT
        )
    ''')

    conn.commit()
    conn.close()


def create_agent(agent_id, agent_name, agent_secret_hash, business_unit, owner_name,
                  location_of_deployment, in_house_or_external, device_id=None):
    conn = _connect()
    cursor = conn.cursor()
    timestamp = _now()
    cursor.execute(
        'INSERT INTO agents (agent_id, agent_name, agent_secret_hash, business_unit, owner_name, '
        'location_of_deployment, in_house_or_external, identity_assignment_timestamp, status, device_id) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (agent_id, agent_name, agent_secret_hash, business_unit, owner_name,
         location_of_deployment, in_house_or_external, timestamp, "active", device_id or None),
    )
    conn.commit()
    conn.close()
    return timestamp


def get_agent(agent_id):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT agent_id, agent_name, agent_secret_hash, business_unit, owner_name, '
        'location_of_deployment, in_house_or_external, identity_assignment_timestamp, status, device_id '
        'FROM agents WHERE agent_id = ?',
        (agent_id,),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "agent_id": row[0],
        "agent_name": row[1],
        "agent_secret_hash": row[2],
        "business_unit": row[3],
        "owner_name": row[4],
        "location_of_deployment": row[5],
        "in_house_or_external": row[6],
        "identity_assignment_timestamp": row[7],
        "status": row[8],
        "device_id": row[9],
    }


def revoke_agent(agent_id) -> bool:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute('UPDATE agents SET status = ? WHERE agent_id = ?', ("revoked", agent_id))
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def backfill_agent_device_id(agent_id, device_id) -> bool:
    """Admin-only backfill for an agent registered before device_id existed on this table --
    not a general-purpose update. Legitimate only when the value being written is actually
    known to be correct (e.g. confirmed the same install as another already-registered
    agent), never a guess."""
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute('UPDATE agents SET device_id = ? WHERE agent_id = ?', (device_id, agent_id))
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def list_agents():
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT agent_id, agent_name, business_unit, owner_name, location_of_deployment, '
        'in_house_or_external, identity_assignment_timestamp, status, device_id '
        'FROM agents ORDER BY identity_assignment_timestamp DESC'
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "agent_id": r[0], "agent_name": r[1], "business_unit": r[2], "owner_name": r[3],
            "location_of_deployment": r[4], "in_house_or_external": r[5],
            "identity_assignment_timestamp": r[6], "status": r[7], "device_id": r[8],
        }
        for r in rows
    ]


def log_activity(agent_id, invoking_user_id, action, outcome, latency_ms=None, correlation_id=None,
                  reason_code=None, device_id=None):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO activity_log (ts, agent_id, invoking_user_id, action, outcome, latency_ms, correlation_id, reason_code, device_id) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (_now(), agent_id, invoking_user_id, action, outcome, latency_ms, correlation_id, reason_code, device_id),
    )
    conn.commit()
    conn.close()


def list_activity(limit=100):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT id, ts, agent_id, invoking_user_id, action, outcome, latency_ms, correlation_id, reason_code, device_id '
        'FROM activity_log ORDER BY id DESC LIMIT ?',
        (limit,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": r[0], "ts": r[1], "agent_id": r[2], "invoking_user_id": r[3],
            "action": r[4], "outcome": r[5], "latency_ms": r[6], "correlation_id": r[7],
            "reason_code": r[8], "device_id": r[9],
        }
        for r in rows
    ]


def log_governance_event(event_id, event_type, severity, agent_id, reason_code, correlation_id):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO governance_events (event_id, event_type, severity, agent_id, reason_code, correlation_id, occurred_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        (event_id, event_type, severity, agent_id, reason_code, correlation_id, _now()),
    )
    conn.commit()
    conn.close()


def list_governance_events(limit=100):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT event_id, event_type, severity, agent_id, reason_code, correlation_id, occurred_at '
        'FROM governance_events ORDER BY occurred_at DESC LIMIT ?',
        (limit,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "event_id": r[0], "event_type": r[1], "severity": r[2], "agent_id": r[3],
            "reason_code": r[4], "correlation_id": r[5], "occurred_at": r[6],
        }
        for r in rows
    ]


def grant_entitlement(principal_ref, agent_id, allowed_app, device_id=None):
    """Seeding/admin helper -- there is no self-service grant endpoint; entitlements are set
    by whoever owns the (mocked) IAM sync process, never by the calling agent itself."""
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO iam_entitlements (principal_ref, agent_id, device_id, allowed_app, granted_at) '
        'VALUES (?, ?, ?, ?, ?)',
        (principal_ref, agent_id, device_id, allowed_app, _now()),
    )
    conn.commit()
    conn.close()


def is_entitled(principal_ref, agent_id, device_id, allowed_app) -> bool:
    """
    True only if a matching (principal_ref, agent_id, allowed_app) row exists AND either the
    row's device_id is NULL (wildcard -- not yet restricted by device) or matches the
    device_id on this call. allowed_app=None (an unrecognized/unmapped purpose) always
    fails closed -- there's nothing to look up, so nothing can be entitled.
    """
    if not allowed_app:
        return False
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT device_id FROM iam_entitlements WHERE principal_ref = ? AND agent_id = ? AND allowed_app = ?',
        (principal_ref, agent_id, allowed_app),
    )
    rows = cursor.fetchall()
    conn.close()
    return any(row[0] is None or row[0] == device_id for row in rows)


def list_entitlements(limit=200):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT principal_ref, agent_id, device_id, allowed_app, granted_at '
        'FROM iam_entitlements ORDER BY granted_at DESC LIMIT ?',
        (limit,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "principal_ref": r[0], "agent_id": r[1], "device_id": r[2],
            "allowed_app": r[3], "granted_at": r[4],
        }
        for r in rows
    ]


def create_incident(event_type, severity, agent_id, principal_ref, reason_code, correlation_id):
    """Dummy incident number -- this never calls a real ITSM tool (ServiceNow or otherwise);
    it's a self-contained record with enough detail to be handed to one, per the design
    doc's explicit scope: create the incident, relinquish post-incident investigation."""
    import random
    incident_id = f"INC-{random.randint(100000, 999999)}"
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO incidents (incident_id, event_type, severity, agent_id, principal_ref, reason_code, correlation_id, created_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (incident_id, event_type, severity, agent_id, principal_ref, reason_code, correlation_id, _now()),
    )
    conn.commit()
    conn.close()
    return incident_id


def list_incidents(limit=100):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT incident_id, event_type, severity, agent_id, principal_ref, reason_code, correlation_id, created_at '
        'FROM incidents ORDER BY created_at DESC LIMIT ?',
        (limit,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "incident_id": r[0], "event_type": r[1], "severity": r[2], "agent_id": r[3],
            "principal_ref": r[4], "reason_code": r[5], "correlation_id": r[6], "created_at": r[7],
        }
        for r in rows
    ]


def query_report(record_types=None, start_ts=None, end_ts=None, agent_id=None,
                  principal_ref=None, outcome=None, reason_code=None, severity=None,
                  correlation_id=None):
    """Backs the Reports tab -- a single filtered, normalized view across activity_log,
    governance_events and incidents, which are otherwise three separate tabs with no
    shared query surface. Each table only pushes its own timestamp/agent_id/reason_code
    filters down to SQL (the columns every table actually has); principal_ref/outcome/
    severity/correlation_id are applied afterwards in Python since not every table has
    every column, and PoC data volumes make that simple approach fast enough.

    Returns rows normalized to one shape:
    {record_type, timestamp, agent_id, principal_ref, outcome_or_severity, reason_code,
     correlation_id, detail, device_id} -- sorted newest first -- plus a summary of counts
    by record_type/outcome_or_severity/reason_code.

    by_record_type is computed over every type regardless of which ones were actually
    requested (every other filter -- date range, agent, principal, outcome, reason_code,
    correlation_id -- still applies). Confirmed directly this was a real bug otherwise:
    narrowing record_types to just "incident" made the by_record_type card's own
    "activity"/"event" checkboxes vanish (there being zero rows of those types left to
    count), so once you unchecked everything but one type there was no way back to the
    others without using the filter form above instead. The rows actually returned (and
    the other two summaries, which legitimately are scoped to the current type
    selection) still respect record_types as before.

    device_id is only ever a column on activity_log; an event/incident row gets it
    backfilled from a same-correlation_id activity_log row when one exists, rather than
    always showing blank for two of the three record types."""
    requested_types = record_types or ["activity", "event", "incident"]
    conn = _connect()
    cursor = conn.cursor()
    rows = []

    if True:  # always fetch every type -- see by_record_type note above
        clauses, params = [], []
        if start_ts:
            clauses.append("ts >= ?"); params.append(start_ts)
        if end_ts:
            clauses.append("ts <= ?"); params.append(end_ts)
        if agent_id:
            clauses.append("agent_id = ?"); params.append(agent_id)
        if reason_code:
            clauses.append("reason_code = ?"); params.append(reason_code)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cursor.execute(
            f'SELECT ts, agent_id, invoking_user_id, outcome, reason_code, correlation_id, action, device_id '
            f'FROM activity_log {where} ORDER BY ts DESC',
            params,
        )
        for r in cursor.fetchall():
            rows.append({
                "record_type": "activity", "timestamp": r[0], "agent_id": r[1],
                "principal_ref": r[2], "outcome_or_severity": r[3], "reason_code": r[4],
                "correlation_id": r[5], "detail": r[6], "device_id": r[7],
            })

    if True:  # always fetch every type -- see by_record_type note above
        clauses, params = [], []
        if start_ts:
            clauses.append("occurred_at >= ?"); params.append(start_ts)
        if end_ts:
            clauses.append("occurred_at <= ?"); params.append(end_ts)
        if agent_id:
            clauses.append("agent_id = ?"); params.append(agent_id)
        if reason_code:
            clauses.append("reason_code = ?"); params.append(reason_code)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cursor.execute(
            f'SELECT occurred_at, agent_id, severity, reason_code, correlation_id, event_type '
            f'FROM governance_events {where} ORDER BY occurred_at DESC',
            params,
        )
        for r in cursor.fetchall():
            rows.append({
                "record_type": "event", "timestamp": r[0], "agent_id": r[1],
                "principal_ref": None, "outcome_or_severity": r[2], "reason_code": r[3],
                "correlation_id": r[4], "detail": r[5], "device_id": None,
            })

    if True:  # always fetch every type -- see by_record_type note above
        clauses, params = [], []
        if start_ts:
            clauses.append("created_at >= ?"); params.append(start_ts)
        if end_ts:
            clauses.append("created_at <= ?"); params.append(end_ts)
        if agent_id:
            clauses.append("agent_id = ?"); params.append(agent_id)
        if reason_code:
            clauses.append("reason_code = ?"); params.append(reason_code)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cursor.execute(
            f'SELECT created_at, agent_id, principal_ref, severity, reason_code, correlation_id, event_type '
            f'FROM incidents {where} ORDER BY created_at DESC',
            params,
        )
        for r in cursor.fetchall():
            rows.append({
                "record_type": "incident", "timestamp": r[0], "agent_id": r[1],
                "principal_ref": r[2], "outcome_or_severity": r[3], "reason_code": r[4],
                "correlation_id": r[5], "detail": r[6], "device_id": None,
            })

    # Backfill device_id for event/incident rows from a same-correlation_id activity_log
    # row, since neither table has its own device_id column -- see docstring.
    missing_device_cids = {r["correlation_id"] for r in rows if r["device_id"] is None and r["correlation_id"]}
    if missing_device_cids:
        placeholders = ",".join("?" * len(missing_device_cids))
        conn2 = _connect()
        device_by_cid = {
            cid: device_id
            for cid, device_id in conn2.execute(
                f"SELECT correlation_id, device_id FROM activity_log "
                f"WHERE correlation_id IN ({placeholders}) AND device_id IS NOT NULL",
                tuple(missing_device_cids),
            )
        }
        conn2.close()
        for r in rows:
            if r["device_id"] is None and r["correlation_id"] in device_by_cid:
                r["device_id"] = device_by_cid[r["correlation_id"]]

    conn.close()

    if principal_ref:
        rows = [r for r in rows if r["principal_ref"] == principal_ref]
    if outcome:
        rows = [r for r in rows if r["outcome_or_severity"] == outcome]
    if severity:
        rows = [r for r in rows if r["outcome_or_severity"] == severity]
    if correlation_id:
        rows = [r for r in rows if r["correlation_id"] == correlation_id]

    # by_record_type is computed here, over every type with every filter above already
    # applied but BEFORE narrowing to requested_types -- see docstring for why.
    by_record_type = {}
    for r in rows:
        by_record_type[r["record_type"]] = by_record_type.get(r["record_type"], 0) + 1

    rows = [r for r in rows if r["record_type"] in requested_types]

    rows.sort(key=lambda r: r["timestamp"] or "", reverse=True)

    summary = {"total": len(rows), "by_record_type": by_record_type, "by_outcome_or_severity": {}, "by_reason_code": {}}
    for r in rows:
        if r["outcome_or_severity"]:
            summary["by_outcome_or_severity"][r["outcome_or_severity"]] = summary["by_outcome_or_severity"].get(r["outcome_or_severity"], 0) + 1
        if r["reason_code"]:
            summary["by_reason_code"][r["reason_code"]] = summary["by_reason_code"].get(r["reason_code"], 0) + 1

    return {"rows": rows, "summary": summary}


def get_stats():
    """Pure read-side aggregation over the three tables above -- no running counters maintained,
    same approach as the DPDP Engine's own get_stats()."""
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute('SELECT outcome, COUNT(*) FROM activity_log GROUP BY outcome')
    calls_by_outcome = {row[0]: row[1] for row in cursor.fetchall()}

    cursor.execute(
        'SELECT agent_id, COUNT(*) FROM activity_log GROUP BY agent_id ORDER BY COUNT(*) DESC LIMIT 10'
    )
    calls_by_agent = {row[0]: row[1] for row in cursor.fetchall()}

    cursor.execute('SELECT severity, COUNT(*) FROM governance_events GROUP BY severity')
    events_by_severity = {row[0]: row[1] for row in cursor.fetchall()}

    cursor.execute('SELECT COUNT(DISTINCT agent_id) FROM agents')
    distinct_agents = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(DISTINCT invoking_user_id) FROM activity_log')
    distinct_users = cursor.fetchone()[0]

    conn.close()
    return {
        "calls_by_outcome": calls_by_outcome,
        "calls_by_agent": calls_by_agent,
        "events_by_severity": events_by_severity,
        "distinct_agents": distinct_agents,
        "distinct_invoking_users": distinct_users,
    }
