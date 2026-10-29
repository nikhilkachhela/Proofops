// 12_cq1_diagnosis_graph_C03  (database: proofops)
// CQ1 + CQ6: one diagnosis, its evidence, and the raw nodes each item came from
MATCH p = (d:Diagnosis {case_id:'C03', rank:1})-[:HAS_EVIDENCE]->(e:Evidence)-[:DERIVED_FROM]->(src)
RETURN p;
