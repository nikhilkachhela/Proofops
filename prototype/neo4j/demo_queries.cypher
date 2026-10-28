// ProofOps demo queries. Load first:  python scripts/load_neo4j.py data/cases/*

// The model
CALL db.schema.visualization();

// One incident as a graph
MATCH (n {case_id:'demo-redis-config'})-[r]->(m) RETURN n, r, m;

// CQ1: dependency path from the changed object to the symptomatic service (multi-hop)
MATCH (x:ConfigMap {case_id:'demo-redis-config', name:'redis-config'}), (y:Service {case_id:'demo-redis-config', name:'frontend'})
MATCH p = shortestPath((x)-[:OWNS|SELECTS|RUNS_ON|MOUNTS|CALLS*..10]-(y))
RETURN p;

// CQ2: changes before symptom onset, in time order (temporal)
MATCH (a:Alert {case_id:'demo-redis-config'}) WITH min(a.time) AS onset
MATCH (e:ChangeEvent {case_id:'demo-redis-config'})-[:ABOUT]->(o)
WHERE e.time < onset
RETURN e.time AS time, o.id AS changed, e.message AS change ORDER BY time;

// CQ3: typed signals on the path, with their source line (provenance)
MATCH (s {case_id:'demo-redis-config'})-[:EMITTED_BY|MENTIONS|FOR|ABOUT]->(t)
WHERE (s:LogSignal OR s:MetricAnomaly OR s:RuntimeEvent)
RETURN s.time AS time, labels(s)[0] AS kind, s.signal_type AS type, t.id AS on, s.source AS source ORDER BY time;
