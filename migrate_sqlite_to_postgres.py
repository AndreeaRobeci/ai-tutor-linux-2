import os
import sqlite3
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor


BASE_DIR = Path(__file__).resolve().parent
SQLITE_DB_PATH = BASE_DIR / "database.db"


TABLES = {
    "users": {
        "columns": [
            "id",
            "username",
            "email",
            "password",
            "avatar",
            "hp",
            "xp",
            "streak",
            "last_date",
            "strike_curent",
            "record_strike",
            "start_world",
            "onboarding_completed",
            "cooldown_until",
            "role",
        ],
        "conflict": "id",
    },
    "completed_tasks": {
        "columns": ["user_id", "task_id"],
        "conflict": "user_id, task_id",
    },
    "user_photos": {
        "columns": ["id", "user_id", "filename", "uploaded_at"],
        "conflict": "id",
    },
    "friend_requests": {
        "columns": ["id", "sender_id", "receiver_id", "status", "created_at"],
        "conflict": "id",
    },
    "friendships": {
        "columns": ["id", "user_id", "friend_id", "created_at"],
        "conflict": "id",
    },
    "messages": {
        "columns": ["id", "sender_id", "receiver_id", "message", "created_at", "is_read"],
        "conflict": "id",
    },
}


def sqlite_table_exists(sqlite_conn, table_name):
    row = sqlite_conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def sqlite_columns(sqlite_conn, table_name):
    return {
        row["name"]
        for row in sqlite_conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def postgres_columns(pg_conn, table_name):
    with pg_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            """,
            (table_name,),
        )
        return {row["column_name"] for row in cursor.fetchall()}


def fetch_sqlite_rows(sqlite_conn, table_name, columns):
    selected_columns = ", ".join(columns)
    return sqlite_conn.execute(f"SELECT {selected_columns} FROM {table_name}").fetchall()


def insert_rows(pg_conn, table_name, columns, conflict_columns, rows):
    if not rows:
        return 0

    column_sql = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    sql = (
        f"INSERT INTO {table_name} ({column_sql}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict_columns}) DO NOTHING"
    )

    inserted = 0
    with pg_conn.cursor() as cursor:
        for row in rows:
            cursor.execute(sql, [row[column] for column in columns])
            inserted += cursor.rowcount
    return inserted


SERIAL_TABLES = ["users", "user_photos", "friend_requests", "friendships", "messages"]


def update_sequence(pg_conn, table_name):
    with pg_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT pg_get_serial_sequence(%s, 'id') AS sequence_name
            """,
            (table_name,),
        )
        sequence = cursor.fetchone()["sequence_name"]
        if not sequence:
            return False

        cursor.execute(
            f"""
            SELECT setval(
                %s,
                COALESCE((SELECT MAX(id) FROM {table_name}), 1),
                (SELECT COUNT(*) > 0 FROM {table_name})
            )
            """,
            (sequence,),
        )
        return True


def update_sequences(pg_conn):
    for table_name in SERIAL_TABLES:
        if update_sequence(pg_conn, table_name):
            print(f"{table_name}_id_seq actualizata.")


def migrate_table(sqlite_conn, pg_conn, table_name, config):
    if not sqlite_table_exists(sqlite_conn, table_name):
        print(f"{table_name}: tabela nu exista in SQLite, sarita.")
        return 0

    sqlite_existing_columns = sqlite_columns(sqlite_conn, table_name)
    pg_existing_columns = postgres_columns(pg_conn, table_name)
    columns = [
        column
        for column in config["columns"]
        if column in sqlite_existing_columns and column in pg_existing_columns
    ]

    if not columns:
        print(f"{table_name}: nu exista coloane comune, sarita.")
        return 0

    rows = fetch_sqlite_rows(sqlite_conn, table_name, columns)
    inserted = insert_rows(pg_conn, table_name, columns, config["conflict"], rows)
    print(f"{table_name}: {inserted} randuri migrate.")
    return inserted


def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL nu este setat in variabilele de mediu.")

    if not SQLITE_DB_PATH.exists():
        raise FileNotFoundError(f"Nu exista baza SQLite: {SQLITE_DB_PATH}")

    sqlite_conn = sqlite3.connect(SQLITE_DB_PATH)
    sqlite_conn.row_factory = sqlite3.Row

    pg_conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)

    try:
        for table_name, config in TABLES.items():
            migrate_table(sqlite_conn, pg_conn, table_name, config)

        update_sequences(pg_conn)
        pg_conn.commit()
        print("Migrare finalizata.")
    except Exception:
        pg_conn.rollback()
        raise
    finally:
        sqlite_conn.close()
        pg_conn.close()


if __name__ == "__main__":
    main()
