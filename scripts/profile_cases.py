"""Profile the evidence available in each downloaded case.

Reads ONLY observable data (raw_data/ and tool_cache.json). It never opens
metadata.json, index.jsonl, process-label/ or golden-trajectory/.

Output: data/processed/case_profile.json, plus a summary table on stdout.

Usage:  .venv/bin/python -I scripts/profile_cases.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "data/raw/hf/benchmark"
OUT = ROOT / "data/processed/case_profile.json"

ERROR_RE = re.compile(r'"(severity|level)"\s*:\s*"(error|ERROR|fatal|FATAL|warn|WARN|WARNING)"|\b(error|exception|refused|failed|timeout)\b', re.I)
TS_KEYS = ("timestamp", "time", "ts", "@timestamp")


def log_timestamp(line):
    """Return the timestamp string from a log line, or None if it has none."""
    try:
        obj = json.loads(line)
    except (ValueError, TypeError):
        m = re.search(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}", line)
        return m.group(0) if m else None
    if isinstance(obj, dict):
        for k in TS_KEYS:
            if k in obj:
                return str(obj[k])
        if "instant" in obj:
            return f"epoch:{obj['instant'].get('epochSecond')}"
    return None


def parse_events(describe_text):
    """Extract rows of the 'Events:' table from `kubectl describe` text."""
    if "Events:" not in describe_text:
        return []
    block = describe_text.split("Events:", 1)[1]
    rows = []
    for line in block.splitlines():
        # Age may be "72s" or "72s (x3 over 82s)" for repeated events.
        m = re.match(r"\s+(Normal|Warning)\s+(\S+)\s+(\S+(?:\s+\(x\d+ over \S+\))?)\s+(\S+)\s+(.*)", line)
        if m:
            rows.append(dict(zip(("type", "reason", "age", "source", "message"), m.groups())))
    return rows


def profile(case_dir):
    raw = case_dir / "raw_data"
    k8s = json.loads((raw / "k8s_states.json").read_text())
    tool = json.loads((case_dir / "tool_cache.json").read_text())
    logs = json.loads((raw / "logs.json").read_text())
    alerts = json.loads((raw / "alert.json").read_text())

    log_lines = sum(len(v) for v in logs.values())
    with_ts = sum(1 for v in logs.values() for line in v if log_timestamp(line))
    err_lines = {svc: sum(1 for line in v if ERROR_RE.search(line)) for svc, v in logs.items()}

    events = [e | {"object": k} for k, v in k8s.items() if k.startswith("kubectl describe") for e in parse_events(v)]
    warnings = [e for e in events if e["type"] == "Warning"]

    pods_table = k8s.get("kubectl get pods -n boutique", "")
    not_running = [l.split()[0] for l in pods_table.splitlines()[1:] if l.split() and "Running" not in l.split()[2]]
    not_ready = [l.split()[0] for l in pods_table.splitlines()[1:]
                 if l.split() and l.split()[1].split("/")[0] != l.split()[1].split("/")[1]]
    restarts = [l.split()[0] for l in pods_table.splitlines()[1:] if l.split() and l.split()[3] != "0"]
    ep_table = k8s.get("kubectl get endpoints -n boutique", "")
    empty_endpoints = [l.split()[0] for l in ep_table.splitlines()[1:] if "<none>" in l]

    return {
        "case_key": str(case_dir.relative_to(BENCH)),
        "collection_timestamp": tool.get("collection_timestamp"),
        "k8s_commands": len(k8s),
        "tool_calls": len(tool) - 1,
        "has_dependencies_tool": any(k.startswith("GetServiceDependencies") for k in tool),
        "log_services": len(logs),
        "log_lines": log_lines,
        "log_lines_with_timestamp_pct": round(100 * with_ts / log_lines, 1) if log_lines else None,
        "error_like_log_lines": sum(err_lines.values()),
        "services_with_error_logs": sorted(s for s, n in err_lines.items() if n),
        "k8s_events": len(events),
        "k8s_warning_events": len(warnings),
        "warning_reasons": sorted({e["reason"] for e in warnings}),
        "pods_not_running": not_running,
        "pods_not_ready": not_ready,
        "pods_with_restarts": restarts,
        "services_with_empty_endpoints": empty_endpoints,
        "alert_count": alerts.get("alert_count", 0) if alerts else 0,
        "has_metrics_csv": (raw / "metrics.csv").exists(),
    }


if __name__ == "__main__":
    cases = sorted(p.parent for p in BENCH.glob("boutique/*/*/tool_cache.json"))
    profiles = [profile(c) for c in cases]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(profiles, indent=2))
    for p in profiles:
        print(f"\n## {p['case_key']}")
        for k, v in p.items():
            if k != "case_key":
                print(f"   {k}: {v}")
    print(f"\nWrote {OUT.relative_to(ROOT)}")
