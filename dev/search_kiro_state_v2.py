import os
import shutil
import sqlite3

db_path = r"C:\Users\Mateusz\AppData\Roaming\Kiro\User\globalStorage\state.vscdb"
temp_db = "state_search.sqlite"

if not os.path.exists(db_path):
    print(f"File not found: {db_path}")
    exit(1)

try:
    shutil.copyfile(db_path, temp_db)
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM ItemTable")
    rows = cursor.fetchall()
    for row in rows:
        key = row[0]
        val = str(row[1])
        # Look for the specific Kiro agent extension ID or similar
        if "kiro" in key.lower() or "amazon" in key.lower() or "q" in key.lower():
            print(f"Key: {key}")
            print(f"Value (start): {val[:100]}...")
            print("-" * 20)
    conn.close()
    os.remove(temp_db)
except Exception as e:
    print(f"Error: {e}")
    if os.path.exists(temp_db):
        os.remove(temp_db)
