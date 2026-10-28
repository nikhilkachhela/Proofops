"""Run all conditions on all cases and score them against ground truth (scoring only).

  python scripts/run_experiment.py data/cases           -> prints a table, writes results.csv
Metrics: object accuracy, component accuracy, evidence closure, unsupported-claim rate.
"""
import csv, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from proofops.agent import run
from proofops.case_loader import load_ground_truth

root = Path(sys.argv[1] if len(sys.argv) > 1 else "data/cases")
cases = sorted(p for p in root.iterdir() if (p / "case.json").exists())
rows = []
for case in cases:
    gt = load_ground_truth(case)  # scoring only
    for cond in ["baseline", "graph", "proofops"]:
        r = run(case, cond)
        rc = r.get("reported_cause") or ""
        name = lambda x: x.split(":", 1)[-1].split("-")[0] if x else ""
        rows.append({
            "case": case.name, "condition": cond, "reported": rc, "status": r["status"],
            "object_correct": int(rc == gt.get("root_cause")),
            "component_correct": int(name(rc) == name(gt.get("root_cause", ""))),
            "evidence_closed": int(r["status"] == "SUPPORTED"),
            "unsupported_claim": int(r["status"] == "CLAIMED"),
        })
out = Path("results.csv")
with out.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print(f"{'case':22s} {'condition':10s} {'reported':28s} {'status':10s} obj comp closed")
for r in rows:
    print(f"{r['case']:22s} {r['condition']:10s} {r['reported']:28s} {r['status']:10s} {r['object_correct']:3d} {r['component_correct']:4d} {r['evidence_closed']:6d}")
print("\nSummary by condition:")
for cond in ["baseline", "graph", "proofops"]:
    rs = [r for r in rows if r["condition"] == cond]
    n = len(rs)
    print(f"  {cond:9s} accuracy={sum(r['object_correct'] for r in rs)/n:.2f}  "
          f"evidence_closure={sum(r['evidence_closed'] for r in rs)/n:.2f}  "
          f"unsupported_claims={sum(r['unsupported_claim'] for r in rs)/n:.2f}")
print(f"\nwrote {out}  (NOTE: demo cases are hand-written; real results come from Cloud-OpsBench)")
