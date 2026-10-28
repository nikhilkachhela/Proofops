"""Controlled vocabulary + thesaurus (Ontology Pipeline stages 1-4), mirrored from ontology/thesaurus.ttl.

Every term has one preferred label (the dict key) and its variants (patterns / reasons).
The SKOS file is the formal version; this module is the runtime copy the pipeline uses.
"""
import re

# Log message variants -> preferred signal type (thesaurus: skos:altLabel / hiddenLabel)
LOG_PATTERNS = [
    ("ConnectionPoolExhausted", r"max(imum)? number of clients reached|too many connections|connection pool exhausted"),
    ("ConnectionFailure", r"can'?t connect|connection refused|econnrefused|no connection is available|connection reset"),
    ("OutOfMemory", r"out of memory|oomkilled|cannot allocate memory"),
    ("UpstreamUnavailable", r"code = unavailable|failed to retrieve|upstream connect error|503 service unavailable"),
    ("Timeout", r"deadline exceeded|timed? ?out|context canceled"),
    ("ConfigError", r"invalid config|config(uration)? error|missing env|parse error"),
]

# Kubernetes event reasons -> (event class, signal type)
EVENT_REASONS = {
    ("ConfigMap", "Updated"): ("ChangeEvent", "ConfigChange"),
    ("Secret", "Updated"): ("ChangeEvent", "ConfigChange"),
    ("Deployment", "Updated"): ("ChangeEvent", "SpecChange"),
    ("Pod", "OOMKilled"): ("RuntimeEvent", "OutOfMemory"),
    ("Pod", "BackOff"): ("RuntimeEvent", "CrashLoop"),
    ("Pod", "Restarted"): ("RuntimeEvent", "Restart"),
    ("Node", "HighCPU"): ("RuntimeEvent", "CPUSaturation"),
}

# Metric names -> signal type
METRIC_TYPES = {
    "error_rate": "ErrorRateSpike",
    "latency_ms": "LatencySpike",
    "cpu_utilization": "CPUSaturation",
    "memory_utilization": "MemorySaturation",
}

# Which fault type a candidate cause suggests (cause signal type + message cues)
def fault_type_for(signal_type: str, message: str = "") -> str:
    msg = (message or "").lower()
    if signal_type == "ConfigChange":
        return "ConfigurationFault"
    if signal_type == "SpecChange":
        if "memory" in msg or "cpu limit" in msg or "limit" in msg:
            return "ResourceLimitFault"
        return "ConfigurationFault"
    if signal_type in ("CPUSaturation", "MemorySaturation"):
        return "ResourceExhaustion"
    return "DependencyFault"

# Taxonomy: fault-type hierarchy (mirrors OWL subclassing; contracts are inherited downwards)
FAULT_PARENTS = {
    "ConfigurationFault": "ChangeInducedFault",
    "ResourceLimitFault": "ChangeInducedFault",
    "ChangeInducedFault": "Fault",
    "ResourceExhaustion": "ResourceFault",
    "ResourceFault": "Fault",
    "DependencyFault": "Fault",
}

def classify_log(line: str):
    """Return (signal_type, matched_text) or (None, None)."""
    for stype, pattern in LOG_PATTERNS:
        m = re.search(pattern, line, flags=re.IGNORECASE)
        if m:
            return stype, m.group(0)
    return None, None
