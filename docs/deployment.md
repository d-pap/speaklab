# Deploying SpeakLab on a Windows PC

This guide runs SpeakLab on a Windows PC with an NVIDIA GPU, inside a dedicated WSL2 Ubuntu distro. Another computer (or a phone) then uses it through a browser. For a single-machine install, follow the README's [Quick start](../README.md#quick-start) instead.

Examples use these placeholders. Replace them with your own values:

| Placeholder | Meaning |
| --- | --- |
| `your-pc` | The Windows PC's SSH host name or address |
| `you` | Your Windows user name |
| `your-pc.your-tailnet.ts.net` | The PC's Tailscale MagicDNS name, if you use Tailscale |
| `X:\WSL\SpeakLab` | A Windows folder with room for the distro disk and models (about 20 GB) |

## Explanation: how the deployment fits together

The PC runs three systemd services inside a WSL distro named `SpeakLab`:

- `speaklab` serves the API and the built frontend on `127.0.0.1:8765`.
- `speaklab-ollama` serves the chat model on `127.0.0.1:11434`.
- `speaklab-whisper` serves whisper.cpp transcription on `127.0.0.1:8080`.

Every listener binds to loopback. No other device can reach these ports directly. A client reaches the app through one of two private routes:

- An SSH tunnel forwards the client's `127.0.0.1:4173` to the PC's `127.0.0.1:8765`. The browser treats `localhost` as a secure context, so microphone recording works.
- Tailscale Serve publishes the app as HTTPS on the PC's tailnet name. Only devices signed in to your tailnet can open it. Phones need this route, because they cannot run the SSH tunnel.

A dedicated distro keeps SpeakLab's packages, users and data apart from other WSL workloads such as Docker Desktop. `wsl --shutdown` stops every distro, including Docker's, so SpeakLab operations use `wsl --terminate SpeakLab` instead.

The Linux GPU path uses the Windows NVIDIA driver. Do not install a Linux display driver inside WSL; see [NVIDIA's WSL guide](https://docs.nvidia.com/cuda/wsl-user-guide/index.html). The defaults (Qwen3.5 9B Q4_K_M, 8192-token context) fit an 8 GB GPU. Whisper runs on the CPU to leave GPU memory for the model.

## How-to: provision the PC

**Prerequisites:** Windows 10 22H2 or Windows 11 with WSL2, a current NVIDIA driver, and the OpenSSH server enabled with key authentication.

1. Download the latest Ubuntu 24.04 `.wsl` image from [releases.ubuntu.com/noble](https://releases.ubuntu.com/noble/).
2. Verify the image against that page's `SHA256SUMS` with `Get-FileHash`.
3. In PowerShell, run `wsl --import SpeakLab X:\WSL\SpeakLab <image-path> --version 2`.
4. Check that `/etc/wsl.conf` inside the distro contains `systemd=true` under `[boot]`.
5. On your development machine, run `npm --prefix frontend ci` and `npm --prefix frontend run build`.
6. Copy the source and `frontend/dist` into `/opt/speaklab` in the distro.

**Exclude `.env`, `.venv`, `node_modules`, `.local`, caches and `data` from the copy.**

7. Inside the distro, as root, run `SPEAKLAB_SERVER_NAME="My PC" bash /opt/speaklab/scripts/provision-linux.sh`.
8. Run the backend tests inside the distro: `cd /opt/speaklab && .venv/bin/python -m pytest backend/tests -q`.

`provision-linux.sh` installs dependencies, builds whisper.cpp, downloads the `small.en` and Qwen weights, writes `/opt/speaklab/.env` if it is missing, and enables the three services. It never overwrites an existing `.env`. The script downloads current Ollama and whisper.cpp releases, so a later run can install newer versions than earlier deployments.

`SPEAKLAB_SERVER_NAME` appears in Settings as the connected computer's name. If you omit it, the script uses the distro's host name.

## How-to: keep the distro running after Windows starts

WSL stops an idle distro. A scheduled task keeps `SpeakLab` open so its services stay available without a Windows sign-in.

1. Open PowerShell as an administrator.
2. Create the task:

```powershell
$action = New-ScheduledTaskAction -Execute "$env:WINDIR\System32\wsl.exe" -Argument '-d SpeakLab -u root --exec /bin/sleep infinity'
$trigger = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = 'PT30S'
$principal = New-ScheduledTaskPrincipal -UserId "$env:COMPUTERNAME\$env:USERNAME" -LogonType S4U -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'SpeakLab Host' -Action $action -Trigger $trigger -Principal $principal -Settings $settings
```

3. Start it now: `Start-ScheduledTask -TaskName 'SpeakLab Host'`.
4. Disable sleep in Windows power settings while the PC hosts SpeakLab.

**Do not enable Windows automatic sign-in as a workaround.** Test a full reboot before you rely on unattended recovery.

## How-to: connect from a Mac with the SSH tunnel

`scripts/connect-pc.command` keeps a reconnecting tunnel open and can install itself as a login item. It refuses to connect without a pinned host key.

1. Confirm the PC's ED25519 host-key fingerprint on the PC itself: `ssh-keygen -lf C:\ProgramData\ssh\ssh_host_ed25519_key.pub`.
2. On the Mac, run `ssh-keyscan -t ed25519 your-pc > .local/ssh_known_hosts`.
3. Run `ssh-keygen -lf .local/ssh_known_hosts` and compare its fingerprint with step 1.
4. If you set `SPEAKLAB_PC_HOST_KEY_ALIAS`, replace the first field of `.local/ssh_known_hosts` with the alias.

**Stop if the fingerprints differ.**

5. Create `.local/pc.env` with your settings (see [Tunnel settings](#tunnel-settings)).
6. Run `bash scripts/connect-pc.command --status` to check the configuration.
7. Run `bash scripts/connect-pc.command --install` to start the tunnel at every Mac login.
8. Open <http://127.0.0.1:4173>.

To run the tunnel in a terminal instead, run `bash scripts/connect-pc.command` without arguments. Ctrl-C stops it. Only one tunnel can own port 4173, so run `--stop` before you use the terminal mode.

`--stop` stops the background tunnel for this login session. `--uninstall` also removes the login item. Logs and state go to `.local/pc-connection*.log` and `.local/pc-connection.json`.

## How-to: open SpeakLab from a phone with Tailscale Serve

**Use `tailscale serve`, never `tailscale funnel`. Funnel publishes the app to the public internet.**

1. Install Tailscale on the PC and the phone, and sign both in to the same tailnet.
2. On the PC, run `tailscale serve --bg --https=443 http://127.0.0.1:8765`.
3. In the distro, add `SPEAKLAB_BROWSER_ORIGINS=["https://your-pc.your-tailnet.ts.net"]` to `/opt/speaklab/.env`.
4. Run `chown speaklab:speaklab /opt/speaklab/.env && chmod 600 /opt/speaklab/.env`.
5. Run `systemctl restart speaklab`.
6. On the phone, open `https://your-pc.your-tailnet.ts.net/` in Safari and allow the microphone.

If the `.env` is mode 600 but owned by root, the `speaklab` service cannot read it and fails to start.

SpeakLab accepts only the exact origins listed in `SPEAKLAB_BROWSER_ORIGINS`. It rejects wildcards. Write requests still need the app's client header.

If the phone cannot resolve the tailnet name, check for another DNS profile under iOS Settings → General → VPN & Device Management → DNS. An encrypted-DNS profile can override Tailscale's resolver; select **Automatic**. See [tailscale/tailscale#12563](https://github.com/tailscale/tailscale/issues/12563).

## How-to: add Open WebUI for general model chat (optional)

Open WebUI gives a general chat interface to the same Ollama models. Tailscale identity headers sign users in, so it has no password form.

1. Inside the distro, as root, run `SPEAKLAB_WEBUI_URL=https://your-pc.your-tailnet.ts.net:8443 bash /opt/speaklab/scripts/provision-webui.sh`.
2. On the PC, run `tailscale serve --bg --https=8443 http://127.0.0.1:3000`.
3. Open `https://your-pc.your-tailnet.ts.net:8443/`.

**Keep port 3000 on loopback.** A LAN or tailnet listener lets clients skip Tailscale Serve and send forged identity headers.

The script refuses to overwrite an existing installation. SpeakLab and Open WebUI share one Ollama queue, so using both at once adds latency. Open WebUI chat history lives in `/var/lib/open-webui`. SpeakLab's backup script does not include that folder.

## How-to: operate the services

Run these in PowerShell on the PC, or over `ssh your-pc`:

```powershell
# Status of the distro and services
wsl --list --verbose
wsl -d SpeakLab -u root --exec systemctl status speaklab speaklab-ollama speaklab-whisper --no-pager

# Restart the app after a code or .env change
wsl -d SpeakLab -u root --exec systemctl restart speaklab

# Recent app logs
wsl -d SpeakLab -u root --exec journalctl -u speaklab -n 50 --no-pager

# Start the host task if it is not running
Start-ScheduledTask -TaskName 'SpeakLab Host'
```

## How-to: update a running deployment

1. Build the frontend on your development machine.
2. Copy changed source files into `/opt/speaklab`, using the same exclusions as provisioning.
3. If only the frontend changed, copy the new hashed files in `frontend/dist/assets` first.
4. Replace `frontend/dist/index.html` last.
5. If backend code changed, run `systemctl restart speaklab`.

Keep the old hashed assets. Browser tabs that are already open still request them.

## How-to: back up and restore practice data

1. Wait until no recording or analysis is in progress.
2. Run `wsl -d SpeakLab -u root --exec bash /opt/speaklab/scripts/backup-data.sh [destination]`.

The script stops the app, archives `/var/lib/speaklab`, verifies the archive, writes a SHA-256 file and restarts the app. The default destination is `/mnt/d/SpeakLabBackups` (the Windows `D:` drive). The script never deletes older backups. It excludes model weights, which can be downloaded again.

To restore, run these inside the distro as root:

1. Stop the app: `systemctl stop speaklab`.
2. Rename the current `/var/lib/speaklab` instead of deleting it.
3. Extract the archive into a new `/var/lib/speaklab`.
4. Run `chown -R speaklab:speaklab /var/lib/speaklab`.
5. Start the app and check a few sessions before you remove the renamed folder.

Restore to the same path. SQLite stores absolute recording paths, so a different path breaks audio playback.

## Reference

### Installed layout

| Component | Location |
| --- | --- |
| Application source | `/opt/speaklab` |
| Service configuration | `/opt/speaklab/.env` (`speaklab:speaklab`, mode 600) |
| Practice data | `/var/lib/speaklab/speaklab.sqlite3`, `/var/lib/speaklab/recordings` |
| LLM weights | `/var/lib/ollama/models` |
| Whisper weights | `/var/lib/speaklab-models/ggml-small.en.bin` |
| whisper.cpp build | `/opt/whisper.cpp` |
| systemd units | `speaklab`, `speaklab-ollama`, `speaklab-whisper` (optional `open-webui`) |
| Windows startup task | `SpeakLab Host` |
| Open WebUI (optional) | `/opt/open-webui`, data `/var/lib/open-webui`, config `/etc/open-webui.env` |

### Tunnel settings

`scripts/pc_connection.py` reads each setting from the environment first, then from `.local/pc.env` (`KEY=VALUE` lines, `#` comments).

| Setting | Required | Meaning |
| --- | --- | --- |
| `SPEAKLAB_PC_HOST` | yes | SSH host name or address of the PC |
| `SPEAKLAB_PC_USER` | no | SSH user; omitted means SSH's own default |
| `SPEAKLAB_PC_PORT` | no | SSH port; default `22` |
| `SPEAKLAB_SSH_KEY` | no | Private key path; default `~/.ssh/id_ed25519` |
| `SPEAKLAB_PC_HOST_KEY_ALIAS` | no | Name under which `.local/ssh_known_hosts` stores the key; use it when the address changes but the key does not |
| `SPEAKLAB_PC_SERVER_NAME` | no | Expected `SPEAKLAB_SERVER_NAME`; the health check then rejects any other server on port 4173 |

Example `.local/pc.env`:

```sh
SPEAKLAB_PC_HOST=your-pc.your-tailnet.ts.net
SPEAKLAB_PC_USER=you
SPEAKLAB_PC_SERVER_NAME=My PC
```

### Supervisor tests

Run `/usr/bin/python3 -m unittest discover -s scripts/tests -v`. The tests replace SSH with stand-in processes. They check retries, host-identity failures, duplicate prevention and child cleanup. They do not prove that Windows starts the services.
