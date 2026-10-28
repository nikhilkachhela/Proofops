"""ProofOps app.   streamlit run app/streamlit_app.py"""
import sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import streamlit as st
from proofops.case_loader import load_case
from proofops.graph_builder import build_graph
from proofops.agent import run, check_hypothesis
from proofops.stores import NxStore

st.set_page_config(page_title="ProofOps", layout="wide")
st.title("ProofOps")
st.caption("Don't just name the root cause. Prove it.")

cases_dir = ROOT / "data" / "cases"
cases = sorted(p.name for p in cases_dir.iterdir() if (p / "case.json").exists())
case_name = st.sidebar.selectbox("Incident case", cases)
use_neo4j = st.sidebar.toggle("Use Neo4j as graph store", value=False,
                              help="Needs Neo4j running and NEO4J_PASSWORD set. Off = in-memory graph.")
case_dir = cases_dir / case_name
case = load_case(case_dir)
graph = build_graph(case)

def make_store():
    if use_neo4j:
        from proofops.stores import Neo4jStore
        s = Neo4jStore(); s.load(graph, case["meta"]["case_id"]); return s
    return NxStore(graph)

tabs = st.tabs(["Overview", "Incident graph", "Diagnose", "Check a hypothesis", "Ontology & contracts", "Evaluation"])

with tabs[0]:
    m = case["meta"]
    st.subheader(m.get("symptom", ""))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Nodes", graph.number_of_nodes()); c2.metric("Relationships", graph.number_of_edges())
    c3.metric("Change events", sum(1 for _, d in graph.nodes(data=True) if d["label"] == "ChangeEvent"))
    c4.metric("Typed log signals", sum(1 for _, d in graph.nodes(data=True) if d["label"] == "LogSignal"))
    if m.get("synthetic"):
        st.info("This is a hand-written demo case for testing the pipeline. Real experiments use Cloud-OpsBench cases.")
    st.markdown("**Timeline**")
    timeline = sorted([(d["time"], d["label"], d.get("message") or d.get("quote") or d.get("alert") or d.get("metric"), d["source"])
                       for _, d in graph.nodes(data=True) if "time" in d])
    st.dataframe([{"time": t, "kind": k, "what": w, "source": s} for t, k, w, s in timeline], use_container_width=True)

with tabs[1]:
    try:
        from pyvis.network import Network
        net = Network(height="620px", width="100%", directed=True, cdn_resources="in_line")
        colors = {"ChangeEvent": "#E8A33D", "Alert": "#D9534F", "LogSignal": "#3B8EA5", "MetricAnomaly": "#3B8EA5",
                  "RuntimeEvent": "#3B8EA5", "Service": "#7A6FB0", "Pod": "#9BA6B2", "ConfigMap": "#E8A33D",
                  "Deployment": "#6C8E5E", "ReplicaSet": "#9BB08E", "Node": "#8C7B6B"}
        for n, d in graph.nodes(data=True):
            net.add_node(n, label=n.split(":", 1)[1][:28], title=f"{d['label']}\n{json.dumps({k: v for k, v in d.items() if k != 'label'}, default=str)[:400]}",
                         color=colors.get(d["label"], "#BBBBBB"), shape="dot", size=16)
        for a, b, k in graph.edges(keys=True):
            net.add_edge(a, b, label=k, font={"size": 9})
        st.components.v1.html(net.generate_html(), height=640)
    except ImportError:
        st.warning("Install pyvis to see the graph here (pip install pyvis). You can also open Neo4j Browser.")

with tabs[2]:
    st.markdown("Run the three agents on this incident and compare what they claim and what they can prove.")
    if st.button("Run all three conditions", type="primary"):
        store = make_store()
        cols = st.columns(3)
        for col, cond, title in zip(cols, ["baseline", "graph", "proofops"], ["Standard agent", "Graph-guided agent", "ProofOps"]):
            r = run(case_dir, cond, store=store if cond != "baseline" else None)
            with col:
                st.markdown(f"#### {title}")
                st.markdown(f"**Cause:** `{r['reported_cause']}`")
                status = r["status"]
                (st.success if status == "SUPPORTED" else st.warning if status == "PLAUSIBLE" else st.error)(status)
                for e in r.get("evidence", []):
                    st.markdown(f"- **{e['type']}**: {e['detail']}  \n  *source: {', '.join(map(str, e['sources']))}*")
                if r.get("missing") and status != "SUPPORTED":
                    st.markdown("Missing: " + ", ".join(r["missing"]))
                with st.expander("Trace"):
                    for t in r["trace"]:
                        st.write(t)

with tabs[3]:
    st.markdown("Propose a cause (as an engineer or another agent would) and see whether it is proven.")
    objects = sorted(n for n, d in graph.nodes(data=True) if d["label"] in ("ConfigMap", "Deployment", "Node", "Service", "Pod"))
    obj = st.selectbox("Proposed cause", objects)
    ft = st.selectbox("Fault type", ["(infer)", "ConfigurationFault", "ResourceLimitFault", "ResourceExhaustion", "DependencyFault"])
    if st.button("Check against the evidence contract"):
        dx, v = check_hypothesis(case_dir, obj, None if ft == "(infer)" else ft, store=make_store())
        (st.success if v["status"] == "SUPPORTED" else st.warning)(f"{v['status']}  (engine: {v['engine']})")
        for e in dx["evidence"]:
            st.markdown(f"- have **{e['type']}**: {e['detail']}")
        for m in v["missing"]:
            st.markdown(f"- missing **{m}**")
        for n in dx["notes"]:
            st.caption(n)

with tabs[4]:
    st.markdown("**Ontology** (`ontology/proofops.ttl`, open in Protégé) and **evidence contracts** (`contracts/contracts.shacl.ttl`).")
    c1, c2 = st.columns(2)
    c1.code((ROOT / "ontology" / "proofops.ttl").read_text()[:6000], language="turtle")
    c2.code((ROOT / "contracts" / "contracts.shacl.ttl").read_text(), language="turtle")

with tabs[5]:
    st.markdown("Scores every condition on every case against ground truth (ground truth is used for scoring only).")
    if st.button("Run evaluation"):
        from proofops.case_loader import load_ground_truth
        rows = []
        for cn in cases:
            gt = load_ground_truth(cases_dir / cn)
            for cond in ["baseline", "graph", "proofops"]:
                r = run(cases_dir / cn, cond)
                rows.append({"case": cn, "condition": cond, "reported": r["reported_cause"], "status": r["status"],
                             "correct": r["reported_cause"] == gt.get("root_cause"),
                             "evidence closed": r["status"] == "SUPPORTED"})
        st.dataframe(rows, use_container_width=True)
        st.caption("Demo cases are hand-written. Report real numbers only from Cloud-OpsBench runs.")
