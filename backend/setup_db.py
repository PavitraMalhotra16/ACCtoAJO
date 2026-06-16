"""
Run this once after cloning to create the acc2ajo database and all tables.
Usage: python setup_db.py
"""
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from urllib.parse import urlparse

DB_URL = os.getenv("DATABASE_URL", "postgresql://acc2ajo:acc2ajo@localhost:5432/acc2ajo")


def create_database_if_missing():
    parsed = urlparse(DB_URL)
    dbname = parsed.path.lstrip("/")
    user = parsed.username
    password = parsed.password
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432

    try:
        import psycopg2
        from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
    except ImportError:
        print("psycopg2 not installed — run: pip install psycopg2-binary")
        sys.exit(1)

    try:
        conn = psycopg2.connect(dbname="postgres", user=user, password=password, host=host, port=port)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s", (dbname,))
        if cur.fetchone():
            print(f"  Database '{dbname}' already exists.")
        else:
            cur.execute(f'CREATE DATABASE "{dbname}"')
            print(f"  Created database: {dbname}")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"  Could not connect to PostgreSQL: {e}")
        print("  Make sure PostgreSQL is running and the credentials in DATABASE_URL are correct.")
        sys.exit(1)


def create_tables():
    from app.db import engine, Base
    from app.models import AccConfig, AjoConfig  # noqa: F401
    Base.metadata.create_all(bind=engine)
    print("  Tables ready: acc_configs, ajo_configs")


if __name__ == "__main__":
    print("Setting up ACC2AJO database...")
    create_database_if_missing()
    create_tables()
    print("Done. You can now start the server with:")
    print("  python -m uvicorn app.main:app --port 8000")
