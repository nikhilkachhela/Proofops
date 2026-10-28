"""Create the empty `proofops` Neo4j database (safe to re-run; never deletes anything).

Credentials come from .env (NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD).

Usage:  .venv/bin/python scripts/create_database.py
"""
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

DB_NAME = "proofops"

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
auth = (os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD"))
if not all(auth):
    sys.exit("NEO4J_USER / NEO4J_PASSWORD not set. See .env.example.")

with GraphDatabase.driver(uri, auth=auth) as driver:
    # IF NOT EXISTS means re-running this never touches an existing database.
    driver.execute_query(f"CREATE DATABASE {DB_NAME} IF NOT EXISTS", database_="system")

    for _ in range(30):
        records, _, _ = driver.execute_query(
            "SHOW DATABASE $name YIELD name, currentStatus",
            name=DB_NAME, database_="system",
        )
        status = records[0]["currentStatus"] if records else "missing"
        if status == "online":
            break
        time.sleep(1)
    print(f"Database '{DB_NAME}' status: {status}")

    records, _, _ = driver.execute_query("MATCH (n) RETURN count(n) AS nodes", database_=DB_NAME)
    print(f"Nodes in '{DB_NAME}': {records[0]['nodes']}")
