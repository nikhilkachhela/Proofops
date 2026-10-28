"""Adapter: Cloud-OpsBench case  ->  ProofOps case format (data/cases/<case_id>/...).

Cloud-OpsBench (MIT): huggingface.co/datasets/LLM4Ops/Cloud-OpsBench
Each benchmark case has metadata.json (GROUND TRUTH: scoring only), tool_cache.json, and raw_data/
(Kubernetes states, logs, alerts, metrics). The exact field names must be confirmed against the
downloaded files; the functions below mark every place that needs that check with TODO.

Usage (after downloading a few cases):
  python adapters/cloudopsbench.py <path/to/benchmark/boutique/<category>/<case_id>> data/cases/
"""
import json, sys
from pathlib import Path

def convert(src: Path, out_root: Path):
    src, out = Path(src), Path(out_root) / Path(src).name
    out.mkdir(parents=True, exist_ok=True)
    meta = json.loads((src / "metadata.json").read_text())

    # Agent-visible case description (NO ground truth here)
    (out / "case.json").write_text(json.dumps({
        "case_id": src.name,
        "system": "Online Boutique (Cloud-OpsBench)",
        "symptom": meta.get("query", ""),                 # TODO confirm field name
        "symptom_service": meta.get("symptom_service", "frontend"),  # TODO derive from query/alerts
        "synthetic": False,
    }, indent=2))

    # Ground truth: scoring only
    (out / "ground_truth.json").write_text(json.dumps({
        "_note": "SCORING ONLY. Never shown to the agent.",
        "root_cause": meta.get("root_cause"),             # TODO confirm field names and map to '<label>:<name>'
        "fault_type": meta.get("fault_type"),
    }, indent=2))

    raw = src / "raw_data"
    # TODO: map raw_data/k8s_states.json -> k8s_state.json  (nodes, deployments(+config_maps), pods, services, config_maps)
    # TODO: map Kubernetes events -> events.json [{time, kind, object, reason, message}]
    # TODO: map logs -> logs.jsonl [{time, pod, line}]
    # TODO: map alerts -> alerts.json [{time, service, alert, severity}]
    # TODO: map metrics anomalies -> metrics.json [{time, target, metric, value, baseline}]
    # TODO: write calls.json from the Online Boutique call graph (static, from the app's architecture)
    print(f"converted (partially) {src.name} -> {out}. Complete the TODOs after inspecting raw_data/.")

if __name__ == "__main__":
    convert(Path(sys.argv[1]), Path(sys.argv[2]))
