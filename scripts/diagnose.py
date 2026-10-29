"""ProofOps diagnosis engine: candidate causes -> evidence -> SHACL contract -> verdict, on the real Neo4j graph.

Reads ONLY the graph (never the answer key). Scoring is a separate script (scripts/evaluate.py).

For each case:
  1. Symptoms: error log signals, alerts, and latency anomalies; onset = earliest of these.
  2. Candidates: graph patterns that indicate a fault class (rules below), each with a cause time,
     a cause kind (WarningEvent, State, PodStatus, LogError, MetricAnomaly) and affected services.
  3. Evidence (each with provenance):
       TemporalPrecedence  cause time <= first symptom + tolerance (event ages: +-uncertainty; metrics: 5 s)
       DependencyPath      Cypher: a symptomatic service CALLS* (0..4 hops) an affected service
       CorroboratingSignal a signal of a DIFFERENT kind on an affected service, of a kind the class allows
  4. Contract: the evidence is turned into RDF and validated with pySHACL against
     contracts/contracts.shacl.ttl + ontology/proofops.ttl -> SUPPORTED or PLAUSIBLE (+ missing evidence).
  5. Ranking: SUPPORTED first, then rule priority, then signal strength. Top 3 written to Neo4j as
     (:Diagnosis)-[:HAS_EVIDENCE]->(:Evidence)-[:DERIVED_FROM]->(source node), and to results/.

Usage: .venv/bin/python scripts/diagnose.py            (all cases)
       .venv/bin/python scripts/diagnose.py C03 C06     (some cases)
"""
import json, os, re, sys
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from neo4j import GraphDatabase
from rdflib import Graph, Namespace, Literal, RDF, URIRef
import pyshacl

ROOT = Path(__file__).resolve().parent.parent
DB = "proofops"
PO = Namespace("https://example.org/proofops#")
PROV = Namespace("http://www.w3.org/ns/prov#")
FIRING_S = 120          # a warning still counts as "firing" if last seen within 2 min of the snapshot
METRIC_TOL_S = 5        # metrics are sampled every 5 s
PRIORITY = {"State": 0, "WarningEvent": 1, "PodStatus": 2, "LogError": 3, "MetricAnomaly": 4}
ALLOWED = {  # mirrors contracts/contracts.shacl.ttl
    "AdmissionFault": {"WarningEvent", "PodStatus", "LogError", "Alert"},
    "SchedulingFault": {"WarningEvent", "PodStatus", "LogError", "Alert"},
    "StartupFault": {"WarningEvent", "PodStatus", "LogError", "Alert"},
    "RuntimeFault": {"WarningEvent", "PodStatus", "LogError", "Alert", "MetricAnomaly"},
    "ServiceRoutingFault": {"LogError", "Alert", "MetricAnomaly", "WarningEvent"},
    "PerformanceFault": {"MetricAnomaly", "Alert", "LogError"},
    "InfrastructureFault": {"WarningEvent", "PodStatus", "MetricAnomaly", "Alert", "LogError"},
    "CodeDefect": {"LogError", "Alert", "MetricAnomaly"},
}
CODE_HINT = re.compile(r"exception|panic|traceback|nil pointer|invalid|unexpected|argument|undefined|typeerror|null", re.I)


def ts(s):
    return datetime.fromisoformat(s) if s else None


class Case:
    """All nodes and relationships of one case, pulled from Neo4j."""
    def __init__(self, drv, cid):
        q = lambda cypher, **k: drv.execute_query(cypher, database_=DB, **k)[0]
        self.drv, self.cid = drv, cid
        self.n = {r["p"]["uid"]: dict(r["p"], label=r["l"])
                  for r in q("MATCH (n {case_id:$c}) RETURN labels(n)[0] AS l, properties(n) AS p", c=cid)}
        self.r = [(r["a"], r["t"], r["b"]) for r in q(
            "MATCH (a {case_id:$c})-[r]->(b {case_id:$c}) WHERE type(r) <> 'IN_CASE' "
            "RETURN a.uid AS a, type(r) AS t, b.uid AS b", c=cid)]
        self.case = next(v for v in self.n.values() if v["label"] == "Case")
        self.snapshot = ts(self.case.get("snapshot_time"))
        self.out = lambda u, t: [b for a, tt, b in self.r if a == u and tt == t]
        self.inn = lambda u, t: [a for a, tt, b in self.r if b == u and tt == t]

    def of(self, label):
        return [v for v in self.n.values() if v["label"] == label]

    def dep_of(self, uid):
        """Deployment name for a Pod / ReplicaSet / Deployment uid."""
        node = self.n.get(uid, {})
        if node.get("label") == "Deployment":
            return node["name"]
        if node.get("label") == "Pod":
            for rs in self.inn(uid, "OWNS"):
                return self.dep_of(rs)
            return re.sub(r"-[a-z0-9]{8,10}-[a-z0-9]{5}$", "", node.get("name", "")) or None
        if node.get("label") == "ReplicaSet":
            for d in self.inn(uid, "OWNS"):
                return self.n[d]["name"]
            return node["name"].rsplit("-", 1)[0]
        return None

    def pods_of_dep(self, dep):
        return [self.n[p] for rs in self.out(f"{self.cid}|Deployment|{dep}", "OWNS") for p in self.out(rs, "OWNS")]

    @staticmethod
    def healthy(pod):
        ready = str(pod.get("ready") or "")
        full = "/" in ready and ready.split("/")[0] == ready.split("/")[1] and ready.split("/")[0] != "0"
        restarts = str(pod.get("restarts") or "0").split(" ")[0]
        return pod.get("status") == "Running" and full and restarts in ("0", "")

    def services_of_dep(self, dep):
        out = {self.n[s]["name"] for s in self.inn(f"{self.cid}|Deployment|{dep}", "SELECTS")}
        if f"{self.cid}|Service|{dep}" in self.n:
            out.add(dep)                    # Online Boutique names services after their deployments
        return out


def symptoms(c):
    """Symptom observations (not causes): error logs, alerts, latency anomalies."""
    obs = []
    logs = [ls for ls in c.of("LogSignal") if ls.get("first_seen")]
    if c.snapshot:   # persistent symptoms only: error groups still occurring near the snapshot (start-up noise stops)
        persistent = [ls for ls in logs if ts(ls.get("last_seen")) and ts(ls["last_seen"]) >= c.snapshot - timedelta(seconds=FIRING_S)]
        logs = persistent or logs
    for ls in logs:
        # user-facing symptom = an error that names another service, or an error at the entry point (frontend);
        # a service logging about itself (e.g. redis background lines) is not a user symptom
        if c.out(ls["uid"], "ABOUT") or ls.get("service") == "frontend":
            obs.append((ts(ls["first_seen"]), ls["service"], ls["uid"]))
    for a in c.of("Alert"):
        if a.get("start"):
            for t in c.out(a["uid"], "ABOUT"):
                obs.append((ts(a["start"]), c.n[t]["name"], a["uid"]))
    for m in c.of("MetricAnomaly"):
        if "latency" in (m.get("metric") or "").lower():
            for t in c.out(m["uid"], "ABOUT"):
                obs.append((ts(m["onset"]), c.n[t]["name"], m["uid"]))
    obs.sort(key=lambda o: o[0])
    services = {o[1] for o in obs} or {"frontend"}
    return (obs[0] if obs else None), services


def candidates(c):
    """Graph patterns -> candidate causes. Each: fault class, object, cause kind, time, affected deployments."""
    cands = {}

    def add(cls, obj, kind, t, tol, src, deps, strength, why):
        key = (cls, obj)
        cur = cands.get(key)
        if cur is None:
            cands[key] = dict(cls=cls, obj=obj, kind=kind, time=t, tol=tol, src={src}, deps=set(deps),
                              strength=strength, why=why)
        else:
            cur["src"].add(src); cur["deps"] |= set(deps); cur["strength"] += strength
            if PRIORITY[kind] < PRIORITY[cur["kind"]]:
                cur.update(kind=kind, why=why)
            if t and (cur["time"] is None or t < cur["time"]):
                cur["time"], cur["tol"] = t, tol

    ns = next((v["name"] for v in c.of("Namespace")), "boutique")
    for e in c.of("Event"):
        if e.get("type") != "Warning":
            continue
        last = ts(e.get("last_seen_approx"))
        firing = (c.snapshot and last and last >= c.snapshot - timedelta(seconds=FIRING_S)) or e.get("count", 1) >= 5
        if not firing:
            continue                                     # start-up noise: fired a few times, then stopped
        tgt = (c.out(e["uid"], "ABOUT") or [None])[0]
        tnode = c.n.get(tgt, {})
        dep = c.dep_of(tgt) if tgt else None
        msg, rsn = (e.get("message") or "").lower(), e.get("reason")
        first, tol, cnt = ts(e.get("first_seen_approx")), e.get("time_uncertainty_s", 60), e.get("count", 1)
        if rsn == "FailedCreate" and "service account" in msg and dep:
            m_sa = re.search(r"service account [\w-]+/([\w-]+)", msg)
            sa_node = c.n.get(f"{c.cid}|ServiceAccount|{m_sa.group(1)}") if m_sa else None
            if sa_node and sa_node.get("exists") is not False:
                continue                                 # the account exists now: a start-up race, not a fault
            add("AdmissionFault", f"app/{dep}", "WarningEvent", first, tol, e["uid"], [dep], cnt, "pod creation forbidden: service account not found")
        elif rsn == "FailedCreate" and "exceeded quota" in msg:
            add("AdmissionFault", f"namespace/{ns}", "WarningEvent", first, tol, e["uid"], [dep] if dep else [], cnt, "pod creation forbidden: namespace quota exceeded")
        elif rsn == "FailedScheduling" and dep:
            add("SchedulingFault", f"app/{dep}", "WarningEvent", first, tol, e["uid"], [dep], cnt, "no node can run the pod")
        elif rsn in ("Failed", "FailedToRetrieveImagePullSecret", "FailedMount") and dep:
            add("StartupFault", f"app/{dep}", "WarningEvent", first, tol, e["uid"], [dep], cnt, f"container cannot start ({rsn})")
        elif rsn in ("Unhealthy", "BackOff") and dep:
            if rsn == "Unhealthy" and all(Case.healthy(p) for p in c.pods_of_dep(dep)):
                continue      # probe flapped but the pod is ready with no restarts: slow start-up noise
            add("RuntimeFault", f"app/{dep}", "WarningEvent", first, tol, e["uid"], [dep], cnt, f"container unhealthy or restarting ({rsn})")
        elif rsn == "FailedCreatePodSandBox" and dep and "oom" in msg:
            add("RuntimeFault", f"app/{dep}", "WarningEvent", first, tol, e["uid"], [dep], cnt, "container init OOM-killed (memory limit)")
        elif rsn in ("FailedCreatePodSandBox", "ContainerGCFailed", "Rebooted", "InvalidDiskCapacity", "NodeNotReady"):
            node = tnode.get("name") if tnode.get("label") == "Node" else None
            if not node and tgt:
                node = next((c.n[x]["name"] for x in c.out(tgt, "RUNS_ON")), None)
            if node:
                deps = {c.dep_of(p) for p in c.inn(f"{c.cid}|Node|{node}", "RUNS_ON")} - {None}
                add("InfrastructureFault", f"node/{node}", "WarningEvent", first, tol, e["uid"], deps, cnt, f"node-level failure ({rsn})")

    for s in c.of("Service"):
        pods = c.pods_of_dep(s["name"])
        if not pods or not all(Case.healthy(p) for p in pods):
            continue          # no endpoints is a CONSEQUENCE of missing/failing pods; the pod-level fault is the cause
        if s.get("has_endpoints") is False and s["name"] != "kubernetes":
            add("ServiceRoutingFault", f"app/{s['name']}", "State", ts(s.get("created_approx")), 0, s["uid"],
                [s["name"]], 10, f"service has no endpoints (selector {s.get('selector')})")
    for sa in c.of("ServiceAccount"):
        if sa.get("exists") is False:
            for d in c.inn(sa["uid"], "USES_ACCOUNT"):
                if c.n[d]["label"] == "Deployment":
                    add("AdmissionFault", f"app/{c.n[d]['name']}", "State", ts(c.n[d].get("created")), 0, sa["uid"],
                        [c.n[d]["name"]], 10, f"deployment uses service account '{sa['name']}', which does not exist")
    for p in c.of("Pod"):
        st, dep = (p.get("status") or ""), c.dep_of(p["uid"])
        if not dep:
            continue
        if st in ("ImagePullBackOff", "ErrImagePull") or st.startswith("Init:") or st == "ContainerCreating":
            add("StartupFault", f"app/{dep}", "PodStatus", ts(p.get("start_time")), 0, p["uid"], [dep], 3, f"pod stuck in {st}")
        elif st == "Pending":
            add("SchedulingFault", f"app/{dep}", "PodStatus", ts(p.get("start_time")), 0, p["uid"], [dep], 3, "pod stuck in Pending")
        elif st == "CrashLoopBackOff":
            add("RuntimeFault", f"app/{dep}", "PodStatus", ts(p.get("start_time")), 0, p["uid"], [dep], 3, "pod in CrashLoopBackOff")
    for nd in c.of("Node"):
        if nd.get("status") and nd["status"] != "Ready":
            deps = {c.dep_of(p) for p in c.inn(nd["uid"], "RUNS_ON")} - {None}
            add("InfrastructureFault", f"node/{nd['name']}", "State", None, 0, nd["uid"], deps, 5, f"node status {nd['status']}")

    svc_ok = {s["name"]: s.get("has_endpoints") for s in c.of("Service")}
    for ls in c.of("LogSignal"):
        about = [c.n[t]["name"] for t in c.out(ls["uid"], "ABOUT")]
        for t in about:
            if svc_ok.get(t):                            # target has endpoints, yet calls fail: port/protocol/address
                add("ServiceRoutingFault", f"app/{t}", "LogError", ts(ls.get("first_seen")), 0, ls["uid"], [t],
                    ls.get("count", 1), f"calls to {t} fail although it has endpoints")
        if not about and CODE_HINT.search(ls.get("sample") or ""):
            add("CodeDefect", f"app/{ls['service']}", "LogError", ts(ls.get("first_seen")), 0, ls["uid"], [ls["service"]],
                ls.get("count", 1), "application error inside the service itself")
    for m in c.of("MetricAnomaly"):
        is_latency = "latency" in (m.get("metric") or "").lower()
        for t in c.out(m["uid"], "ABOUT"):
            if is_latency and (c.n[t]["label"] != "Service" or c.n[t]["name"] == "frontend"):
                continue      # latency at the entry point is the symptom; downstream latency may be the cause
            tn = c.n[t]
            obj = f"node/{tn['name']}" if tn["label"] == "Node" else f"app/{tn['name']}"
            deps = ({c.dep_of(p) for p in c.inn(t, "RUNS_ON")} - {None}) if tn["label"] == "Node" else {tn["name"]}
            add("PerformanceFault", obj, "MetricAnomaly", ts(m.get("onset")), METRIC_TOL_S, m["uid"], deps,
                1 + min(abs(m.get("change_pct") or 0) / 100, 50), f"{m.get('metric')} anomaly on {tn['name']}")
    return list(cands.values())


def relevance(c, cand):
    """How many symptom observations point AT this candidate's services (logs naming them, alerts, anomalies)."""
    services = set().union(*[c.services_of_dep(d) for d in cand["deps"]]) if cand["deps"] else set()
    score = 0
    for s in services:
        su = f"{c.cid}|Service|{s}"
        for x in c.inn(su, "ABOUT"):
            node = c.n[x]
            if node["label"] == "LogSignal":
                score += node.get("count", 1)
            elif node["label"] in ("Alert", "MetricAnomaly"):
                score += 5
        if cand["cls"] == "CodeDefect":
            score += sum(c.n[x].get("count", 1) for x in c.inn(su, "EMITTED_BY"))
    return score


def evidence(c, cand, onset, sym_services):
    ev = []
    if onset and cand["time"]:
        if cand["time"] <= onset[0] + timedelta(seconds=cand["tol"]):
            ev.append(dict(type="TemporalPrecedence", detail=f"cause {cand['time'].isoformat()} <= first symptom "
                           f"{onset[0].isoformat()} (+/-{cand['tol']} s)", src=[sorted(cand['src'])[0], onset[2]]))
    services = set().union(*[c.services_of_dep(d) for d in cand["deps"]]) if cand["deps"] else set()
    if services:
        r = c.drv.execute_query(
            "MATCH (s:Service {case_id:$c}) WHERE s.name IN $sym "
            "MATCH (t:Service {case_id:$c}) WHERE t.name IN $aff "
            "MATCH p = shortestPath((s)-[:CALLS*0..4]->(t)) "
            "RETURN [n IN nodes(p) | n.name] AS path ORDER BY length(p) LIMIT 1",
            c=c.cid, sym=sorted(sym_services), aff=sorted(services), database_=DB)[0]
        if r:
            ev.append(dict(type="DependencyPath", detail=" -> ".join(r[0]["path"]),
                           src=[f"{c.cid}|Service|{x}" for x in r[0]["path"]]))
    sig = []
    for s in services:
        su = f"{c.cid}|Service|{s}"
        for ls in c.inn(su, "EMITTED_BY") + c.inn(su, "ABOUT"):
            node = c.n[ls]
            if node["label"] == "LogSignal":
                sig.append(("LogError", node.get("first_seen"), ls, f"{node.get('count')} error lines: {(node.get('sample') or '')[:90]}"))
            elif node["label"] == "Alert":
                sig.append(("Alert", node.get("start"), ls, f"alert {node.get('name')}"))
            elif node["label"] == "MetricAnomaly":
                sig.append(("MetricAnomaly", node.get("onset"), ls, f"{node.get('metric')} {node.get('change_pct')}%"))
    for d in cand["deps"]:
        for rs in c.out(f"{c.cid}|Deployment|{d}", "OWNS"):
            for pod in c.out(rs, "OWNS"):
                p = c.n[pod]
                if p.get("status") not in (None, "Running") or str(p.get("restarts", "0")).split(" ")[0] not in ("0", ""):
                    sig.append(("PodStatus", p.get("start_time"), pod, f"pod {p['name']} {p.get('status')} restarts {p.get('restarts')}"))
                for e in c.inn(pod, "ABOUT") + c.inn(rs, "ABOUT"):
                    en = c.n[e]
                    if en["label"] == "Event" and en.get("type") == "Warning":
                        sig.append(("WarningEvent", en.get("first_seen_approx"), e, f"{en.get('reason')} x{en.get('count')}"))
    for kind, t, uid, detail in sig:
        if kind == cand["kind"] or kind not in ALLOWED[cand["cls"]] or uid in cand["src"]:
            continue
        ev.append(dict(type="CorroboratingSignal", kind=kind, detail=detail, src=[uid]))
        break
    return ev


SHAPES = Graph().parse(ROOT / "contracts/contracts.shacl.ttl")
ONTO = Graph().parse(ROOT / "ontology/proofops.ttl")
for _demo in (PO.dx_C06, PO.fault_C06):          # demo individuals are for Protege only, not for validation
    ONTO.remove((_demo, None, None))


def contract(cand, ev):
    g = Graph()
    d = PO["dx"]
    g.add((d, RDF.type, PO.Diagnosis)); g.add((d, RDF.type, PO[f"{cand['cls']}Diagnosis"]))
    for i, e in enumerate(ev):
        x = PO[f"ev{i}"]
        g.add((d, PO.hasEvidence, x)); g.add((x, RDF.type, PO[e["type"]]))
        if e.get("kind"):
            g.add((x, PO.signalKind, PO[e["kind"]]))
        for s in e["src"]:
            g.add((x, PROV.wasDerivedFrom, Literal(s)))
    ok, _, text = pyshacl.validate(g, shacl_graph=SHAPES, ont_graph=ONTO, inference="rdfs")
    missing = [k for k in ("TemporalPrecedence", "DependencyPath", "CorroboratingSignal") if f"Missing evidence: {k}" in text]
    return ("SUPPORTED" if ok else "PLAUSIBLE"), missing


def write(drv, cid, ranked):
    drv.execute_query("MATCH (d:Diagnosis {case_id:$c}) OPTIONAL MATCH (d)-[:HAS_EVIDENCE]->(e) DETACH DELETE d, e",
                      c=cid, database_=DB)
    for rank, x in enumerate(ranked[:3], start=1):
        uid = f"{cid}|Diagnosis|{rank}"
        drv.execute_query(
            "MATCH (k:Case {case_id:$c}) CREATE (d:Diagnosis {uid:$u, case_id:$c, rank:$rank, fault_class:$cls, "
            "cause_object:$obj, status:$st, missing:$miss, cause_kind:$kind, why:$why}) CREATE (d)-[:IN_CASE]->(k) "
            "WITH d UNWIND $srcs AS s MATCH (n {uid:s}) MERGE (d)-[:ABOUT_CAUSE]->(n)",
            c=cid, u=uid, rank=rank, cls=x["cls"], obj=x["obj"], st=x["status"], miss=x["missing"], kind=x["kind"],
            why=x["why"], srcs=sorted(x["src"])[:5], database_=DB)
        for i, e in enumerate(x["evidence"]):
            drv.execute_query(
                "MATCH (d:Diagnosis {uid:$u}) CREATE (e:Evidence {uid:$eu, case_id:$c, type:$t, kind:$k, detail:$det}) "
                "CREATE (d)-[:HAS_EVIDENCE]->(e) WITH e UNWIND $srcs AS s MATCH (n {uid:s}) MERGE (e)-[:DERIVED_FROM]->(n)",
                u=uid, eu=f"{uid}|ev{i}", c=cid, t=e["type"], k=e.get("kind"), det=e["detail"][:300], srcs=e["src"],
                database_=DB)


def main():
    load_dotenv(ROOT / ".env")
    drv = GraphDatabase.driver(os.getenv("NEO4J_URI", "bolt://localhost:7687"),
                               auth=(os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD")))
    ids = json.loads((ROOT / "data/processed/case_ids.json").read_text())
    todo = sys.argv[1:] or list(ids)
    out = {}
    for cid in todo:
        c = Case(drv, cid)
        onset, sym = symptoms(c)
        res = []
        for cand in candidates(c):
            ev = evidence(c, cand, onset, sym)
            st, miss = contract(cand, ev)
            res.append(dict(cand, evidence=ev, status=st, missing=miss, relevance=relevance(c, cand)))
        ranked = sorted(res, key=lambda x: (x["status"] != "SUPPORTED", len(x["missing"]), -x["relevance"],
                                            PRIORITY[x["kind"]], -x["strength"]))
        graph_first = sorted(res, key=lambda x: (PRIORITY[x["kind"]], -x["strength"]))
        write(drv, cid, ranked)
        top = ranked[0] if ranked else None
        out[cid] = {
            "symptom_services": sorted(sym), "onset": onset[0].isoformat() if onset else None,
            "n_candidates": len(res),
            "proofops": top and {k: top[k] for k in ("cls", "obj", "status", "missing", "kind", "why")},
            "proofops_top3": [x["obj"] for x in ranked[:3]],
            "graph_first": graph_first[0]["obj"] if graph_first else None,
            "graph_first_status": graph_first[0]["status"] if graph_first else None,
            "evidence": top and [{k: e[k] for k in ("type", "detail")} for e in top["evidence"]],
        }
        print(f"{cid}: {len(res):2d} candidates | top: {top and top['obj']:<28s} {top and top['cls']:<20s} "
              f"{top and top['status']:<10s} missing={top and top['missing']}" if top else f"{cid}: no candidates")
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results/diagnoses.json").write_text(json.dumps(out, indent=2, default=str))
    drv.close()
    print("wrote results/diagnoses.json and Diagnosis/Evidence nodes in Neo4j")


if __name__ == "__main__":
    main()
