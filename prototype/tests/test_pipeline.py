"""Run with:  python -m pytest -q   (or: python tests/test_pipeline.py)"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from proofops.entity_resolution import resolve_pod, resolve_mentions
from proofops.thesaurus import classify_log
from proofops.agent import run, check_hypothesis
from proofops.contracts import allowed_signals

A = ROOT / "data/cases/demo-redis-config"
B = ROOT / "data/cases/demo-memory-limit"

def test_entity_resolution():
    assert resolve_pod("cartservice-7d9f8c6b5-x2k4p", ["cartservice", "frontend"]) == ("cartservice-7d9f8c6b5", "cartservice")
    assert resolve_mentions("Can't connect to redis-cart:6379", ["redis-cart", "cartservice"]) == ["redis-cart"]

def test_thesaurus():
    assert classify_log("ERR max number of clients reached")[0] == "ConnectionPoolExhausted"
    assert classify_log("fatal error: runtime: out of memory")[0] == "OutOfMemory"

def test_inheritance():
    assert "ConnectionPoolExhausted" in allowed_signals("ConfigurationFault")   # inherited from ChangeInducedFault
    assert "OutOfMemory" in allowed_signals("ResourceLimitFault")

def test_proofops_supported():
    r = run(A, "proofops")
    assert r["reported_cause"] == "configmap:redis-config" and r["status"] == "SUPPORTED"
    r = run(B, "proofops")
    assert r["reported_cause"] == "deployment:cartservice" and r["status"] == "SUPPORTED"

def test_decoy_is_only_plausible():
    dx, v = check_hypothesis(A, "node:node-2")
    assert v["status"] == "PLAUSIBLE" and "TemporalPrecedence" in v["missing"]

def test_baseline_blames_symptom():
    assert run(A, "baseline")["reported_cause"] == "service:cartservice"

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("PASS", name)
