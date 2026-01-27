import os
import shutil
import sqlite3

db_path = r"C:\Users\Mateusz\AppData\Roaming\Kiro\Network\Cookies"
temp_db = "cookies_temp.sqlite"

if not os.path.exists(db_path):
    print(f"File not found: {db_path}")
    exit(1)

try:
    # Try to read the file first to see if it's readable
    with open(db_path, "rb") as f:
        data = f.read(100)
        print(f"Read first 100 bytes: {data.hex()[:50]}...")

    shutil.copyfile(db_path, temp_db)
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT host_key, name, value FROM cookies")
    rows = cursor.fetchall()
    for row in rows:
        print(f"Host: {row[0]}, Name: {row[1]}")
    conn.close()
    os.remove(temp_db)
except Exception as e:
    print(f"Error: {e}")
    if os.path.exists(temp_db):
        os.remove(temp_db)
