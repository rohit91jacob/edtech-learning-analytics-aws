"""Parse every model compiled for the Athena target with sqlglot's Trino dialect.

`dbt compile --target athena` proves the Jinja renders for Athena; this proves the rendered SQL is
syntactically valid Trino (Athena engine v3), e.g. that the DuckDB-only functions were dispatched
away. It does not prove semantics, which only a real Athena run can.

    uv run python scripts/check_athena_sql.py dbt/target/compiled
"""

from __future__ import annotations

import sys
from pathlib import Path

import sqlglot
from sqlglot.errors import ParseError

DUCKDB_ONLY = ("quantile_cont(", "iceberg_scan(")


def main(root: Path) -> int:
    files = sorted(root.rglob("*.sql"))
    if not files:
        print(f"no compiled SQL under {root}; run dbt compile --target athena first")
        return 1
    failures = 0
    for path in files:
        sql = path.read_text(encoding="utf-8")
        problems = [f for f in DUCKDB_ONLY if f in sql.lower()]
        try:
            sqlglot.parse(sql, read="trino")
        except ParseError as exc:
            problems.append(str(exc).splitlines()[0])
        if problems:
            failures += 1
            print(f"FAIL {path.relative_to(root)}: {'; '.join(problems)}")
    print(
        f"{len(files) - failures}/{len(files)} compiled Athena models and tests parse as Trino SQL"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "dbt/target/compiled")))
