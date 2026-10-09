"""Unit-level Spark tests for the silver conform step (null encodings, casts, IMD fix-up).

The rows below are hand-written edge cases (not OULAD data) shaped like the real CSV columns.
"""

from __future__ import annotations

import pytest
from pyspark.sql import functions as F

from edtech_analytics.spark import silver
from edtech_analytics.spark.session import build_session

pytestmark = pytest.mark.spark


@pytest.fixture(scope="module")
def spark(tmp_path_factory):
    session = build_session(
        "test-conform",
        warehouse=tmp_path_factory.mktemp("wh").as_posix(),
        master="local[1]",
        driver_memory="1g",
        shuffle_partitions=1,
    )
    yield session
    session.stop()


def _raw(spark, table, rows):
    return spark.createDataFrame(rows, silver._raw_schema(table))


def test_both_missing_value_encodings_become_null(spark):
    # figshare writes "", the UCI mirror writes "?": both mean missing.
    raw = _raw(spark, "studentAssessment", [("1", "10", "5", "0", ""), ("1", "11", "6", "0", "?")])
    frame, failures = silver.conform(raw, "student_assessments", "v1")
    rows = frame.select("score", failures.alias("f")).collect()
    assert [r.score for r in rows] == [None, None]
    assert [r.f for r in rows] == [0, 0]


def test_unparseable_values_are_counted_not_hidden(spark):
    raw = _raw(
        spark, "studentAssessment", [("1", "10", "five", "0", "80"), ("1", "11", "6", "0", "x")]
    )
    frame, failures = silver.conform(raw, "student_assessments", "v1")
    assert frame.agg(F.sum(failures)).first()[0] == 2


def test_imd_band_spelling_is_normalised(spark):
    row = (
        "AAA",
        "2013J",
        "1",
        "M",
        "Scotland",
        "HE Qualification",
        "10-20",
        "0-35",
        "0",
        "60",
        "N",
        "Pass",
    )
    frame, _ = silver.conform(_raw(spark, "studentInfo", [row]), "students", "v1")
    assert frame.first().imd_band == "10-20%"


def test_presentation_attributes_are_derived(spark):
    raw = _raw(spark, "courses", [("AAA", "2013J", "268"), ("BBB", "2014B", "234")])
    frame, _ = silver.conform(raw, "courses", "v1")
    derived = silver._derive("courses", frame).orderBy("code_module").collect()
    assert [(r.presentation_year, r.presentation_start_month) for r in derived] == [
        (2013, 10),
        (2014, 2),
    ]
