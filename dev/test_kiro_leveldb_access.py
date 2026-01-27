import os

db_dir = r"C:\Users\Mateusz\AppData\Roaming\Kiro\Local Storage\leveldb"
temp_dir = "leveldb_test"

if not os.path.exists(db_dir):
    print(f"Directory not found: {db_dir}")
    exit(1)

if not os.path.exists(temp_dir):
    os.makedirs(temp_dir)

try:
    for filename in os.listdir(db_dir):
        if (
            filename.endswith(".ldb")
            or filename.endswith(".log")
            or filename in ["CURRENT", "MANIFEST-014142"]
        ):
            src = os.path.join(db_dir, filename)
            dst = os.path.join(temp_dir, filename)
            print(f"Attempting to copy {src}...")
            try:
                with open(src, "rb") as f_in:
                    with open(dst, "wb") as f_out:
                        f_out.write(f_in.read())
                print(f"Successfully copied {filename}")
            except Exception as e:
                print(f"Failed to copy {filename}: {e}")
except Exception as e:
    print(f"Error: {e}")
