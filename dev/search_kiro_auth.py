import os
import sqlite3

db_path = r"C:\Users\Mateusz\AppData\Roaming\Kiro\User\globalStorage\state.vscdb"
if not os.path.exists(db_path):
    print(f"File not found: {db_path}")
    exit(1)

try:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT key, value FROM ItemTable WHERE key LIKE '%auth%' OR key LIKE '%token%'"
    )
    rows = cursor.fetchall()
    for row in rows:
        print(f"Key: {row[0]}")
        print(f"Value: {row[1]}")
        print("-" * 20)
    conn.close()
except Exception as e:
    print(f"Error: {e}")
