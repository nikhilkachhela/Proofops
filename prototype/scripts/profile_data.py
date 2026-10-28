"""Profile Cloud-OpsBench: what data we have, and how complete and trustworthy it is.

Produces docs/DATA_PROFILE.md with measured numbers (nothing is assumed).

  pip install huggingface_hub
  python scripts/profile_data.py                      # index + 2 sample cases per Online Boutique category
  python scripts/profile_data.py --per-category 4     # bigger sample
  python scripts/profile_data.py --local-dir cloudopsbench-data --no-download   # re-profile what you have

Checks performed
  1. Coverage        - counts by system, category, fault taxonomy, root cause, difficulty, symptom query
  2. Integrity       - SHA-256 of every downloaded file vs the publisher's manifest.json
  3. Completeness    - does each sampled case have metadata, tool cache, raw data?
  4. Referential     - does the labeled faulty object actually appear in the case's own snapshot?
  5. Entity resol.   - share of pod names that resolve to a known Online Boutique deployment
  6. Vocabulary      - share of error-like log lines our thesaurus can type
  7. Evidence avail. - per category: are change/config, log, alert and metric evidence present?
NOTE: ground-truth fields (root_cause, fault_object) are read here only to DESCRIBE the dataset and
check its integrity. They are never given to the diagnostic agent.
"""
import argparse, collections, hashlib, json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from proofops.thesaurus import classify_log

REPO = "LLM4Ops/Cloud-OpsBench"
OB_DEPLOYMENTS = {"frontend", "cartservice", "productcatalogservice", "currencyservice", "paymentservice",
                  "shippingservice", "emailservice", "checkoutservice", "recommendationservice", "adservice",
                  "redis-cart", "loadgenerator"}
POD_RE = re.compile(r"\b([a-z][a-z0-9-]*?)-([a-z0-9]{8,10})-([a-z0-9]{5})\b")
TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
ERRORISH = re.compile(r"error|fail|exception|refused|timeout|timed out|oom|unavailable|denied|forbidden|exceeded", re.I)
MAX_BYTES = 30_000_000
PLATFORM = ("prometheus", "coredns", "istiod", "istio", "chaosblade", "kubernetes-dashboard", "kube-", "calico",
            "metrics-server", "grafana", "jaeger", "local-path", "etcd", "dashboard-metrics", "node-exporter",
            "openebs", "alertsnitch", "rabbitmq", "cpu-consumer", "x-readiness")


def sha256(p: Path):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_entries(m):
    """Accept the common manifest shapes: {path: {sha256,size}}, {files: [...]}, or [...]."""
    if isinstance(m, dict) and "files" in m:
        m = m["files"]
    if isinstance(m, dict):
        for path, info in m.items():
            if isinstance(info, dict):
                yield path, info.get("sha256") or info.get("sha"), info.get("size")
            else:
                yield path, info, None
    elif isinstance(m, list):
        for e in m:
            yield e.get("path") or e.get("name"), e.get("sha256") or e.get("sha"), e.get("size")


def table(counter, header, top=None, unit="Cases"):
    rows = counter.most_common(top)
    out = [f"| {header} | {unit} |", "|---|---|"] + [f"| {k} | {v} |" for k, v in rows]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local-dir", default="cloudopsbench-data")
    ap.add_argument("--system", default="boutique")
    ap.add_argument("--per-category", type=int, default=2)
    ap.add_argument("--revision", default="main")
    ap.add_argument("--no-download", action="store_true")
    a = ap.parse_args()
    root = Path(a.local_dir)

    # ---------- 1. Index ----------
    if not a.no_download:
        from huggingface_hub import hf_hub_download
        for fn in ("index.jsonl", "release.json", "manifest.json"):
            try:
                hf_hub_download(REPO, fn, repo_type="dataset", revision=a.revision, local_dir=str(root))
            except Exception as e:
                print(f"warning: could not download {fn}: {e}")
    rows = [json.loads(l) for l in (root / "index.jsonl").read_text().splitlines() if l.strip()]
    C = {k: collections.Counter(r.get(k) for r in rows) for k in
         ("system", "category", "fault_taxonomy", "root_cause", "difficulty", "query", "fault_object")}
    sys_rows = [r for r in rows if r.get("system") == a.system]

    # ---------- sample selection + download ----------
    by_cat = collections.defaultdict(list)
    for r in sys_rows:
        by_cat[r["category"]].append(r)
    sample = []
    for cat, rs in sorted(by_cat.items()):
        rs.sort(key=lambda r: int(r["case_id"]) if str(r["case_id"]).isdigit() else 0)
        sample += rs[:a.per_category]
    if not a.no_download:
        from huggingface_hub import snapshot_download
        patterns = [f"benchmark/{r['case_key']}/**" for r in sample]
        print(f"downloading {len(sample)} sample cases ...")
        snapshot_download(REPO, repo_type="dataset", revision=a.revision, local_dir=str(root), allow_patterns=patterns)

    # ---------- 2. Integrity ----------
    integ = collections.Counter()
    mpath = root / "manifest.json"
    if mpath.exists():
        manifest = {p: (h, s) for p, h, s in manifest_entries(json.loads(mpath.read_text())) if p}
        for r in sample:
            cdir = root / "benchmark" / r["case_key"]
            for f in cdir.rglob("*") if cdir.exists() else []:
                if f.is_file():
                    rel = f.relative_to(root).as_posix()
                    if rel not in manifest or not manifest[rel][0]:
                        integ["not in manifest"] += 1
                    elif sha256(f) == manifest[rel][0]:
                        integ["checksum verified"] += 1
                    else:
                        integ["CHECKSUM MISMATCH"] += 1
    release = json.loads((root / "release.json").read_text()) if (root / "release.json").exists() else {}

    # ---------- 3-7. Per-case checks ----------
    comp = collections.Counter(); ref = collections.Counter(); er = collections.Counter(); voc = collections.Counter()
    file_names = collections.Counter(); avail = collections.defaultdict(collections.Counter); spans = []
    for r in sample:
        cdir = root / "benchmark" / r["case_key"]
        if not cdir.exists():
            comp["case folder missing"] += 1
            continue
        has = {"metadata.json": (cdir / "metadata.json").exists(), "tool_cache.json": (cdir / "tool_cache.json").exists(),
               "raw_data/": (cdir / "raw_data").exists() and any((cdir / "raw_data").rglob("*"))}
        comp["complete" if all(has.values()) else "incomplete"] += 1
        texts = []
        for f in sorted((cdir / "raw_data").rglob("*")) if has["raw_data/"] else []:
            if f.is_file():
                file_names[f.relative_to(cdir / "raw_data").as_posix().split("/")[0]] += 1
                if f.stat().st_size <= MAX_BYTES:
                    try:
                        texts.append((f.name.lower(), f.read_text(errors="ignore")))
                    except Exception:
                        pass
        tc = cdir / "tool_cache.json"
        if tc.exists() and tc.stat().st_size <= MAX_BYTES:
            texts.append(("tool_cache.json", tc.read_text(errors="ignore")))
        blob = "\n".join(t for _, t in texts).replace("\\n", "\n").replace("\\t", "\t")
        # 4. referential integrity of the labeled faulty object
        obj = (r.get("fault_object") or "").split("/")[-1]
        ref["found in snapshot" if obj and obj.lower() in blob.lower() else "NOT found"] += 1
        # 5. entity resolution of pod names
        for m in set(POD_RE.findall(blob)):
            if m[0] in OB_DEPLOYMENTS:
                er["app pod resolved to its Deployment"] += 1
            elif m[0].startswith(PLATFORM) or "-".join(m).startswith(PLATFORM):
                er["platform pod (monitoring, mesh, DNS, fault injector)"] += 1
            else:
                er["unresolved"] += 1
        # 6. vocabulary coverage on error-like lines (log files and tool cache text)
        for name, t in texts:
            if "log" in name or name == "tool_cache.json":
                for line in t.splitlines():
                    if ERRORISH.search(line) and len(line) < 2000:
                        voc["typed" if classify_log(line)[0] else "untyped"] += 1
        # 7. evidence availability by category
        cat = r["category"]
        low = blob.lower()
        avail[cat]["cases"] += 1
        raw = cdir / "raw_data"
        def nonempty(name):
            f = raw / name
            if not f.exists():
                return False
            try:
                v = json.loads(f.read_text(errors="ignore")) if f.suffix == ".json" else f.read_text(errors="ignore").strip()
                return bool(v)
            except Exception:
                return f.stat().st_size > 2
        ev_lines = [l for l in blob.splitlines() if re.match(r"\s*(Normal|Warning)\s+\w+", l)]
        avail[cat]["k8s events"] += int(bool(ev_lines))
        avail[cat]["warning events"] += int(any(l.strip().startswith("Warning") for l in ev_lines))
        avail[cat]["log evidence"] += int(nonempty("logs.json"))
        avail[cat]["alert evidence"] += int(nonempty("alert.json"))
        avail[cat]["metric evidence"] += int(nonempty("metrics.csv"))
        ts = sorted(set(TS_RE.findall(blob)))
        if ts:
            spans.append((r["case_key"], ts[0], ts[-1], len(ts)))

    pct = lambda c, k: f"{100 * c[k] / max(1, sum(c.values())):.0f}%"
    out = [f"# Cloud-OpsBench data profile ({a.system}, {len(sample)} sample cases)", "",
           "_Generated by `scripts/profile_data.py`. Every number below was measured, not assumed._", "",
           "## 1. Coverage (full index, all 754 cases)", "",
           f"Total cases: **{len(rows)}**. Release: `{release.get('version', release.get('distribution_version', 'see release.json'))}`.", "",
           table(C["system"], "System"), "", table(C["category"], "Category"), "", table(C["fault_taxonomy"], "Fault taxonomy"), "",
           table(C["difficulty"], "Difficulty"), "", table(C["query"], "Symptom query (what the agent is told)"), "",
           f"Distinct root causes: **{len(C['root_cause'])}**; distinct faulty objects: **{len(C['fault_object'])}**.", "",
           table(C["root_cause"], "Root cause (top 15)", 15), "",
           f"## 2. Integrity (SHA-256 vs publisher manifest)", "", table(integ, "Result", unit="Files") if integ else "_manifest.json not available_", "",
           f"## 3. Completeness", "", table(comp, "Sample case status"), "",
           "Top-level items in `raw_data/` across sampled cases:", "", table(file_names, "raw_data item", unit="Cases containing it"), "",
           f"## 4. Referential integrity: labeled faulty object present in its own snapshot", "",
           table(ref, "Result") + f"\n\nRate: **{pct(ref, 'found in snapshot')}**", "",
           f"## 5. Entity resolution: pod names resolved to an Online Boutique deployment", "",
           table(er, "Result", unit="Distinct pod names") + f"\n\nApplication pods resolved: **{er['app pod resolved to its Deployment']}** of {er['app pod resolved to its Deployment'] + er['unresolved']} application-like names ({100 * er['app pod resolved to its Deployment'] / max(1, er['app pod resolved to its Deployment'] + er['unresolved']):.0f}%)", "",
           f"## 6. Vocabulary coverage: error-like log lines typed by our thesaurus", "",
           table(voc, "Result", unit="Log lines") + f"\n\nRate: **{pct(voc, 'typed')}** (untyped lines are candidates for new thesaurus entries or LLM extraction)", "",
           "## 7. Evidence availability by category (decides which fault types get contracts)", "",
           "| Category | Cases | K8s events | Warning events | Logs (non-empty) | Alerts (non-empty) | Metrics |", "|---|---|---|---|---|---|---|"]
    for cat, c in sorted(avail.items()):
        out.append(f"| {cat} | {c['cases']} | {c['k8s events']} | {c['warning events']} | {c['log evidence']} | {c['alert evidence']} | {c['metric evidence']} |")
    out += ["", "## 8. Time coverage of sampled snapshots", "", "_Min/max of every timestamp in the snapshot. Wide spans include historical times (e.g. resource creation), so the incident window is taken from events and alerts, not from these extremes._", "", "| Case | First timestamp | Last timestamp | Distinct timestamps |", "|---|---|---|---|"]
    out += [f"| {k} | {s} | {e} | {n} |" for k, s, e, n in spans]
    Path("docs").mkdir(exist_ok=True)
    Path("docs/DATA_PROFILE.md").write_text("\n".join(out) + "\n")
    print("\n".join(out[:12]))
    print("\n... full report written to docs/DATA_PROFILE.md")


if __name__ == "__main__":
    main()
