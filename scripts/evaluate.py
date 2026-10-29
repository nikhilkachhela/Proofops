"""Score diagnoses against the benchmark answer key (SCORING ONLY: the engine never reads this).

Compares three approaches on identical cases:
  baseline   - symptom-only: blame the service most named in error logs and alerts (no graph reasoning)
  graph      - graph-only: top candidate from graph patterns, NO evidence contract
  proofops   - contract-gated: SUPPORTED candidates first; reports what evidence is missing otherwise

Metrics (reported for dev, test, and all):
  component accuracy@1  reported object == benchmark fault_object (app/x, namespace/x, node/x)
  component accuracy@3  answer in ProofOps' top 3
  class accuracy        ProofOps fault class == benchmark fault_taxonomy
  evidence closure      share of ProofOps answers whose contract is satisfied (SUPPORTED)
  right but unproven    graph-only answers that are correct but whose contract is NOT satisfied
  wrong but confident   graph-only answers that are wrong (it would have claimed them anyway)

Usage: .venv/bin/python scripts/evaluate.py
"""
import json, os
from collections import Counter, defaultdict
from pathlib import Path
from dotenv import load_dotenv
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parent.parent
CLASS = {"AdmissionFault": "Admission_Fault", "SchedulingFault": "Scheduling_Fault", "StartupFault": "Startup_Fault",
         "RuntimeFault": "Runtime_Fault", "ServiceRoutingFault": "Service_Routing_Fault",
         "PerformanceFault": "Performance_Fault", "InfrastructureFault": "Infrastructure_Fault",
         "CodeDefect": "Application_Code_Defect"}


def baseline(drv, cid):
    r = drv.execute_query(
        "MATCH (x {case_id:$c})-[:ABOUT|EMITTED_BY]->(s:Service) WHERE x:LogSignal OR x:Alert "
        "RETURN s.name AS s, sum(coalesce(x.count, 1)) AS n ORDER BY n DESC LIMIT 1", c=cid, database_="proofops")[0]
    return f"app/{r[0]['s']}" if r else None


def pct(a, b):
    return f"{100 * a / b:.0f}% ({a}/{b})" if b else "n/a"


def main():
    load_dotenv(ROOT / ".env")
    drv = GraphDatabase.driver(os.getenv("NEO4J_URI", "bolt://localhost:7687"),
                               auth=(os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD")))
    dx = json.loads((ROOT / "results/diagnoses.json").read_text())
    ids = json.loads((ROOT / "data/processed/case_ids.json").read_text())
    sel = json.loads((ROOT / "data/selected_cases.json").read_text())
    idx = {}
    for line in (ROOT / "data/raw/hf/index.jsonl").open():
        if line.strip():
            r = json.loads(line); idx[r["case_key"]] = r

    rows = []
    for cid, key in ids.items():
        if cid not in dx:
            continue
        gt, d = idx[key], dx[cid]
        p = d["proofops"] or {}
        row = dict(case=cid, split=sel["split"][key], category=gt["category"], truth=gt["fault_object"],
                   truth_class=gt["fault_taxonomy"], root_cause=gt["root_cause"],
                   proofops=p.get("obj"), proofops_class=p.get("cls"), status=p.get("status"),
                   missing=",".join(p.get("missing") or []), top3=d["proofops_top3"],
                   graph=d["graph_first"], graph_status=d["graph_first_status"], baseline=baseline(drv, cid))
        row["ok"] = row["proofops"] == row["truth"]
        row["ok3"] = row["truth"] in row["top3"]
        row["ok_class"] = CLASS.get(row["proofops_class"]) == row["truth_class"]
        row["graph_ok"] = row["graph"] == row["truth"]
        row["base_ok"] = row["baseline"] == row["truth"]
        rows.append(row)
    drv.close()

    def summary(rs):
        n = len(rs)
        return {
            "cases": n,
            "baseline_acc@1": pct(sum(r["base_ok"] for r in rs), n),
            "graph_acc@1": pct(sum(r["graph_ok"] for r in rs), n),
            "proofops_acc@1": pct(sum(r["ok"] for r in rs), n),
            "proofops_acc@3": pct(sum(r["ok3"] for r in rs), n),
            "proofops_class_acc": pct(sum(r["ok_class"] for r in rs), n),
            "evidence_closure": pct(sum(r["status"] == "SUPPORTED" for r in rs), n),
            "supported_and_correct": pct(sum(r["status"] == "SUPPORTED" and r["ok"] for r in rs),
                                         sum(r["status"] == "SUPPORTED" for r in rs)),
            "graph_right_but_unproven": pct(sum(r["graph_ok"] and r["graph_status"] != "SUPPORTED" for r in rs), n),
            "graph_wrong_but_claimed": pct(sum(not r["graph_ok"] for r in rs), n),
            "missing_evidence": dict(Counter(m for r in rs if r["status"] != "SUPPORTED" for m in r["missing"].split(",") if m)),
        }

    out = {"all": summary(rows), "dev": summary([r for r in rows if r["split"] == "dev"]),
           "test": summary([r for r in rows if r["split"] == "test"])}
    by_cat = defaultdict(list)
    for r in rows:
        if r["split"] == "test":
            by_cat[r["category"]].append(r)
    out["test_by_category"] = {c: {"cases": len(rs), "acc@1": pct(sum(r["ok"] for r in rs), len(rs)),
                                   "class_acc": pct(sum(r["ok_class"] for r in rs), len(rs)),
                                   "supported": pct(sum(r["status"] == "SUPPORTED" for r in rs), len(rs))}
                               for c, rs in sorted(by_cat.items())}
    (ROOT / "results/evaluation.json").write_text(json.dumps(out, indent=2))
    with (ROOT / "results/per_case.csv").open("w") as f:
        cols = ["case", "split", "category", "root_cause", "truth", "proofops", "status", "missing", "ok", "ok_class",
                "graph", "graph_ok", "baseline", "base_ok"]
        f.write(",".join(cols) + "\n")
        for r in rows:
            f.write(",".join(str(r[c]).replace(",", ";") for c in cols) + "\n")

    md = ["# ProofOps evaluation", "", "Answer key used for scoring only. Dev = 17 cases used to write rules; "
          "test = 43 held-out cases never inspected while writing rules.", ""]
    for split in ("test", "dev", "all"):
        md += [f"## {split}", "", "| Metric | Value |", "|---|---|"] + [f"| {k} | {v} |" for k, v in out[split].items()] + [""]
    md += ["## Test set by category", "", "| Category | Cases | Component acc@1 | Class acc | Supported |", "|---|---|---|---|---|"]
    md += [f"| {c} | {v['cases']} | {v['acc@1']} | {v['class_acc']} | {v['supported']} |" for c, v in out["test_by_category"].items()]
    (ROOT / "results/evaluation.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
