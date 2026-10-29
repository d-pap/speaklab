"""Mac SSH tunnel supervisor. Standard library only; never handles private-key contents.

Settings come from SPEAKLAB_PC_* environment variables, falling back to the
gitignored .local/pc.env (KEY=VALUE lines). See docs/deployment.md.
"""
import argparse
import fcntl
import json
import os
import plistlib
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parent.parent
LOCAL = ROOT / ".local"
LABEL = "dev.speaklab.pc-tunnel"
STATUS = LOCAL / "pc-connection.json"
AGENT = Path.home() / "Library/LaunchAgents" / (LABEL + ".plist")
SETTINGS = ("SPEAKLAB_PC_HOST", "SPEAKLAB_PC_USER", "SPEAKLAB_PC_PORT", "SPEAKLAB_SSH_KEY",
            "SPEAKLAB_PC_HOST_KEY_ALIAS", "SPEAKLAB_PC_SERVER_NAME")
FATAL_SSH = (
    "host key verification failed", "remote host identification has changed",
    "permission denied (", "bad permissions", "unprotected private key",
    "invalid format", "address already in use",
)


def setting(name, default=None):
    if name in os.environ:
        return os.environ[name] or default
    path = LOCAL / "pc.env"
    if path.is_file():
        for line in path.read_text().splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key == name and not key.startswith("#"):
                return value.strip() or default
    return default


def ssh_command():
    known = LOCAL / "ssh_known_hosts"
    key = Path(setting("SPEAKLAB_SSH_KEY", str(Path.home() / ".ssh/id_ed25519")))
    if not known.is_file() or not known.stat().st_size:
        raise ValueError("Missing verified .local/ssh_known_hosts; see docs/deployment.md.")
    if not key.is_file():
        raise ValueError("SSH key file is missing. Restore your configured key; do not generate a new server identity.")
    host = setting("SPEAKLAB_PC_HOST")
    if not host:
        raise ValueError("Set SPEAKLAB_PC_HOST in the environment or .local/pc.env.")
    user = setting("SPEAKLAB_PC_USER")
    alias = setting("SPEAKLAB_PC_HOST_KEY_ALIAS")
    port = int(setting("SPEAKLAB_PC_PORT", "22"))
    if any(value.startswith("-") for value in (host, user or "", alias or "")) or not 1 <= port <= 65535:
        raise ValueError("Invalid SSH host, user, host-key alias or port.")
    # Optionally pin the verified identity independently of the route's address.
    pin = ["-o", "HostKeyAlias=" + alias] if alias else []
    return [
        "/usr/bin/ssh", "-4", "-N", "-T", "-p", str(port),
        "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
        "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=15",
        "-o", "ServerAliveCountMax=2", "-o", "StrictHostKeyChecking=yes",
        "-o", "UserKnownHostsFile=" + str(known),
        *pin, "-o", "HostKeyAlgorithms=ssh-ed25519",
        "-o", "IdentitiesOnly=yes", "-o", "ControlMaster=no", "-o", "ControlPath=none",
        "-i", str(key), "-L", "127.0.0.1:4173:127.0.0.1:8765",
        user + "@" + host if user else host,
    ]


def write_status(state, message):
    record = {"state": state, "message": message, "pid": os.getpid(),
              "updated_at": datetime.now(timezone.utc).isoformat()}
    temporary = STATUS.with_suffix(".tmp")
    temporary.write_text(json.dumps(record) + "\n")
    temporary.replace(STATUS)
    print(time.strftime("%H:%M:%S"), message, flush=True)


def healthy():
    try:
        request = Request("http://127.0.0.1:4173/api/health")
        # Do not send a loopback health check through a configured HTTP proxy.
        with build_opener(ProxyHandler({})).open(request, timeout=2) as response:
            payload = json.loads(response.read(65536))
        # Optionally confirm the tunnel reached the intended server, not another local app.
        expected = setting("SPEAKLAB_PC_SERVER_NAME")
        return isinstance(payload, dict) and "server_name" in payload and (
            expected is None or payload["server_name"] == expected)
    except (OSError, URLError, ValueError):
        return False


def backoff(failures):
    return min(30, 2 ** min(failures, 5))


def terminate(child):
    if child is not None and child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=4)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def run():
    LOCAL.mkdir(exist_ok=True)
    with (LOCAL / "pc-connection.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("SpeakLab connection is already managed. Use --status or --stop.")
            return 0
        try:
            command = ssh_command()
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 4173))
        except (OSError, ValueError) as error:
            write_status("attention", str(error) + " Close any old tunnel using port 4173.")
            return 0  # Configuration errors require attention, not launchd restart loops.
        stopped = threading.Event()
        child = None

        def stop(_signum, _frame):
            stopped.set()
            if child is not None and child.poll() is None:
                child.terminate()

        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        failures = 0
        try:
            while not stopped.is_set():
                write_status("connecting", "Connecting to PC; it may still be starting. Ctrl-C stops retries.")
                started = time.monotonic()
                with tempfile.TemporaryFile(mode="w+") as errors:
                    child = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                             stdout=subprocess.DEVNULL, stderr=errors)
                    last_check = 0.0
                    ready = None
                    while child.poll() is None and not stopped.wait(1):
                        now = time.monotonic()
                        if now - last_check < 5:
                            continue
                        last_check = now
                        current = healthy()
                        if current != ready:
                            write_status("connected" if current else "waiting",
                                         "Connected: http://127.0.0.1:4173" if current else
                                         "Waiting for SSH / SpeakLab startup; retrying automatically.")
                            ready = current
                    terminate(child)
                    errors.seek(0)
                    detail = errors.read().strip()[-2000:]
                if stopped.is_set():
                    break
                if any(pattern in detail.lower() for pattern in FATAL_SSH):
                    write_status("attention", "SSH needs attention; retries stopped: " + detail)
                    return 0
                failures = 1 if time.monotonic() - started >= 30 else failures + 1
                delay = backoff(failures)
                write_status("retrying", "Connection lost / unavailable. Retrying in %ss. %s" % (delay, detail))
                stopped.wait(delay)
        finally:
            terminate(child)
            if stopped.is_set():
                write_status("stopped", "SpeakLab connection stopped.")
    return 0


def agent_plist():
    return {
        "Label": LABEL,
        "ProgramArguments": ["/usr/bin/python3", str(Path(__file__).resolve())],
        "WorkingDirectory": str(ROOT), "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False}, "ThrottleInterval": 10,
        "StandardOutPath": str(LOCAL / "pc-connection.log"),
        "StandardErrorPath": str(LOCAL / "pc-connection-error.log"),
        "EnvironmentVariables": {
            k: os.environ[k] for k in SETTINGS if k in os.environ
        },
    }


def manage(action):
    target = "gui/%s/%s" % (os.getuid(), LABEL)
    if action == "status":
        print(STATUS.read_text().strip() if STATUS.exists() else "Connection has not been started.")
        result = subprocess.run(["/bin/launchctl", "print", target], capture_output=True, text=True)
        print("Background agent: " + ("loaded" if result.returncode == 0 else "not loaded"))
        # State files survive exit/crash; report current reachability separately.
        print("SpeakLab reachable now: " + ("yes" if healthy() else "no"))
        return 0
    if action == "install":
        ssh_command()  # Verify configured files before modifying login startup.
        if AGENT.exists():
            previous = plistlib.loads(AGENT.read_bytes())
            if previous.get("ProgramArguments") != agent_plist()["ProgramArguments"]:
                raise ValueError("A different installation owns " + str(AGENT))
        LOCAL.mkdir(exist_ok=True)
        AGENT.parent.mkdir(parents=True, exist_ok=True)
        AGENT.write_bytes(plistlib.dumps(agent_plist()))
        AGENT.chmod(0o600)
        subprocess.run(["/bin/launchctl", "bootout", target], capture_output=True)
        # bootout can return before the old worker has finished child cleanup.
        with (LOCAL / "pc-connection.lock").open("a+") as lock:
            deadline = time.monotonic() + 7
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise ValueError("A foreground connection still owns the tunnel. Stop it with Ctrl-C, then retry --install.")
                    time.sleep(0.1)
        result = subprocess.run(["/bin/launchctl", "bootstrap", "gui/%s" % os.getuid(), str(AGENT)])
        if result.returncode:
            return result.returncode
        print("Background reconnect enabled, including after Mac login. No terminal or tmux required.")
    elif action == "stop" or action == "uninstall":
        subprocess.run(["/bin/launchctl", "bootout", target], capture_output=True)
        if action == "uninstall" and AGENT.exists():
            AGENT.unlink()
        print("Background connection stopped." + (" Login startup removed." if action == "uninstall" else ""))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group()
    for name in ("install", "status", "stop", "uninstall"):
        choice.add_argument("--" + name, action="store_true")
    options = parser.parse_args()
    action = next((name for name, selected in vars(options).items() if selected), None)
    try:
        sys.exit(manage(action) if action else run())
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
