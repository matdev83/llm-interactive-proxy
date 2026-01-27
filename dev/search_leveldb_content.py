import os
import re

temp_dir = "leveldb_test"

# Basic pattern for a bearer token or something similar
# Often they are JWT-like or base64-ish strings
pattern = re.compile(b"[a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+")

for filename in os.listdir(temp_dir):
    path = os.path.join(temp_dir, filename)
    print(f"Searching {filename}...")
    with open(path, "rb") as f:
        content = f.read()

        # Look for 'accessToken' or 'refreshToken' nearby
        if (
            b"accessToken" in content
            or b"refreshToken" in content
            or b"Bearer" in content
        ):
            print(f"Found keyword in {filename}!")
            # Extract some context around the keyword
            for keyword in [b"accessToken", b"refreshToken", b"Bearer"]:
                idx = content.find(keyword)
                if idx != -1:
                    start = max(0, idx - 50)
                    end = min(len(content), idx + 200)
                    print(f"Context for {keyword.decode()}: {content[start:end]}")

        # Also try to find long-ish base64 strings or JWTs
        matches = pattern.findall(content)
        for match in matches:
            if len(match) > 50:
                print(
                    f"Possible token-like string in {filename}: {match[:50].decode()}..."
                )
