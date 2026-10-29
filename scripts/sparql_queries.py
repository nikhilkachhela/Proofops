"""SPARQL over the ProofOps ontology + contracts (the semantic half of the competency questions).

CQ4a  Which root causes does each fault class cover? (taxonomy)
CQ4b  What evidence must a diagnosis of class X carry, and which signal kinds may corroborate it? (contracts)
CQ4c  Reasoning: what is a diagnosis of 'missing service account' classified as? (OWL RL inference)

Usage: .venv/bin/python scripts/sparql_queries.py [FaultClass]      e.g. AdmissionFault
"""
import sys
from pathlib import Path
from rdflib import Graph
import owlrl

ROOT = Path(__file__).resolve().parent.parent
PFX = """PREFIX po: <https://example.org/proofops#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX sh: <http://www.w3.org/ns/shacl#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
"""

def run(g, title, q):
    print(f"\n=== {title} ===")
    for row in g.query(PFX + q):
        print("  " + " | ".join(str(x).split("#")[-1] if x is not None else "-" for x in row))

def main():
    cls = sys.argv[1] if len(sys.argv) > 1 else "AdmissionFault"
    onto = Graph().parse(ROOT / "ontology/proofops.ttl")
    shapes = Graph().parse(ROOT / "contracts/contracts.shacl.ttl")

    run(onto, "CQ4a: fault classes and how many root causes each covers", """
        SELECT ?class (COUNT(?rc) AS ?root_causes) WHERE {
          ?class rdfs:subClassOf po:Fault . ?rc rdfs:subClassOf ?class }
        GROUP BY ?class ORDER BY DESC(?root_causes)""")
    run(onto, f"CQ4a: root causes under {cls}", f"""
        SELECT ?rc ?label WHERE {{ ?rc rdfs:subClassOf po:{cls} ; skos:prefLabel ?label }} ORDER BY ?label""")
    run(shapes, "CQ4b: evidence every diagnosis must carry (base contract)", """
        SELECT ?required WHERE { po:DiagnosisContract sh:property ?p . ?p sh:qualifiedValueShape ?v . ?v sh:class ?required }""")
    run(shapes, f"CQ4b: signal kinds allowed to corroborate a {cls} diagnosis", f"""
        SELECT ?kind WHERE {{ po:{cls}Contract sh:property ?p . ?p sh:in ?list . ?list rdf:rest*/rdf:first ?kind }}""")

    inferred = Graph().parse(ROOT / "ontology/proofops.ttl")
    owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(inferred)
    run(inferred, "CQ4c: inferred classes of dx_C06 (asserted only: Diagnosis about a missing-service-account fault)", """
        SELECT ?type WHERE { po:dx_C06 rdf:type ?type . FILTER(STRSTARTS(STR(?type), STR(po:))) }""")

if __name__ == "__main__":
    main()
