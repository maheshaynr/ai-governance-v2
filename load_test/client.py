"""
Load test client for the AI Governance API.

Runs three isolated scenarios:

  pii       -> POST {base_url}/govern_ai        (no LLM call; pure guardrail masking)
  toxicity  -> POST {base_url}/demo_chat (toxic) (ingress-blocked before any LLM call)
  llm       -> POST {ollama_url} directly        (bypasses api.py entirely — no tool-call
                                                   routing, no DB round trip, no guardrails.
                                                   Validates the raw model's responsiveness
                                                   and behavior in isolation, since routing
                                                   llm requests through api.py's two-hop
                                                   tool-call flow made latency measurements
                                                   conflate app overhead with model latency,
                                                   and doubled the chance of hitting the
                                                   client-side request timeout.)

Messages live in messages.json, tagged with a size/technique and an
`expect` block so results can be checked for correctness, not just timed.
The llm scenario's messages are informational-only (no expect assertions),
since bypassing api.py means there's no guardrail behavior left to check.

Usage:
    python load_test/client.py --scenario all --requests 15 --concurrency 5
    python load_test/client.py --scenario pii --requests 30 --concurrency 8
    python load_test/client.py --scenario llm --ollama-model tinyllama-cpu
"""

import argparse
import csv
import json
import os
import random
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
MESSAGES_FILE = os.path.join(SCRIPT_DIR, "messages.json")

sys.path.insert(0, PROJECT_ROOT)
import config  # noqa: E402 - needs PROJECT_ROOT on sys.path first, for OLLAMA_URL/DEFAULT_LLM_MODEL defaults

SCENARIOS = ("pii", "toxicity", "llm")


def load_messages():
    with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def build_work_items(messages, scenario, count):
    """Pick `count` messages (even random draw, with replacement) from a scenario's bank."""
    bank = messages[scenario]
    return [random.choice(bank) for _ in range(count)]


def send_pii(ctx, item, timeout):
    resp = requests.post(f"{ctx['base_url']}/govern_ai", json={"text": item["payload"]}, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    masked = data.get("masked_output", "")
    fired = masked != item["payload"]
    passed = None
    expect = item.get("expect", {})
    if "masked" in expect and not item.get("informational"):
        passed = fired == expect["masked"]
    return {"api_status": data.get("status"), "fired": fired, "passed": passed}


def send_toxicity(ctx, item, timeout):
    resp = requests.post(
        f"{ctx['base_url']}/demo_chat",
        json={"message": item["payload"], "mode": "toxic"},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    status = data.get("status")
    passed = None
    expect = item.get("expect", {})
    if "status" in expect and not item.get("informational"):
        passed = status == expect["status"]
    return {"api_status": status, "fired": status == "blocked_toxic", "passed": passed}


def send_llm(ctx, item, timeout):
    """Posts straight to Ollama's /api/chat, bypassing api.py (and every guardrail) entirely."""
    payload = {
        "model": ctx["ollama_model"],
        "messages": [{"role": "user", "content": item["payload"]}],
        "stream": False,
        "keep_alive": -1,
    }
    resp = requests.post(ctx["ollama_url"], json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    content = data.get("message", {}).get("content", "")
    return {
        "api_status": "success" if content else "empty_response",
        "fired": None,
        "passed": None,
        "response_chars": len(content),
    }


SENDERS = {"pii": send_pii, "toxicity": send_toxicity, "llm": send_llm}


def run_one(ctx, scenario, item, index, timeout):
    sender = SENDERS[scenario]
    start = time.perf_counter()
    row = {
        "index": index,
        "scenario": scenario,
        "message_id": item["id"],
        "technique": item.get("technique", ""),
        "size": item.get("size", ""),
        "input_chars": len(item["payload"]),
        "input_words": len(item["payload"].split()),
        "informational": bool(item.get("informational", False)),
        "response_chars": "",
        "error": "",
    }
    try:
        result = sender(ctx, item, timeout)
        row.update(result)
    except Exception as exc:  # noqa: BLE001 - report any failure as a row, don't crash the run
        row.update({"api_status": "error", "fired": None, "passed": False, "error": str(exc)})
    row["latency_ms"] = (time.perf_counter() - start) * 1000
    return row


def get_alarm_count(base_url):
    try:
        resp = requests.get(f"{base_url}/alarms", timeout=10)
        resp.raise_for_status()
        return len(resp.json().get("alarms", []))
    except Exception:
        return None


def percentile(sorted_values, pct):
    if not sorted_values:
        return None
    k = (len(sorted_values) - 1) * pct
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def summarize(rows):
    latencies = sorted(r["latency_ms"] for r in rows)
    errors = [r for r in rows if r["error"]]
    checked = [r for r in rows if r["passed"] is not None]
    passed = [r for r in checked if r["passed"]]
    failed = [r for r in checked if not r["passed"]]

    print(f"  Requests:     {len(rows)}  (errors: {len(errors)})")
    if checked:
        print(f"  Pass/Fail:    {len(passed)} passed / {len(failed)} failed  (of {len(checked)} with an expectation)")
    if latencies:
        print(
            "  Latency ms:   "
            f"min={latencies[0]:.0f} mean={statistics.mean(latencies):.0f} "
            f"p50={percentile(latencies, 0.50):.0f} p90={percentile(latencies, 0.90):.0f} "
            f"p95={percentile(latencies, 0.95):.0f} max={latencies[-1]:.0f}"
        )

    by_size = {}
    for r in rows:
        by_size.setdefault(r["size"] or "unknown", []).append(r["latency_ms"])
    if len(by_size) > 1:
        print("  By size:")
        for size, vals in sorted(by_size.items()):
            print(f"    {size:8s} n={len(vals):3d}  mean={statistics.mean(vals):.0f}ms  max={max(vals):.0f}ms")

    by_technique = {}
    for r in rows:
        by_technique.setdefault(r["technique"] or "unknown", []).append(r)
    print("  By technique:")
    for tech, trows in sorted(by_technique.items()):
        tlat = [r["latency_ms"] for r in trows]
        tchecked = [r for r in trows if r["passed"] is not None]
        tfailed = [r for r in tchecked if not r["passed"]]
        fail_note = f", {len(tfailed)} failed" if tfailed else ""
        print(f"    {tech:32s} n={len(trows):3d}  mean={statistics.mean(tlat):.0f}ms{fail_note}")

    if failed:
        print("  Failed expectations:")
        for r in failed:
            print(f"    [{r['message_id']}] expected mismatch — api_status={r['api_status']} fired={r['fired']}")


def write_csv(rows, out_dir, scenario, timestamp):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{scenario}_{timestamp}.csv")
    fieldnames = [
        "index", "scenario", "message_id", "technique", "size", "input_chars", "input_words",
        "informational", "api_status", "fired", "passed", "response_chars", "latency_ms", "error",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    return path


def run_scenario(ctx, messages, scenario, count, concurrency, timeout, out_dir, timestamp):
    print(f"\n=== Scenario: {scenario} ({count} requests, concurrency {concurrency}) ===")
    if scenario == "llm":
        print(f"  Target:       {ctx['ollama_url']} (model={ctx['ollama_model']}) — direct, bypassing api.py")
    else:
        print(f"  Target:       {ctx['base_url']}")
    items = build_work_items(messages, scenario, count)

    # Alarms are only meaningful for scenarios that actually run through the app's guardrails;
    # the llm scenario bypasses api.py entirely, so this will always show a flat +0 there.
    alarms_before = get_alarm_count(ctx["base_url"])
    wall_start = time.perf_counter()

    rows = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(run_one, ctx, scenario, item, idx, timeout)
            for idx, item in enumerate(items)
        ]
        for future in as_completed(futures):
            rows.append(future.result())

    wall_elapsed = time.perf_counter() - wall_start
    alarms_after = get_alarm_count(ctx["base_url"])

    rows.sort(key=lambda r: r["index"])
    summarize(rows)
    print(f"  Throughput:   {len(rows) / wall_elapsed:.2f} req/s (wall clock {wall_elapsed:.1f}s)")
    if scenario != "llm" and alarms_before is not None and alarms_after is not None:
        print(f"  Alarms:       {alarms_before} -> {alarms_after} (+{alarms_after - alarms_before})")

    path = write_csv(rows, out_dir, scenario, timestamp)
    print(f"  CSV written:  {path}")
    return rows


def main():
    parser = argparse.ArgumentParser(description="Load test the AI Governance API.")
    parser.add_argument("--scenario", choices=SCENARIOS + ("all",), default="all")
    parser.add_argument("--requests", type=int, default=15, help="Total requests per scenario.")
    parser.add_argument("--concurrency", type=int, default=5)
    # 127.0.0.1, not localhost: on this machine, resolving "localhost" through requests/urllib3
    # adds ~2s per call (IPv6 attempt before falling back to IPv4), which would otherwise swamp
    # every latency measurement below with a fixed client-side artifact unrelated to the API.
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=120.0, help="Per-request timeout in seconds.")
    parser.add_argument("--out-dir", default=os.path.join(SCRIPT_DIR, "results"))
    parser.add_argument(
        "--ollama-url", default=config.OLLAMA_URL,
        help="Direct Ollama chat endpoint for the llm scenario (bypasses the app entirely). Defaults to config.py's OLLAMA_URL.",
    )
    parser.add_argument(
        "--ollama-model", default=config.DEFAULT_LLM_MODEL,
        help="Model name for the llm scenario's direct Ollama calls. Defaults to config.py's DEFAULT_LLM_MODEL.",
    )
    args = parser.parse_args()

    messages = load_messages()
    scenarios = SCENARIOS if args.scenario == "all" else (args.scenario,)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ctx = {"base_url": args.base_url, "ollama_url": args.ollama_url, "ollama_model": args.ollama_model}

    if "llm" not in scenarios or len(scenarios) > 1:
        try:
            requests.get(f"{args.base_url}/system_status", timeout=5)
        except Exception as exc:
            print(f"WARNING: could not reach {args.base_url}/system_status ({exc}). Is the backend running?")

    for scenario in scenarios:
        run_scenario(
            ctx, messages, scenario, args.requests, args.concurrency,
            args.timeout, args.out_dir, timestamp,
        )


if __name__ == "__main__":
    main()
