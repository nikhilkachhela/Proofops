// 06_cq2_c06_graph  (database: proofops)
MATCH p = (d {case_id:'C06'})-[:USES_ACCOUNT]->(sa:ServiceAccount {case_id:'C06'})
WHERE sa.exists = false
RETURN p;
