// 03_cq1_c03_graph  (database: proofops)
MATCH p = (a {case_id: 'C03'})-[r]->(b)
WHERE NOT type(r) IN ['IN_CASE','ABOUT','EMITTED_BY'] AND NOT a:Event AND NOT a:LogSignal
RETURN p;
