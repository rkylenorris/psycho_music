import sqlite3 as sql

def create_connection(db_file) -> sql.Connection | None:
    """ create a database connection to the SQLite database
        specified by db_file
    :param db_file: database file
    :return: Connection object or None
    """

    try:
        conn = sql.connect(db_file)
        return conn
    except sql.Error as e:
        print(e)
    except Exception as e:
        print(f"Unexpected error: {e}")