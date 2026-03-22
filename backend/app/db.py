from contextlib import contextmanager
from typing import Iterator
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from psycopg import OperationalError
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from psycopg_pool.errors import PoolTimeout

from app.config import settings


class DatabaseUnavailableError(RuntimeError):
    pass


def _normalize_conninfo(conninfo: str) -> str:
    parts = urlsplit(conninfo)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))

    host = parts.hostname or ""
    port = parts.port
    if host.endswith(".pooler.supabase.com") and port == 5432:
        port = 6543

    auth = ""
    if parts.username:
        auth = quote(parts.username, safe="")
        if parts.password is not None:
            auth += f":{quote(parts.password, safe='')}"
        auth += "@"

    if port is None:
        host_port = host
    else:
        host_port = f"{host}:{port}"

    netloc = f"{auth}{host_port}"

    # Supabase poolers require SSL, but local PostgreSQL commonly runs without SSL.
    if "sslmode" not in query and host.endswith(".pooler.supabase.com"):
        query["sslmode"] = "require"
    if "connect_timeout" not in query:
        query["connect_timeout"] = "5"

    return urlunsplit((parts.scheme, netloc, parts.path, urlencode(query), parts.fragment))


pool = ConnectionPool(
    conninfo=_normalize_conninfo(settings.supabase_db_url),
    min_size=0,
    max_size=8,
    open=False,
)


@contextmanager
def get_conn() -> Iterator:
    conn_ctx = None
    try:
        if pool.closed:
            pool.open(wait=False)
        conn_ctx = pool.connection()
    except PoolTimeout as exc:
        raise DatabaseUnavailableError(
            "Database connection unavailable. Verify DB URL credentials, host, and port."
        ) from exc
    except OperationalError as exc:
        message = str(exc).lower()
        connectivity_markers = (
            "authentication",
            "circuit breaker",
            "connection to server",
            "could not connect",
            "timeout expired",
        )
        if any(marker in message for marker in connectivity_markers):
            raise DatabaseUnavailableError(
                "Database connection unavailable. Verify DB URL credentials, host, and port."
            ) from exc
        raise

    assert conn_ctx is not None
    with conn_ctx as conn:
        yield conn


@contextmanager
def get_cursor() -> Iterator:
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("set statement_timeout = '120s'")
            yield cur
            conn.commit()
