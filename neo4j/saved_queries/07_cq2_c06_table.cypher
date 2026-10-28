// 07_cq2_c06_table  (database: proofops)
MATCH (ls:LogSignal {case_id:'C06'})-[:ABOUT]->(:Service)
WITH min(datetime(ls.first_seen)) AS symptom_onset
MATCH (ev:Event {case_id:'C06', type:'Warning'})-[:ABOUT]->(r)
WHERE datetime(ev.first_seen_approx) <= symptom_onset + duration({seconds: ev.time_uncertainty_s})
RETURN ev.reason AS reason, labels(r)[0] + ':' + r.name AS about, ev.count AS times,
       left(ev.message, 110) AS message, ev.time_uncertainty_s AS uncertainty_s
ORDER BY times DESC;
