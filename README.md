# ProofOps

**Don't just name the root cause. Prove it.**

ProofOps diagnoses failures in Kubernetes systems, and only calls a cause **proven** when an evidence contract is satisfied. Every diagnosis must show three things, each traced to its raw source:

1. **It happened first.** The cause state existed no later than the first symptom, within a stated tolerance.
2. **It is connected.** A call path links a symptomatic service to the affected component.
3. **Something else agrees.** A signal of a different kind corroborates it.

All three present means **SUPPORTED**. Anything missing means **PLAUSIBLE**, together with the list of what is missing.

The project uses both knowledge-graph stacks:
* **Neo4j** holds what was observed and finds the paths.
* **OWL + SHACL** hold what the evidence means, and decide whether a path counts as proof.

DAMG 6310 (Knowledge Graphs with GenAI/DBs), Northeastern University. Nikhil Kachhela and Divesh Naik.

## Results (60 real incidents, Cloud-OpsBench, Online Boutique)

The **43 test cases were never inspected** while writing the rules (dev = 17 cases). The answer key is used **only** by `scripts/evaluate.py`.

| Held-out test set (43 cases) | Symptom-only baseline | Graph-only (no contract) | **ProofOps** |
|---|---|---|---|
| Correct faulty component (top 1) | 9% | 23% | **77%** |
| Correct component in top 3 | | | **81%** |
| Correct fault class | | | **72%** |
| Evidence contract satisfied | | | **58%** |
| Of the satisfied ones, correct | | | **80%** |

**Known limits** (see `results/evaluation.md`):
* Code defects are found by component (56%), but classified as performance faults (0% class accuracy), because telling them apart needs the source code.
* One in five proven answers is still wrong: a contract can be satisfied by the wrong cause.
* Timing is the weakest evidence type in the data.

## Architecture

```
Cloud-OpsBench v1.0.0 ──► verify (seed-42 sample, SHA-256 checks, answer key removed, opaque IDs C01..C60)
   ──► extract (kubectl text, logs, alerts, metrics; 3 clock formats normalized)
   ──► resolve (pod → ReplicaSet → Deployment; ClusterIP / DNS → Service)
   ──► Neo4j incident graphs (every edge labeled observed / extracted / inferred)
   ──► diagnose: candidates → 3 evidence types → SHACL contract → verdict (written back to Neo4j)
   ──► evaluate against the benchmark answer key
OWL ontology (8 fault classes, 48 root causes, from the benchmark taxonomy) + SHACL contracts drive the verdicts.
```

## Competency questions

| # | Question | Answered by |
|---|---|---|
| CQ1 | Which component on a call path explains the symptom? | Neo4j path (`05_cq1_c03_paths`, `12_cq1_diagnosis_graph_C03`) |
| CQ2 | Which warnings came before the first symptom, and which are start-up noise? | Neo4j, temporal with ± tolerance (`07_cq2_c06_table`) |
| CQ3 | Which anomaly began first along the call chain? | Neo4j (`08_cq3_c09_table`) |
| CQ4 | What evidence must a diagnosis of fault class X carry, and which root causes does X cover? | SPARQL + OWL reasoning (`scripts/sparql_queries.py`) |
| CQ5 | Does a proposed diagnosis satisfy its contract, and if not, what is missing? | SHACL (`scripts/diagnose.py`) → `11_cq5_verdicts_all`, `15_cq5_candidates_C08` |
| CQ6 | For any piece of evidence, which raw source produced it? | Neo4j provenance (`13_cq6_evidence_provenance_C06`) |
| CQ7 | Across incidents, which evidence is most often missing, per fault class? | Neo4j aggregate (`14_cq7_missing_by_class`) |

## Run it

```bash
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt rdflib pyshacl owlrl
cp .env.example .env                                   # set NEO4J_PASSWORD; start Neo4j
python scripts/scale_selection.py --total 60 --download   # reproducible 60-case sample (seed 42)
python scripts/build_graph.py                          # 60 incident graphs into database 'proofops'
python scripts/build_ontology.py                       # OWL ontology + SHACL contracts from the benchmark taxonomy
python scripts/diagnose.py                             # verdicts for every case, written to Neo4j + results/
python scripts/evaluate.py                             # scoring vs the answer key -> results/evaluation.md
python scripts/sparql_queries.py AdmissionFault        # the semantic competency questions
python scripts/profile_data.py --no-download           # data checks (checksums, integrity, coverage)
```

Saved Neo4j queries are in `neo4j/saved_queries/`. Import them in Neo4j Desktop (Query → saved queries → upload).

## Layout

| Path | What it is |
|---|---|
| `scripts/` | selection, graph build, ontology build, diagnosis engine, evaluation, SPARQL, data profiling |
| `ontology/proofops.ttl` | OWL ontology (open in Protégé; start HermiT to see `dx_C06` classified) |
| `contracts/contracts.shacl.ttl` | evidence contracts (base + one per fault class) |
| `results/` | `diagnoses.json`, `evaluation.md`, `per_case.csv` |
| `docs/` | data notes, data profile, phase-1 data slice |
| `prototype/` | early prototype on hand-written cases (reference only) |
