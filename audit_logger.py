import json
from datetime import datetime

LOG_FILE = "governance_audit.json"


class AuditLogger:
    # Entry kinds. Written into every record so consumers can tell traffic apart from
    # administration -- get_analytics counts transactions as requests and must not count
    # configuration changes among them. Records written before this field existed are
    # treated as transactions.
    EVENT_TRANSACTION = "transaction"
    EVENT_CONFIG_CHANGE = "config_change"

    @staticmethod
    def _append(entry: dict):
        """
        Stored as JSON Lines (one JSON object per line, appended) rather than a single
        JSON array: appending is O(1) regardless of how large the log has grown, whereas
        reading the whole array and rewriting it on every call (the old approach) gets
        slower as the file grows.
        """
        with open(LOG_FILE, 'a') as f:
            f.write(json.dumps(entry) + "\n")
        return entry

    @staticmethod
    def log_transaction(pii_masked_input: str, final_rewrite: str, fidelity_score: float = None,
                        fallback_triggered: bool = False, groundedness_score: float = None,
                        unsupported_claims: list = None):
        """
        Logs the chain of custody for a single transaction.
        For TrustArc compliance, the raw unmasked input is NEVER written to disk.
        """
        return AuditLogger._append({
            "event": AuditLogger.EVENT_TRANSACTION,
            "timestamp": datetime.now().isoformat(),
            "pii_masked_input": pii_masked_input,
            "final_rewrite": final_rewrite,
            "fidelity_score": fidelity_score,
            "fallback_triggered": fallback_triggered,
            "groundedness_score": groundedness_score,
            "unsupported_claims": unsupported_claims or [],
        })

    @staticmethod
    def log_config_change(actor: str, actor_role: str, action: str, before=None, after=None):
        """
        Record who changed a guardrail setting, and what it was before.

        Without this, the endpoints that disable the guards leave no trace of who
        disabled them -- and an audit trail that only covers traffic cannot answer the
        question a reviewer actually asks, which is whether the control was on at the
        time.
        """
        return AuditLogger._append({
            "event": AuditLogger.EVENT_CONFIG_CHANGE,
            "timestamp": datetime.now().isoformat(),
            "actor": actor,
            "actor_role": actor_role,
            "action": action,
            "before": before,
            "after": after,
        })
