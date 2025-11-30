import subprocess
import time
import sys
import os

def main():
    log_file = "var/logs/hang_check.log"
    os.makedirs("var/logs", exist_ok=True)
    
    print("Starting pytest scan with timeout...")
    # Using -rf to show reasons for failures/skips
    cmd = [
        r".venv\Scripts\python.exe", "-m", "pytest", 
        "-v", 
        "-n0", 
        "--timeout=2",
        "-rf" 
    ]
    
    with open(log_file, "w", encoding='utf-8') as f:
        proc = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT)
        
    print(f"PID: {proc.pid}")
    
    start = time.time()
    while time.time() - start < 60:
        if proc.poll() is not None:
            print(f"Finished with code {proc.returncode}")
            break
        time.sleep(2)
    
    if proc.poll() is None:
        print("Still running after 60s. Terminating to inspect log.")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except:
            proc.kill()
            
    print("Log tail:")
    if os.path.exists(log_file):
        with open(log_file, "r", encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
            # Show more lines to see context
            for line in lines[-30:]:
                print(line.strip())
    else:
        print("Log file not found.")

if __name__ == "__main__":
    main()
