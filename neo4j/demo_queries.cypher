// ProofOps — demo queries for Neo4j Browser / Neo4j Desktop
// Database: proofops   (in Browser, type  :use proofops  first)
//
// Pick a case by setting a parameter, e.g.
//   :param case => 'C06'
// Good demo cases:
//   C03 = a Service whose selector matches no pod (endpoints empty)
//   C06 = a Deployment that references a ServiceAccount that does not exist
//   C09 = a latency incident with metric anomalies and alerts
// (Case IDs are opaque on purpose; the mapping lives in data/processed/case_ids.json.)


// ---------------------------------------------------------------- 0. Schema
CALL db.schema.visualization();


// ---------------------------------------------------------------- 0b. What is in the graph
MATCH (n) RETURN labels(n)[0] AS label, count(*) AS nodes ORDER BY nodes DESC;


// ---------------------------------------------------------------- 1. One case drawn as a graph
// Kubernetes objects + call graph (events and log signals hidden to keep it readable)
MATCH p = (a {case_id: $case})-[r]->(b)
WHERE NOT type(r) IN ['IN_CASE', 'ABOUT', 'EMITTED_BY'] AND NOT a:Event AND NOT a:LogSignal
RETURN p;


// 1b. Same case, only the "interesting" evidence: warnings still firing, error log signals
//     that point at a Service, alerts, metric anomalies, and what they are about.
MATCH (c:Case {case_id: $case})
MATCH p = (e)-[:ABOUT]->(target)
WHERE e.case_id = $case
  AND ( (e:Event AND e.type = 'Warning'
         AND datetime(e.last_seen_approx) >= datetime(c.snapshot_time) - duration({seconds: 60}))
        OR e:LogSignal OR e:Alert OR e:MetricAnomaly )
OPTIONAL MATCH q = (e)-[:EMITTED_BY]->(:Service)
RETURN p, q;


// ---------------------------------------------------------------- CQ1
// Dependency paths from a suspicious resource to the service that shows the symptom.
// "Suspicious" = target of a Warning event that is still firing (last seen <= 60 s before
// the snapshot), OR a Service with no endpoints, OR a ServiceAccount that is referenced
// but does not exist. "Symptomatic" = a caller whose error logs name the service.
MATCH (c:Case {case_id: $case})
MATCH (r {case_id: $case})
WHERE EXISTS {
        MATCH (ev:Event {type: 'Warning'})-[:ABOUT]->(r)
        WHERE datetime(ev.last_seen_approx) >= datetime(c.snapshot_time) - duration({seconds: 60}) }
   OR (r:Service AND r.has_endpoints = false)
   OR (r:ServiceAccount AND r.exists = false)
MATCH p = (sym:Service)-[:CALLS*1..3]->(svc:Service)-[:SELECTS|OWNS|USES_ACCOUNT*0..3]->(r)
WHERE EXISTS { MATCH (ls:LogSignal)-[:EMITTED_BY]->(sym) MATCH (ls)-[:ABOUT]->(svc) }
RETURN p;

// CQ1 as a table
MATCH (c:Case {case_id: $case})
MATCH (r {case_id: $case})
WHERE EXISTS {
        MATCH (ev:Event {type: 'Warning'})-[:ABOUT]->(r)
        WHERE datetime(ev.last_seen_approx) >= datetime(c.snapshot_time) - duration({seconds: 60}) }
   OR (r:Service AND r.has_endpoints = false)
   OR (r:ServiceAccount AND r.exists = false)
MATCH p = (sym:Service)-[:CALLS*1..3]->(svc:Service)-[:SELECTS|OWNS|USES_ACCOUNT*0..3]->(r)
WHERE EXISTS { MATCH (ls:LogSignal)-[:EMITTED_BY]->(sym) MATCH (ls)-[:ABOUT]->(svc) }
RETURN labels(r)[0] AS suspicious_kind, r.name AS suspicious_resource,
       svc.name AS failing_service, sym.name AS symptomatic_caller,
       [n IN nodes(p) | labels(n)[0] + ':' + n.name] AS path
ORDER BY length(p);


// ---------------------------------------------------------------- CQ2
// Changes (warning events) before symptom onset, in time order.
// Symptom onset = first error log line that names a Service.
// Event times are approximate (+/- time_uncertainty_s, see docs/DATA_NOTES.md section 3).
MATCH (ls:LogSignal {case_id: $case})-[:ABOUT]->(:Service)
WITH min(datetime(ls.first_seen)) AS symptom_onset
MATCH (ev:Event {case_id: $case, type: 'Warning'})-[:ABOUT]->(r)
WHERE datetime(ev.first_seen_approx) <= symptom_onset + duration({seconds: ev.time_uncertainty_s})
RETURN ev.first_seen_approx AS first_seen, ev.last_seen_approx AS last_seen, ev.count AS times,
       ev.reason AS reason, labels(r)[0] + ':' + r.name AS about, left(ev.message, 120) AS message,
       symptom_onset,
       CASE WHEN datetime(ev.first_seen_approx) < symptom_onset - duration({seconds: ev.time_uncertainty_s})
            THEN 'before (clear)' ELSE 'before or same time (within uncertainty)' END AS order_confidence
ORDER BY first_seen;


// ---------------------------------------------------------------- CQ3
// Anomalies in called services vs. their callers: which began first?
// (Most useful for latency cases: C09, C10.)
MATCH (mc:MetricAnomaly {case_id: $case})-[:ABOUT]->(callee:Service)
MATCH (caller:Service)-[:CALLS*1..3]->(callee)
MATCH (mk:MetricAnomaly)-[:ABOUT]->(caller)
WITH callee, caller, min(datetime(mc.onset)) AS callee_onset, min(datetime(mk.onset)) AS caller_onset
RETURN callee.name AS called_service, toString(callee_onset) AS callee_onset,
       caller.name AS caller_service, toString(caller_onset) AS caller_onset,
       CASE WHEN callee_onset < caller_onset THEN 'called service first'
            WHEN callee_onset > caller_onset THEN 'caller first'
            ELSE 'same 5 s sample (tie)' END AS which_first
ORDER BY callee_onset, caller_onset;

// CQ3b: every anomaly in the case, earliest first
MATCH (m:MetricAnomaly {case_id: $case})-[:ABOUT]->(t)
RETURN m.onset AS onset, labels(t)[0] + ':' + t.name AS entity, m.metric AS metric,
       m.baseline AS baseline, m.peak AS peak, m.change_pct AS change_pct
ORDER BY onset;


// ---------------------------------------------------------------- Provenance
// Where did a fact come from? Every node has `source`, every relationship has `derivation` + `source`.
MATCH (a {case_id: $case})-[r]->(b)
WHERE type(r) <> 'IN_CASE'
RETURN type(r) AS rel, r.derivation AS derivation, count(*) AS n, collect(DISTINCT r.source)[0..2] AS example_sources
ORDER BY rel, derivation;
