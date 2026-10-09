"""Build the committed test fixtures: a small, seeded sample of real OULAD rows.

OULAD is CC BY 4.0, which permits redistribution with attribution (see DATA_LICENSE.md). The
sample keeps four module presentations (two per module, one of them the 2014J hold-out) and a
stratified sample of students in each, plus every row that belongs to them, so all referential
checks still hold. Output is byte-for-byte reproducible from the same archive.

    uv run python scripts/build_fixtures.py ~/projects/_data/edtech-learning-analytics-aws/raw/anonymisedData.zip
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import random
import zipfile
from collections import defaultdict
from pathlib import Path

PRESENTATIONS = [("AAA", "2013J"), ("AAA", "2014J"), ("CCC", "2014B"), ("CCC", "2014J")]
PER_RESULT = {"Pass": 24, "Distinction": 8, "Fail": 16, "Withdrawn": 24}
SEED = 20171128
OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "oulad"
MAX_BYTES = 300 * 1024


def read(zf: zipfile.ZipFile, name: str) -> tuple[list[str], list[list[str]]]:
    with zf.open(name) as fh:
        reader = csv.reader(io.TextIOWrapper(fh, encoding="utf-8", newline=""))
        header = next(reader)
        return header, list(reader)


def write_csv(path: Path, header: list[str], rows: list[list[str]], *, gz: bool = False) -> None:
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    data = buf.getvalue().encode("utf-8")
    if gz:
        data = gzip.compress(data, compresslevel=9, mtime=0)
    path.write_bytes(data)
    if len(data) >= MAX_BYTES:
        raise SystemExit(f"{path.name} is {len(data)} bytes; fixtures must stay under 300 KB")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    rng = random.Random(SEED)
    keep = set(PRESENTATIONS)
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.csv*"):
        old.unlink()

    with zipfile.ZipFile(args.archive) as zf:
        h_info, info = read(zf, "studentInfo.csv")
        by_group: dict[tuple, list[list[str]]] = defaultdict(list)
        for row in info:
            key = (row[0], row[1])
            if key in keep:
                by_group[(*key, row[11])].append(row)
        chosen = set()
        for (module, pres, result), rows in sorted(by_group.items()):
            rows = sorted(rows, key=lambda r: int(r[2]))
            for row in rng.sample(rows, min(PER_RESULT[result], len(rows))):
                chosen.add((module, pres, row[2]))

        def enrolled(row, m=0, p=1, s=2):
            return (row[m], row[p], row[s]) in chosen

        write_csv(OUT / "studentInfo.csv", h_info, [r for r in info if enrolled(r)])
        h, rows = read(zf, "studentRegistration.csv")
        write_csv(OUT / "studentRegistration.csv", h, [r for r in rows if enrolled(r)])
        h, rows = read(zf, "courses.csv")
        write_csv(OUT / "courses.csv", h, [r for r in rows if (r[0], r[1]) in keep])
        h, assessments = read(zf, "assessments.csv")
        assessments = [r for r in assessments if (r[0], r[1]) in keep]
        write_csv(OUT / "assessments.csv", h, assessments)
        presentation_of = {r[2]: (r[0], r[1]) for r in assessments}
        h, rows = read(zf, "studentAssessment.csv")
        write_csv(
            OUT / "studentAssessment.csv",
            h,
            [
                r
                for r in rows
                if r[0] in presentation_of and (*presentation_of[r[0]], r[1]) in chosen
            ],
        )
        h, rows = read(zf, "vle.csv")
        write_csv(OUT / "vle.csv", h, [r for r in rows if (r[1], r[2]) in keep])
        h, rows = read(zf, "studentVle.csv")
        parts: dict[tuple, list[list[str]]] = defaultdict(list)
        for r in rows:
            if enrolled(r):
                parts[(r[0], r[1])].append(r)
        for i, key in enumerate(PRESENTATIONS):
            write_csv(OUT / f"studentVle.part-{i:03d}.csv.gz", h, parts[key], gz=True)

    for path in sorted(OUT.glob("*.csv*")):
        print(f"{path.name:32s} {path.stat().st_size:>8,d} bytes")
    print(f"students: {len(chosen)}")


if __name__ == "__main__":
    main()
