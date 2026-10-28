"""Entity resolution (the 'authority record' idea): many variant names -> one canonical entity.

Kubernetes pod names look like  <deployment>-<replicaset-hash>-<pod-hash>, e.g.
cartservice-7d9f8c6b5-x2k4p -> ReplicaSet cartservice-7d9f8c6b5 -> Deployment cartservice.
Log lines mention services as host:port, e.g. 'redis-cart:6379' -> Service redis-cart.
"""
import re

POD_RE = re.compile(r"^(?P<rs>(?P<deploy>.+)-[a-z0-9]{8,10})-[a-z0-9]{5}$")

def resolve_pod(pod_name: str, deployment_names):
    """Return (replicaset_name, deployment_name) for a pod, or (None, None)."""
    m = POD_RE.match(pod_name)
    if m and m.group("deploy") in deployment_names:
        return m.group("rs"), m.group("deploy")
    # fallback: longest deployment name that prefixes the pod name
    best = max((d for d in deployment_names if pod_name.startswith(d + "-")), key=len, default=None)
    if best:
        rest = pod_name[len(best) + 1:].split("-")
        rs = f"{best}-{rest[0]}" if len(rest) >= 2 else None
        return rs, best
    return None, None

def resolve_mentions(text: str, service_names):
    """Find service names mentioned in free text (host, host:port, service URLs)."""
    found = set()
    for s in service_names:
        if re.search(rf"(?<![a-z0-9-]){re.escape(s)}(?![a-z0-9-])(:\d+)?", text, flags=re.IGNORECASE):
            found.add(s)
    return sorted(found)
