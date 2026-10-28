"""Build the time-ordered incident graph from a case (what was OBSERVED).

Node ids:  <label>:<name>  e.g. pod:cartservice-7d9f8c6b5-x2k4p, configmap:redis-config
Labels reuse the ontology's class names (author the meaning once).
"""
import networkx as nx
from .entity_resolution import resolve_pod, resolve_mentions
from .thesaurus import EVENT_REASONS, METRIC_TYPES
from .log_extraction import extract

STRUCTURAL = {"OWNS", "SELECTS", "RUNS_ON", "MOUNTS", "CALLS"}
KIND_LABEL = {"ConfigMap": "configmap", "Deployment": "deployment", "Pod": "pod", "Node": "node",
              "Service": "service", "Secret": "secret"}

def build_graph(case: dict, use_llm: bool = False) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    st = case["state"]
    deployments = {d["name"]: d for d in st.get("deployments", [])}
    services = [s["name"] for s in st.get("services", [])]

    def node(nid, label, **props):
        g.add_node(nid, label=label, **props)
        return nid

    def edge(a, b, etype, **props):
        g.add_edge(a, b, key=etype, type=etype, **props)

    for n in st.get("nodes", []):
        node(f"node:{n['name']}", "Node", name=n["name"], source="k8s_state.json")
    for c in st.get("config_maps", []):
        node(f"configmap:{c['name']}", "ConfigMap", name=c["name"], source="k8s_state.json")
    for d in deployments.values():
        node(f"deployment:{d['name']}", "Deployment", name=d["name"], source="k8s_state.json")
    for s in st.get("services", []):
        node(f"service:{s['name']}", "Service", name=s["name"], source="k8s_state.json")

    # Pods, with entity resolution to ReplicaSet and Deployment
    for p in st.get("pods", []):
        pid = node(f"pod:{p['name']}", "Pod", name=p["name"], phase=p.get("phase"),
                   restarts=p.get("restarts", 0), source="k8s_state.json")
        rs, dep = resolve_pod(p["name"], deployments.keys())
        if dep:
            rsid = node(f"replicaset:{rs}", "ReplicaSet", name=rs, source="entity_resolution")
            edge(f"deployment:{dep}", rsid, "OWNS", source="entity_resolution")
            edge(rsid, pid, "OWNS", source="entity_resolution")
            for cm in deployments[dep].get("config_maps", []):
                edge(pid, f"configmap:{cm}", "MOUNTS", source="k8s_state.json")
            for s in st.get("services", []):
                if s.get("selector") == dep:
                    edge(f"service:{s['name']}", pid, "SELECTS", source="k8s_state.json")
        if p.get("node"):
            edge(pid, f"node:{p['node']}", "RUNS_ON", source="k8s_state.json")

    for c in case.get("calls", []):
        edge(f"service:{c['from']}", f"service:{c['to']}", "CALLS", source="calls.json")

    # Events: change events vs runtime events
    for i, e in enumerate(case.get("events", []), start=1):
        cls, stype = EVENT_REASONS.get((e["kind"], e["reason"]), ("RuntimeEvent", e["reason"]))
        eid = node(f"event:{i}", cls, time=e["time"], signal_type=stype, message=e["message"],
                   source=e["_source"])
        target = f"{KIND_LABEL.get(e['kind'], e['kind'].lower())}:{e['object']}"
        if target in g:
            edge(eid, target, "ABOUT", source=e["_source"])

    # Logs -> typed LogSignals (LLM extraction step), attached to pod + mentioned services
    for i, rec in enumerate(case.get("logs", []), start=1):
        ex = extract(rec["line"], use_llm=use_llm)
        if not ex:
            continue
        lid = node(f"log:{i}", "LogSignal", time=rec["time"], signal_type=ex["signal_type"],
                   quote=ex["quote"], line=rec["line"], method=ex["method"], source=rec["_source"])
        if f"pod:{rec['pod']}" in g:
            edge(lid, f"pod:{rec['pod']}", "EMITTED_BY", source=rec["_source"])
        for s in resolve_mentions(rec["line"], services):
            edge(lid, f"service:{s}", "MENTIONS", source="entity_resolution")

    for i, a in enumerate(case.get("alerts", []), start=1):
        aid = node(f"alert:{i}", "Alert", time=a["time"], alert=a["alert"], severity=a.get("severity"),
                   source=a["_source"])
        edge(aid, f"service:{a['service']}", "ON", source=a["_source"])

    for i, m in enumerate(case.get("metrics", []), start=1):
        mid = node(f"metric:{i}", "MetricAnomaly", time=m["time"], metric=m["metric"],
                   signal_type=METRIC_TYPES.get(m["metric"], "MetricAnomaly"),
                   value=m["value"], baseline=m["baseline"], source=m["_source"])
        if m["target"] in g:
            edge(mid, m["target"], "FOR", source=m["_source"])
    return g
