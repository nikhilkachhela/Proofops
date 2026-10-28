# Phase 1: Data Slice

## Source
| What | Where | Version |
|---|---|---|
| Dataset | Hugging Face `LLM4Ops/Cloud-OpsBench` → `data/raw/hf/` | HF revision `1a02e543`, release v1.0.0 (source commit `ea05dafb`) |
| Code / tools / MCP / evaluator | GitHub `LLM4Ops/Cloud-OpsBench` → `vendor/Cloud-OpsBench/` | commit `e4fbd37f` (2026-10-14) |
| License | MIT, © 2026 Yilun Wang | `data/raw/hf/LICENSE` |

Both `data/raw/` and `vendor/` are git-ignored. To re-create them:
```bash
.venv/bin/python scripts/select_cases.py   # writes data/selected_cases.json
```
Then download the selected folders (see `allow_patterns` in that file) with `huggingface_hub.snapshot_download`.

## What `index.jsonl` contains
754 lines, one per case (550 Online Boutique, 204 TrainTicket). This matches `release.json`.
Fields: `case_id, case_key, category, difficulty, fault_object, fault_taxonomy, metadata_path, milestone_path, namespace, query, root_cause, system, tool_cache_path, trajectory_paths`.

**⚠ Ground truth leak risk:** `root_cause`, `fault_object` and `fault_taxonomy` are the answers. `index.jsonl` counts as a ground-truth file. It is used only for sampling and scoring, never as agent input.
`query` holds the symptom description (for example, "Partial Service Unreachability."). This is the intended agent input.

**⚠ Second leak risk:** the folder path itself, `benchmark/boutique/<category>/<id>/`, reveals the fault category. The agent must receive cases under an opaque ID, never their folder path.

## Online Boutique: 8 categories, 47 root causes
admission 58 · codedefect 98 · infrastructure 40 · performance 29 · runtime 45 · scheduling 164 · service 54 · startup 62.

## Selected cases (10 cases from 5 categories, seed 42, 54 MB)
Root causes were chosen by us to match the node types in the brief (ServiceAccount, Secret, Service selectors, and so on). Cases were then drawn at random with seed 42.

| Case | Category | Size |
|---|---|---|
| boutique/runtime/23 | runtime | 0.7 MB |
| boutique/runtime/9 | runtime | 1.3 MB |
| boutique/service/54 | service | 1.3 MB |
| boutique/service/39 | service | 1.2 MB |
| boutique/service/12 | service | 1.0 MB |
| boutique/admission/4 | admission | 1.1 MB |
| boutique/admission/24 | admission | 1.2 MB |
| boutique/startup/45 | startup | 0.7 MB |
| boutique/performance/11 | performance | 25.1 MB |
| boutique/performance/20 | performance | 20.7 MB |

(The specific root cause per case is in `scripts/select_cases.py` / `index.jsonl`. It is not repeated here so these notes stay safe to share.)

## What's in each case folder (verified for all 10)
`metadata.json`, `tool_cache.json`, `code/` (source code of the 10 microservices), and `raw_data/`, which contains:

| File | Present in |
|---|---|
| `k8s_states.json` (~210–295 KB) | 10/10 |
| `logs.json` (16 KB – 24 MB) | 10/10 |
| `alert.json` | 10/10, but **empty (`{}`) in 8/10**. Only the 2 performance cases contain alerts |
| `metrics.csv` | **2/10, performance cases only** |

**Differs from the brief:** alerts and metrics are not available for most fault types. For non-performance cases, any "corroborating signal of a different kind" will have to come from Kubernetes events/state and logs, not from metrics or alerts. We'll confirm this per fault type in Phase 2.

## The GitHub repo
Cloned shallow and sparse (6.8 MB). We skipped `benchmark/`, `golden-trajectory/` and `process-label/`, which duplicate the HF data and contain ground truth.
It contains `agents/` (reference agents), `cloudopsbench_mcp/` (MCP tool server), `interact.py`, and `fault_knowledge/` (40 YAML templates).
The `fault_knowledge/` templates describe each fault type in general terms (mechanism, triggers, injection commands, generic `nginx` examples). They don't contain per-case answers. **Open decision:** whether these templates may inform our contracts.

## Disk
Free space went from 5.6 GB to 4.3 GB during Phases 0 and 1. Our files account for only part of that (~54 MB data + venv + 6.8 MB repo), so something else on the machine is also using space.
