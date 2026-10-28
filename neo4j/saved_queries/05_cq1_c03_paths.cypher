// 05_cq1_c03_paths  (database: proofops)
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
