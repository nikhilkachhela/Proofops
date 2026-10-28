// 02_graph_size  (database: proofops)
MATCH (n) WITH count(n) AS nodes
MATCH ()-[r]->()
RETURN nodes, count(r) AS relationships;
