"""Explicit SSH doubles exercise reconnect and child cleanup without a real PC."""
import contextlib
import fcntl
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "pc_connection.py"
SPEC = importlib.util.spec_from_file_location("pc_connection", SCRIPT)
pc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pc)

class ConnectionTests(unittest.TestCase):
    def test_retry_delay_is_bounded(self):
        self.assertEqual([pc.backoff(n) for n in range(1, 8)], [2, 4, 8, 16, 30, 30, 30])

    def command_with(self, environment, pc_env=None):
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory)
            (local / "ssh_known_hosts").write_text("Explicit public host-key test double")
            if pc_env is not None:
                (local / "pc.env").write_text(pc_env)
            key = local / "test-key"
            key.touch()
            environment = {"SPEAKLAB_SSH_KEY": str(key), **environment}
            with patch.object(pc, "LOCAL", local), patch.dict(os.environ, environment, clear=True):
                return pc.ssh_command()

    def test_command_preserves_pinned_identity_and_loopback_binding(self):
        command = self.command_with({"SPEAKLAB_PC_HOST": "pc.example", "SPEAKLAB_PC_USER": "user",
                                     "SPEAKLAB_PC_HOST_KEY_ALIAS": "pinned-pc"})
        self.assertEqual(command[-1], "user@pc.example")
        for expected in ["HostKeyAlias=pinned-pc", "StrictHostKeyChecking=yes",
                         "BatchMode=yes", "ControlPath=none", "127.0.0.1:4173:127.0.0.1:8765"]:
            self.assertIn(expected, command)

    def test_local_settings_file_supplies_defaults_and_environment_wins(self):
        pc_env = "# comment\nSPEAKLAB_PC_HOST=file.example\nSPEAKLAB_PC_USER=fileuser\n"
        self.assertEqual(self.command_with({}, pc_env)[-1], "fileuser@file.example")
        command = self.command_with({"SPEAKLAB_PC_HOST": "env.example"}, pc_env)
        self.assertEqual(command[-1], "fileuser@env.example")
        self.assertFalse(any(part.startswith("HostKeyAlias=") for part in command))

    def test_missing_host_fails_before_connecting(self):
        with self.assertRaisesRegex(ValueError, "SPEAKLAB_PC_HOST"):
            self.command_with({})
        with self.assertRaisesRegex(ValueError, "Invalid"):
            self.command_with({"SPEAKLAB_PC_HOST": "-oProxyCommand=x"})

    def test_missing_verified_key_fails_before_connecting(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(pc, "LOCAL", Path(directory)):
            with self.assertRaisesRegex(ValueError, "Missing verified"):
                pc.ssh_command()

    def test_health_uses_expected_machine_and_ignores_proxy(self):
        with patch.object(pc, "build_opener") as opener, \
                patch.dict(os.environ, {"SPEAKLAB_PC_SERVER_NAME": "Home PC"}):
            response = opener.return_value.open.return_value.__enter__.return_value
            response.read.return_value = b'{"server_name":"Home PC"}'
            self.assertTrue(pc.healthy())
            for payload in [b'{"server_name":"other"}', b'[]', b'not JSON']:
                response.read.return_value = payload
                self.assertFalse(pc.healthy())

    def test_health_without_expected_name_requires_speaklab_response(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(pc, "LOCAL", Path(directory)), \
                patch.dict(os.environ, {}, clear=True), patch.object(pc, "build_opener") as opener:
            response = opener.return_value.open.return_value.__enter__.return_value
            response.read.return_value = b'{"server_name":"anything"}'
            self.assertTrue(pc.healthy())
            response.read.return_value = b'{"status":"ok"}'
            self.assertFalse(pc.healthy())

    def test_agent_has_no_terminal_dependency(self):
        plist = pc.agent_plist()
        self.assertEqual(plist["ProgramArguments"], ["/usr/bin/python3", str(SCRIPT)])
        self.assertTrue(plist["RunAtLoad"])
        self.assertEqual(plist["KeepAlive"], {"SuccessfulExit": False})

    def test_second_supervisor_does_not_replace_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory)
            with (local / "pc-connection.lock").open("a+") as owner:
                fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch.object(pc, "LOCAL", local), contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(pc.run(), 0)
                self.assertIn("already managed", output.getvalue())

    def harness(self, directory, fatal=False):
        local = Path(directory)
        fake = local / "fake_ssh.py"
        fake.write_text("""
import os, sys, time
from pathlib import Path
root = Path(sys.argv[1])
counter = root / 'calls'
number = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(number))
if sys.argv[2] == 'fatal':
    print('Host key verification failed.', file=sys.stderr)
    sys.exit(255)
if number == 1:
    print('Connection reset by peer', file=sys.stderr)
    sys.exit(255)
(root / 'child_pid').write_text(str(os.getpid()))
(root / 'ready').touch()
while True:
    time.sleep(0.1)
""")
        harness = local / "harness.py"
        harness.write_text("""
import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('pc', sys.argv[1])
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)
pc.LOCAL = Path(sys.argv[2])
pc.STATUS = pc.LOCAL / 'status.json'
pc.ssh_command = lambda: [sys.executable, str(pc.LOCAL / 'fake_ssh.py'), str(pc.LOCAL), sys.argv[3]]
pc.healthy = lambda: (pc.LOCAL / 'ready').exists()
pc.backoff = lambda failures: 0.01
class NoNetworkSocket:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def bind(self, address): pass
pc.socket.socket = NoNetworkSocket
sys.exit(pc.run())
""")
        return subprocess.Popen([sys.executable, str(harness), str(SCRIPT), directory,
                                 "fatal" if fatal else "transient"], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)

    def test_transient_failure_reconnects_and_sigterm_cleans_child(self):
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory)
            process = self.harness(directory)
            try:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    status = local / "status.json"
                    if status.exists() and json.loads(status.read_text())["state"] == "connected":
                        break
                    time.sleep(0.05)
                else:
                    self.fail("Explicit SSH double never reconnected")
                child_pid = int((local / "child_pid").read_text())
                self.assertEqual((local / "calls").read_text(), "2")
                process.terminate()
                output, error = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, error)
                self.assertIn("Retrying", output)
                self.assertEqual(json.loads(status.read_text())["state"], "stopped")
                with self.assertRaises(ProcessLookupError):
                    os.kill(child_pid, 0)
                with (local / "pc-connection.lock").open("a+") as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.communicate(timeout=5)

    def test_bad_host_identity_stops_without_retry_or_launchd_loop(self):
        with tempfile.TemporaryDirectory() as directory:
            process = self.harness(directory, fatal=True)
            output, error = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, error)
            self.assertIn("retries stopped", output)
            self.assertEqual((Path(directory) / "calls").read_text(), "1")
            self.assertEqual(json.loads((Path(directory) / "status.json").read_text())["state"], "attention")

if __name__ == "__main__":
    unittest.main()
