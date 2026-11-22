#!/usr/bin/env python3
"""Idempotently seed the demo database and policy chunks.

From the repository root, run ``python db/seed/seed.py`` after applying the
numbered migrations. Pass ``--skip-policies`` to seed the core demo data only.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
SEED_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(SEED_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env", override=False)

from app.services.identity_match import name_phonetic_key, normalize_name  # noqa: E402

SEED_SQL = SEED_DIR / "003_seed_test.sql"
SUPPLEMENTAL_RECORD_COUNT = 193  # seven scripted records already exist in 003

_GIVEN_NAMES = (
    ("Ayesha", "Aisha"),
    ("Fatima", "Fathima"),
    ("Zainab", "Zainub"),
    ("Nasreen", "Nasrin"),
    ("Muhammad", "Mohammad"),
    ("Hussain", "Hussein"),
    ("Sakina", "Sakeena"),
    ("Nusrat", "Nosrat"),
)
_FAMILY_NAMES = (
    "Bibi", "Khatoon", "Akhtar", "Begum", "Siddiqui", "Javed", "Noor", "Khan",
)
_FATHER_NAMES = (
    "Rashid Ali", "Ghulam Nabi", "Abdul Karim", "Aslam Khan", "Hassan Ahmed",
)
_DISTRICTS = ("Karachi East", "Karachi West", "Karachi South", "Thatta", "Badin")


def generate_mock_identity_records() -> list[dict]:
    """Create stable mock registry rows with deliberate matching edge cases."""
    records = []
    for index in range(1, SUPPLEMENTAL_RECORD_COUNT + 1):
        # Pair adjacent rows to represent duplicate people with separate IDs.
        person = (index + 1) // 2
        canonical, variant = _GIVEN_NAMES[person % len(_GIVEN_NAMES)]
        given = variant if index % 3 == 0 else canonical
        family = _FAMILY_NAMES[person % len(_FAMILY_NAMES)]
        full_name = f"{given} {family}"
        father_name = _FATHER_NAMES[person % len(_FATHER_NAMES)]

        # Some source rows have given and father names swapped or no CNIC.
        if index % 29 == 0:
            full_name, father_name = father_name, full_name
        cnic = None if index % 23 == 0 else f"9{index:012d}"
        normalized = normalize_name(full_name)
        records.append({
            "id": str(uuid5(NAMESPACE_URL, f"relief-mock-identity-{index}")),
            "cnic": cnic,
            "full_name": full_name,
            "father_name": father_name,
            "dob": date(1950 + person % 50, 1 + person % 12, 1 + person % 27),
            "district": _DISTRICTS[person % len(_DISTRICTS)],
            "name_normalized": normalized,
            "name_phonetic": name_phonetic_key(normalized),
            # The seven scripted records contain the sole deceased match.
            "is_deceased": False,
        })
    return records


def _database_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is required; add it to the repository .env file.")
    if value.startswith("postgres://"):
        return "postgresql://" + value[len("postgres://"):]
    if value.startswith("postgresql+psycopg://"):
        return "postgresql://" + value[len("postgresql+psycopg://"):]
    return value


def seed_core_data() -> None:
    """Apply the fixed demo rows and deterministic supplemental identities."""
    import psycopg

    sql = SEED_SQL.read_text(encoding="utf-8")
    rows = generate_mock_identity_records()
    with psycopg.connect(_database_url()) as connection:
        # The SQL file is a parameter-free script containing multiple statements.
        connection.execute(sql, prepare=False)
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO mock_identity_records
                    (id, cnic, full_name, father_name, dob, district,
                     name_normalized, name_phonetic, is_deceased)
                VALUES
                    (%(id)s, %(cnic)s, %(full_name)s, %(father_name)s, %(dob)s,
                     %(district)s, %(name_normalized)s, %(name_phonetic)s, %(is_deceased)s)
                ON CONFLICT (id) DO UPDATE SET
                    cnic = EXCLUDED.cnic,
                    full_name = EXCLUDED.full_name,
                    father_name = EXCLUDED.father_name,
                    dob = EXCLUDED.dob,
                    district = EXCLUDED.district,
                    name_normalized = EXCLUDED.name_normalized,
                    name_phonetic = EXCLUDED.name_phonetic,
                    is_deceased = EXCLUDED.is_deceased
                """,
                rows,
            )


def seed_policy_chunks() -> None:
    from seed_policies import seed_policies

    seed_policies()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-policies",
        action="store_true",
        help="skip embedding and policy_chunks seeding",
    )
    args = parser.parse_args()

    seed_core_data()
    if not args.skip_policies:
        seed_policy_chunks()
    print("Demo seed completed: 200 identity records; fixed data is safe to rerun.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
