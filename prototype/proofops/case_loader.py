"""Load one incident case (ProofOps case format). Ground truth is loaded separately, for scoring only."""
import json
from pathlib import Path

def _read_json(p: Path, default):
    return json.loads(p.read_text()) if p.exists() else default

def load_case(case_dir) -> dict:
    d = Path(case_dir)
    logs = []
    lp = d / "logs.jsonl"
    if lp.exists():
        for i, line in enumerate(lp.read_text().splitlines(), start=1):
            if line.strip():
                rec = json.loads(line)
                rec["_source"] = f"logs.jsonl:{i}"
                logs.append(rec)
    case = {
        "meta": _read_json(d / "case.json", {}),
        "state": _read_json(d / "k8s_state.json", {}),
        "calls": _read_json(d / "calls.json", []),
        "events": _read_json(d / "events.json", []),
        "logs": logs,
        "alerts": _read_json(d / "alerts.json", []),
        "metrics": _read_json(d / "metrics.json", []),
        "dir": str(d),
    }
    for name in ("events", "alerts", "metrics"):
        for i, rec in enumerate(case[name], start=1):
            rec["_source"] = f"{name}.json[{i}]"
    return case

def load_ground_truth(case_dir) -> dict:
    """SCORING ONLY. Never pass this to the agent."""
    return _read_json(Path(case_dir) / "ground_truth.json", {})
