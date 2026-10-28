// 08_cq3_c09_table  (database: proofops)
MATCH (m:MetricAnomaly {case_id:'C09'})-[:ABOUT]->(t)
RETURN m.onset AS onset, labels(t)[0] + ':' + t.name AS entity, m.metric AS metric,
       m.baseline AS baseline, m.peak AS peak, m.change_pct AS change_pct
ORDER BY onset;
