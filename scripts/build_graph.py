"""Build the ProofOps Neo4j graph from the downloaded Cloud-OpsBench cases.

What it loads (per case, all from OBSERVABLE data only):
  raw_data/k8s_states.json  -> Namespace, Deployment, ReplicaSet, Pod, Node, Service,
                               ServiceAccount, ConfigMap, Secret, Event
  tool_cache.json           -> Service CALLS Service (GetServiceDependencies)
  raw_data/logs.json        -> LogSignal (grouped error lines)
  raw_data/alert.json       -> Alert
  raw_data/metrics.csv      -> MetricAnomaly (performance cases only)
  metadata.json             -> ONLY `namespace` and `query` (the symptom text)

Never loaded: metadata.json `result`/`difficulty`, index.jsonl, process-label/,
golden-trajectory/. Cases get opaque IDs (C01..C10) so the folder path
(which names the fault category) never enters the graph.

Every node has `case_id` and `source` (the exact kubectl command / file it came from).
Every relationship has `derivation`:
  observed   - stated directly in kubectl output (e.g. "Controlled By: ReplicaSet/x")
  extracted  - pulled out of free text (e.g. a ClusterIP inside a log line)
  inferred   - computed by a documented rule (e.g. selector matches labels)

Usage:  .venv/bin/python scripts/build_graph.py            # load all selected cases
        .venv/bin/python scripts/build_graph.py --dry-run  # parse only, print counts
"""
import argparse
import csv
import json
import os
import re
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "data/raw/hf/benchmark"
SELECTED = ROOT / "data/selected_cases.json"
CASE_IDS = ROOT / "data/processed/case_ids.json"   # opaque id -> case_key (scoring side only)
DB_NAME = "proofops"
NS = "boutique"
LOCAL_TZ = timezone(timedelta(hours=8))   # collection/metrics/alert clocks (see docs/DATA_NOTES.md §3)
AGE_UNCERTAINTY_S = 60                    # relative ages -> clock time, see DATA_NOTES §3


# ---------------------------------------------------------------- text parsing
def parse_table(text):
    """Parse a kubectl table (columns aligned by spaces) into a list of dicts."""
    lines = [l for l in (text or "").splitlines() if l.strip()]
    if not lines or not lines[0].startswith("NAME"):
        return []
    header = lines[0]
    cols = [(m.group(0), m.start()) for m in re.finditer(r"\S+(?: \S+)*", header)]
    rows = []
    for line in lines[1:]:
        row = {}
        for i, (name, start) in enumerate(cols):
            end = cols[i + 1][1] if i + 1 < len(cols) else None
            row[name] = line[start:end].strip() if end else line[start:].strip()
        rows.append(row)
    return rows


def age_seconds(age):
    """'5m43s' -> 343; '2 (28s ago)' is not an age. Returns None if unparseable."""
    parts = re.findall(r"(\d+)([dhms])", age or "")
    if not parts:
        return None
    return sum(int(n) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[u] for n, u in parts)


def field(text, name):
    m = re.search(rf"^{re.escape(name)}:\s*(.*)$", text or "", re.M)
    return m.group(1).strip() if m else None


def labels_block(text, name="Labels"):
    """Read 'Labels: a=b' plus indented continuation lines into a dict."""
    m = re.search(rf"^(\s*){name}:\s*(.*)$", text or "", re.M)
    if not m:
        return {}
    indent, values = m.group(1), [m.group(2)]
    for line in text[m.end():].splitlines()[1:]:
        if re.match(rf"^{indent}\s+\S+=\S*$", line) and ":" not in line.split("=")[0]:
            values.append(line.strip())
        else:
            break
    out = {}
    for v in values:
        for pair in v.split(","):
            if "=" in pair:
                k, val = pair.strip().split("=", 1)
                out[k] = val
    return out


def parse_events(describe_text):
    if not describe_text or "Events:" not in describe_text:
        return []
    rows = []
    for line in describe_text.split("Events:", 1)[1].splitlines():
        # Age may be "72s" or "72s (x3 over 82s)" for repeated events.
        m = re.match(r"\s+(Normal|Warning)\s+(\S+)\s+(\S+(?:\s+\(x\d+ over \S+\))?)\s+(\S+)\s+(.*)", line)
        if m:
            rows.append(dict(zip(("type", "reason", "age", "source", "message"), m.groups())))
    return rows


def parse_abs_time(s):
    """'Tue, 11 Nov 2025 22:31:08 +0800' -> aware datetime."""
    try:
        return datetime.strptime(s.strip(), "%a, %d %b %Y %H:%M:%S %z")
    except (ValueError, AttributeError):
        return None


# ------------------------------------------------------------- log parsing
LOG_TS_PATTERNS = [
    # "2025-12-25T16:53:53.429760399+08:00 {...}" prefix (performance cases)
    (re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?([+-]\d{2}:\d{2}|Z)"), "iso"),
    # redis: "1:M 21 Nov 2025 12:13:40.758 *"
    (re.compile(r"(\d{1,2} \w{3} \d{4} \d{2}:\d{2}:\d{2})"), "redis"),
]


def log_time(line):
    """Return (UTC datetime or None, parsed JSON object or None)."""
    body = line
    m = LOG_TS_PATTERNS[0][0].match(line)
    if m:
        tz = timezone.utc if m.group(3) == "Z" else datetime.strptime(m.group(3).replace(":", ""), "%z").tzinfo
        ts = datetime.fromisoformat(m.group(1)).replace(tzinfo=tz).astimezone(timezone.utc)
        body = line[m.end():].strip()
        try:
            return ts, json.loads(body)
        except ValueError:
            return ts, None
    try:
        obj = json.loads(line)
    except ValueError:
        obj = None
    if isinstance(obj, dict):
        for k in ("timestamp", "time", "ts"):
            v = obj.get(k)
            if isinstance(v, str):
                mm = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?(Z|[+-]\d{2}:\d{2})?", v)
                if mm:
                    tz = timezone.utc if mm.group(3) in (None, "Z") else datetime.strptime(mm.group(3).replace(":", ""), "%z").tzinfo
                    return datetime.fromisoformat(mm.group(1)).replace(tzinfo=tz).astimezone(timezone.utc), obj
        if isinstance(obj.get("instant"), dict):
            return datetime.fromtimestamp(obj["instant"]["epochSecond"], timezone.utc), obj
        return None, obj
    m = LOG_TS_PATTERNS[1][0].search(line)
    if m:
        # redis logs print UTC (verified against JSON logs in the same case)
        return datetime.strptime(m.group(1), "%d %b %Y %H:%M:%S").replace(tzinfo=timezone.utc), None
    return None, None


ERROR_WORDS = re.compile(r"\b(error|exception|failed|failure|refused|fatal)\b", re.I)


def is_error(line, obj):
    if isinstance(obj, dict):
        lvl = str(obj.get("severity") or obj.get("level") or "").lower()
        if lvl:
            return lvl in ("error", "fatal", "critical")
        return "error" in obj or bool(ERROR_WORDS.search(line))
    return bool(ERROR_WORDS.search(line))


def normalise(msg):
    msg = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<id>", msg)
    msg = re.sub(r"\(#\w+\)", "(#<id>)", msg)
    msg = re.sub(r"\d+(\.\d+)?(ms|s)\b", "<dur>", msg)
    return msg[:220]


# ------------------------------------------------------------- one case
def build_case(case_id, case_key):
    cdir = BENCH / case_key
    k8s = json.loads((cdir / "raw_data/k8s_states.json").read_text())
    tool = json.loads((cdir / "tool_cache.json").read_text())
    meta = json.loads((cdir / "metadata.json").read_text())
    meta = {"namespace": meta.get("namespace"), "query": meta.get("query")}   # nothing else
    nodes, rels = [], []

    def node(label, name, src, **props):
        uid = f"{case_id}|{label}|{name}"
        nodes.append({"label": label, "uid": uid, "props": {"uid": uid, "case_id": case_id, "name": name, "source": src, **props}})
        return uid

    def rel(a, typ, b, derivation, src, **props):
        rels.append({"a": a, "b": b, "type": typ, "props": {"derivation": derivation, "source": src, **props}})

    def get(cmd):
        return k8s.get(cmd, "")

    # Snapshot time: pod Start Time (absolute) + AGE  (fallback: Deployment CreationTimestamp + AGE)
    estimates = []
    for p in parse_table(get(f"kubectl get pods -n {NS}")):
        st = parse_abs_time(field(get(f"kubectl describe pods {p['NAME']} -n {NS}"), "Start Time"))
        if st and age_seconds(p["AGE"]) is not None:
            estimates.append(st + timedelta(seconds=age_seconds(p["AGE"])))
    for d in parse_table(get(f"kubectl get deployments -n {NS}")):
        ct = parse_abs_time(field(get(f"kubectl describe deployments {d['NAME']} -n {NS}"), "CreationTimestamp"))
        if ct and age_seconds(d["AGE"]) is not None:
            estimates.append(ct + timedelta(seconds=age_seconds(d["AGE"])))
    snapshot = min(estimates).astimezone(timezone.utc) if estimates else None

    def ago(age_s):
        return (snapshot - timedelta(seconds=age_s)).isoformat() if snapshot and age_s is not None else None

    case_uid = node("Case", case_id, "metadata.json:query,namespace", query=meta["query"],
                    snapshot_time=snapshot.isoformat() if snapshot else None,
                    collection_timestamp_local=tool.get("collection_timestamp"))
    ns_uid = node("Namespace", NS, f"metadata.json:namespace")
    rel(ns_uid, "IN_CASE", case_uid, "observed", "metadata.json")

    def in_case(uid):
        rel(uid, "IN_CASE", case_uid, "observed", "case folder")

    # Nodes (cluster)
    for n in parse_table(get(f"kubectl get nodes -n {NS}")):
        in_case(node("Node", n["NAME"], f"kubectl get nodes -n {NS}", status=n["STATUS"], roles=n["ROLES"]))

    # ServiceAccounts, ConfigMaps, Secrets
    listed_sa = set()
    for s in parse_table(get(f"kubectl get serviceaccounts -n {NS}")):
        listed_sa.add(s["NAME"])
        in_case(node("ServiceAccount", s["NAME"], f"kubectl get serviceaccounts -n {NS}", exists=True,
                     created_approx=ago(age_seconds(s["AGE"]))))
    for c in parse_table(get(f"kubectl get configmaps -n {NS}")):
        in_case(node("ConfigMap", c["NAME"], f"kubectl get configmaps -n {NS}"))
    secrets = {s["NAME"] for s in parse_table(get(f"kubectl get secrets -n {NS}"))}
    for s in secrets:
        in_case(node("Secret", s, f"kubectl get secrets -n {NS}"))

    def sa_uid(name, src):
        if name not in listed_sa:   # referenced but not in `get serviceaccounts`
            listed_sa.add(name)
            in_case(node("ServiceAccount", name, src, exists=False))
        return f"{case_id}|ServiceAccount|{name}"

    # Deployments
    dep_template_labels = {}
    for d in parse_table(get(f"kubectl get deployments -n {NS}")):
        src = f"kubectl describe deployments {d['NAME']} -n {NS}"
        desc = get(src)
        tmpl = desc.split("Pod Template:", 1)[1] if "Pod Template:" in desc else ""
        dep_template_labels[d["NAME"]] = labels_block(tmpl)
        uid = node("Deployment", d["NAME"], src, ready=d["READY"], available=d["AVAILABLE"],
                   created=(parse_abs_time(field(desc, "CreationTimestamp")) or snapshot).astimezone(timezone.utc).isoformat()
                   if snapshot else None,
                   replicas=field(desc, "Replicas"))
        in_case(uid)
        sa = field(tmpl, "  Service Account") if tmpl else None
        if sa:
            rel(uid, "USES_ACCOUNT", sa_uid(sa, src), "observed", src + " (Pod Template)")

    # ReplicaSets (Deployment OWNS ReplicaSet)
    for r in parse_table(get(f"kubectl get replicasets -n {NS}")):
        src = f"kubectl describe replicasets {r['NAME']} -n {NS}"
        uid = node("ReplicaSet", r["NAME"], f"kubectl get replicasets -n {NS}", desired=r["DESIRED"],
                   current=r["CURRENT"], ready=r["READY"])
        in_case(uid)
        owner = field(get(src), "Controlled By")
        if owner and owner.startswith("Deployment/"):
            rel(f"{case_id}|Deployment|{owner.split('/', 1)[1]}", "OWNS", uid, "observed", src)
        else:
            dep = r["NAME"].rsplit("-", 1)[0]
            if dep in dep_template_labels:
                rel(f"{case_id}|Deployment|{dep}", "OWNS", uid, "inferred", "rule:name-prefix (rs = deployment-hash)")

    # Pods
    pod_labels = {}
    wide = {p["NAME"]: p for p in parse_table(get(f"kubectl get pods -n {NS} -o wide"))}
    for p in parse_table(get(f"kubectl get pods -n {NS} --show-labels")):
        name = p["NAME"]
        src = f"kubectl describe pods {name} -n {NS}"
        desc = get(src)
        pod_labels[name] = dict(kv.split("=", 1) for kv in p["LABELS"].split(",") if "=" in kv)
        st = parse_abs_time(field(desc, "Start Time"))
        uid = node("Pod", name, f"kubectl get pods -n {NS} --show-labels", ready=p["READY"], status=p["STATUS"],
                   restarts=p["RESTARTS"], ip=wide.get(name, {}).get("IP"),
                   start_time=st.astimezone(timezone.utc).isoformat() if st else None)
        in_case(uid)
        owner = field(desc, "Controlled By")
        if owner and owner.startswith("ReplicaSet/"):
            rel(f"{case_id}|ReplicaSet|{owner.split('/', 1)[1]}", "OWNS", uid, "observed", src)
        node_name = wide.get(name, {}).get("NODE")
        if node_name and node_name != "<none>":
            rel(uid, "RUNS_ON", f"{case_id}|Node|{node_name}", "observed", f"kubectl get pods -n {NS} -o wide")
        sa = field(desc, "Service Account")
        if sa:
            rel(uid, "USES_ACCOUNT", sa_uid(sa, src), "observed", src)
        for cm in set(re.findall(r"ConfigMapName:\s+(\S+)", desc)):
            rel(uid, "MOUNTS", f"{case_id}|ConfigMap|{cm}", "observed", src)
        for sec in set(re.findall(r"SecretName:\s+(\S+)", desc)):
            if sec not in secrets:
                secrets.add(sec)
                in_case(node("Secret", sec, src, exists=False))
            rel(uid, "MOUNTS", f"{case_id}|Secret|{sec}", "observed", src)

    # Services (SELECTS Pod / Deployment by selector rule)
    endpoints = {e["NAME"]: e["ENDPOINTS"] for e in parse_table(get(f"kubectl get endpoints -n {NS}"))}
    svc_ip = {}
    services = parse_table(get(f"kubectl get services -n {NS}"))
    for s in services:
        name = s["NAME"]
        src = f"kubectl describe services {name} -n {NS}"
        desc = get(src)
        sel = labels_block(desc, "Selector")
        svc_ip[name] = s["CLUSTER-IP"]
        ep = endpoints.get(name, "")
        uid = node("Service", name, f"kubectl get services -n {NS}", cluster_ip=s["CLUSTER-IP"], ports=s["PORT(S)"],
                   target_port=field(desc, "TargetPort"), selector=",".join(f"{k}={v}" for k, v in sel.items()),
                   endpoints=ep or "<none>", has_endpoints=bool(ep) and ep != "<none>",
                   created_approx=ago(age_seconds(s["AGE"])))
        in_case(uid)
        rule = "rule:selector-subset (every selector label is on the target)"
        for pod, labels in pod_labels.items():
            if sel and all(labels.get(k) == v for k, v in sel.items()):
                rel(uid, "SELECTS", f"{case_id}|Pod|{pod}", "inferred", rule)
        for dep, labels in dep_template_labels.items():
            if sel and all(labels.get(k) == v for k, v in sel.items()):
                rel(uid, "SELECTS", f"{case_id}|Deployment|{dep}", "inferred", rule + " on Pod Template")
    svc_names = {s["NAME"] for s in services}

    # CALLS (benchmark dependency tool; direct children only)
    for key, text in tool.items():
        if not key.startswith("GetServiceDependencies"):
            continue
        caller = json.loads(key.split(":", 1)[1])["service_name"]
        for m in re.finditer(r"^(?:├|└)── (\S+)", text, re.M):   # first-level children only
            callee = m.group(1)
            if caller in svc_names and callee in svc_names:
                rel(f"{case_id}|Service|{caller}", "CALLS", f"{case_id}|Service|{callee}", "observed", key)

    # Events (from every `describe` block)
    kind_label = {"pods": "Pod", "replicasets": "ReplicaSet", "deployments": "Deployment", "nodes": "Node",
                  "services": "Service", "endpoints": "Service", "serviceaccounts": "ServiceAccount"}
    n_ev = 0
    for cmd, text in k8s.items():
        m = re.match(r"kubectl describe (\S+) (\S+) -n", cmd)
        if not m or m.group(1) not in kind_label:
            continue
        target = f"{case_id}|{kind_label[m.group(1)]}|{m.group(2)}"
        for i, e in enumerate(parse_events(text)):
            last_s = age_seconds(e["age"].split(" ")[0])
            over = re.search(r"\(x(\d+) over (\S+)\)", e["age"])
            first_s = age_seconds(over.group(2)) if over else last_s
            n_ev += 1
            uid = node("Event", f"{m.group(2)}#{i}", cmd, type=e["type"], reason=e["reason"], message=e["message"][:400],
                       reporter=e["source"], count=int(over.group(1)) if over else 1, age_raw=e["age"],
                       first_seen_approx=ago(first_s), last_seen_approx=ago(last_s),
                       time_uncertainty_s=AGE_UNCERTAINTY_S)
            in_case(uid)
            rel(uid, "ABOUT", target, "observed", cmd)

    # LogSignals: group error lines by (emitting service, normalised message)
    logs = json.loads((cdir / "raw_data/logs.json").read_text())
    ip_to_svc = {ip: s for s, ip in svc_ip.items() if ip and ip != "None"}
    groups = {}
    for svc, lines in logs.items():
        for idx, line in enumerate(lines):
            ts, obj = log_time(line)
            if not is_error(line, obj):
                continue
            msg = (obj.get("error") or obj.get("message") or line) if isinstance(obj, dict) else line
            msg = str(msg)
            targets = {ip_to_svc[ip] for ip in re.findall(r"\b\d+\.\d+\.\d+\.\d+\b", msg) if ip in ip_to_svc}
            targets |= {s for s in svc_names if s != svc and re.search(rf"(lookup |//|\b){re.escape(s)}[:\s.\"]", msg)}
            g = groups.setdefault((svc, normalise(msg)), {"count": 0, "first": None, "last": None, "idx": idx,
                                                         "sample": msg[:400], "targets": set()})
            g["count"] += 1
            g["targets"] |= targets
            if ts:
                g["first"] = min(g["first"] or ts, ts)
                g["last"] = max(g["last"] or ts, ts)
    for n, ((svc, _), g) in enumerate(sorted(groups.items(), key=lambda kv: -kv[1]["count"])):
        uid = node("LogSignal", f"{svc}#{n}", f"raw_data/logs.json:{svc}[{g['idx']}]", service=svc, count=g["count"],
                   sample=g["sample"], first_seen=g["first"].isoformat() if g["first"] else None,
                   last_seen=g["last"].isoformat() if g["last"] else None)
        in_case(uid)
        if svc in svc_names:
            rel(uid, "EMITTED_BY", f"{case_id}|Service|{svc}", "observed", f"raw_data/logs.json key '{svc}'")
        for t in g["targets"]:
            rel(uid, "ABOUT", f"{case_id}|Service|{t}", "extracted", "rule:ClusterIP-or-DNS-name in log message")

    # Alerts
    alerts = json.loads((cdir / "raw_data/alert.json").read_text() or "{}")
    for i, a in enumerate(alerts.get("alerts", []) if isinstance(alerts, dict) else []):
        start, _, end = a.get("time_range", "").partition(" ~ ")
        to_utc = lambda s: datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc).isoformat() if s.strip() else None
        uid = node("Alert", f"{a.get('name')}#{i}", f"raw_data/alert.json alerts[{i}]", target_type=a.get("type"),
                   status=a.get("status"), evidence=a.get("evidence", []), start=to_utc(start), end=to_utc(end))
        in_case(uid)
        label = "Node" if a.get("type") == "Node" else "Service"
        rel(uid, "ABOUT", f"{case_id}|{label}|{a.get('name')}", "observed", f"raw_data/alert.json alerts[{i}]")

    # MetricAnomalies (rule: baseline = first 6 samples; anomaly = z > 3 for 2 consecutive samples
    # AND >= 50% change vs baseline mean). Documented in docs/DATA_NOTES.md.
    mpath = cdir / "raw_data/metrics.csv"
    node_names = {n["NAME"] for n in parse_table(get(f"kubectl get nodes -n {NS}"))}
    if mpath.exists():
        with mpath.open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        times = [datetime.strptime(r["time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc) for r in rows]
        for col in rows[0]:
            if col == "time":
                continue
            entity, metric = col.rsplit("-", 1)
            try:
                vals = [float(r[col]) for r in rows]
            except (TypeError, ValueError):
                continue
            base = vals[:6]
            mu, sd = statistics.mean(base), statistics.pstdev(base) or 1e-9
            onset = None
            for i in range(6, len(vals) - 1):
                if all((v - mu) / sd > 3 for v in vals[i:i + 2]) and (mu == 0 or (vals[i] - mu) / abs(mu) >= 0.5):
                    onset = i
                    break
            if onset is None:
                continue
            label = "Node" if entity in node_names else "Service" if entity in svc_names else None
            if not label:
                continue
            uid = node("MetricAnomaly", col, f"raw_data/metrics.csv column '{col}'", metric=metric, entity=entity,
                       baseline=round(mu, 4), peak=round(max(vals), 4), onset=times[onset].isoformat(),
                       change_pct=round(100 * (max(vals) - mu) / abs(mu), 1) if mu else None,
                       rule="z>3 for 2 samples and >=50% vs first-6-sample baseline")
            in_case(uid)
            rel(uid, "ABOUT", f"{case_id}|{label}|{entity}", "inferred", "rule:metric column prefix = entity name")

    return nodes, rels


# ------------------------------------------------------------- Neo4j load
LABELS = ["Case", "Namespace", "Service", "Deployment", "ReplicaSet", "Pod", "Node", "ConfigMap", "Secret",
          "ServiceAccount", "Event", "Alert", "LogSignal", "MetricAnomaly"]
REL_TYPES = {"OWNS", "SELECTS", "RUNS_ON", "MOUNTS", "USES_ACCOUNT", "CALLS", "EMITTED_BY", "ABOUT", "IN_CASE"}


def load(driver, case_ids, nodes, rels):
    run = lambda q, **kw: driver.execute_query(q, database_=DB_NAME, **kw)
    for label in LABELS:   # label names come from the fixed list above, never from data
        run(f"CREATE CONSTRAINT {label.lower()}_uid IF NOT EXISTS FOR (n:{label}) REQUIRE n.uid IS UNIQUE")
        run(f"CREATE INDEX {label.lower()}_case IF NOT EXISTS FOR (n:{label}) ON (n.case_id)")
    # Re-runnable: remove only the nodes of the cases we are about to load.
    run("MATCH (n) WHERE n.case_id IN $ids DETACH DELETE n", ids=case_ids)
    for label in LABELS:
        batch = [n["props"] for n in nodes if n["label"] == label]
        if batch:
            run(f"UNWIND $rows AS r CREATE (n:{label}) SET n = r", rows=batch)
    for typ in sorted(REL_TYPES):
        batch = [{"a": r["a"], "b": r["b"], "p": r["props"]} for r in rels if r["type"] == typ]
        if batch:
            res = run(f"UNWIND $rows AS r MATCH (a {{uid: r.a}}) MATCH (b {{uid: r.b}}) "
                      f"CREATE (a)-[x:{typ}]->(b) SET x = r.p RETURN count(x) AS c", rows=batch)
            made = res.records[0]["c"]
            if made != len(batch):
                print(f"   [warn] {typ}: {len(batch) - made} relationship(s) skipped (endpoint node not found)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    case_keys = json.loads(SELECTED.read_text())["case_keys"]
    ids = {f"C{i + 1:02d}": key for i, key in enumerate(case_keys)}
    CASE_IDS.parent.mkdir(parents=True, exist_ok=True)
    CASE_IDS.write_text(json.dumps(ids, indent=2))

    all_nodes, all_rels = [], []
    for cid, key in ids.items():
        n, r = build_case(cid, key)
        all_nodes += n
        all_rels += r
        counts = {}
        for x in n:
            counts[x["label"]] = counts.get(x["label"], 0) + 1
        print(f"{cid}: {len(n):4d} nodes, {len(r):4d} rels  " + " ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print(f"TOTAL: {len(all_nodes)} nodes, {len(all_rels)} relationships")
    if args.dry_run:
        return

    load_dotenv(ROOT / ".env")
    from neo4j import GraphDatabase
    auth = (os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD"))
    if not all(auth):
        sys.exit("NEO4J_USER / NEO4J_PASSWORD not set. See .env.example.")
    with GraphDatabase.driver(os.getenv("NEO4J_URI", "bolt://localhost:7687"), auth=auth) as driver:
        driver.execute_query(f"CREATE DATABASE {DB_NAME} IF NOT EXISTS WAIT", database_="system")
        load(driver, list(ids), all_nodes, all_rels)
        res = driver.execute_query("MATCH (n) RETURN labels(n)[0] AS l, count(*) AS c ORDER BY l", database_=DB_NAME)
        print("In Neo4j:", ", ".join(f"{r['l']}={r['c']}" for r in res.records))
        res = driver.execute_query("MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c ORDER BY t", database_=DB_NAME)
        print("Relationships:", ", ".join(f"{r['t']}={r['c']}" for r in res.records))


if __name__ == "__main__":
    main()
