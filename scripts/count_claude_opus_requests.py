import sqlite3
import os
import glob
import re
from datetime import datetime

def count_requests():
    model_pattern = "claude-opus-4-5-thinking"
    db_path = 'var/db/proxy.db'
    logs_pattern = 'var/logs/proxy-20251212*.log'
    
    # 1. Check Database
    db_count = 0
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Use LIKE to match the model name roughly
            query = "SELECT COUNT(*) FROM usage_records WHERE model LIKE ? AND timestamp >= ?"
            # Assuming timestamp is stored as string or datetime compatible
            # UsageRecordTable timestamp is datetime, but in SQLite it's usually string "YYYY-MM-DD..."
            today_str = datetime.now().strftime('%Y-%m-%d')
            
            cursor.execute(query, (f'%{model_pattern}%', today_str))
            result = cursor.fetchone()
            if result:
                db_count = result[0]
            
            conn.close()
        except Exception as e:
            print(f"Database error: {e}")
    else:
        print(f"Database not found at {db_path}")

    # 2. Check Logs
    log_count = 0
    log_files = glob.glob(logs_pattern)
    
    # Pattern to match the start of a request handling for this model
    # Log example: Handling chat completion request: model=gemini-oauth-antigravity:anthropic/claude-opus-4-5-thinking
    log_regex = re.compile(rf"Handling chat completion request: model=.*{re.escape(model_pattern)}")
    
    print(f"Scanning {len(log_files)} log files...")
    
    for log_file in log_files:
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    if log_regex.search(line):
                        log_count += 1
        except Exception as e:
            print(f"Error reading {log_file}: {e}")

    print("-" * 30)
    print(f"Usage Report for '{model_pattern}' on {datetime.now().strftime('%Y-%m-%d')}")
    print("-" * 30)
    print(f"Database records found: {db_count}")
    print(f"Log entries found:      {log_count}")
    print("-" * 30)
    
    if db_count == 0 and log_count > 0:
        print("Note: Activity tracking might be disabled in config, but requests are visible in logs.")

if __name__ == "__main__":
    count_requests()
