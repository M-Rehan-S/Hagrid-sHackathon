from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from unittest.mock import MagicMock

import psycopg
import pytest

SEED_DIR = Path(__file__).resolve().parents[2] / "db" / "seed"
sys.path.insert(0, str(SEED_DIR))

import seed as seed_script  # noqa: E402


def test_mock_identity_seed_is_deterministic_and_completes_proposal_size():
    first = seed_script.generate_mock_identity_records()
    second = seed_script.generate_mock_identity_records()

    assert len(first) + 7 == 200  # seven scripted identity personas in 003_seed_test.sql
    assert [row["id"] for row in first] == [row["id"] for row in second]
    assert len({row["id"] for row in first}) == len(first)
    assert sum(row["cnic"] is None for row in first) > 0
    assert all(row["is_deceased"] is False for row in first)
    assert any(count > 1 for count in Counter(row["name_normalized"] for row in first).values())
    assert all(row["name_phonetic"] for row in first)


def test_seeded_scam_examples_use_fixed_ids_and_are_idempotent():
    sql = (SEED_DIR / "003_seed_test.sql").read_text(encoding="utf-8")

    assert "('70000000-0000-0000-0000-000000000001'" in sql
    assert "on conflict (id) do nothing" in sql.lower()


def test_seed_core_data_executes_script_and_bulk_upserts(monkeypatch, tmp_path):
    rows = seed_script.generate_mock_identity_records()
    cursor = MagicMock()
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    monkeypatch.setattr(seed_script, "_database_url", lambda: "postgresql://test")
    seed_file = tmp_path / "seed.sql"
    seed_file.write_text("SELECT 1;", encoding="utf-8")
    monkeypatch.setattr(seed_script, "SEED_SQL", seed_file)

    connect = MagicMock()
    connect.return_value.__enter__.return_value = connection
    monkeypatch.setattr(psycopg, "connect", connect)

    seed_script.seed_core_data()

    connect.assert_called_once_with("postgresql://test")
    connection.execute.assert_called_once_with("SELECT 1;", prepare=False)
    cursor.executemany.assert_called_once()
    statement, parameters = cursor.executemany.call_args.args
    assert "ON CONFLICT (id) DO UPDATE" in statement
    assert len(parameters) == 193
    assert parameters == rows
