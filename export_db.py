import pyodbc
import sqlite3

MSSQL_CONN = r"DRIVER={SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=anket;Trusted_Connection=yes;"
SQLITE_FILE = "anket.db"

with pyodbc.connect(MSSQL_CONN) as ms_conn, sqlite3.connect(SQLITE_FILE) as sq_conn:
    ms_cur = ms_conn.cursor()
    sq_cur = sq_conn.cursor()

    sq_cur.executescript("""
        CREATE TABLE IF NOT EXISTS role (
            id INTEGER PRIMARY KEY,
            name TEXT,
            duties TEXT
        );
        CREATE TABLE IF NOT EXISTS sub_role (
            id INTEGER PRIMARY KEY,
            name TEXT,
            role_id INTEGER REFERENCES role(id)
        );
        CREATE TABLE IF NOT EXISTS [user] (
            id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_at TEXT,
            banned INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS application (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submitted TEXT,
            status INTEGER DEFAULT 0,
            form TEXT,
            sub_role_id INTEGER REFERENCES sub_role(id),
            user_id INTEGER REFERENCES [user](id),
            role_id INTEGER REFERENCES role(id)
        );
    """)

    for row in ms_cur.execute("SELECT id, name, duties FROM role").fetchall():
        sq_cur.execute("INSERT OR REPLACE INTO role VALUES (?, ?, ?)", tuple(row))

    for row in ms_cur.execute("SELECT id, name, role_id FROM sub_role").fetchall():
        sq_cur.execute("INSERT OR REPLACE INTO sub_role VALUES (?, ?, ?)", tuple(row))

    for row in ms_cur.execute("SELECT id, username, first_name, joined_at, banned FROM [user]").fetchall():
        sq_cur.execute("INSERT OR REPLACE INTO [user] VALUES (?, ?, ?, ?, ?)", (row[0], row[1], row[2], str(row[3]), int(bool(row[4]))))

    for row in ms_cur.execute("SELECT id, submitted, status, form, sub_role_id, user_id, role_id FROM application").fetchall():
        sq_cur.execute("INSERT OR REPLACE INTO application VALUES (?, ?, ?, ?, ?, ?, ?)", (row[0], str(row[1]), row[2], row[3], row[4], row[5], row[6]))

    sq_conn.commit()

print("✅ Вся база успешно перенесена в файл anket.db!")