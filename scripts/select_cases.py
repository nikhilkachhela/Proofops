"""Pick a small, reproducible slice of Online Boutique cases and report download size.

The selection plan is fixed below. For each (category, root_cause) slot we draw
case(s) with a fixed random seed, so re-running gives the same cases.

NOTE: index.jsonl contains ground truth (root_cause, fault_object). It is used
here only to *sample* cases (a researcher decision), never as agent input.

Output: data/selected_cases.json (case keys + the HF paths to download).

Usage:  .venv/bin/python scripts/select_cases.py
"""
import json
import random
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "data/raw/hf/index.jsonl"
OUT = ROOT / "data/selected_cases.json"
SEED = 42

# (category, root_cause, how many) -- 10 cases across 5 categories.
PLAN = [
    ("runtime", "container_memory_limit_too_low", 1),
    ("runtime", "liveness_probe_incorrect_port", 1),
    ("service", "service_selector_mismatch", 2),
    ("service", "service_port_mapping_mismatch", 1),
    ("admission", "missing_service_account", 1),
    ("admission", "namespace_memory_quota_exceeded", 1),
    ("startup", "missing_image_pull_secret", 1),
    ("performance", "pod_cpu_overload", 1),
    ("performance", "pod_network_delay", 1),
]

rows = [json.loads(line) for line in INDEX.open()]
boutique = [r for r in rows if r["system"] == "boutique"]

rng = random.Random(SEED)
selected = []
for category, root_cause, n in PLAN:
    pool = sorted(
        (r for r in boutique if r["category"] == category and r["root_cause"] == root_cause),
        key=lambda r: int(r["case_id"]),
    )
    selected += rng.sample(pool, n)

case_dirs = [f"benchmark/{r['case_key']}/" for r in selected]

# Size check against the Hub's file listing (no data downloaded yet).
info = HfApi().dataset_info("LLM4Ops/Cloud-OpsBench", files_metadata=True)
total = 0
print(f"{'case_key':32s} {'files':>5s} {'MB':>7s}")
for r, d in zip(selected, case_dirs):
    files = [f for f in info.siblings if f.rfilename.startswith(d)]
    size = sum(f.size or 0 for f in files)
    total += size
    print(f"{r['case_key']:32s} {len(files):5d} {size / 1e6:7.1f}")
print(f"{'TOTAL':32s} {'':5s} {total / 1e6:7.1f}")

OUT.write_text(json.dumps(
    {"seed": SEED, "system": "boutique",
     "case_keys": [r["case_key"] for r in selected],
     "allow_patterns": [d + "*" for d in case_dirs],
     "download_mb": round(total / 1e6, 1)},
    indent=2))
print(f"Wrote {OUT.relative_to(ROOT)}")
