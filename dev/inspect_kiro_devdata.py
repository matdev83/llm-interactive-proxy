import os
import sqlite3

db_path = r"C:\Users\Mateusz\AppData\Roaming\Kiro\User\globalStorage\kiro.kiroagent\dev_data\devdata.sqlite"
if not os.path.exists(db_path):
    print(f"File not found: {db_path}")
    exit(1)

try:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    for table in tables:
        print(f"Table: {table[0]}")
        cursor.execute(f"PRAGMA table_info({table[0]})")
        columns = cursor.fetchall()
        for col in columns:
            print(f"  Column: {col[1]} ({col[2]})")
    conn.close()
except Exception as e:
    print(f"Error: {e}")
