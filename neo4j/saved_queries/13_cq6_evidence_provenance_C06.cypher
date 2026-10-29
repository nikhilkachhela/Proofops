// 13_cq6_evidence_provenance_C06  (database: proofops)
// CQ6: for each evidence item, which raw source produced it
MATCH (d:Diagnosis {case_id:'C06', rank:1})-[:HAS_EVIDENCE]->(e:Evidence)
OPTIONAL MATCH (e)-[:DERIVED_FROM]->(src)
RETURN e.type AS evidence, e.kind AS signal_kind, e.detail AS detail,
       collect(labels(src)[0] + ':' + src.name) AS derived_from, collect(DISTINCT src.source)[0] AS raw_source;
