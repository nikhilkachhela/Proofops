# Brief for Claude working in this repository

This is **ProofOps** (DAMG 6310, Northeastern). Read `README.md` first. The core pipeline works on two hand-written demo cases. Your job is to connect it to real data, without breaking what works.

## Rules
1. **Never show ground truth to the agent.** In Cloud-OpsBench that means `metadata.json` ground-truth fields, `process-label/` and `golden-trajectory/`. Only `ground_truth.json` (scoring) may contain it.
2. **Don't invent data or results.** If the real files differ from what this brief expects, describe what you found and adapt.
3. **Ask before large downloads.** Use `huggingface_hub.snapshot_download(..., allow_patterns=[...])` to fetch only the cases you need.
4. **Run the tests after every change.** Use `python tests/test_pipeline.py`. Keep both demo cases passing.
5. **Stop after each task** and summarize what changed.

## Tasks, in order
1. **Download data.** Fetch `index.jsonl` and about 10 Online Boutique cases across at least 4 categories from `LLM4Ops/Cloud-OpsBench` (dataset repo). Clone `github.com/LLM4Ops/Cloud-OpsBench` into `vendor/`.
2. **Document the files.** Inspect 3 cases and write `docs/DATA_NOTES.md`: the exact file names and fields for Kubernetes state, events, logs, alerts and metrics, and where the ground truth lives.
3. **Complete the adapter.** Finish `adapters/cloudopsbench.py` and convert the 10 cases into `data/cases/`. Write the Online Boutique call graph to `calls.json`.
4. **Extend the vocabulary.** Add thesaurus patterns and event reasons in `proofops/thesaurus.py` and `ontology/thesaurus.ttl` for the log messages you actually see.
5. **Check the contracts.** Run `python scripts/run_experiment.py data/cases`. Report which fault types reach SUPPORTED and why the others don't. Add contracts (`proofops/contracts.py` + `contracts/contracts.shacl.ttl`) only for fault types whose evidence exists in the snapshots.
6. **Verify the live paths.** Load into Neo4j with `python scripts/load_neo4j.py data/cases/*` and confirm `--neo4j` gives the same verdicts as the in-memory store. Install pyshacl and confirm `engine: shacl` agrees with the Python check.
