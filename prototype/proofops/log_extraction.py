"""Turn raw log lines into typed evidence (LLM extraction step, with a deterministic thesaurus first).

1. Thesaurus match (fast, auditable).
2. Optional LLM fallback for unmatched lines: the LLM must choose from the controlled vocabulary
   and quote the exact text it relied on; quotes not present in the line are rejected.
"""
import json
from .thesaurus import classify_log, LOG_PATTERNS
from . import llm

ALLOWED = [t for t, _ in LOG_PATTERNS] + ["Benign"]

def extract(line: str, use_llm: bool = False):
    stype, quote = classify_log(line)
    if stype:
        return {"signal_type": stype, "quote": quote, "method": "thesaurus"}
    if use_llm and llm.available():
        prompt = (
            "Classify this Kubernetes log line into exactly one type from this list: "
            f"{ALLOWED}. Reply with JSON only: {{\"signal_type\": ..., \"quote\": <exact substring of the line>}}.\n"
            f"Log line: {line}"
        )
        try:
            out = json.loads(llm.complete(prompt))
            if out.get("signal_type") in ALLOWED and out.get("quote") and out["quote"] in line:
                if out["signal_type"] == "Benign":
                    return None
                return {"signal_type": out["signal_type"], "quote": out["quote"], "method": "llm"}
        except Exception:
            return None
    return None
