"""Simple DuckDB Quack-like gateway server.

Starts a small HTTP server (FastAPI) that accepts SQL queries and executes
them against a persistent DuckDB file. On startup the server will attempt to
install/load the Postgres extension and attach the Postgres metadata DB so
DuckDB views can be created that reference Postgres tables.

This is a pragmatic, minimal gateway that provides the functionality we need
for Metabase to query analytics-ready DuckDB views backed by Postgres metadata
and raw files.
"""
import os
import logging
import duckdb
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi import Request
import threading
import time

from .api.utils import duckdb_session

app = FastAPI()


class QueryRequest(BaseModel):
    query: str


def get_duckdb_path() -> str:
    return os.environ.get("MFETHULS_DUCKDB_PATH", "/app/mfethuls.duckdb")


def read_only_mode() -> bool:
    val = os.environ.get("MFETHULS_DUCKDB_READ_ONLY", "true")
    return str(val).lower() in ("1", "true", "yes")
def get_postgres_attach_dsn() -> str | None:
    user = os.environ.get("MFETHULS_POSTGRES_USER")
    pw = os.environ.get("MFETHULS_POSTGRES_PASSWORD")
    host = os.environ.get("MFETHULS_POSTGRES_HOST", "postgres")
    port = os.environ.get("MFETHULS_POSTGRES_PORT", "5432")
    db = os.environ.get("MFETHULS_POSTGRES_DB")
    if not (user and pw and host and port and db):
        return None
    return f"dbname={db} user={user} password={pw} host={host} port={port}"


def is_database_attached(conn: duckdb.DuckDBPyConnection, database_name: str) -> bool:
    try:
        rows = conn.execute("SELECT database_name FROM duckdb_databases()").fetchall()
    except Exception:
        return False
    return any(row and row[0] == database_name for row in rows)


def attach_postgres(conn: duckdb.DuckDBPyConnection) -> bool:
    dsn = get_postgres_attach_dsn()
    if not dsn:
        return False

    if is_database_attached(conn, "pg_meta"):
        return True

    conn.execute("INSTALL postgres")
    conn.execute("LOAD postgres")
    dsn_sql = dsn.replace("'", "''")
    conn.execute(f"ATTACH '{dsn_sql}' AS pg_meta (TYPE postgres, READ_ONLY)")
    return True


def init_duckdb():
    path = get_duckdb_path()
    # ensure directory exists
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # In read-only mode we avoid modifying the DuckDB file (no ATTACH/CREATE)
    ro = read_only_mode()
    if ro:
        return None

    conn = duckdb.connect(database=path, read_only=False)

    try:
        if attach_postgres(conn):
            conn.execute(
                "CREATE OR REPLACE VIEW experiments_view AS SELECT p.*, CASE WHEN p.path IS NULL OR p.path = '' THEN NULL ELSE p.path END AS storage_path FROM pg_meta.public.experiments p"
            )
    except Exception:
        logging.exception("Failed to attach Postgres in init_duckdb")
        raise

    return conn


def refresh_views(conn: duckdb.DuckDBPyConnection):
    """Rebuild analytics-ready views/tables in DuckDB using Postgres metadata.

    This implementation is conservative: if Postgres is attached as `pg_meta`,
    it (re)creates a simple `experiments_view` and a materialized `experiments_mv`
    table for faster reads.
    """
    try:
        # If server is running in read-only mode, do not attempt any writes or attach.
        if read_only_mode():
            return True

        # Re-attach Postgres on refresh if the connection was reset.
        attach_postgres(conn)

        # Recreate the main analytics view directly from Postgres.
        conn.execute(
            "CREATE OR REPLACE VIEW experiments_view AS SELECT p.*, CASE WHEN p.path IS NULL OR p.path = '' THEN NULL ELSE p.path END AS storage_path FROM pg_meta.public.experiments p"
        )

        # Create/replace a materialized table for faster queries (drop then create)
        try:
            conn.execute("DROP TABLE IF EXISTS experiments_mv")
            conn.execute("CREATE TABLE experiments_mv AS SELECT * FROM experiments_view")
        except Exception:
            # If creation fails, ignore — views still exist
            pass

        # Try to register raw data files referenced by experiments (parquet/csv)
        # so they become discoverable datasets in DuckDB. This is best-effort.
        try:
            # ensure dataset_registry exists (same schema used by API backend)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS dataset_registry (table_name TEXT PRIMARY KEY, storage_path TEXT NOT NULL, registered_at TIMESTAMP DEFAULT now())"
            )
        except Exception:
            pass

        # Keep the discovery registry in sync with any experiment paths, but do not
        # fall back to non-extension reads. The gateway should stay DuckDB-native.
        try:
            rows = conn.execute("SELECT id, path FROM pg_meta.public.experiments WHERE path IS NOT NULL AND path <> ''").fetchall()
        except Exception:
            rows = []

        for idx, row in enumerate(rows):
            exp_id, rel_path = row
            try:
                table_name = f"experiments_data_{exp_id or idx}"
                conn.execute(
                    "INSERT INTO dataset_registry (table_name, storage_path) VALUES (?, ?) ON CONFLICT(table_name) DO UPDATE SET storage_path = excluded.storage_path, registered_at = now();",
                    [table_name, rel_path],
                )
            except Exception:
                continue

        return True
    except Exception:
        return False


def start_refresh_loop(conn: duckdb.DuckDBPyConnection, interval: int):
    def loop():
        while True:
            try:
                refresh_views(conn)
            except Exception:
                pass
            time.sleep(interval)

    t = threading.Thread(target=loop, daemon=True)
    t.start()


@app.on_event("startup")
def startup_event():
    # If running in read-only mode we do not open a persistent connection or
    # run the refresh loop. Queries will open/close connections per request.
    if not read_only_mode():
        app.state.duck_conn = init_duckdb()
        try:
            interval = int(os.environ.get("VIEW_REFRESH_INTERVAL", "300"))
        except Exception:
            interval = 300
        start_refresh_loop(app.state.duck_conn, interval)
    else:
        app.state.duck_conn = None


@app.on_event("shutdown")
def shutdown_event():
    try:
        app.state.duck_conn.close()
    except Exception:
        pass


@app.get("/health")
def health():
    try:
        with duckdb_session(read_only=True) as backend:
            frame = backend.query("SELECT 1 AS ok")
            return {"ok": True, "duckdb": not frame.empty}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/query")
def query(req: QueryRequest):
    try:
        with duckdb_session(read_only=True) as backend:
            frame = backend.query(req.query)
            results = frame.to_dict(orient="records")
        return {"rows": results}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/admin/refresh")
async def admin_refresh(request: Request):
    """Trigger a manual refresh of DuckDB views. Protect with `MFETHULS_ADMIN_TOKEN` if set."""
    token = os.environ.get("MFETHULS_ADMIN_TOKEN")
    if token:
        auth = request.headers.get("Authorization")
        if not auth or not auth.startswith("Bearer ") or auth.split(" ", 1)[1] != token:
            raise HTTPException(status_code=401, detail="Unauthorized")

    # Admin refresh is not permitted in read-only mode because it may write
    # to the DuckDB file. Require the server to be started in writable mode.
    if read_only_mode():
        raise HTTPException(status_code=403, detail="Server running in read-only mode; cannot refresh views")

    ok = refresh_views(app.state.duck_conn)
    if not ok:
        raise HTTPException(status_code=500, detail="Refresh failed or pg_meta missing")
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    bind = os.environ.get("QUACK_BIND", "0.0.0.0")
    port = int(os.environ.get("QUACK_PORT", "8080"))
    uvicorn.run("mfethuls.quack_server:app", host=bind, port=port, log_level="info")
