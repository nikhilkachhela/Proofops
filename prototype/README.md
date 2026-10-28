# ProofOps

**Don't just name the root cause. Prove it.**
ProofOps is evidence-contracted root-cause diagnosis for Kubernetes incidents, built on a hybrid knowledge graph:
* **Neo4j** holds what was observed in each incident.
* **An OWL ontology and SHACL evidence contracts** decide whether a proposed cause counts as proven.

DAMG 6310, Knowledge Graphs with GenAI/DBs. Team: Nikhil Kachhela and Divesh Naik.

## The idea in one example
An agent proposes "node-2 CPU" as the root cause. ProofOps checks the evidence contract:

| Requirement | Result |
|---|---|
| Dependency path from node-2 to the frontend | ✅ |
| Corroborating signal (CPU metric) | ✅ |
| **Happened before the first symptom?** | ❌ CPU rose at 10:20:30; users were hit at 10:15 |

Verdict: **PLAUSIBLE — missing: TemporalPrecedence**.

The real cause is the ConfigMap change at 10:02. It is **SUPPORTED** by all three: it came first, there is a path (ConfigMap → redis pod → redis-cart → cartservice → frontend), and the log line "max number of clients reached" corroborates it.

## Quick start (no database needed)
```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python tests/test_pipeline.py                          # 6 tests
python scripts/diagnose.py data/cases/demo-redis-config
python scripts/diagnose.py data/cases/demo-redis-config --check node:node-2
python scripts/run_experiment.py data/cases            # baseline vs graph vs ProofOps
streamlit run app/streamlit_app.py                     # the app
```

## With Neo4j and Protégé
1. Copy `.env.example` to `.env` and set `NEO4J_PASSWORD`.
2. Run `python scripts/load_neo4j.py data/cases/*`.
3. Run the queries in `neo4j/demo_queries.cypher` in Neo4j Query. This gives the schema, one incident drawn as a graph, and CQ1–CQ3.
4. Run `python scripts/diagnose.py data/cases/demo-redis-config --neo4j`. This is the same diagnosis, with Neo4j as the graph store.
5. In Protégé, open `ontology/proofops.ttl` and start the HermiT reasoner. `dx_demo` is inferred to be a `ConfigurationFaultDiagnosis` and therefore a `ChangeInducedFaultDiagnosis`, so it inherits that contract.

## Project layout
| Path | What it does |
|---|---|
| `proofops/thesaurus.py`, `ontology/thesaurus.ttl` | Controlled vocabulary + thesaurus: log-message variants → signal types |
| `proofops/entity_resolution.py` | Pod name → ReplicaSet → Deployment; host:port mentions → Service |
| `proofops/log_extraction.py` | Raw log line → typed evidence (thesaurus first, optional LLM with verbatim-quote check) |
| `proofops/graph_builder.py` | Case files → time-ordered incident graph (labels = ontology class names) |
| `proofops/stores.py` | Same API over NetworkX (offline) or **Neo4j** (Cypher) |
| `proofops/evidence.py` | Builds TemporalPrecedence, DependencyPath and CorroboratingSignal evidence, each with its source |
| `proofops/contracts.py`, `contracts/contracts.shacl.ttl` | Evidence contracts, checked with **pyshacl** (Python fallback if not installed) |
| `ontology/proofops.ttl` | OWL: resources, signals, fault taxonomy, evidence types, defined diagnosis classes |
| `proofops/agent.py` | Three conditions: `baseline`, `graph`, `proofops` (heuristic by default; `--llm` optional) |
| `scripts/run_experiment.py` | Scores conditions: accuracy, evidence closure, unsupported-claim rate |
| `adapters/cloudopsbench.py` | Converts Cloud-OpsBench cases into this format (TODOs to complete against real files) |
| `app/streamlit_app.py` | Tabs: Overview, Incident graph, Diagnose, Check a hypothesis, Ontology & contracts, Evaluation |

## Honesty notes
* **The two cases in `data/cases/` are hand-written demo cases** for testing the pipeline. Real results must come from **Cloud-OpsBench** (MIT, `LLM4Ops/Cloud-OpsBench` on Hugging Face) once the adapter is completed.
* **Ground truth (`ground_truth.json`) is used only for scoring** and is never shown to the agent.
* **Tested here:** the core pipeline (tests pass).
* **Written but not yet run against live services:** the Neo4j store, the pyshacl path, and the Streamlit UI.

## Next steps
1. Download 10 Online Boutique cases and complete `adapters/cloudopsbench.py` (see `CLAUDE.md`).
2. Add contracts for 6–8 fault types whose evidence exists in the snapshots.
3. Plug in the LLM agent (`--llm`) and run the three-condition experiment on about 60 cases.
