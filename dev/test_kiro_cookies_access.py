import os
import shutil

db_path = r"C:\Users\Mateusz\AppData\Roaming\Kiro\Network\Cookies"
temp_db = "cookies_test.sqlite"

if not os.path.exists(db_path):
    print(f"File not found: {db_path}")
    exit(1)

try:
    print(f"Attempting to copy {db_path} to {temp_db}...")
    # Use binary read and write instead of shutil.copyfile to be sure about permissions
    with open(db_path, "rb") as f_in:
        with open(temp_db, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
    print("Copy successful")
    os.remove(temp_db)
except Exception as e:
    print(f"Error: {e}")
    if os.path.exists(temp_db):
        os.remove(temp_db)
