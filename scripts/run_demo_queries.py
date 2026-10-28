"""Run the queries in neo4j/demo_queries.cypher from the terminal (table output).

Usage:  .venv/bin/python scripts/run_demo_queries.py C06          # all queries for case C06
        .venv/bin/python scripts/run_demo_queries.py C03 CQ1      # only blocks whose title contains CQ1
"""
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

case = sys.argv[1] if len(sys.argv) > 1 else "C06"
only = sys.argv[2] if len(sys.argv) > 2 else None

text = (ROOT / "neo4j/demo_queries.cypher").read_text()
blocks, title = [], ""
for chunk in text.split(";"):
    lines = [l for l in chunk.strip().splitlines()]
    comments = [l for l in lines if l.strip().startswith("//")]
    body = "\n".join(l for l in lines if not l.strip().startswith("//")).strip()
    for c in comments:
        if re.match(r"//\s*(-+\s*)?(\d|CQ|Provenance|[A-Z])", c.strip()) and len(c.strip()) > 4:
            title = c.strip("/ -")
            break
    if body and "RETURN p" not in body and "db.schema" not in body:   # graph-only queries need Browser
        blocks.append((title, body))

auth = (os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD"))
with GraphDatabase.driver(os.getenv("NEO4J_URI", "bolt://localhost:7687"), auth=auth) as driver:
    for title, q in blocks:
        if only and only not in title:
            continue
        print(f"\n=== {title}  [case={case}]")
        res = driver.execute_query(q, case=case, database_="proofops")
        if not res.records:
            print("   (no rows)")
        for r in res.records[:25]:
            print("  ", " | ".join(f"{k}={v}" for k, v in r.items()))
        if len(res.records) > 25:
            print(f"   ... {len(res.records) - 25} more rows")
