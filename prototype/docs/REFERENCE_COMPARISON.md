# How ProofOps relates to the reference projects

| | MediGraph AI | SecurityGraphAI | **ProofOps** |
|---|---|---|---|
| Domain | Healthcare (synthetic EHR) | Cybersecurity (CVE/CWE) | Cloud reliability (Kubernetes incidents) |
| Data | Synthea via Snowflake | NVD API, CWE, OWASP | Cloud-OpsBench (MIT, verified ground truth) |
| Graph store | Neo4j | Neo4j | Neo4j **+ OWL/SHACL** |
| App | Streamlit tabs | Streamlit + agents | Streamlit tabs + agent conditions |
| Reasoning | NL → Cypher lookups | GraphRAG, agent investigation, attack paths | Multi-hop dependency paths + **contract-gated conclusions** |
| Semantic layer | none | none | OWL taxonomy with inheritance, SKOS thesaurus, SHACL evidence contracts, PROV-O provenance |
| Evaluation | data completeness | BLEU/EM/faithfulness on 20 questions | accuracy, **evidence closure**, unsupported-claim rate, cost; controlled comparison |

**What we kept from the references:**
* From MediGraph: the Streamlit tab structure (overview, graph explorer, Q&A, evaluation).
* From SecurityGraphAI: the agents/ETL/evaluation split, and an investigation agent that produces a report.

**What we added:**
* A semantic layer that decides whether a conclusion is proven.
* Provenance on every evidence item.
* An evaluation that measures proof, not just answers.
