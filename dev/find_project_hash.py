import os

base_dir = r"C:\Users\Mateusz\AppData\Roaming\Kiro\User\globalStorage\kiro.kiroagent\af41c61c12d351c72e8683318a9d1cb5\74a08cf8613c7dec4db7b264470db812"
project_key = "llm-interactive-proxy"

if not os.path.exists(base_dir):
    print(f"Base dir not found: {base_dir}")
    exit(1)

for folder in os.listdir(base_dir):
    folder_path = os.path.join(base_dir, folder)
    if os.path.isdir(folder_path):
        # Look for any JSON file that might contain project path
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                if file.endswith(".json"):
                    try:
                        with open(os.path.join(root, file), encoding="utf-8") as f:
                            content = f.read()
                            if project_key in content:
                                print(
                                    f"Found in {folder}/{file}: content contains {project_key}"
                                )
                    except Exception:
                        pass
