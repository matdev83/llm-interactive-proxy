import sqlite3
import os
from datetime import datetime

def list_models():
    db_path = 'var/db/proxy.db'
    
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        return

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print("Querying distinct models from usage_records...")
        cursor.execute("SELECT DISTINCT model FROM usage_records")
        models = cursor.fetchall()
        
        print("Models found:")
        for model in models:
            print(f"- {model[0]}")
            
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    list_models()
