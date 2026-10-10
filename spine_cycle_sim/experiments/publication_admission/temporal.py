"""Disk-backed full temporal input ingestion and deterministic order controls."""

import gzip
import hashlib
from contextlib import contextmanager
from pathlib import Path
import sqlite3

from spine_cycle_sim.experiments.campaign_runtime import sha256_file


@contextmanager
def connect(path: Path, cache_kib: int = 65536):
    connection = sqlite3.connect(path)
    try:
        connection.execute(f"PRAGMA cache_size = -{int(cache_kib)}")
        connection.execute("PRAGMA temp_store = FILE")
        with connection:
            yield connection
    finally:
        connection.close()


def ingest(source: Path, expected_sha256: str, database: Path, max_events: int,
           cache_kib: int = 65536):
    if sha256_file(source) != expected_sha256:
        raise ValueError("temporal source identity differs")
    if database.exists():
        raise FileExistsError("refuse to reuse a temporal database")
    decompressed = hashlib.sha256()
    inversions = loops = records = 0
    previous = None
    first = last = minimum = maximum = None
    with connect(database, cache_kib) as connection:
        connection.execute("CREATE TABLE events(seq INTEGER PRIMARY KEY, timestamp INTEGER NOT NULL, edge INTEGER NOT NULL)")
        pending = []
        with gzip.open(source, "rb") as stream:
            for line_number, raw in enumerate(stream, 1):
                decompressed.update(raw)
                line = raw.strip()
                if not line or line.startswith(b"#"):
                    continue
                fields = line.split()
                if len(fields) != 3:
                    raise ValueError(f"temporal line {line_number}: expected src dst timestamp")
                src, dst, timestamp = map(int, fields)
                if not (0 <= src < 2**31 and 0 <= dst < 2**31 and 0 <= timestamp < 2**63):
                    raise ValueError(f"temporal line {line_number}: unsupported signed-ABI value")
                if records >= max_events:
                    raise ValueError("temporal event limit exceeded")
                inversions += previous is not None and timestamp < previous
                loops += src == dst
                first = timestamp if first is None else first
                last = previous = timestamp
                minimum = timestamp if minimum is None else min(minimum, timestamp)
                maximum = timestamp if maximum is None else max(maximum, timestamp)
                pending.append((records, timestamp, (src << 32) | dst))
                records += 1
                if len(pending) == 8192:
                    connection.executemany("INSERT INTO events VALUES(?,?,?)", pending)
                    pending.clear()
            connection.executemany("INSERT INTO events VALUES(?,?,?)", pending)
        if not records:
            raise ValueError("empty temporal input")
        connection.execute("CREATE INDEX time_order ON events(timestamp,seq)")
    if sha256_file(source) != expected_sha256:
        raise ValueError("temporal source changed during ingestion")
    return {"events": records, "self_loop_events": loops, "timestamp_inversions": inversions,
            "first_timestamp": first, "last_timestamp": last, "min_timestamp": minimum,
            "max_timestamp": maximum, "source_sha256": expected_sha256,
            "decompressed_sha256": decompressed.hexdigest(), "database_bytes": database.stat().st_size}


def materialize_order(connection, ordering: str):
    order = {"file_order": "seq", "timestamp_then_file_order": "timestamp,seq"}.get(ordering)
    if order is None:
        raise ValueError("undeclared temporal ordering")
    connection.execute("DROP TABLE IF EXISTS firsts")
    # Rank every raw event before grouping: duplicates/loops still consume base positions.
    connection.execute(f"""CREATE TABLE firsts AS
        SELECT edge, MIN(position) AS first, MIN(timestamp) AS earliest_timestamp
        FROM (SELECT edge, timestamp, ROW_NUMBER() OVER(ORDER BY {order}) - 1 AS position FROM events)
        GROUP BY edge""")
    connection.execute("CREATE INDEX first_order ON firsts(first)")
    connection.commit()


def ordered_events(connection, ordering: str):
    order = {"file_order": "seq", "timestamp_then_file_order": "timestamp,seq"}.get(ordering)
    if order is None:
        raise ValueError("undeclared temporal ordering")
    return connection.execute(f"SELECT edge,timestamp FROM events ORDER BY {order}")
