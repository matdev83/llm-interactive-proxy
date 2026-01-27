import os
import shutil
import sqlite3

db_path = r"C:\Users\Mateusz\AppData\Roaming\Kiro\Network\Cookies"
temp_db = "cookies_temp.sqlite"

if not os.path.exists(db_path):
    print(f"File not found: {db_path}")
    exit(1)

try:
    shutil.copy2(db_path, temp_db)
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT host_key, name, value, encrypted_value FROM cookies WHERE host_key LIKE '%kiro%'"
    )
    rows = cursor.fetchall()
    for row in rows:
        print(f"Host: {row[0]}, Name: {row[1]}")
        print(f"Value: {row[2]}")
        print(f"Has Encrypted Value: {bool(row[3])}")
        print("-" * 20)
    conn.close()
    os.remove(temp_db)
except Exception as e:
    print(f"Error: {e}")
    if os.path.exists(temp_db):
        os.remove(temp_db)
