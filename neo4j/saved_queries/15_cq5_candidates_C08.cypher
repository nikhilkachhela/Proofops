// 15_cq5_candidates_C08  (database: proofops)
// CQ5: all ranked candidates for one incident, proven vs plausible
MATCH (d:Diagnosis {case_id:'C08'})
RETURN d.rank AS rank, d.cause_object AS cause, d.fault_class AS fault_class, d.status AS verdict,
       d.missing AS missing_evidence, d.why AS why ORDER BY rank;
