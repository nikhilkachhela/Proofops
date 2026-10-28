// All midpoint demo queries. Select database 'proofops' first.

// ===== 01_schema =====
CALL db.schema.visualization();

// ===== 02_graph_size =====
MATCH (n) WITH count(n) AS nodes
MATCH ()-[r]->()
RETURN nodes, count(r) AS relationships;

// ===== 03_cq1_c03_graph =====
MATCH p = (a {case_id: 'C03'})-[r]->(b)
WHERE NOT type(r) IN ['IN_CASE','ABOUT','EMITTED_BY'] AND NOT a:Event AND NOT a:LogSignal
RETURN p;

// ===== 04_cq1_c03_table =====
MATCH (ls:LogSignal {case_id:'C03'})-[r:ABOUT]->(s:Service)
MATCH (ls)-[:EMITTED_BY]->(c)
RETURN c.name AS from_service, s.name AS about, ls.count AS lines,
       r.derivation AS how_linked, s.endpoints AS endpoints, ls.source AS source
ORDER BY lines DESC;

// ===== 05_cq1_c03_paths =====
MATCH (c:Case {case_id:'C03'})
MATCH (r {case_id:'C03'})
WHERE EXISTS { MATCH (ev:Event {type:'Warning'})-[:ABOUT]->(r)
               WHERE datetime(ev.last_seen_approx) >= datetime(c.snapshot_time) - duration({seconds:60}) }
   OR (r:Service AND r.has_endpoints = false)
   OR (r:ServiceAccount AND r.exists = false)
MATCH p = (sym:Service)-[:CALLS*1..3]->(svc:Service)-[:SELECTS|OWNS|USES_ACCOUNT*0..3]->(r)
WHERE EXISTS { MATCH (ls:LogSignal)-[:EMITTED_BY]->(sym) MATCH (ls)-[:ABOUT]->(svc) }
RETURN labels(r)[0] AS suspicious_kind, r.name AS suspicious_resource, svc.name AS failing_service,
       sym.name AS symptomatic_caller, [n IN nodes(p) | labels(n)[0] + ':' + n.name] AS path
ORDER BY length(p);

// ===== 06_cq2_c06_graph =====
MATCH p = (d {case_id:'C06'})-[:USES_ACCOUNT]->(sa:ServiceAccount {case_id:'C06'})
WHERE sa.exists = false
RETURN p;

// ===== 07_cq2_c06_table =====
MATCH (ls:LogSignal {case_id:'C06'})-[:ABOUT]->(:Service)
WITH min(datetime(ls.first_seen)) AS symptom_onset
MATCH (ev:Event {case_id:'C06', type:'Warning'})-[:ABOUT]->(r)
WHERE datetime(ev.first_seen_approx) <= symptom_onset + duration({seconds: ev.time_uncertainty_s})
RETURN ev.reason AS reason, labels(r)[0] + ':' + r.name AS about, ev.count AS times,
       left(ev.message, 110) AS message, ev.time_uncertainty_s AS uncertainty_s
ORDER BY times DESC;

// ===== 08_cq3_c09_table =====
MATCH (m:MetricAnomaly {case_id:'C09'})-[:ABOUT]->(t)
RETURN m.onset AS onset, labels(t)[0] + ':' + t.name AS entity, m.metric AS metric,
       m.baseline AS baseline, m.peak AS peak, m.change_pct AS change_pct
ORDER BY onset;

// ===== 09_provenance_all =====
MATCH ()-[r]->() WHERE type(r) <> 'IN_CASE'
RETURN r.derivation AS how_we_know, count(*) AS edges
ORDER BY edges DESC;

// ===== 10_nodes_by_label =====
MATCH (n) RETURN labels(n)[0] AS label, count(*) AS nodes ORDER BY nodes DESC;
