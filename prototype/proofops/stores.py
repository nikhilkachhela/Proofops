"""Two interchangeable graph stores with the same API:
  NxStore     - in-memory (NetworkX), for tests and offline demos
  Neo4jStore  - Neo4j via Cypher, the real property-graph backend
"""
import os
import networkx as nx
from .graph_builder import STRUCTURAL
from .thesaurus import fault_type_for

SIGNAL_LABELS = ("LogSignal", "MetricAnomaly", "RuntimeEvent")


class NxStore:
    def __init__(self, graph: nx.MultiDiGraph):
        self.g = graph

    def symptom_onset(self):
        alerts = [(d["time"], n) for n, d in self.g.nodes(data=True) if d["label"] == "Alert"]
        return min(alerts) if alerts else (None, None)

    def candidate_causes(self):
        # Root-cause candidates: changes anywhere, or saturation of infrastructure (nodes).
        # Pod-level runtime events (restarts, OOMKilled, back-off) are EFFECTS: they are used
        # as corroborating evidence, never proposed as root causes.
        out = []
        for n, d in self.g.nodes(data=True):
            if d["label"] not in ("ChangeEvent", "RuntimeEvent", "MetricAnomaly"):
                continue
            targets = [v for _, v, k in self.g.out_edges(n, keys=True) if k in ("ABOUT", "FOR")]
            for t in targets:
                if d["label"] != "ChangeEvent" and not t.startswith("node:"):
                    continue
                out.append({"cause_id": n, "object_id": t, "time": d["time"], "modality": d["label"],
                            "signal_type": d["signal_type"],
                            "fault_type": fault_type_for(d["signal_type"], d.get("message", "")),
                            "source": d["source"]})
        return out

    def _structural(self):
        h = nx.Graph()
        for a, b, k in self.g.edges(keys=True):
            if k in STRUCTURAL:
                h.add_edge(a, b)
        return h

    def dependency_path(self, a, b):
        h = self._structural()
        try:
            return nx.shortest_path(h, a, b)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    def signals_on(self, components):
        comps = set(components)
        for c in list(comps):  # include pods selected by services on the path
            if c.startswith("service:"):
                comps.update(v for _, v, k in self.g.out_edges(c, keys=True) if k == "SELECTS")
        out = []
        for n, d in self.g.nodes(data=True):
            if d["label"] not in SIGNAL_LABELS:
                continue
            hits = [v for _, v, k in self.g.out_edges(n, keys=True)
                    if k in ("EMITTED_BY", "MENTIONS", "FOR", "ABOUT") and v in comps]
            if hits:
                out.append({"signal_id": n, "modality": d["label"], "signal_type": d["signal_type"],
                            "time": d["time"], "on": hits[0], "source": d["source"],
                            "quote": d.get("quote") or d.get("message") or d.get("metric")})
        return sorted(out, key=lambda s: s["time"])


class Neo4jStore:
    """Same API, backed by Neo4j. Call load(graph) once per case."""
    def __init__(self, uri=None, user=None, password=None, database=None):
        from neo4j import GraphDatabase
        self.driver = GraphDatabase.driver(uri or os.getenv("NEO4J_URI", "bolt://localhost:7687"),
                                           auth=(user or os.getenv("NEO4J_USER", "neo4j"),
                                                 password or os.environ["NEO4J_PASSWORD"]))
        self.db = database or os.getenv("NEO4J_DATABASE", "neo4j")

    def _run(self, q, **params):
        with self.driver.session(database=self.db) as s:
            return [r.data() for r in s.run(q, **params)]

    def load(self, graph: nx.MultiDiGraph, case_id: str):
        self._run("MATCH (n {case_id:$c}) DETACH DELETE n", c=case_id)
        for n, d in graph.nodes(data=True):
            props = {k: v for k, v in d.items() if k != "label" and v is not None}
            self._run(f"MERGE (x:{d['label']} {{id:$id, case_id:$c}}) SET x += $p", id=n, c=case_id, p=props)
        for a, b, k, d in graph.edges(keys=True, data=True):
            self._run(f"MATCH (x {{id:$a, case_id:$c}}), (y {{id:$b, case_id:$c}}) MERGE (x)-[r:{k}]->(y) SET r.source=$s",
                      a=a, b=b, c=case_id, s=d.get("source"))
        self.case_id = case_id

    def symptom_onset(self):
        r = self._run("MATCH (a:Alert {case_id:$c}) RETURN a.time AS t, a.id AS id ORDER BY t LIMIT 1", c=self.case_id)
        return (r[0]["t"], r[0]["id"]) if r else (None, None)

    def candidate_causes(self):
        rows = self._run("""
            MATCH (e {case_id:$c})-[:ABOUT|FOR]->(t)
            WHERE e:ChangeEvent OR ((e:RuntimeEvent OR e:MetricAnomaly) AND t:Node)
            RETURN e.id AS cause_id, t.id AS object_id, e.time AS time, labels(e)[0] AS modality,
                   e.signal_type AS signal_type, coalesce(e.message,'') AS message, e.source AS source""", c=self.case_id)
        for r in rows:
            r["fault_type"] = fault_type_for(r["signal_type"], r.pop("message"))
        return rows

    def dependency_path(self, a, b):
        r = self._run("""
            MATCH (x {id:$a, case_id:$c}), (y {id:$b, case_id:$c})
            MATCH p = shortestPath((x)-[:OWNS|SELECTS|RUNS_ON|MOUNTS|CALLS*..10]-(y))
            RETURN [n IN nodes(p) | n.id] AS path""", a=a, b=b, c=self.case_id)
        return r[0]["path"] if r else None

    def signals_on(self, components):
        rows = self._run("""
            MATCH (svc {case_id:$c}) WHERE svc.id IN $ids
            OPTIONAL MATCH (svc)-[:SELECTS]->(pod)
            WITH collect(DISTINCT svc.id) + collect(DISTINCT pod.id) AS comps
            MATCH (s {case_id:$c})-[:EMITTED_BY|MENTIONS|FOR|ABOUT]->(t)
            WHERE (s:LogSignal OR s:MetricAnomaly OR s:RuntimeEvent) AND t.id IN comps
            RETURN DISTINCT s.id AS signal_id, labels(s)[0] AS modality, s.signal_type AS signal_type,
                   s.time AS time, t.id AS on, s.source AS source,
                   coalesce(s.quote, s.message, s.metric) AS quote
            ORDER BY time""", ids=list(components), c=self.case_id)
        seen, out = set(), []
        for r in rows:
            if r["signal_id"] not in seen:
                seen.add(r["signal_id"]); out.append(r)
        return out
