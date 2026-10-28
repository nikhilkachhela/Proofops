# Environment Report (Phase 0)

Checked on 2026-10-14. Everything below was actually run and verified on this machine, except where marked "not verified".

## Machine
| Item | Found |
|---|---|
| OS | macOS 26.1 (Apple Silicon, arm64) |
| Python | 3.11.2 (`/Library/Frameworks/Python.framework/Versions/3.11`) |
| Git | 2.51.0 |
| Java | 19.0.2 (Oracle) |
| Node.js | 25.9.0 (not needed for this project) |
| Free disk space | **5.6 GB free (disk is 98% full)** |

## Python environment
- Virtual environment: `.venv/` in the project folder (nothing installed system-wide).
- Installed versions are pinned in `requirements.txt`:
  huggingface_hub 2.2.0, neo4j 6.4.0, rdflib 7.6.0, pyshacl 0.40.1, owlrl 7.6.2, pandas 3.0.6, python-dotenv 1.2.4.
- `python-dotenv` was added beyond the brief so Neo4j credentials can be kept in a git-ignored `.env` file instead of being typed into code.
- Smoke test: pyshacl correctly rejected a tiny test graph that broke a shape, so the SHACL validator works.

## Neo4j
- Neo4j Desktop 2 is installed and a database server is **running**.
- Version: **Neo4j 2026.09.0, Enterprise edition** (reported by `http://localhost:7474/`).
- Bolt port `bolt://localhost:7687` is **reachable** (`scripts/check_neo4j.py`).
- **Login verified** as user `neo4j` using credentials from the git-ignored `.env` file. Existing databases: `neo4j` (online) and `system` (online); there is no `proofops` database yet.
- Enterprise edition supports `CREATE DATABASE`, so a separate `proofops` database should be possible in Phase 3 (not verified yet).

## Protégé
- **Not found** in `/Applications`, `~/Applications`, or by Spotlight search. It's needed in Phase 4 to open the ontology and run the HermiT reasoner.

## Project folders created
`data/`, `scripts/`, `neo4j/`, `ontology/`, `contracts/`, `docs/`, plus `.env.example`, `.gitignore`, `requirements.txt`.
`CLAUDE.md` was copied from `files/` to the project root so it loads automatically. The original is unchanged.

## Risks / actions needed
1. **Disk space**: 5.6 GB free. The full dataset (~3.8 GB) would nearly fill the disk. Phase 1 downloads only about 10 cases, so this is fine, but don't download the full set.
2. ~~Neo4j password~~: done. `.env` was created and the login check passes.
3. **Protégé**: install Protégé 5.6.x from https://protege.stanford.edu before Phase 4.

## Reproduce
```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/check_neo4j.py
```
