import os
from datetime import datetime

BENCHMARK_LOG_FILE = "benchmark.log"

class BenchmarkLogger:
    @staticmethod
    def log_metric(request_id: str, component_name: str, processing_time_ms: float):
        """
        Logs a benchmark metric to benchmark.log.
        Format: UTC,request_id,component_name,processing_time_ms
        """
        timestamp = datetime.utcnow().isoformat() + "Z"
        log_entry = f"{timestamp},{request_id},{component_name},{processing_time_ms:.6f}\n"
        
        with open(BENCHMARK_LOG_FILE, "a") as f:
            f.write(log_entry)
