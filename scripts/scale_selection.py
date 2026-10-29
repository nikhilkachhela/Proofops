"""Scale the case slice from 10 to N cases, stratified across ALL 8 Online Boutique categories.

Design (researcher decisions, recorded so they can be defended):
  * Keep the original 10 cases first, so their opaque IDs C01..C10 do not change.
  * Per-category quota proportional to the category's real size in Online Boutique
    (largest-remainder rounding), so the sample looks like the dataset.
  * Within a category, draw uniformly at random with seed 42 (reproducible).
  * Split: ~20% "dev" (used to write contracts), the rest "test" (held out). Stratified by
    category with seed 42. The original 10 are all "dev", because we already looked at them.

NOTE: index.jsonl holds ground truth. It is used only for sampling and splitting (a researcher
decision), never as agent input.

Usage:
  .venv/bin/python scripts/scale_selection.py --total 60            # plan + size report only
  .venv/bin/python scripts/scale_selection.py --total 60 --download # then download the new cases
"""
import argparse, json, math, random
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "data/raw/hf/index.jsonl"
SEL = ROOT / "data/selected_cases.json"
SEED = 42
REPO = "LLM4Ops/Cloud-OpsBench"


def quotas(sizes, total):
    raw = {c: total * n / sum(sizes.values()) for c, n in sizes.items()}
    q = {c: math.floor(v) for c, v in raw.items()}
    for c in sorted(raw, key=lambda c: raw[c] - q[c], reverse=True)[: total - sum(q.values())]:
        q[c] += 1
    return q


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--total", type=int, default=60)
    ap.add_argument("--dev-share", type=float, default=0.2)
    ap.add_argument("--download", action="store_true")
    a = ap.parse_args()

    rows = [json.loads(l) for l in INDEX.open() if l.strip()]
    ob = [r for r in rows if r["system"] == "boutique"]
    by_key = {r["case_key"]: r for r in ob}
    sizes = Counter(r["category"] for r in ob)
    q = quotas(sizes, a.total)

    old = json.loads(SEL.read_text())
    keep = old["case_keys"][:10]
    have = Counter(by_key[k]["category"] for k in keep)

    rng = random.Random(SEED)
    new = []
    for cat in sorted(sizes):
        need = q[cat] - have[cat]
        if need <= 0:
            continue
        pool = sorted((r for r in ob if r["category"] == cat and r["case_key"] not in keep),
                      key=lambda r: int(r["case_id"]))
        new += [r["case_key"] for r in rng.sample(pool, need)]
    case_keys = keep + new

    # dev/test split: originals are dev; top up dev per category to ~dev_share
    split = {k: "dev" for k in keep}
    per_cat = defaultdict(list)
    for k in new:
        per_cat[by_key[k]["category"]].append(k)
    rng2 = random.Random(SEED)
    for cat, ks in sorted(per_cat.items()):
        target_dev = max(1, round(q[cat] * a.dev_share)) - sum(1 for k in keep if by_key[k]["category"] == cat)
        dev = set(rng2.sample(ks, max(0, min(target_dev, len(ks)))))
        for k in ks:
            split[k] = "dev" if k in dev else "test"

    print(f"{'category':16s} {'OB size':>7s} {'quota':>6s} {'kept':>5s} {'new':>4s} {'dev':>4s} {'test':>5s}")
    for cat in sorted(sizes):
        ks = [k for k in case_keys if by_key[k]["category"] == cat]
        print(f"{cat:16s} {sizes[cat]:7d} {q[cat]:6d} {have[cat]:5d} {len(ks) - have[cat]:4d} "
              f"{sum(split[k] == 'dev' for k in ks):4d} {sum(split[k] == 'test' for k in ks):5d}")
    print(f"TOTAL cases: {len(case_keys)}  (dev {sum(v == 'dev' for v in split.values())}, "
          f"test {sum(v == 'test' for v in split.values())})")

    from huggingface_hub import HfApi
    info = HfApi().dataset_info(REPO, files_metadata=True)
    size_new = sum((f.size or 0) for f in info.siblings
                   if any(f.rfilename.startswith(f"benchmark/{k}/") for k in new))
    print(f"Download needed for {len(new)} new cases: {size_new / 1e6:.1f} MB")

    SEL.write_text(json.dumps({
        "seed": SEED, "system": "boutique", "total": len(case_keys),
        "design": "original 10 first; proportional stratified sample of all 8 categories; ~20% dev / 80% test",
        "case_keys": case_keys,
        "split": split,
        "allow_patterns": [f"benchmark/{k}/*" for k in case_keys],
    }, indent=2))
    print(f"Wrote {SEL.relative_to(ROOT)}")

    if a.download:
        from huggingface_hub import snapshot_download
        snapshot_download(REPO, repo_type="dataset", local_dir=str(ROOT / "data/raw/hf"),
                          allow_patterns=[f"benchmark/{k}/**" for k in new] + ["manifest.json", "release.json"])
        print("Download complete.")


if __name__ == "__main__":
    main()
