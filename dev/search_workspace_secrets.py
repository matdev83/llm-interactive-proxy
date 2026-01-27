import os
import shutil
import sqlite3

storage_dir = r"C:\Users\Mateusz\AppData\Roaming\Kiro\User\workspaceStorage"
temp_db = "workspace_search.sqlite"

if not os.path.exists(storage_dir):
    print(f"Directory not found: {storage_dir}")
    exit(1)

for folder in os.listdir(storage_dir):
    db_path = os.path.join(storage_dir, folder, "state.vscdb")
    if os.path.exists(db_path):
        print(f"Checking {folder}...")
        try:
            shutil.copyfile(db_path, temp_db)
            conn = sqlite3.connect(temp_db)
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM ItemTable")
            rows = cursor.fetchall()
            for row in rows:
                key = row[0]
                val = str(row[1])
                if "accessToken" in val or "refreshToken" in val or "Bearer" in val:
                    print(f"  FOUND IN {folder}: Key: {key}")
                    print(f"  Value (start): {val[:100]}...")
            conn.close()
            os.remove(temp_db)
        except Exception as e:
            print(f"  Error checking {folder}: {e}")
            if os.path.exists(temp_db):
                os.remove(temp_db)
