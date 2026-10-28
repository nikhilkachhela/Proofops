# Data Notes (Phase 2)

> ⚠ **This file names the ground-truth root cause of each case (Section 6).** It is for us and for scoring only. Never put it into anything the agent reads.

The cases opened in detail were **service/54** (selector mismatch), **runtime/9** (liveness probe) and **performance/11** (CPU overload). The other 7 were checked with the same scripts (`scripts/profile_cases.py` plus the ad-hoc checks described below).

---

## 1. Files in one case folder

| File | What it is | Agent may read? |
|---|---|---|
| `metadata.json` | `namespace`, `query` (symptom sentence, e.g. "Partial Service Unreachability."), `difficulty`, and `result` = **{fault_taxonomy, fault_object, root_cause} — the answers** | Only `query` and `namespace`. **Never `result`.** Treat `difficulty` as hidden too |
| `raw_data/k8s_states.json` | Dict of ~415 entries. Key = the exact `kubectl` command, value = its **plain-text output** (tables or `describe` text). No YAML/JSON | Yes |
| `tool_cache.json` | Dict of ~490 entries. Key = `ToolName:{json args}`, value = the tool's text output. Contains everything in k8s_states (identical text, verified) **plus** `GetServiceDependencies`, `GetErrorLogs`, `GetAlerts`, `GetAppYAML`, `CheckServiceConnectivity`, `CheckNodeServiceStatus`, `GetClusterConfiguration`, `ListCodeFiles`, and a `collection_timestamp` | Yes |
| `raw_data/logs.json` | Dict `service → list of raw log lines` for 11 services. Formats differ per service (see §4) | Yes |
| `raw_data/alert.json` | Pre-computed alerts. **`{}` in 8/10 cases.** Only the performance cases have alerts | Yes |
| `raw_data/metrics.csv` | **Performance cases only.** About 46 rows × 111 columns, one row every 5 s (~4 min). Columns are `<service>-<metric>` and `<node>-<metric>` | Yes |
| `code/` | Source code of the 10 Online Boutique services | Yes (not used yet) |

`index.jsonl` (repo root) also contains `root_cause`/`fault_object`, so it counts as **ground truth**.
The **folder path** (`benchmark/boutique/<category>/<id>`) reveals the category. The agent must get cases under an opaque ID.

## 2. Where each kind of information lives

| Need | Source (key in k8s_states / tool_cache) | Notes |
|---|---|---|
| **Pods** | `kubectl get pods -n boutique [-o wide / --show-labels]`, `kubectl describe pods <pod>` | `describe` gives Node, Service Account, Labels, `Controlled By: ReplicaSet/...`, container ports, limits, probes, env vars, mounts, State/Restart Count, Events |
| **ReplicaSet → Deployment** | `kubectl describe replicasets <rs>`, `kubectl describe deployments <d>` | Pod name `cartservice-79b49f5555-5746n` = ReplicaSet `cartservice-79b49f5555` + suffix. `Controlled By:` confirms it. Deployment `describe` lists `NewReplicaSet` and the Service Account the template asks for |
| **Services** | `kubectl get services`, `kubectl describe services <s>` | `Selector`, `Port`, `TargetPort`, `Endpoints`, ClusterIP |
| **Endpoints** | `kubectl get endpoints` | `<none>` or blank = no pod is behind the Service |
| **ServiceAccounts / ConfigMaps / Secrets** | `kubectl get serviceaccounts/configmaps/secrets`, `describe serviceaccounts` | Secrets only via `get` (names, no contents) |
| **Nodes** | `kubectl describe nodes <n>`, `-o wide` pod listing | 4 nodes: master, worker-01..03 |
| **ResourceQuota** | `kubectl get resourcequota -n boutique` | e.g. `requests.memory: 3000Mi/3Gi` |
| **Dependencies (CALLS)** | `tool_cache` → `GetServiceDependencies:{service_name}` | **Identical in all 10 cases.** It's the app's fixed call map (frontend→adservice, checkoutservice→paymentservice, …). Also confirmed by env vars like `SHIPPING_SERVICE_ADDR: shippingservice:50051` in pod `describe` |
| **Kubernetes events** | The `Events:` table at the end of each `describe` output | Columns Type, Reason, Age, From, Message. Age is **relative** (e.g. `62s`, `72s (x2 over 82s)`). There's no `kubectl get events` |
| **Logs** | `raw_data/logs.json`; summary in `GetErrorLogs` | Absolute timestamps (most lines) |
| **Alerts** | `raw_data/alert.json` (= `GetAlerts`) | Each alert: `type` (Service/Node), `name`, `time_range`, `evidence` strings such as `LATENCY_DEGRADATION ... +345%` |
| **Metrics** | `raw_data/metrics.csv` | `cpu, mem, cpu_cfs, rps, success_rate, network_receive/transmit, p50latency, p95latency` **or `p90latency`** (differs per case), plus node cpu/mem/tcp_retrans |

## 3. Timestamps (important)

- **Logs** are UTC (`...Z`, or `instant.epochSecond` for the Java adservice). Performance-case logs instead carry a `+08:00` prefix.
- **`collection_timestamp`** has no zone. It is **China local time (UTC+8)**: it matches the log clock + 8 h in all 10 cases.
- **Pod `Start Time`** in `describe` is absolute with zone (`+0800`). It's the most reliable absolute anchor.
- **Event ages / object AGE** are relative to *when that kubectl command ran*. Working back from pod Start Time + AGE, the `get pods` snapshot was taken **28–55 s before** `collection_timestamp`. So converting an age to clock time has roughly **±1 min uncertainty** across different commands.
- **Alerts and metrics** times have no zone. They line up with local time (UTC+8).

**Consequence:** ordering is reliable *within one source* (events in the same `describe`, logs of one service, metrics rows). Ordering *across sources* (a Kubernetes event vs. a log line) is only trustworthy when the gap is well over ~1 min. Config faults have no change event at all; the bad setting exists from the moment the object is created.

## 4. Noise and traps (observed in many cases, regardless of the fault)

1. **`FailedCreate … error looking up service account boutique/<svc>`** appears for 4–7 services in **every** case. It's a start-up race: pods were created before their ServiceAccounts, and the controller retried. Transient events have their last occurrence ~40 s–6 min ago and then stop. The **real** missing-SA fault (admission/4) keeps repeating (`19s (x15 over 102s)`) and names an SA that doesn't exist (`currencyservices`).
2. **adservice `Unhealthy` probe failures right after start** (Java starts slowly) appear in 6/10 cases.
3. **frontend `Failed to fetch the Zone/cluster name` (GCE metadata)**: error-level lines in every case.
4. **redis-cart** startup lines contain words like "timeout", so naive error matching hits them every time.
5. **"Logs" of a container that never started** are a kubectl error message (`container "server" ... is waiting to start: ContainerCreating`), not application output.
6. Pod env var `SHOPPING_ASSISTANT_SERVICE_ADDR` points to a service that doesn't exist, so it must not become a CALLS edge.
7. startup/45 also has an unrelated `redis-cart FailedScheduling … unbound PersistentVolumeClaims` warning.
8. Caller logs name the failing service by **ClusterIP** (`dial tcp 10.68.145.154:9555`) or by DNS name, so IP→Service resolution is needed.
9. Log time formats vary: JSON `timestamp`, JSON `time`, Java `instant`, redis `21 Nov 2025 12:13:40.758`, `+08:00` prefixes. 32–100% of lines have a parseable timestamp.

## 5. The three contract evidence items, as defined for this data

- **E1 Temporal precedence:** the cause (bad config / cause event / cause metric) exists before the first symptom (caller error log, symptom event, symptom metric).
- **E2 Dependency path:** a graph path from the faulty resource to the symptomatic service, e.g. `Service ─SELECTS→ (no pods)` and `frontend ─CALLS→ Service`, or `Pod ─OWNED BY→ RS ─OWNED BY→ Deployment`, and `Service ─SELECTS→ Pod`.
- **E3 Corroborating signal of a different kind:** e.g. a Kubernetes state/event confirmed by a caller **log**, or a **metric** confirmed by a log.

## 6. Can we find E1–E3? (per case, using ground truth for this analysis only)

Legend: ✅ found · 🟡 partial/weak · ❌ not available

| Case | Root cause | E1 Temporal | E2 Dependency path | E3 Corroboration (different kind) |
|---|---|---|---|---|
| runtime/23 | container_memory_limit_too_low (cartservice) | 🟡 limit `5Mi` in spec → `FailedCreatePodSandBox … OOM-killed` (x3 over 29s). Order only from relative ages | ✅ Pod→RS→Deployment; Service has `<none>` endpoints; frontend/checkout CALL cartservice | 🟡 **Kubernetes only** (spec + event + pod status + endpoints). No app or caller logs: logs were collected seconds after start |
| runtime/9 | liveness_probe_incorrect_port (adservice) | ✅ probe `:8080` vs port `9555` → `Unhealthy` (x8) → `Killing` (x2) → restarts=2 | ✅ frontend CALLS adservice | ✅ events + **frontend logs** `failed to get ads … 10.68.145.154:9555 connection refused` (114 lines) |
| service/54 | service_selector_mismatch (shippingservice) | 🟡 no change event. Bad selector exists from Service creation; first caller error 14:31:40 UTC is within the ±1 min uncertainty | ✅ Service selector `app=shippingservice,env=production` vs pod labels `app=shippingservice` → endpoints `<none>`; frontend CALLS shippingservice | ✅ state + **frontend logs** (129 lines) |
| service/39 | service_selector_mismatch (adservice) | 🟡 same as above | ✅ endpoints `<none>`; frontend CALLS adservice | ✅ state + **frontend logs** `failed to get ads` (164 lines, ClusterIP) |
| service/12 | service_port_mapping_mismatch (paymentservice) | 🟡 same as above | ✅ `TargetPort 80` vs container port `50051`; endpoints `…:80`; **2 hops**: frontend→checkoutservice→paymentservice | ✅ state + **frontend logs** `failed to charge card` (94 lines) |
| admission/4 | missing_service_account (currencyservice) | ✅ `FailedCreate` (x15 over 102s, still recurring) started ≈1 min before the first frontend error (07:41:40 UTC), just beyond the uncertainty | ✅ Deployment asks for SA `currencyservices`, which is not in the SA list; RS creates 0 pods; endpoints `<none>`; frontend CALLS currencyservice | ✅ event + **frontend logs** with its ClusterIP (213 lines) |
| admission/24 | namespace_memory_quota_exceeded (namespace) | 🟡 quota age 112s → `FailedCreate … exceeded quota: memory-request-quota` from 102s (same-source relative ages) | ✅ Namespace→ResourceQuota (`3000Mi/3Gi`)→checkoutservice RS creates 0 pods→endpoints `<none>`; frontend CALLS checkoutservice | ✅ event + **frontend logs** `failed to complete the order … 10.68.232.185:5050` (8 lines) |
| startup/45 | missing_image_pull_secret (emailservice) | 🟡 `Failed to pull image ghcr.io/…` → `ErrImagePull` → `ImagePullBackOff`, relative ages only | ✅ emailservice endpoints empty; checkoutservice CALLS emailservice | 🟡 **Kubernetes only**. No caller logs (collected too early). Unrelated redis-cart PVC warning is present as a distractor |
| performance/11 | pod_cpu_overload (shippingservice) | ❌ **reversed** with a simple 3σ onset test: frontend p95 latency rises 16:55:46, checkout 16:55:56, shipping CPU 16:56:06. Alerts all share one time range | ✅ checkoutservice & frontend CALL shippingservice | ✅ CPU/throttling **metrics** + latency metrics + alert + frontend logs `shipping quote failure` (70 lines). Note: alerts are derived from the metrics, so they're not independent |
| performance/20 | pod_network_delay (recommendationservice) | ❌ **tie**: recommendation, productcatalog and frontend latency all jump at 00:34:07 (5 s resolution) | ✅ frontend→recommendationservice→productcatalogservice | ✅ latency **metrics** + alert + frontend logs (36 lines). No CPU change on recommendationservice |

### Summary per fault family
- **Best candidates for the first contract (Phase 5):** `service_selector_mismatch` (2 cases) and `missing_service_account`. All three evidence items are clearly present, with E3 coming from a Kubernetes state plus caller logs. `liveness_probe_incorrect_port` is also strong.
- **E1 is the weakest item overall.** For config faults the only time evidence is "the bad setting existed from creation", with ±1 min across-source uncertainty. We should define E1 as *"cause state/event exists no later than the first symptom, within tolerance"* and make the uncertainty explicit, rather than claim exact ordering.
- **runtime/23 and startup/45** only have Kubernetes evidence. Under a strict E3 ("different source") they'd come out **Plausible**, not Supported. That may be correct behaviour, but we need to decide whether "Kubernetes event vs. Kubernetes object state" counts as a different kind.
- **Performance faults:** strict E1 fails on both cases with naive onset detection. Either the contract uses a tolerance window (as with config faults) or these come out Plausible. We must not loosen the rule just to make them pass.

## 7. Implications for the Phase 3 graph build
- Parse kubectl **text**, not JSON (pods, services, endpoints, deployments, RS, SAs, quota tables; `describe` blocks; event tables).
- Entity resolution: Pod→RS by name prefix *and* `Controlled By`; RS→Deployment by name prefix; ClusterIP/DNS name in log lines → Service.
- Store event time as `observed_at_approx` plus a `time_uncertainty_s`, and keep the raw `age` string as provenance.
- Each node/edge carries `case_id` and a `source` (exact kubectl command key or log file + line index).
- Don't load `metadata.json` `result`, `difficulty`, or anything from `index.jsonl`.
