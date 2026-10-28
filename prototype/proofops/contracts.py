"""Evidence contracts: the 'definition of done' for each fault type.

Formal version: contracts/contracts.shacl.ttl (validated with pyshacl when installed).
This module also provides an equivalent pure-Python check so the pipeline runs anywhere.
Contracts are INHERITED down the fault taxonomy (as OWL subclassing does in ontology/proofops.ttl).
"""
from pathlib import Path
from .thesaurus import FAULT_PARENTS

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = ["TemporalPrecedence", "DependencyPath", "CorroboratingSignal"]  # declared on Fault, inherited by all

# Allowed corroborating signal types, declared at the most general fault type that needs them.
ALLOWED = {
    "Fault": set(),
    "ChangeInducedFault": {"ConnectionFailure", "ConnectionPoolExhausted", "ConfigError"},
    "ConfigurationFault": set(),
    "ResourceLimitFault": {"OutOfMemory", "CrashLoop", "MemorySaturation"},
    "ResourceFault": {"CPUSaturation", "MemorySaturation", "Timeout"},
    "ResourceExhaustion": set(),
    "DependencyFault": {"ConnectionFailure", "UpstreamUnavailable", "Timeout"},
}

def lineage(fault_type):
    out = [fault_type]
    while out[-1] in FAULT_PARENTS:
        out.append(FAULT_PARENTS[out[-1]])
    return out

def allowed_signals(fault_type):
    s = set()
    for t in lineage(fault_type):
        s |= ALLOWED.get(t, set())
    return s

def check(diagnosis: dict) -> dict:
    """Return {'status': 'SUPPORTED'|'PLAUSIBLE', 'missing': [...], 'engine': 'shacl'|'python'}."""
    try:
        return check_shacl(diagnosis)
    except ImportError:
        return check_python(diagnosis)

def check_python(diagnosis: dict) -> dict:
    have = {e["type"] for e in diagnosis["evidence"] if e.get("sources")}
    missing = [r for r in REQUIRED if r not in have]
    return {"status": "SUPPORTED" if not missing else "PLAUSIBLE", "missing": missing, "engine": "python"}

# ---------- RDF + SHACL (formal path) ----------
def to_rdf(diagnosis: dict):
    from rdflib import Graph, Namespace, URIRef, Literal, RDF
    PO = Namespace("https://example.org/proofops#")
    PROV = Namespace("http://www.w3.org/ns/prov#")
    g = Graph(); g.bind("po", PO); g.bind("prov", PROV)
    h = diagnosis["hypothesis"]
    d = PO["diagnosis"]
    g.add((d, RDF.type, PO.Diagnosis))
    g.add((d, RDF.type, PO[f"{h['fault_type']}Diagnosis"]))
    g.add((d, PO.aboutCause, Literal(h["object_id"])))
    for i, e in enumerate(diagnosis["evidence"]):
        en = PO[f"evidence_{i}"]
        g.add((d, PO.hasEvidence, en))
        g.add((en, RDF.type, PO[e["type"]]))
        g.add((en, PO.detail, Literal(e["detail"])))
        if e.get("signal_type"):
            g.add((en, PO.signalType, PO[e["signal_type"]]))
        for s in e.get("sources", []):
            g.add((en, PROV.wasDerivedFrom, Literal(str(s))))
    return g

def check_shacl(diagnosis: dict) -> dict:
    import pyshacl  # raises ImportError if not installed -> python fallback
    from rdflib import Graph
    shapes = Graph().parse(ROOT / "contracts" / "contracts.shacl.ttl")
    ont = Graph().parse(ROOT / "ontology" / "proofops.ttl")
    conforms, report_graph, report_text = pyshacl.validate(
        to_rdf(diagnosis), shacl_graph=shapes, ont_graph=ont, inference="rdfs")
    missing = []
    for r in REQUIRED:
        if f"Missing evidence: {r}" in report_text:
            missing.append(r)
    if not conforms and not missing:
        missing = ["CorroboratingSignal (type not allowed for this fault)"]
    return {"status": "SUPPORTED" if conforms else "PLAUSIBLE", "missing": missing,
            "engine": "shacl", "report": report_text}
