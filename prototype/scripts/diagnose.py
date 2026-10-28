"""Diagnose one case from the command line.

  python scripts/diagnose.py data/cases/demo-redis-config
  python scripts/diagnose.py data/cases/demo-redis-config --condition graph
  python scripts/diagnose.py data/cases/demo-redis-config --check node:node-2
  python scripts/diagnose.py data/cases/demo-redis-config --neo4j     (uses Neo4j as the graph store)
"""
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from proofops.agent import run, check_hypothesis

ap = argparse.ArgumentParser()
ap.add_argument("case")
ap.add_argument("--condition", default="proofops", choices=["baseline", "graph", "proofops"])
ap.add_argument("--check", help="check a specific proposed cause, e.g. node:node-2")
ap.add_argument("--fault-type", help="fault type for --check, e.g. DependencyFault")
ap.add_argument("--neo4j", action="store_true")
ap.add_argument("--llm", action="store_true", help="let the LLM order hypotheses and classify unknown logs")
a = ap.parse_args()

store = None
if a.neo4j:
    from proofops.stores import Neo4jStore
    store = Neo4jStore()

if a.check:
    dx, v = check_hypothesis(a.case, a.check, a.fault_type, store=store)
    print(f"\nProposed cause: {a.check}\nVerdict: {v['status']}   (engine: {v['engine']})")
    for e in dx["evidence"]:
        print(f"  [have]    {e['type']}: {e['detail']}   source: {', '.join(map(str, e['sources']))}")
    for m in v["missing"]:
        print(f"  [missing] {m}")
    for n in dx["notes"]:
        print(f"  note: {n}")
else:
    r = run(a.case, a.condition, store=store, use_llm=a.llm)
    print(f"\nCondition: {r['condition']}\nReported cause: {r['reported_cause']}   ({r.get('fault_type')})\nStatus: {r['status']}")
    for e in r.get("evidence", []):
        print(f"  [have]    {e['type']}: {e['detail']}   source: {', '.join(map(str, e['sources']))}")
    for m in r.get("missing", []):
        print(f"  [missing] {m}")
    print("\nTrace:")
    for t in r["trace"]:
        print("  -", t)
