import sqlite3 as sql
from contextlib import contextmanager
from typing import Generator

@contextmanager
def get_connection(path) -> Generator[sql.Connection]:
    con = sql.connect(path)
    try:
        yield con
    finally:
        con.close()

