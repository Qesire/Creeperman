"""Extract exact hostnames and URL witnesses from the local LAW WebBase 2001 node list.

Install the project with its parquet extra. The default checksum and node count
identify webbase-2001.urls.gz in the LAW random-access graph ordering.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
import re
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from creeperman.core import url_host
from creeperman.source_precheck import new_output


PUBLISHER = "https://law.di.unimi.it/webdata/webbase-2001/"
PUBLISHED_MD5 = "cf08c1cebef1f79387d2c07c61f84ad8"
PUBLISHED_NODES = 118_142_155
AUTHORITY = re.compile(br"^(https?://[^/?#\t\r\n]+)(?:[/?#]|$)", re.I)
RUN_SCHEMA = pa.schema([
    ("hostname", pa.string()), ("nodes", pa.int64()),
    ("first_line", pa.int64()), ("first_url_bytes", pa.binary()),
])


@lru_cache(maxsize=32768)
def parse_host(identity):
    try:
        return url_host(identity.decode("utf-8"))
    except ValueError:
        return None


def scan(stream, writer, chunk_hosts):
    """Reduce each chunk in memory. Preserve the first physical URL for each host."""
    chunk = {}
    previous_prefix = None
    last_entry = None
    line_number = accepted = 0

    def flush():
        if chunk:
            columns = zip(*((name, *values) for name, values in chunk.items()))
            writer.write_table(pa.Table.from_arrays(list(columns), schema=RUN_SCHEMA))
            chunk.clear()

    for line_number, line in enumerate(stream, 1):
        url = line.removesuffix(b"\n").removesuffix(b"\r")
        if not url.isascii():
            url.decode("utf-8", errors="strict")   # LAW specifies UTF-8, including paths.
        if previous_prefix is None or not url.startswith(previous_prefix):
            match = AUTHORITY.match(url)
            identity = match[1] if match else url
            hostname = parse_host(identity)
            previous_prefix = identity + b"/" if match else None
            last_entry = None
            if hostname is not None:
                if hostname not in chunk and len(chunk) >= chunk_hosts:
                    flush()
                last_entry = chunk.get(hostname)
                if last_entry is None:
                    last_entry = chunk[hostname] = [0, line_number, url]
        if last_entry is not None:
            last_entry[0] += 1
            accepted += 1
    flush()
    return line_number, accepted


def extract(source, out, expected_md5=PUBLISHED_MD5, expected_nodes=PUBLISHED_NODES,
            *, chunk_hosts=40000):
    if not re.fullmatch("[a-fA-F0-9]{32}", expected_md5) or expected_nodes < 1 or chunk_hosts < 1:
        raise ValueError("provide a valid compressed MD5 and positive node and chunk sizes")
    with new_output(out) as stage, TemporaryDirectory(dir=stage) as temp:
        partial = Path(temp) / "runs.parquet"
        with Path(source).open("rb") as raw:
            before = os.fstat(raw.fileno())
            md5, sha256 = hashlib.md5(usedforsecurity=False), hashlib.sha256()
            for data in iter(lambda: raw.read(4 << 20), b""):
                md5.update(data)
                sha256.update(data)
            if md5.hexdigest() != expected_md5.lower():
                raise ValueError("compressed file does not match expected MD5")
            raw.seek(0)
            with gzip.GzipFile(fileobj=raw) as gz, io.BufferedReader(gz, 1 << 20) as lines:
                with pq.ParquetWriter(partial, RUN_SCHEMA, compression="zstd") as writer:
                    count, accepted = scan(lines, writer, chunk_hosts)
            after = os.fstat(raw.fileno())
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError("source changed during extraction")
            if count != expected_nodes:
                raise ValueError(f"expected {expected_nodes} URL node lines, read {count}")

        output = stage / "hosts.parquet"
        with duckdb.connect() as db:
            db.execute("SET threads=2")
            db.execute("SET memory_limit='750MB'")
            db.execute("SET temp_directory=?", [temp])
            db.read_parquet(str(partial)).create_view("host_runs")
            db.sql("""
                SELECT hostname, 2001 AS year, sum(nodes)::BIGINT AS nodes,
                       min(first_line) AS first_line, min(first_line)-1 AS first_node_id,
                       arg_min(first_url_bytes, first_line) AS first_url_bytes
                FROM host_runs GROUP BY hostname ORDER BY hostname
            """).write_parquet(str(output), compression="zstd")
            hosts, total = db.execute("SELECT count(*), coalesce(sum(nodes),0) FROM read_parquet(?)",
                                      [str(output)]).fetchone()
        if accepted != total:
            raise RuntimeError("aggregated counts differ from accepted URL lines")
        report = {
            "publisher": PUBLISHER, "input_file": Path(source).name,
            "compressed_md5": md5.hexdigest(), "compressed_sha256": sha256.hexdigest(),
            "compressed_bytes": after.st_size, "physical_node_lines": count,
            "valid_url_lines": accepted, "excluded_url_lines": count-accepted,
            "distinct_hosts": hosts, "year": 2001,
            "date_basis": "WebBase graph collection year; per-node capture timestamps and response status are absent.",
            "record_locator": "first_line is 1-based; first_node_id is 0-based in this exact compressed file.",
            "qualification": "candidate_only",
        }
        (stage / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="new output directory")
    parser.add_argument("--expected-md5", default=PUBLISHED_MD5)
    parser.add_argument("--expected-nodes", type=int, default=PUBLISHED_NODES)
    args = parser.parse_args()
    print(json.dumps(extract(args.input, args.out, args.expected_md5, args.expected_nodes)))


if __name__ == "__main__":
    main()
