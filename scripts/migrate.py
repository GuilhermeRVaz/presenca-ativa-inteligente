from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = ROOT_DIR / "migrations" / "versions"
SUPABASE_HOST_RE = re.compile(r"\.supabase\.(co|in)|supabase\.co", re.IGNORECASE)


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path
    checksum: str
    sql: str


def load_migrations() -> list[Migration]:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    migrations: list[Migration] = []
    for path in files:
        sql = path.read_text(encoding="utf-8")
        version = path.name.split("_", 1)[0]
        checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        migrations.append(Migration(version=version, path=path, checksum=checksum, sql=sql))
    return migrations


def assert_local_database_url(database_url: str) -> None:
    if not database_url:
        raise SystemExit("DATABASE_URL is required for apply-local.")
    if SUPABASE_HOST_RE.search(database_url):
        raise SystemExit(
            "Refusing to apply to a Supabase-looking URL. This runner is local-only for now."
        )
    allowed_markers = ("localhost", "127.0.0.1", "::1", "host.docker.internal")
    if not any(marker in database_url for marker in allowed_markers):
        raise SystemExit(
            "Refusing to apply because DATABASE_URL is not clearly local. "
            "Use localhost, 127.0.0.1, ::1, or host.docker.internal."
        )


def dry_run(migrations: list[Migration]) -> int:
    print(f"Found {len(migrations)} migration(s).")
    for migration in migrations:
        rel_path = migration.path.relative_to(ROOT_DIR)
        print(f"- {migration.version} {rel_path} sha256={migration.checksum[:12]}")
    print("\nNo SQL was applied.")
    return 0


def print_sql(migrations: list[Migration]) -> int:
    for migration in migrations:
        print(f"-- >>> {migration.path.name} sha256={migration.checksum}")
        print(migration.sql.rstrip())
        print(f"-- <<< {migration.path.name}\n")
    return 0


def apply_local(migrations: list[Migration]) -> int:
    database_url = os.getenv("DATABASE_URL", "")
    assert_local_database_url(database_url)

    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit(
            "psycopg is required for apply-local. Install with: pip install -r requirements.txt"
        ) from exc

    with psycopg.connect(database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            for migration in migrations:
                print(f"Applying {migration.path.name}...")
                cur.execute(migration.sql)
                cur.execute(
                    """
                    insert into busca_ativa_v2.schema_migrations
                      (version, filename, checksum_sha256)
                    values (%s, %s, %s)
                    on conflict (version) do nothing
                    """,
                    (migration.version, migration.path.name, migration.checksum),
                )
        conn.commit()

    print("Local migrations applied.")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Busca Ativa V2 migration runner")
    parser.add_argument(
        "command",
        choices=("dry-run", "print-sql", "apply-local"),
        help="dry-run lists migrations; print-sql emits SQL; apply-local runs only against local DB URLs.",
    )
    args = parser.parse_args(argv)

    migrations = load_migrations()
    if not migrations:
        raise SystemExit(f"No migrations found in {MIGRATIONS_DIR}")

    if args.command == "dry-run":
        return dry_run(migrations)
    if args.command == "print-sql":
        return print_sql(migrations)
    if args.command == "apply-local":
        return apply_local(migrations)

    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
