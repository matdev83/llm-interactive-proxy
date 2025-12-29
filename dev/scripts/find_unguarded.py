
import os

def find_unguarded(root_dir):
    for dirpath, _, filenames in os.walk(root_dir):
        if any(p.startswith(".") or p.startswith("_") for p in dirpath.split(os.sep)):
            continue
            
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
                
            filepath = os.path.join(dirpath, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
                
            for i, line in enumerate(lines):
                stripped = line.strip()
                # Check for logger calls
                if stripped.startswith("logger.debug(") or stripped.startswith("logger.info(") or stripped.startswith("logger.warning("):
                    # Check if previous lines have guard
                    is_guarded = False
                    # Look back up to 5 lines
                    for j in range(1, 6):
                        if i - j < 0:
                            break
                        prev_line = lines[i-j].strip()
                        if not prev_line or prev_line.startswith("#"):
                            continue
                        if "isEnabledFor" in prev_line:
                            is_guarded = True
                            break
                        # If we hit another code line (ending in :) that isn't isEnabledFor, stop?
                        # No, simpler: just check if isEnabledFor is in recent context.
                        # Actually strict guarding requires it to be the immediate conditional.
                        # But let's just see what we find.
                            
                    if not is_guarded:
                        # Check if it uses f-string or .format
                        if "f\"" in stripped or "f'" in stripped or ".format(" in stripped:
                             print(f"{filepath}:{i+1}: {stripped}")

if __name__ == "__main__":
    find_unguarded("src")
