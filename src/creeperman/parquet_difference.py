"""Compare observed exact host-years with a frozen baseline and a chosen review ledger."""
import argparse
import json
from decimal import Decimal
from pathlib import Path

from .core import HOST, YEARS, audit_binding, host, jsonl, sha, weights


def load_source(db, name, path):
    # Both formats occur in the archived experiments. Only the observation year
    # and canonical identity travel across the join; weights and decisions can change.
    data = db.read_parquet(str(path))
    types = dict(zip(data.columns, map(str, data.types)))
    year_columns = set(types).intersection(("year", "source_year"))
    if types.get("hostname") != "VARCHAR" or len(year_columns) != 1:
        raise ValueError(f"{path}: expected hostname and exactly one of year or source_year")
    year, = year_columns
    if types[year] not in ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT"):
        raise ValueError(f"{path}: expected integer years")
    db.execute(f"INSERT INTO input_rows SELECT DISTINCT ?, {year}, hostname FROM read_parquet(?)", [name, str(path)])


def load_reviewed(db, path, authority):
    digest = sha(path)
    # Stream and batch the usual reviewed.jsonl schema, including ledgers with
    # several legitimate evidence records for the same hostname-year.
    batch = []
    for line, record in jsonl(path):
        h, y = record["hostname"], record["year"]
        if (record.get("authority") != authority or record.get("validation_status") != "verified_web_year"
                or type(y) is not int or y not in YEARS or host(h) != h):
            raise ValueError(f"{path}:{line}: invalid reviewed host-year or authority")
        batch.append((y, h))
        if len(batch) == 1000:
            db.executemany("INSERT INTO reviewed_raw VALUES (?,?)", batch)
            batch.clear()
    if batch:
        db.executemany("INSERT INTO reviewed_raw VALUES (?,?)", batch)
    if sha(path) != digest:
        raise ValueError("review ledger changed while reading")
    db.execute("CREATE TEMP TABLE reviewed AS SELECT DISTINCT year,hostname FROM reviewed_raw")
    return digest


def load_hits(db, directory, year, expected):
    parquet = directory / f"baseline-{year}.parquet"
    if parquet.exists():
        receipt = json.loads(parquet.with_suffix(".json").read_bytes())
        if receipt["source_sha256"] != expected["sha256"] or sha(parquet) != receipt["sha256"]:
            raise ValueError(f"{parquet}: baseline projection fingerprint mismatch")
        rows, dated = db.execute("SELECT count(*), count(*) FILTER (WHERE year=?) FROM read_parquet(?)",
                                 [year, str(parquet)]).fetchone()
        if rows != expected["unique_valid_domains"] or dated != rows:
            raise ValueError(f"{parquet}: wrong baseline year or row count")
        source = "SELECT hostname FROM read_parquet(?)"
        params = [str(parquet)]
    else:
        text = directory / f"{year}.txt"
        if sha(text) != expected["sha256"]:
            raise ValueError(f"{text}: baseline fingerprint mismatch")
        source = """SELECT lower(trim(hostname)) AS hostname FROM read_csv(?,
                    header=false, auto_detect=false, delim='\t', quote='', columns={'hostname':'VARCHAR'})"""
        params = [str(text)]
    db.execute(f"""INSERT INTO hits SELECT DISTINCT ?, b.hostname FROM ({source}) b
                SEMI JOIN (SELECT hostname FROM targets WHERE year=?) t USING(hostname)""", [year, *params, year])


SUMMARY = """
SELECT t.source, t.year, count(*) AS exact_hosts, count(h.hostname) AS baseline_hits,
       count(*) - count(h.hostname) AS outside_baseline,
       count(*) FILTER (WHERE h.hostname IS NULL AND r.hostname IS NOT NULL) AS already_reviewed_outside,
       count(*) FILTER (WHERE h.hostname IS NULL AND r.hostname IS NULL) AS unsettled_candidates,
       coalesce(sum(w.units) FILTER (WHERE h.hostname IS NULL AND r.hostname IS NULL),0) AS unsettled_weight_units
FROM targets t
LEFT JOIN hits h USING(year,hostname)
LEFT JOIN reviewed r USING(year,hostname)
LEFT JOIN tld_weights w ON w.tld=regexp_extract(t.hostname,'([^.]+)$',1)
GROUP BY t.source,t.year ORDER BY t.source,t.year
"""


def compare(sources, baseline_dir, reviewed, model, audit):
    import duckdb

    binding, annual = audit_binding(audit, model)
    fixed = []
    for tld, weight in weights(model).items():
        units = weight * 10000
        if units != units.to_integral_value():
            raise ValueError("model has weights finer than 1/10,000 EED")
        fixed.append((tld, int(units)))

    with duckdb.connect() as db:
        db.execute("SET threads=2")
        db.execute("SET memory_limit='900MB'")
        db.execute("CREATE TEMP TABLE input_rows(source VARCHAR, year BIGINT, hostname VARCHAR)")
        for name, path in sources:
            load_source(db, name, Path(path).resolve(strict=True))
        db.execute("CREATE TEMP TABLE targets AS SELECT DISTINCT * FROM input_rows")
        invalid = db.execute("""SELECT 1 FROM targets WHERE year IS NULL OR year NOT BETWEEN ? AND ?
                             OR hostname IS NULL OR length(hostname)>253 OR NOT regexp_full_match(hostname,?)
                             OR regexp_full_match(hostname,'www[.][a-z]+') LIMIT 1""",
                             [min(YEARS), max(YEARS), HOST.pattern.removesuffix(r"\Z")]).fetchone()
        if invalid:
            raise ValueError("source contains invalid or noncanonical hostname/year; inspect the source extraction")
        db.execute("CREATE TEMP TABLE reviewed_raw(year INTEGER, hostname VARCHAR)")
        ledger_sha = load_reviewed(db, reviewed, binding["id"])
        db.execute("CREATE TEMP TABLE hits(year INTEGER, hostname VARCHAR)")
        for year, in db.execute("SELECT DISTINCT year FROM targets ORDER BY year").fetchall():
            load_hits(db, baseline_dir, year, annual[year])
        db.execute("CREATE TEMP TABLE tld_weights(tld VARCHAR PRIMARY KEY, units INTEGER)")
        db.executemany("INSERT INTO tld_weights VALUES (?,?)", fixed)
        result = db.execute(SUMMARY)
        names = [c[0] for c in result.description]
        rows = [dict(zip(names, row)) for row in result.fetchall()]
        for row in rows:
            row["unsettled_eed_ceiling"] = str(Decimal(row.pop("unsettled_weight_units")).scaleb(-4))
    return {"authority": binding["id"], "reviewed_sha256": ledger_sha, "rows": rows, "qualified_new_eed": None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", nargs=2, action="append", metavar=("LABEL", "PARQUET"), required=True,
                        help="repeat for each source or shard; shards with the same label are combined")
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--reviewed", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--audit", type=Path, default=Path("audit/baseline_summary.json"))
    args = parser.parse_args()
    print(json.dumps(compare(args.source, args.baseline_dir, args.reviewed, args.model, args.audit), indent=2))


if __name__ == "__main__":
    main()
