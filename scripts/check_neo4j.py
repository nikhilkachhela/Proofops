"""Check that Neo4j is reachable and (if credentials are set) that we can log in.

Credentials are read from environment variables or a local .env file:
    NEO4J_URI (default bolt://localhost:7687), NEO4J_USER, NEO4J_PASSWORD
The password is never printed.

Usage:  .venv/bin/python scripts/check_neo4j.py
"""
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
user = os.getenv("NEO4J_USER")
password = os.getenv("NEO4J_PASSWORD")

parsed = urlparse(uri)
host, port = parsed.hostname or "localhost", parsed.port or 7687

# Step 1: is anything listening on the Bolt port?
try:
    with socket.create_connection((host, port), timeout=3):
        print(f"[ok]   Port {host}:{port} is open (Neo4j Bolt port reachable)")
except OSError as exc:
    print(f"[fail] Cannot reach {host}:{port}: {exc}")
    print("       Is the database started in Neo4j Desktop?")
    sys.exit(1)

# Step 2: can we log in?
if not user or not password:
    print("[skip] NEO4J_USER / NEO4J_PASSWORD not set, so login was not tested.")
    print("       Copy .env.example to .env and fill in your Neo4j password.")
    sys.exit(2)

from neo4j import GraphDatabase  # noqa: E402

try:
    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        driver.verify_connectivity()
        print(f"[ok]   Logged in to {uri} as '{user}'")
        records, _, _ = driver.execute_query(
            "CALL dbms.components() YIELD name, versions, edition "
            "RETURN name, versions[0] AS version, edition"
        )
        for r in records:
            print(f"[ok]   {r['name']} {r['version']} ({r['edition']} edition)")
        try:
            records, _, _ = driver.execute_query(
                "SHOW DATABASES YIELD name, currentStatus RETURN name, currentStatus",
                database_="system",
            )
            names = ", ".join(f"{r['name']} ({r['currentStatus']})" for r in records)
            print(f"[ok]   Databases: {names}")
        except Exception as exc:  # listing databases is informational only
            print(f"[warn] Could not list databases: {type(exc).__name__}")
except Exception as exc:
    # Print only the error type/message, never the credentials.
    print(f"[fail] Login failed: {type(exc).__name__}: {exc}")
    sys.exit(1)
