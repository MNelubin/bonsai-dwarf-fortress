from collections.abc import Iterator
from contextlib import contextmanager

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .settings import get_settings


pool: ConnectionPool | None = None


def open_pool() -> None:
    global pool
    if pool is None:
        pool = ConnectionPool(
            conninfo=get_settings().database_url,
            min_size=1,
            max_size=8,
            kwargs={"row_factory": dict_row},
            open=True,
        )


def close_pool() -> None:
    global pool
    if pool is not None:
        pool.close()
        pool = None


@contextmanager
def connection() -> Iterator[Connection]:
    if pool is None:
        raise RuntimeError("database pool is not open")
    with pool.connection() as active_connection:
        yield active_connection
