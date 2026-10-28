# Prototype (reference only)

Early end-to-end prototype on two HAND-WRITTEN demo incidents: evidence assembly, contract
checks (Python + SHACL), three agent conditions, Streamlit app. It uses its own simple case
format, not the real Cloud-OpsBench graph.

What moved into the main project:
- ontology/proofops.ttl, ontology/thesaurus.ttl  -> ../ontology/
- contracts/contracts.shacl.ttl                  -> ../contracts/
- scripts/profile_data.py, proofops/thesaurus.py -> ../scripts/, ../proofops/

Next: port evidence assembly + contract checking onto the real Neo4j graph (scripts/check_contracts.py).
