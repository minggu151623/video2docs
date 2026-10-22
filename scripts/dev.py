"""Start the API, SQLite worker, and Vite. Ctrl-C stops all three."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
os.chdir(root)
sys.path.insert(0, str(root / "backend"))
from app.core.config import get_settings
from app.db.session import migrate

settings = get_settings()
migrate(settings)
env = {**os.environ, "PYTHONPATH": str(root / "backend")}
commands = [
    [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        settings.app_host,
        "--port",
        str(settings.app_port),
    ],
    [sys.executable, "-m", "app.workers.runner"],
    ["npm", "--prefix", "frontend", "run", "dev"],
]
processes = []
try:
    for command in commands:
        processes.append(subprocess.Popen(command, env=env, start_new_session=True))
    print("Video2docs: http://127.0.0.1:5173 · API/worker local running", flush=True)
    while all(p.poll() is None for p in processes):
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    for process in processes:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
    for process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
