
import sys
import cbor2
from datetime import datetime, timezone

def inspect_cbor(file_path, target_time_str):
    target_time = datetime.strptime(target_time_str, "%Y-%m-%d %H:%M:%S")
    target_ts = target_time.replace(tzinfo=timezone.utc).timestamp()
    
    # Allow a window of +/- 60 seconds
    start_ts = target_ts - 60
    end_ts = target_ts + 60

    print(f"Inspecting {file_path} around {target_time_str} (UTC timestamp: {target_ts})")

    with open(file_path, "rb") as f:
        try:
            header = cbor2.load(f)
            print("Header:", header)
        except Exception as e:
            print("Failed to read header:", e)
            return

        count = 0
        while True:
            try:
                entry = cbor2.load(f)
                # entry is a dict with 'timestamp', 'direction', 'data', 'metadata', etc.
                # timestamp might be a float or int (nanoseconds) or a Tag
                
                ts = entry.get('ts')
                
                if count < 1:
                    print(f"Debug Entry {count}: {entry}")

                if isinstance(ts, datetime):
                    ts_val = ts.timestamp()
                elif isinstance(ts, (int, float)):
                    # If it's nanoseconds (large int), convert to seconds
                    if ts > 1e11: # heuristic for ns vs s
                        ts_val = ts / 1e9
                    else:
                        ts_val = ts
                else:
                    ts_val = 0

                if start_ts <= ts_val <= end_ts:
                    dt = datetime.fromtimestamp(ts_val, tz=timezone.utc)
                    print(f"\n--- Entry {count} at {dt} ---")
                    print(f"Direction: {entry.get('dir')}")
                    print(f"Metadata: {entry.get('meta')}")
                    data = entry.get('data')
                    if data:
                        try:
                            print(f"Data (utf-8): {data.decode('utf-8')}")
                        except:
                            print(f"Data (hex): {data.hex()}")
                    else:
                        print("Data: <empty>")
                
                count += 1
            except EOFError:
                break
            except Exception as e:
                print(f"Error reading entry {count}: {e}")
                break

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python inspect_cbor.py <file_path> <timestamp_str>")
        sys.exit(1)
    
    inspect_cbor(sys.argv[1], sys.argv[2])
