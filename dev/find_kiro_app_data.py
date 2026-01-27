import os

# Locations for Kiro desktop app data (Electron app)
kiro_paths = [
    os.path.expandvars(r"%APPDATA%\Kiro"),
    os.path.expandvars(r"%LOCALAPPDATA%\Kiro"),
]

for base in kiro_paths:
    if os.path.exists(base):
        print(f"Base: {base}")
        # Look for any .json or .sqlite files that might contain settings
        for root, dirs, files in os.walk(base):
            for file in files:
                if file.endswith((".json", ".sqlite", ".vscdb")):
                    print(os.path.join(root, file))
