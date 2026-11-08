#!/usr/bin/env python3
"""Probe Generator - injeta trafego sintetico com trace context B3.

Varios workers por processo, para que requisicoes lentas (heavy-reports)
nao reduzam a taxa de amostras. Escreve o historico em RESULT_FILE.
"""
import json
import os
import random
import threading
import time
import uuid
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.request import Request, urlopen

CLUSTER_NAME = os.getenv("CLUSTER_NAME", "unknown")
APP_URL = os.getenv("APP_URL", "http://app-service.lab-apps.svc.cluster.local")
PROBE_INTERVAL = float(os.getenv("PROBE_INTERVAL", "5"))
HEAVY_RATIO = float(os.getenv("HEAVY_RATIO", "0.3"))
WORKERS = int(os.getenv("WORKERS", "4"))
# teste A/B do Flagger: fração das requisições que leva o header que roteia ao canary
CANARY_HEADER_RATIO = float(os.getenv("CANARY_HEADER_RATIO", "0"))
RESULT_FILE = os.getenv("RESULT_FILE", "/tmp/probe_results.json")
MAX_HISTORY = 500

ENDPOINTS = {"dashboard": "/api/v1/fast-data", "heavy-reports": "/api/v1/slow-data"}

_history = []
_lock = threading.Lock()


def record(result):
    with _lock:
        _history.append(result)
        del _history[:-MAX_HISTORY]
        snapshot = list(_history)
    tmp = f"{RESULT_FILE}.{threading.get_ident()}.tmp"
    with open(tmp, "w") as f:
        json.dump(snapshot, f)
    os.replace(tmp, RESULT_FILE)


def probe_once():
    trace = {
        "X-B3-TraceId": uuid.uuid4().hex,
        "X-B3-SpanId": uuid.uuid4().hex[:16],
        "X-B3-Sampled": "1",
        "X-Cluster": CLUSTER_NAME,
    }
    probe_type = "heavy-reports" if random.random() < HEAVY_RATIO else "dashboard"
    full_url = f"{APP_URL}{ENDPOINTS[probe_type]}"
    headers = {
        **trace,
        "X-Synthetic-Probe": "true",
        "X-Feature-Context": probe_type,
        "X-Request-Id": uuid.uuid4().hex[:8],
    }
    if CANARY_HEADER_RATIO > 0 and random.random() < CANARY_HEADER_RATIO:
        headers["x-canary"] = "insider"
    try:
        req = Request(full_url, headers=headers)
        start = time.time()
        resp = urlopen(req, timeout=30)
        elapsed_ms = int((time.time() - start) * 1000)
        result = {
            "cluster": CLUSTER_NAME, "type": probe_type, "url": full_url,
            "trace_id": trace["X-B3-TraceId"], "span_id": trace["X-B3-SpanId"],
            "status_code": resp.status, "elapsed_ms": elapsed_ms,
            "timestamp": datetime.now(timezone.utc).isoformat(), "success": True,
        }
    except URLError as e:
        result = {
            "cluster": CLUSTER_NAME, "type": probe_type,
            "trace_id": trace["X-B3-TraceId"], "error": str(getattr(e, "reason", e)),
            "timestamp": datetime.now(timezone.utc).isoformat(), "success": False,
        }
    record(result)
    if result["success"] and result["elapsed_ms"] > 4000:
        print(f"[probe] SLOW: [{CLUSTER_NAME}] {probe_type} {result['elapsed_ms']}ms", flush=True)
    elif not result["success"]:
        print(f"[probe] FAIL: [{CLUSTER_NAME}] {probe_type} error={result['error']}", flush=True)


def worker():
    while True:
        probe_once()
        time.sleep(PROBE_INTERVAL)


def main():
    print(f"[probe] cluster={CLUSTER_NAME} workers={WORKERS} interval={PROBE_INTERVAL}s", flush=True)
    threads = [threading.Thread(target=worker, daemon=True) for _ in range(WORKERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
