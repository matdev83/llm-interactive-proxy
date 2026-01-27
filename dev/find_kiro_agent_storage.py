import os

# Possible locations for Kiro agent storage based on other VS Code-like extensions
base_dirs = [
    r"C:\Users\Mateusz\AppData\Roaming\Kiro\User\globalStorage\kiro.kiro-agent",
    r"C:\Users\Mateusz\AppData\Roaming\Kiro\User\globalStorage\kiro.kiroagent",
    r"C:\Users\Mateusz\AppData\Roaming\Kiro\User\globalStorage\Amazon.Amazon-Q",
    r"C:\Users\Mateusz\AppData\Roaming\Kiro\User\globalStorage\Amazon.Amazon-Q-For-CLI",
]

for d in base_dirs:
    if os.path.exists(d):
        print(f"Found: {d}")
        for root, dirs, files in os.walk(d):
            for file in files:
                print(os.path.join(root, file))
    else:
        print(f"Not found: {d}")
