// 09_provenance_all  (database: proofops)
MATCH ()-[r]->() WHERE type(r) <> 'IN_CASE'
RETURN r.derivation AS how_we_know, count(*) AS edges
ORDER BY edges DESC;
