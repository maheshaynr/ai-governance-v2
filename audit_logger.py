import json
from datetime import datetime

LOG_FILE = "governance_audit.json"

class AuditLogger:
    @staticmethod
    def log_transaction(pii_masked_input: str, final_rewrite: str, fidelity_score: float = None, fallback_triggered: bool = False):
        """
        Logs the chain of custody for a single transaction.
        For TrustArc compliance, the raw unmasked input is NEVER written to disk.

        Stored as JSON Lines (one JSON object per line, appended) rather than a
        single JSON array: appending is O(1) regardless of how large the log has
        grown, whereas reading the whole array and rewriting it on every call (the
        old approach) gets slower as the file grows.
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "pii_masked_input": pii_masked_input,
            "final_rewrite": final_rewrite,
            "fidelity_score": fidelity_score,
            "fallback_triggered": fallback_triggered
        }

        with open(LOG_FILE, 'a') as f:
            f.write(json.dumps(log_entry) + "\n")

        return log_entry
