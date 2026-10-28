"""Three diagnostic conditions compared in the ProofOps experiment.

  baseline  - reads signals without the graph; names the noisiest component
  graph     - uses the graph to find the closest upstream change; claims it without checking
  proofops  - same graph tools, but a cause may only be reported as SUPPORTED if its
              evidence contract is satisfied; otherwise it is PLAUSIBLE with the missing evidence listed

Runs in heuristic mode by default. With an API key and use_llm=True, the LLM orders the
candidate hypotheses (it never sees ground truth, and it cannot bypass the contract check).
"""
import json
from .case_loader import load_case
from .graph_builder import build_graph
from .stores import NxStore
from .evidence import assemble
from .contracts import check
from . import llm


def _rank_candidates(store, candidates, symptom_service, use_llm):
    onset, _ = store.symptom_onset()
    # closest-before-onset first among causes that precede onset; then the rest
    before = sorted([c for c in candidates if onset and c["time"] < onset], key=lambda c: c["time"], reverse=True)
    after = sorted([c for c in candidates if not (onset and c["time"] < onset)], key=lambda c: c["time"])
    ranked = before + after
    if use_llm and llm.available() and ranked:
        listing = [{"i": i, "object": c["object_id"], "signal": c["signal_type"], "time": c["time"],
                    "fault_type": c["fault_type"]} for i, c in enumerate(ranked)]
        prompt = ("You are diagnosing a Kubernetes incident. Symptom service: "
                  f"{symptom_service}; first symptom at {onset}. Order these candidate causes from most to least "
                  f"likely. Reply with a JSON list of indices only.\n{json.dumps(listing)}")
        try:
            order = json.loads(llm.complete(prompt))
            ranked = [ranked[i] for i in order if 0 <= i < len(ranked)] or ranked
        except Exception:
            pass
    return ranked


def run(case_dir, condition="proofops", store=None, use_llm=False):
    case = load_case(case_dir)
    graph = build_graph(case, use_llm=use_llm)
    store = store or NxStore(graph)
    if hasattr(store, "load") and not isinstance(store, NxStore):
        store.load(graph, case["meta"].get("case_id", "case"))
    symptom = case["meta"]["symptom_service"]
    trace = []

    if condition == "baseline":
        # no graph: count error-like signals per component and blame the noisiest one
        counts = {}
        for n, d in graph.nodes(data=True):
            if d["label"] in ("Alert", "LogSignal", "MetricAnomaly"):
                for _, v, k in graph.out_edges(n, keys=True):
                    if k in ("ON", "FOR", "EMITTED_BY"):
                        name = v.split(":", 1)[1]
                        if v.startswith("pod:"):
                            name = next((u.split(":", 1)[1] for u, _, kk in graph.in_edges(v, keys=True)
                                         if kk == "SELECTS"), name)
                        comp = f"service:{name}" if not v.startswith(("node:", "configmap:", "deployment:")) else v
                        if comp != f"service:{symptom}":
                            counts[comp] = counts.get(comp, 0) + 1
        guess = max(counts, key=counts.get) if counts else None
        trace.append(f"signal counts per component: {counts}")
        return {"condition": condition, "reported_cause": guess, "fault_type": None,
                "status": "CLAIMED", "evidence": [], "missing": ["TemporalPrecedence", "DependencyPath", "CorroboratingSignal"],
                "trace": trace}

    candidates = store.candidate_causes()
    ranked = _rank_candidates(store, candidates, symptom, use_llm)
    trace.append(f"{len(ranked)} candidate causes: " + ", ".join(c["object_id"] for c in ranked))

    if condition == "graph":
        top = ranked[0] if ranked else None
        return {"condition": condition, "reported_cause": top and top["object_id"],
                "fault_type": top and top["fault_type"], "status": "CLAIMED", "evidence": [],
                "missing": ["not checked"], "trace": trace}

    # proofops: check contracts in order; report the first SUPPORTED, else the best PLAUSIBLE
    best = None
    for c in ranked:
        dx = assemble(store, c, symptom)
        verdict = check(dx)
        trace.append(f"{c['object_id']} as {c['fault_type']}: {verdict['status']} "
                     f"(missing: {', '.join(verdict['missing']) or 'none'})")
        result = {"condition": condition, "reported_cause": c["object_id"], "fault_type": c["fault_type"],
                  "status": verdict["status"], "evidence": dx["evidence"], "missing": verdict["missing"],
                  "notes": dx["notes"], "engine": verdict["engine"], "trace": trace}
        if verdict["status"] == "SUPPORTED":
            return result
        if best is None or len(result["missing"]) < len(best["missing"]):
            best = result
    return best or {"condition": condition, "reported_cause": None, "status": "ABSTAINED",
                    "evidence": [], "missing": [], "trace": trace}


def check_hypothesis(case_dir, object_id, fault_type=None, store=None):
    """Check a specific proposed cause (e.g. one an engineer or another agent suggested)."""
    case = load_case(case_dir)
    graph = build_graph(case)
    store = store or NxStore(graph)
    cands = [c for c in store.candidate_causes() if c["object_id"] == object_id]
    hyp = cands[0] if cands else {"cause_id": None, "object_id": object_id, "time": None,
                                  "modality": "None", "signal_type": None, "source": "user hypothesis",
                                  "fault_type": fault_type or "DependencyFault"}
    if fault_type:
        hyp = dict(hyp, fault_type=fault_type)
    dx = assemble(store, hyp, case["meta"]["symptom_service"])
    return dx, check(dx)
