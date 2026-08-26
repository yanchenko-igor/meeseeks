"""Tests for CSV parsing utilities."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils import parse_csv


def test_parse_csv_basic():
    csv = "name,age,city\nAlice,30,NYC\nBob,25,LA"
    result = parse_csv(csv)
    assert len(result) == 2
    assert result[0] == {"name": "Alice", "age": "30", "city": "NYC"}
    assert result[1] == {"name": "Bob", "age": "25", "city": "LA"}


def test_parse_csv_single_row():
    csv = "name,age\nAlice,30"
    result = parse_csv(csv)
    assert len(result) == 1
    assert result[0] == {"name": "Alice", "age": "30"}


def test_parse_csv_multiple_rows():
    csv = "name,age\nAlice,30\nBob,25\nCharlie,35"
    result = parse_csv(csv)
    assert len(result) == 3
    assert result[2] == {"name": "Charlie", "age": "35"}


def test_parse_csv_empty():
    csv = "name,age"
    result = parse_csv(csv)
    assert result == []


def test_parse_csv_header_only():
    csv = "name,age,city"
    result = parse_csv(csv)
    assert result == []


def test_parse_csv_extra_columns():
    csv = "name,age\nAlice,30,NYC,extra"
    result = parse_csv(csv)
    assert len(result) == 1
    assert result[0]["name"] == "Alice"
    assert result[0]["age"] == "30"
