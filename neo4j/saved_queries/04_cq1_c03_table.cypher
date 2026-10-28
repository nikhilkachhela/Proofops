// 04_cq1_c03_table  (database: proofops)
MATCH (ls:LogSignal {case_id:'C03'})-[r:ABOUT]->(s:Service)
MATCH (ls)-[:EMITTED_BY]->(c)
RETURN c.name AS from_service, s.name AS about, ls.count AS lines,
       r.derivation AS how_linked, s.endpoints AS endpoints, ls.source AS source
ORDER BY lines DESC;
