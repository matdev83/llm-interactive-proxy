import os
import subprocess
import sys


def run_pytest() -> int:
    out_path = os.path.join(os.getcwd(), "dev", "pytest_output.log")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cmd = [sys.executable, "-m", "pytest", "-q"]
    with open(out_path, "wb") as out_f:
        proc = subprocess.Popen(cmd, stdout=out_f, stderr=subprocess.STDOUT)
        ret = proc.wait()
    print(ret)
    return ret


if __name__ == "__main__":
    sys.exit(run_pytest())
