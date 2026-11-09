import subprocess
import sys
import time

CHILD = """
import subprocess, sys, time
from server.winjob import kill_with_me
grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
kill_with_me(grandchild.pid)
print(grandchild.pid, flush=True)
time.sleep(60)
"""


def alive(pid):
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


def test_grandchild_dies_with_parent():
    parent = subprocess.Popen([sys.executable, "-c", CHILD], stdout=subprocess.PIPE, text=True, cwd=".")
    grandchild_pid = int(parent.stdout.readline())
    assert alive(grandchild_pid)
    parent.kill()  # like closing the console window: no clean shutdown
    parent.wait()
    for _ in range(30):
        if not alive(grandchild_pid):
            break
        time.sleep(0.1)
    assert not alive(grandchild_pid)
