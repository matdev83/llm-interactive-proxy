import json
import os

history_dir = r"C:\Users\Mateusz\AppData\Roaming\Kiro\User\History"
project_path = "llm-interactive-proxy"

for folder in os.listdir(history_dir):
    entries_path = os.path.join(history_dir, folder, "entries.json")
    if os.path.exists(entries_path):
        try:
            with open(entries_path, encoding="utf-8") as f:
                data = json.load(f)
                resource = data.get("resource", "")
                if project_path in resource:
                    print(f"Found project in folder {folder}: {resource}")
        except Exception:
            pass
