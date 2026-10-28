"""Load case graphs into Neo4j.   python scripts/load_neo4j.py data/cases/*
Requires NEO4J_PASSWORD (and optionally NEO4J_URI, NEO4J_USER, NEO4J_DATABASE) in the environment or .env."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass
from proofops.case_loader import load_case
from proofops.graph_builder import build_graph
from proofops.stores import Neo4jStore

store = Neo4jStore()
for case_dir in sys.argv[1:]:
    case = load_case(case_dir)
    g = build_graph(case)
    store.load(g, case["meta"]["case_id"])
    print(f"loaded {case['meta']['case_id']}: {g.number_of_nodes()} nodes, {g.number_of_edges()} relationships")
