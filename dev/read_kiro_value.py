import os
import sqlite3

db_path = r"C:\Users\Mateusz\AppData\Roaming\Kiro\User\globalStorage\state.vscdb"
if not os.path.exists(db_path):
    print(f"File not found: {db_path}")
    exit(1)

try:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM ItemTable WHERE key = 'kiro.kiroAgent'")
    row = cursor.fetchone()
    if row:
        print(row[0])
    else:
        print("Key not found")
    conn.close()
except Exception as e:
    print(f"Error: {e}")
