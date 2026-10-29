#!/usr/bin/env bash
# Separate, loopback-only chat UI in the E-drive-backed SpeakLab WSL distro.
# Uses the official pinned slim requirements; no Docker or extra model runtime.
set -euo pipefail
umask 077
test "$(id -u)" = 0 || { echo 'Run as root inside the dedicated PC distro.' >&2; exit 1; }
# Public HTTPS address of the Tailscale Serve route, e.g. https://your-pc.your-tailnet.ts.net:8443
webui_url="${SPEAKLAB_WEBUI_URL:?Set SPEAKLAB_WEBUI_URL to the private HTTPS address, e.g. https://your-pc.your-tailnet.ts.net:8443}"
case "$webui_url" in https://*) ;; *) echo 'SPEAKLAB_WEBUI_URL must start with https://' >&2; exit 1 ;; esac
test ! -e /opt/open-webui || { echo 'Existing Open WebUI installation: inspect before changing it.' >&2; exit 1; }
test ! -e /etc/open-webui.env || { echo 'Existing Open WebUI configuration: inspect first.' >&2; exit 1; }
curl -fsS http://127.0.0.1:11434/api/tags >/dev/null
install -d /opt/open-webui
python3 -m venv /opt/open-webui/.venv
/opt/open-webui/.venv/bin/pip install --disable-pip-version-check --no-cache-dir uv==0.12.10
curl -fsSL --retry 3 https://raw.githubusercontent.com/open-webui/open-webui/v0.12.4/backend/requirements-slim.txt -o /opt/open-webui/requirements-slim.txt
/opt/open-webui/.venv/bin/uv pip install --python /opt/open-webui/.venv/bin/python --no-cache -r /opt/open-webui/requirements-slim.txt
/opt/open-webui/.venv/bin/uv pip install --python /opt/open-webui/.venv/bin/python --no-cache --no-deps open-webui==0.12.4
id openwebui >/dev/null 2>&1 || useradd --system --home-dir /var/lib/open-webui --shell /usr/sbin/nologin openwebui
install -d -o openwebui -g openwebui /var/lib/open-webui
SPEAKLAB_WEBUI_URL="$webui_url" python3 - <<'PY'
import os
from pathlib import Path
import secrets
config = {
    'DATA_DIR': '/var/lib/open-webui',
    'WEBUI_SECRET_KEY': secrets.token_hex(32),
    'WEBUI_URL': os.environ['SPEAKLAB_WEBUI_URL'],
    'CORS_ALLOW_ORIGIN': os.environ['SPEAKLAB_WEBUI_URL'],
    'OLLAMA_BASE_URL': 'http://127.0.0.1:11434',
    'ENABLE_OLLAMA_API': 'true',
    'ENABLE_OPENAI_API': 'false',
    'DEFAULT_MODELS': 'gemma4:e4b',
    'USE_SLIM_DOCKER': 'true',
    'ENV': 'prod',
    'OFFLINE_MODE': 'true',
    'HF_HUB_OFFLINE': '1',
    'DO_NOT_TRACK': 'true',
    'SCARF_NO_ANALYTICS': 'true',
    'ANONYMIZED_TELEMETRY': 'false',
    'ENABLE_VERSION_UPDATE_CHECK': 'false',
    'RAG_EMBEDDING_ENGINE': 'ollama',
    'WEBUI_AUTH': 'true',
    'ENABLE_SIGNUP': 'false',
    'ENABLE_LOGIN_FORM': 'false',
    'WEBUI_AUTH_TRUSTED_EMAIL_HEADER': 'Tailscale-User-Login',
    'WEBUI_AUTH_TRUSTED_NAME_HEADER': 'Tailscale-User-Name',
    'WEBUI_SESSION_COOKIE_SECURE': 'true',
    'WEBUI_AUTH_COOKIE_SECURE': 'true',
    'ENABLE_DIRECT_CONNECTIONS': 'false',
    'ENABLE_CODE_EXECUTION': 'false',
    'ENABLE_CODE_INTERPRETER': 'false',
    'ENABLE_WEB_SEARCH': 'false',
    'ENABLE_IMAGE_GENERATION': 'false',
}
p = Path('/etc/open-webui.env')
p.write_text(''.join(f'{key}={value}\n' for key, value in config.items()))
p.chmod(0o600)
PY
chown -R openwebui:openwebui /opt/open-webui
cat > /etc/systemd/system/open-webui.service <<'UNIT'
[Unit]
Description=Private local-model chat through Tailscale Serve
After=network.target speaklab-ollama.service
[Service]
User=openwebui
Group=openwebui
WorkingDirectory=/opt/open-webui
EnvironmentFile=/etc/open-webui.env
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/open-webui/.venv/bin/open-webui serve --host 127.0.0.1 --port 3000
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now open-webui
for attempt in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:3000/health >/dev/null 2>&1; then
    echo 'Open WebUI healthy on loopback port 3000; private HTTPS route can now be enabled.'
    /opt/open-webui/.venv/bin/uv pip freeze --python /opt/open-webui/.venv/bin/python > /opt/open-webui/installed-packages.txt
    sha256sum /opt/open-webui/requirements-slim.txt
    du -sh /opt/open-webui /var/lib/open-webui
    exit 0
  fi
  sleep 2
done
journalctl -u open-webui -n 60 --no-pager
exit 1
