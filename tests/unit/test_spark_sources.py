"""Static checks on the modules shipped to EMR Serverless (no JVM needed)."""

from __future__ import annotations

import ast
import re
import sys
import zipfile
from pathlib import Path

from edtech_analytics.aws.emr_package import build
from edtech_analytics.spark import dq

SPARK_DIR = Path(__file__).resolve().parents[2] / "src" / "edtech_analytics" / "spark"


def test_spark_modules_parse_as_python_39():
    for path in sorted(SPARK_DIR.glob("*.py")):
        ast.parse(path.read_text(), filename=str(path), feature_version=(3, 9))


def test_spark_modules_only_import_stdlib_and_pyspark():
    allowed_roots = {"pyspark", "edtech_analytics", "__future__"}
    for path in sorted(SPARK_DIR.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                root = name.split(".")[0]
                assert root in allowed_roots or root in sys.stdlib_module_names, (path.name, name)


def test_package_is_reproducible(tmp_path):
    first = build(tmp_path / "a")
    second = build(tmp_path / "b")
    assert sorted(first.values()) == sorted(second.values())
    with zipfile.ZipFile(tmp_path / "a" / "edtech_spark.zip") as zf:
        names = set(zf.namelist())
    assert "edtech_analytics/__init__.py" in names
    assert "edtech_analytics/spark/job.py" in names


def test_every_dq_check_renders():
    for layer, checks in dq.CHECKS_BY_LAYER.items():
        names = [c.name for c in checks]
        assert len(names) == len(set(names)), layer
        for check in checks:
            sql = dq._render(check.sql, "silver")
            assert "{" not in sql, check.name
            assert "}" not in sql, check.name
            assert re.search(r"lake\.silver\.\w+", sql), check.name
            assert check.severity in {"error", "warn"}
