import os
import sqlite3

db_path = r"C:\Users\Mateusz\AppData\Roaming\Kiro\User\globalStorage\kiro.kiroagent\index\index.sqlite"
if not os.path.exists(db_path):
    print(f"File not found: {db_path}")
    exit(1)

try:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cursor = conn.cursor()
    cursor.execute("SELECT cacheKey FROM global_cache")
    rows = cursor.fetchall()
    for row in rows:
        print(row[0])
    conn.close()
except Exception as e:
    print(f"Error: {e}")
