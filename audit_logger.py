import json
import os
from datetime import datetime

LOG_FILE = "governance_audit.json"

class AuditLogger:
    @staticmethod
    def log_transaction(pii_masked_input: str, final_rewrite: str, fidelity_score: float = None, fallback_triggered: bool = False):
        """
        Logs the chain of custody for a single transaction. 
        For TrustArc compliance, the raw unmasked input is NEVER written to disk.
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "pii_masked_input": pii_masked_input,
            "final_rewrite": final_rewrite,
            "fidelity_score": fidelity_score,
            "fallback_triggered": fallback_triggered
        }
        
        # Load existing logs or create new list
        logs = []
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r') as f:
                try:
                    logs = json.load(f)
                except json.JSONDecodeError:
                    pass
        
        logs.append(log_entry)
        
        # Write back to file
        with open(LOG_FILE, 'w') as f:
            json.dump(logs, f, indent=4)
        
        return log_entry
