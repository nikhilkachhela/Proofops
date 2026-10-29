// 11_cq5_verdicts_all  (database: proofops)
// CQ5: verdict for every incident (top diagnosis), with what is missing
MATCH (d:Diagnosis {rank: 1})
RETURN d.case_id AS case, d.fault_class AS fault_class, d.cause_object AS cause,
       d.status AS verdict, d.missing AS missing_evidence, d.why AS why
ORDER BY case;
