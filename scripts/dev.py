"""Start the local API and browser app; Ctrl-C stops only these child processes."""

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    python = ROOT / ".venv" / "bin" / "python"
    npm = shutil.which("npm")
    if (
        not python.exists()
        or not npm
        or not (ROOT / "frontend" / "node_modules").is_dir()
    ):
        sys.exit(
            "Install the Python and frontend dependencies first. See README.md → Quick start."
        )
    for port in (8765, 5173):
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                sys.exit(
                    f"Port {port} is already in use. Stop an earlier SpeakLab instance or use the separate-terminal commands in README.md."
                )
    commands = [
        (
            [
                str(python),
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8765",
            ],
            ROOT,
        ),
        ([npm, "run", "dev"], ROOT / "frontend"),
    ]
    children = []

    def interrupted(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        for command, cwd in commands:
            children.append(subprocess.Popen(command, cwd=cwd, start_new_session=True))
        print(
            "\nSpeakLab is starting at http://127.0.0.1:5173\nCtrl-C stops the API and frontend.\n",
            flush=True,
        )
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
        for child in children:
            try:
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()


if __name__ == "__main__":
    main()
