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

// ===== 11_cq5_verdicts_all =====
// CQ5: verdict for every incident (top diagnosis), with what is missing
MATCH (d:Diagnosis {rank: 1})
RETURN d.case_id AS case, d.fault_class AS fault_class, d.cause_object AS cause,
       d.status AS verdict, d.missing AS missing_evidence, d.why AS why
ORDER BY case;

// ===== 12_cq1_diagnosis_graph_C03 =====
// CQ1 + CQ6: one diagnosis, its evidence, and the raw nodes each item came from
MATCH p = (d:Diagnosis {case_id:'C03', rank:1})-[:HAS_EVIDENCE]->(e:Evidence)-[:DERIVED_FROM]->(src)
RETURN p;

// ===== 13_cq6_evidence_provenance_C06 =====
// CQ6: for each evidence item, which raw source produced it
MATCH (d:Diagnosis {case_id:'C06', rank:1})-[:HAS_EVIDENCE]->(e:Evidence)
OPTIONAL MATCH (e)-[:DERIVED_FROM]->(src)
RETURN e.type AS evidence, e.kind AS signal_kind, e.detail AS detail,
       collect(labels(src)[0] + ':' + src.name) AS derived_from, collect(DISTINCT src.source)[0] AS raw_source;

// ===== 14_cq7_missing_by_class =====
// CQ7: across all incidents, which evidence is missing most often, per fault class
MATCH (d:Diagnosis {rank: 1})
RETURN d.fault_class AS fault_class, count(*) AS incidents,
       sum(CASE WHEN d.status = 'SUPPORTED' THEN 1 ELSE 0 END) AS supported,
       sum(CASE WHEN 'TemporalPrecedence' IN d.missing THEN 1 ELSE 0 END) AS missing_timing,
       sum(CASE WHEN 'DependencyPath' IN d.missing THEN 1 ELSE 0 END) AS missing_path,
       sum(CASE WHEN 'CorroboratingSignal' IN d.missing THEN 1 ELSE 0 END) AS missing_corroboration
ORDER BY incidents DESC;

// ===== 15_cq5_candidates_C08 =====
// CQ5: all ranked candidates for one incident, proven vs plausible
MATCH (d:Diagnosis {case_id:'C08'})
RETURN d.rank AS rank, d.cause_object AS cause, d.fault_class AS fault_class, d.status AS verdict,
       d.missing AS missing_evidence, d.why AS why ORDER BY rank;
