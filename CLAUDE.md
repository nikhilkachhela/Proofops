# ProofOps — project brief for Claude

You are helping two graduate students (Nikhil Kachhela, Divesh Naik) build **ProofOps** for the Northeastern course **DAMG 6310 Knowledge Graphs with GenAI/DBs**. Explain what you're doing in plain English as you go. They are new to Neo4j and Protégé.

## The project in one paragraph
An AI agent diagnoses Kubernetes incidents. Each incident becomes a **time-ordered dependency graph** in **Neo4j** (services, pods, deployments, ConfigMaps, events, alerts, log signals, all with timestamps). An **OWL ontology** (opened in Protégé) defines fault types, evidence types and diagnostic statuses. A **SHACL "evidence contract"** per fault type decides whether a proposed root cause is **supported** or only **plausible** (and lists what's missing). Every contract requires: (1) the cause happened before the symptoms, (2) a dependency path from the affected resource to the failing service, (3) a corroborating signal of a different kind (e.g., a log error backing a metric anomaly). Each evidence item must cite its source (PROV-O).

## Data
- **Cloud-OpsBench**, MIT license. Hugging Face: `LLM4Ops/Cloud-OpsBench`. Code, tools, MCP interface and evaluator: GitHub `LLM4Ops/Cloud-OpsBench`.
- 754 cases (Online Boutique 550, TrainTicket 204). **Use Online Boutique only.**
- Per case, under `benchmark/<system>/<category>/<case_id>/`: `metadata.json` (contains the ground truth), `tool_cache.json`, `raw_data/` (Kubernetes states, logs, alerts, metrics), and `code/`.
- `process-label/.../milestone.json` holds evidence labels. `golden-trajectory/` holds expert paths.

## Non-negotiable rules
1. **Never show ground truth to the agent.** Ground-truth fields in `metadata.json`, the `process-label/` files and the `golden-trajectory/` files are for **scoring only**. Keep them out of anything the agent reads, and don't use them to write contracts.
2. **Don't invent data or results.** If a file doesn't look the way this brief expects, stop, describe what you actually found, and adapt the plan.
3. **Ask before large downloads.** The full dataset is about 3.8 GB, so use `allow_patterns` to fetch only what's needed.
4. Neo4j credentials come from environment variables (`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`). Never hard-code passwords.
5. After each phase, stop, summarize what was built, and wait for a "continue".

## Phases

**Phase 0 – Setup.**
- Create a Python virtual environment and install `huggingface_hub neo4j rdflib pyshacl owlrl pandas`.
- Check that Neo4j is reachable at `bolt://localhost:7687`.
- Create the folders: `data/`, `scripts/`, `neo4j/`, `ontology/`, `contracts/`, `docs/`.

**Phase 1 – Get a small slice of data.**
- Download `index.jsonl` first.
- Pick about 10 Online Boutique cases across at least 4 categories (e.g., runtime, service, performance, admission).
- Download only those case folders, then clone the GitHub repo into `vendor/`.

**Phase 2 – Understand the data.**
- Open 3 cases and write `docs/DATA_NOTES.md`. It should cover what each file contains and which fields hold resources, dependencies, timestamps, logs and alerts.
- For each chosen fault type, record whether the three contract evidence items can actually be found in the snapshot.

**Phase 3 – Build the Neo4j graph.**
- Write `scripts/build_graph.py` to load the 10 cases into a Neo4j database named `proofops`. Create the database if possible; otherwise use the default and say so.
- Node labels: Case, Namespace, Service, Deployment, ReplicaSet, Pod, Node, ConfigMap, Secret, ServiceAccount, Event, Alert, LogSignal, MetricAnomaly.
- Relationships: OWNS, SELECTS, RUNS_ON, MOUNTS, USES_ACCOUNT, CALLS, EMITTED_BY, ABOUT, IN_CASE. Every node carries a `case_id`; events and signals carry timestamps.
- Use **entity resolution** to map pod names to their ReplicaSet and Deployment.
- Do **not** load ground-truth fields.
- Write `neo4j/demo_queries.cypher` with:
  - the schema view;
  - one case drawn as a graph;
  - CQ1: dependency paths from a changed resource to the symptomatic service;
  - CQ2: changes before symptom onset, in time order;
  - CQ3: upstream anomalies and which began first.

**Phase 4 – Ontology for Protégé.**
- Write `ontology/proofops.ttl` (OWL, Turtle) containing:
  - a fault-type taxonomy built from the benchmark's categories and root-cause names, with OWL subclassing so specific faults inherit from broader ones;
  - evidence types (TemporalPrecedence, DependencyPath, CorroboratingSignal);
  - diagnostic statuses (Supported, Plausible, Refuted, Abstained);
  - PROV-O alignment.
- Include a few demo individuals so the HermiT reasoner shows at least one inferred classification.
- Check that it parses with rdflib.

**Phase 5 – First evidence contract.**
- Choose one fault type whose evidence exists (from Phase 2). Write `contracts/<fault_type>.shacl.ttl`.
- Write `scripts/check_contract.py`. It takes a proposed diagnosis (a JSON file with the cause, the evidence items and their sources), converts it to RDF, validates it with pyshacl, and prints either SUPPORTED or PLAUSIBLE plus the list of missing evidence.
- Include one example that passes and one that fails.

**Phase 6 – README for the demo.**
- Write `README.md` with how to load and view everything:
  - Neo4j: which queries to run;
  - Protégé: open the file, start the reasoner, see the inferred types;
  - the contract checker.
- Add a 3-minute demo walkthrough, and list honestly what was built and what is still planned.

## Later (not now)
LLM log-to-evidence extraction, the agent with MCP tools (Cypher, SPARQL, SHACL), the three-condition experiment (standard agent vs graph-guided agent vs ProofOps), and evaluation with the benchmark's evaluator.
