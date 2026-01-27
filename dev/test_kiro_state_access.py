import os
import shutil
import sqlite3

db_path = r"C:\Users\Mateusz\AppData\Roaming\Kiro\User\globalStorage\state.vscdb"
temp_db = "state_temp.sqlite"

if not os.path.exists(db_path):
    print(f"File not found: {db_path}")
    exit(1)

try:
    shutil.copyfile(db_path, temp_db)
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT key FROM ItemTable")
    rows = cursor.fetchall()
    print(f"Total keys: {len(rows)}")
    conn.close()
    os.remove(temp_db)
    print("Success")
except Exception as e:
    print(f"Error: {e}")
    if os.path.exists(temp_db):
        os.remove(temp_db)
